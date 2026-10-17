"""底部字幕（附加功能，用户说要才做）：按原文案做字幕，时间跟着跳剪后的画面，烧进视频，同时导出 .srt / .ass。

  python captions.py --workdir <项目目录>          # 预览：每条字幕的文字和时间、放在哪个高度，不出文件
  python captions.py --workdir <项目目录> --yes    # avatar/final_jumpcut.mp4 → avatar/final_subtitled.mp4
  python captions.py --video <视频> --copy <文案.txt> --words <words.json 或 plan.json> [--jumpcut <剪辑记录.json>] --out <输出.mp4> --yes
  python captions.py --workdir <项目目录> --translation <译文.json> --yes     # 译文字幕（例如英文配音配中文字幕）

译文字幕（用户要别的语言的字幕时）：
  * 译文.json：{"units": [{"src": "原文的一句或一个分句", "text": "这一句的译文"}, ...]}，src 按顺序拼起来必须等于原文案。
    译文由 agent 按原文写，交付时请用户核对；原文案仍然一个字不改。
  * 每个 src 在配音里的起止由原文对逐词时间得到；译文按下面的中文规则断成一行一条，按各条的宽度分这一句的时间。
    长句拆成几个 src（按分句）时间更准。

规则（2026-10-14 用户看样片后定）：
  * 文字是原文案，一个字不改。句中的逗号、顿号、问号、感叹号保留，句末的句号去掉；中文和英文、数字之间留一个空格。
  * 专有名词不拆开：常见公司和产品名、文案里重复出现的三四字词自动保护；只出现一次的名词用 --terms 列出（例如 国星宇航）。
  * 一句一条，一屏一行（竖屏每条最多约 12 个字宽）。长句先在逗号处断，没有逗号再在词与词之间断：
    词边界用中文分词（jieba），识别结果认为是同一个词的地方也不断（分词会把“隔空投送”切错）；不断在英文、数字中间，
    尽量不让一条以“的、了、着”这类字开头，也尽量不留只有一两个字的条。不跨句合并。
  * 时间：原文逐字对到逐词时间上（识别有同音错字，所以对齐而不是查找），再按跳剪记录的 map 换算到跳剪后的时间。
    项目里用 avatar/words_final.json（已换算到成片时间轴：拼接时裁过每段开头），没有它才用 out/words.json。
    每条显示到下一条开始；后面停顿超过 0.9 秒时，说完 0.5 秒就收掉。
  * 样式：粗黑体（Windows 用微软雅黑），字号约为画面宽度的 6.5%，白字黑描边加轻微阴影，不加底板，水平居中。
  * 位置：整行字幕落在画面 68%–80% 高度里，挑全片画面变化最小（手最少经过）的位置；下面约 20% 留给平台的标题和按钮。
  * 自检：字幕拼起来和文案逐字一致、每条不超过一行、不重叠、不超出视频。另出一张抽帧图看字幕有没有压到脸、出没出画面。
"""
import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import _cli  # noqa: E402
import _util  # noqa: E402

STRIP = r"[\s，。、！？!?；;：:“”\"'‘’（）()\-—…,.~～《》]"
CJK = "[一-鿿]"
MAX_W = 12.0             # 一条最宽多少个汉字宽（768 宽的竖屏、字号 6.5% 时一行放得下）
SLACK = 0.5              # 英文、数字按 0.55 个字宽估，留一点余量
MIN_SEC = 1.0
BAND = (0.68, 0.80)      # 整行字幕要落在这个高度范围里（占画面高度的比例）
FONT_RATIO = 0.065       # 字号 = 画面宽度 × 这个比例
SOFT_AFTER = "的了着过"                              # 断在这些字后面读着自然
SOFT_BEFORE = "把被就都也还才和跟让给对从向但而所"     # 断在这些字前面读着自然
BAD_START = "的了着地得们吗呢吧啊过个"                 # 一条不要以这些字开头


def width(s):
    return sum(1.0 if re.match(CJK, c) or c in "，。、！？：；“”（）《》" else 0.55 for c in s if not c.isspace())


def tidy(s):
    s = re.sub(r"[。~～；;]+$", "", s.strip())
    return re.sub(r"[，、：:；;]+$", "", s).strip()


def load_words(path):
    """words.json（合并轴上的逐词时间），或 plan.json（每段的词是段内时间）"""
    d = json.load(open(path, encoding="utf-8"))
    if isinstance(d, dict) and "words" in d:
        return d["words"]
    if isinstance(d, list):
        return d
    words = []
    for s in d["segments"]:
        for w in s["words"]:
            words.append({"word": w["word"], "start": s["start"] + w["start"], "end": s["start"] + w["end"]})
    return words


def char_times(words):
    chars, times, wid = [], [], []
    for n, w in enumerate(words):
        t = re.sub(STRIP, "", w.get("text") or w.get("word") or "")
        for k, ch in enumerate(t):
            chars.append(ch.lower())
            times.append((w["start"] + (w["end"] - w["start"]) * k / max(1, len(t)), w["end"]))
            wid.append(n)
    return chars, times, wid


def align_chars(text, chars):
    """原文里每个（去掉标点后的）字 → 识别结果里的第几个字（对不上为 None），以及是不是逐字对上的"""
    c = [ch.lower() for ch in re.sub(STRIP, "", text)]
    m, eq = [None] * len(c), [False] * len(c)
    sm = difflib.SequenceMatcher(None, "".join(c), "".join(chars), autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("delete", "insert"):
            continue
        for k in range(i1, i2):
            m[k] = j1 + (k - i1) * max(1, j2 - j1) // max(1, i2 - i1) if tag == "replace" else j1 + (k - i1)
            eq[k] = tag == "equal"
    return m, eq


def cut_points(s, same_word):
    """一句话里可以断开的位置 b（断成 s[:b] 和 s[b:]）→ 代价。逗号处最便宜，其次是词边界。"""
    import logging
    import jieba
    jieba.setLogLevel(logging.WARNING)
    cost = {mm.end(): 0.0 for mm in re.finditer(r"[，,：:；;、]", s) if mm.end() < len(s)}
    keep = [i for i, ch in enumerate(s) if not ch.isspace()]            # 去掉空格再分词（“接给 AI”带空格时会切错）
    pos = 0
    for w in jieba.cut("".join(s[i] for i in keep)):
        pos += len(w)
        if 0 < pos < len(keep):
            b = keep[pos]
            if b not in cost:
                cost[b] = 3.0 if (s[keep[pos - 1]] in SOFT_AFTER or s[b] in SOFT_BEFORE) else 4.0
    for b in list(cost):
        if cost[b] == 0.0:
            continue
        if re.match(r"[A-Za-z0-9.]", s[b - 1]) and re.match(r"[A-Za-z0-9.]", s[b]):
            del cost[b]                                    # 不断在英文、数字中间
        elif same_word(b):
            del cost[b]                                    # 识别结果认为是同一个词
        elif s[b] in BAD_START:
            cost[b] += 4.0
    return cost


def split_sentence(s, same_word, max_w=MAX_W):
    """一句话断成几条：每条不超过一行；条数少、断在逗号、不留特别短的条、不以“的”这类字开头"""
    if width(s) <= max_w + SLACK:
        return [s]
    cost = cut_points(s, same_word)
    pts = [0] + sorted(cost) + [len(s)]
    best = {0: (0.0, [])}
    for j in pts[1:]:
        for i in pts:
            if i >= j or i not in best:
                continue
            piece = tidy(s[i:j])
            w = width(piece)
            if not piece or w > max_w + SLACK:
                continue
            c = best[i][0] + 2.0 + (cost[j] if j < len(s) else 0.0) + max(0.0, 5.0 - w) * 1.2
            if j not in best or c < best[j][0]:
                best[j] = (c, best[i][1] + [(i, j)])
    if len(s) not in best:                                 # 实在断不开（超长的英文词）：原样一条
        return [s]
    return [s[i:j] for i, j in best[len(s)][1]]


def sentences(copy):
    copy = re.sub(r"！+", "！", copy)
    parts = re.split(r"(?<=[。！？!?~～；;])(?![”\"])|(?<=[。！？!?~～][”\"])|\n", copy)
    return [t for t in (tidy(x) for x in parts if x and x.strip()) if t]


# 分词常切错的专有名词（“对英/伟达”“国星/宇航”）。只出现一次的名词由调用方用 --terms 补
COMMON_TERMS = ["英伟达", "微软", "谷歌", "苹果", "华为", "阿里巴巴", "阿里云", "腾讯", "字节跳动", "小米", "特斯拉", "亚马逊", "百度",
                "京东", "美团", "拼多多", "抖音", "小红书", "快手", "哔哩哔哩", "大模型", "人工智能", "智能体", "数字人"]


def add_terms(copy, extra=()):
    """把专有名词告诉分词，断句时不拆开：常见的公司和产品名、文案里重复出现的三四字词、调用方给的 --terms"""
    import logging
    import jieba
    jieba.setLogLevel(logging.WARNING)
    terms = set(COMMON_TERMS) | {t.strip() for t in extra if t.strip()}
    plain = re.sub(r"[^一-鿿]+", "|", copy)
    for n in (4, 3):
        seen = {}
        for chunk in plain.split("|"):
            for i in range(len(chunk) - n + 1):
                seen[chunk[i:i + n]] = seen.get(chunk[i:i + n], 0) + 1
        terms |= {k for k, v in seen.items() if v >= 2}
    for t in terms:
        jieba.add_word(t, freq=200000)
    return sorted(terms)


def build(words, copy, max_w=MAX_W, terms=()):
    """原文 → [[文字, 起, 止]]（原片时间）"""
    add_terms(copy, terms)
    sents = sentences(copy)
    chars, times, wid = char_times(words)
    m, eq = align_chars("".join(sents), chars)
    out, off = [], 0
    for s in sents:
        vb = [len(re.sub(STRIP, "", s[:b])) for b in range(len(s) + 1)]

        def same_word(b, off=off, vb=vb):
            k = off + vb[b]                                 # 断点后第一个字在全文里的序号
            if k == 0 or k >= len(m) or not (eq[k - 1] and eq[k]):
                return False
            return m[k - 1] is not None and m[k] is not None and wid[m[k - 1]] == wid[m[k]]
        for p in split_sentence(s, same_word, max_w):
            pn = len(re.sub(STRIP, "", p))
            idx = [j for j in m[off:off + pn] if j is not None and j < len(times)]
            out.append([tidy(p), times[idx[0]][0] if idx else None, times[idx[-1]][1] if idx else None])
            off += pn
    for i, x in enumerate(out):                            # 整条都没对上的，夹在前一条后面
        if x[1] is None:
            x[1] = out[i - 1][2] if i else 0.0
            x[2] = x[1] + 0.8
    return out


def load_translation(path, copy):
    """译文字幕：{"units": [{"src": 原文的一句或一个分句, "text": 这一句的译文}, ...]}。src 按顺序拼起来要等于原文案。"""
    d = json.load(open(path, encoding="utf-8-sig"))
    units = d.get("units") if isinstance(d, dict) else d
    if not units or not all(isinstance(u, dict) and u.get("src", "").strip() and u.get("text", "").strip() for u in units):
        _cli.fail(_cli.USAGE, "译文文件格式不对：要有 units，每项都有非空的 src（原文）和 text（译文）")
    if re.sub(STRIP, "", "".join(u["src"] for u in units)).lower() != re.sub(STRIP, "", copy).lower():
        _cli.fail(_cli.ERROR, "译文文件里的 src 按顺序拼起来和文案对不上（漏句、多句或顺序错了）；每句原文都要有一项")
    return units


def build_translated(words, units, max_w=MAX_W, terms=()):
    """译文字幕 → [[文字, 起, 止]]（原片时间）。每个 src 在配音里的起止由原文对逐词时间得到；
    译文按中文规则断成一行一条，按各条的宽度分这一句的时间。"""
    add_terms("".join(u["text"] for u in units), terms)
    chars, times, _ = char_times(words)
    m, _ = align_chars("".join(u["src"] for u in units), chars)
    out, off = [], 0
    for u in units:
        n = len(re.sub(STRIP, "", u["src"]))
        idx = [j for j in m[off:off + n] if j is not None and j < len(times)]
        off += n
        pieces = [p for s in sentences(u["text"]) for p in split_sentence(s, lambda b: False, max_w)]
        pieces = [tidy(p) for p in pieces if tidy(p)]
        if not idx:
            out += [[p, None, None] for p in pieces]
            continue
        s0, e0 = times[idx[0]][0], times[idx[-1]][1]
        total_w = sum(max(1.0, width(p)) for p in pieces)
        t = s0
        for p in pieces:
            d = (e0 - s0) * max(1.0, width(p)) / total_w
            out.append([p, t, t + d])
            t += d
    for i, x in enumerate(out):
        if x[1] is None:
            x[1] = out[i - 1][2] if i else 0.0
            x[2] = x[1] + 0.8
    return out


def to_out(t, mapping, side):
    """原片时间 → 跳剪后的时间。落在被剪掉的静音里：起点挪到下一截的开头，终点挪到上一截的结尾"""
    if not mapping:
        return t
    for k, mp in enumerate(mapping):
        if mp["src_start"] <= t <= mp["src_end"]:
            return mp["out_start"] + t - mp["src_start"]
        if t < mp["src_start"]:
            if side == "start":
                return mp["out_start"]
            prev = mapping[k - 1] if k else mp
            return prev["out_start"] + prev["src_end"] - prev["src_start"]
    last = mapping[-1]
    return last["out_start"] + last["src_end"] - last["src_start"]


def cues_from(raw, mapping, total):
    cues = [[txt, to_out(s, mapping, "start"), to_out(e, mapping, "end")] for txt, s, e in raw]
    out = []
    for i, (txt, s, e) in enumerate(cues):
        nxt = cues[i + 1][1] if i + 1 < len(cues) else min(total, e + 0.6)
        stop = min(nxt, e + 0.5) if nxt - e > 0.9 else nxt
        stop = max(stop, s + MIN_SEC * 0.8)
        txt = re.sub("(" + CJK + ")(?=[A-Za-z0-9])", r"\1 ", txt)
        txt = re.sub("([A-Za-z0-9.]+)(?=" + CJK + ")", r"\1 ", txt)
        out.append({"text": re.sub(r"\s+", " ", txt).strip(), "start": round(max(0.0, s - 0.06), 3), "end": round(min(stop, total), 3)})
    for a, b in zip(out, out[1:]):                         # 不重叠
        if a["end"] > b["start"]:
            a["end"] = b["start"]
    return out


def pick_band(video, font_px, H, band=BAND):
    """全片每个高度上的画面变化量（手经过的地方变化大），在 band 里挑变化最小、放得下一行字的位置 → 中心高度比例"""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(video)
    prof, prev, n, i = None, None, 0, 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        i += 1
        if i % 6:
            continue
        g = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (48, 200)).astype(np.float32)
        if prev is not None:
            d = (np.abs(g - prev) > 12).mean(axis=1)
            prof = d if prof is None else prof + d
            n += 1
        prev = g
    cap.release()
    if prof is None:
        return sum(band) / 2
    prof = prof / max(1, n)
    box = max(2, int(round(font_px * 1.5 / H * 200)))
    lo, hi = int(band[0] * 200), int(band[1] * 200) - box
    best = min(range(lo, max(lo + 1, hi + 1)), key=lambda y: float(prof[y:y + box].mean()))
    return round((best + box / 2) / 200.0, 3)


def font_setup(name):
    """（字体名, fontsdir）。Windows 用微软雅黑粗体，没有就用黑体；别的系统交给 fontconfig 找思源黑体。"""
    if name:
        return name, None
    if os.name == "nt":
        fd = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        for f, n in (("msyhbd.ttc", "Microsoft YaHei"), ("msyh.ttc", "Microsoft YaHei"), ("simhei.ttf", "SimHei"),
                     ("NotoSansSC-VF.ttf", "Noto Sans SC")):
            if os.path.isfile(os.path.join(fd, f)):
                return n, fd
        return "Microsoft YaHei", fd
    if sys.platform == "darwin":
        return "PingFang SC", "/System/Library/Fonts"
    return "Noto Sans CJK SC", None


def ass_time(t):
    cs = int(round(t * 100))
    return "%d:%02d:%02d.%02d" % (cs // 360000, cs // 6000 % 60, cs // 100 % 60, cs % 100)


def srt_time(t):
    ms = int(round(t * 1000))
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def write_ass(path, cues, W, H, font_name, font_px, center):
    margin_v = int(round(H * (1 - center) - font_px * 0.75))
    lines = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: %d" % W, "PlayResY: %d" % H, "WrapStyle: 2",
             "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
             "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
             "Style: Sub,%s,%d,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,1,0,0,0,100,100,1,0,1,%.1f,%.1f,2,%d,%d,%d,1"
             % (font_name, font_px, font_px * 0.07, font_px * 0.04, int(W * 0.06), int(W * 0.06), margin_v), "",
             "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for c in cues:
        lines.append("Dialogue: 0,%s,%s,Sub,,0,0,0,,%s" % (ass_time(c["start"]), ass_time(c["end"]), c["text"]))
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    return margin_v


def write_srt(path, cues):
    with open(path, "w", encoding="utf-8") as f:
        for k, c in enumerate(cues, 1):
            f.write("%d\n%s --> %s\n%s\n\n" % (k, srt_time(c["start"]), srt_time(c["end"]), c["text"]))


def check_sheet(video, cues, path, n=6):
    """均匀挑 n 条字幕，在每条中间抽一帧拼成一张图"""
    import cv2
    pick = [cues[int(k * (len(cues) - 1) / max(1, n - 1))] for k in range(min(n, len(cues)))]
    cap = cv2.VideoCapture(video)
    cells = []
    for c in pick:
        cap.set(cv2.CAP_PROP_POS_MSEC, (c["start"] + c["end"]) / 2 * 1000)
        ok, f = cap.read()
        if ok:
            cells.append(cv2.resize(f, (300, int(300 * f.shape[0] / f.shape[1]))))
    cap.release()
    if not cells:
        return None
    while len(cells) % 3:
        cells.append(cells[-1] * 0)
    rows = [cv2.hconcat(cells[i:i + 3]) for i in range(0, len(cells), 3)]
    _util.imwrite(path, cv2.vconcat(rows))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", help="项目目录：给 avatar/final_jumpcut.mp4 加字幕，写 avatar/final_subtitled.mp4")
    ap.add_argument("--video", help="不在项目里的视频")
    ap.add_argument("--copy", help="原文案（--video 时必给；项目里默认用 copy.txt）")
    ap.add_argument("--words", help="逐词时间：words.json 或 plan.json（--video 时必给；项目里默认用 out/words.json）")
    ap.add_argument("--jumpcut", help="跳剪记录（视频剪过停顿时给，项目里自动用 avatar/jumpcut.json）")
    ap.add_argument("--out", help="输出（--video 时用；不给就在原视频旁边加 _字幕）")
    ap.add_argument("--max-chars", type=float, default=MAX_W, help="每条最宽多少个汉字宽（默认 %g）" % MAX_W)
    ap.add_argument("--terms", default="", help="断句时不能拆开的专有名词，逗号分隔，例如 国星宇航,星算（常见公司名和文案里重复出现的词会自动加）")
    ap.add_argument("--font", help="字体名（默认 Windows 微软雅黑）")
    ap.add_argument("--font-ratio", type=float, default=FONT_RATIO, help="字号占画面宽度的比例（默认 %g）" % FONT_RATIO)
    ap.add_argument("--position", type=float, help="字幕中心的高度比例，例如 0.76；不给就自动挑")
    ap.add_argument("--translation", help="译文字幕：{\"units\": [{\"src\": 原文分句, \"text\": 译文}]}；不给就用原文案")
    ap.add_argument("--yes", action="store_true", help="用户要字幕，开始烧录。不加就只预览")
    a = ap.parse_args()
    if bool(a.workdir) == bool(a.video):
        _cli.fail(_cli.USAGE, "--workdir 和 --video 二选一")
    if a.workdir:
        od = os.path.join(a.workdir, "avatar")
        src = os.path.join(od, "final_jumpcut.mp4")
        raw_video = os.path.join(od, "final_avatar.mp4")
        copy_p = a.copy or os.path.join(a.workdir, "copy.txt")
        words_p = a.words or os.path.join(od, "words_final.json")       # 成片时间轴上的逐词时间（拼接时裁过开头）
        if not a.words and not os.path.isfile(words_p):
            words_p = os.path.join(a.workdir, "out", "words.json")        # 旧项目：没裁过，配音时间轴就是成片时间轴
        jc_p = a.jumpcut or os.path.join(od, "jumpcut.json")
        dst = os.path.join(od, "final_subtitled.mp4")
        base = os.path.join(od, "subtitles")
        if not os.path.isfile(src):
            _cli.fail(_cli.ERROR, "没有 %s：字幕加在跳剪后的成片上，先请用户确认人物视频，再运行 jumpcut.py（--user-approved \"用户回复的原话\" --yes）" % src)
        if os.path.isfile(raw_video) and os.path.getmtime(raw_video) > os.path.getmtime(src):
            _cli.fail(_cli.ERROR, "final_avatar.mp4 比 final_jumpcut.mp4 新：人物视频改过，先请用户看新的 final_avatar.mp4，确认后重跑 jumpcut.py")
    else:
        src = a.video
        if not (a.copy and a.words):
            _cli.fail(_cli.USAGE, "--video 时要同时给 --copy 和 --words")
        copy_p, words_p, jc_p = a.copy, a.words, a.jumpcut
        dst = a.out or os.path.splitext(src)[0] + "_字幕.mp4"
        base = os.path.splitext(dst)[0]
    for p, what in ((src, "视频"), (copy_p, "文案"), (words_p, "逐词时间")):
        if not os.path.isfile(p):
            _cli.fail(_cli.USAGE if a.video else _cli.ERROR, "%s不存在：%s" % (what, p))
    if os.path.abspath(src) == os.path.abspath(dst):
        _cli.fail(_cli.USAGE, "输出不能覆盖原片")
    mapping = None
    if jc_p and os.path.isfile(jc_p):
        mapping = json.load(open(jc_p, encoding="utf-8")).get("map")
    elif a.jumpcut:
        _cli.fail(_cli.USAGE, "跳剪记录不存在：%s" % a.jumpcut)

    import cv2
    cap = cv2.VideoCapture(src)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total = cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    cap.release()
    if not W:
        _cli.fail(_cli.ERROR, "读不出视频：%s" % src)
    copy = open(copy_p, encoding="utf-8-sig").read()
    terms = re.split(r"[,，、]", a.terms)
    units = load_translation(a.translation, copy) if a.translation else None
    raw = build_translated(load_words(words_p), units, a.max_chars, terms) if units else build(load_words(words_p), copy, a.max_chars, terms)
    cues = cues_from(raw, mapping, total)
    if not cues:
        _cli.fail(_cli.ERROR, "没有生成任何字幕：检查文案和逐词时间")
    font_name, fonts_dir = font_setup(a.font)
    font_px = int(round(W * a.font_ratio))
    center = a.position if a.position else pick_band(src, font_px, H)

    joined = re.sub(STRIP, "", "".join(c["text"] for c in cues))
    want = re.sub(STRIP, "", "".join(u["text"] for u in units) if units else copy)
    same_name = "文字和译文一致" if units else "文字和文案一致"
    widest = max(width(c["text"]) for c in cues)
    overlaps = sum(1 for x, y in zip(cues, cues[1:]) if x["end"] > y["start"] + 1e-3)
    checks = [(same_name, "一致" if joined == want else "不一致（%d 字 / 应为 %d 字）" % (len(joined), len(want)), joined == want),
              ("每条一行", "最宽 %.1f 个字宽（上限 %.1f）" % (widest, a.max_chars + SLACK), widest <= a.max_chars + SLACK + 1e-6),
              ("不重叠、不超出视频", "重叠 %d 处，最后一条到 %.2f 秒（视频 %.2f 秒）" % (overlaps, cues[-1]["end"], total),
               overlaps == 0 and cues[-1]["end"] <= total + 0.05)]
    short = [c for c in cues if c["end"] - c["start"] < 0.8]
    report = dict(translation=bool(units), cues=len(cues), font=font_name, font_px=font_px, center_y=center, widest=round(widest, 2),
                  short_cues=[{"text": c["text"], "start": c["start"], "seconds": round(c["end"] - c["start"], 2)} for c in short],
                  checks=[{"name": n, "value": v, "ok": ok} for n, v, ok in checks])
    if not a.yes:
        for c in cues:
            print("%7.2f–%7.2f  %s" % (c["start"], c["end"], c["text"]))
        print("\n[预览] %d 条字幕，%s %dpx，中心在画面 %.0f%% 高度。没有出文件。" % (len(cues), font_name, font_px, center * 100))
        for n, v, ok in checks:
            print("%s %s：%s" % ("✓" if ok else "✗", n, v))
        print("字幕是附加功能：用户说要字幕，再加 --yes。")
        _cli.report(preview=True, **report)
        if not all(ok for _, _, ok in checks):
            sys.exit(_cli.ERROR)
        return
    if not all(ok for _, _, ok in checks):
        for n, v, ok in checks:
            print("%s %s：%s" % ("✓" if ok else "✗", n, v))
        _cli.report(**report)
        _cli.fail(_cli.ERROR, "字幕自检没过，没有烧录")

    tmp = tempfile.mkdtemp(prefix="captions_")
    locked = None
    try:
        margin_v = write_ass(os.path.join(tmp, "subs.ass"), cues, W, H, font_name, font_px, center)
        vf = "subtitles=subs.ass"
        if fonts_dir:
            vf += ":fontsdir='%s'" % fonts_dir.replace("\\", "/").replace(":", "\\:")
        subprocess.run([_util.ffmpeg_exe(), "-y", "-v", "error", "-i", os.path.abspath(src), "-vf", vf, "-c:v", "libx264", "-crf", "18",
                        "-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", "out.mp4"],
                       check=True, cwd=tmp)
        shutil.copy2(os.path.join(tmp, "subs.ass"), base + ".ass")
        write_srt(base + ".srt", cues)
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        try:
            shutil.move(os.path.join(tmp, "out.mp4"), dst)
        except PermissionError:
            locked = dst
            dst = os.path.splitext(dst)[0] + "_新.mp4"
            shutil.move(os.path.join(tmp, "out.mp4"), dst)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    sheet = check_sheet(dst, cues, base + "_check.jpg")
    json.dump({"video": os.path.abspath(dst), "source": os.path.abspath(src), "margin_v": margin_v, **report, "cues": cues},
              open(base + ".json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.workdir:
        mp = os.path.join(a.workdir, "meta.json")
        if os.path.isfile(mp):
            meta = json.load(open(mp, encoding="utf-8"))
            meta["avatar_video_subtitled"] = os.path.abspath(dst)
            json.dump(meta, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("加字幕：%s" % dst)
    print("%d 条，%s %dpx，中心在画面 %.0f%% 高度" % (len(cues), font_name, font_px, center * 100))
    for n, v, ok in checks:
        print("%s %s：%s" % ("✓" if ok else "✗", n, v))
    if short:
        print("停留不到 0.8 秒的：%s" % "、".join("%s（%.1f 秒）" % (c["text"], c["end"] - c["start"]) for c in short))
    print("字幕文件：%s.srt、%s.ass；抽帧图（要看）：%s" % (base, base, sheet))
    _cli.report(out=os.path.abspath(dst), srt=base + ".srt", ass=base + ".ass", record=base + ".json", check_sheet=sheet, **report)
    if locked:
        print("%s 被其他程序占用（多半是播放器），新的已另存为 %s。关掉播放器后重跑同一条命令即可。" % (locked, dst))
        _cli.report(locked=locked)
        sys.exit(_cli.FILE_LOCKED)


if __name__ == "__main__":
    _cli.run(main)
