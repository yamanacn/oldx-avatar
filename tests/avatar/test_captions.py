"""底部字幕（avatar/captions.py）的离线测试：断句、时间换算、预览、烧录。
  python tests/avatar/test_captions.py
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "..", "scripts")
CAP = os.path.join(SCRIPTS, "avatar", "captions.py")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(SCRIPTS, "avatar"))
import _util             # noqa: E402
import captions as C     # noqa: E402

TMP = tempfile.mkdtemp(prefix="captions_test_")
cases = []


def check(name, ok, extra=""):
    print("✓" if ok else "✗", name, "" if ok else extra)
    cases.append(bool(ok))


def fake_words(tokens, t0=0.0, rate=0.2, gaps=None):
    """识别结果的样子：一个个词，每个字 rate 秒；gaps={词序号: 词前的停顿秒数}"""
    out, t = [], t0
    for k, w in enumerate(tokens):
        t += (gaps or {}).get(k, 0.0)
        d = rate * len(re.sub(C.STRIP, "", w))
        out.append({"word": w, "text": w, "start": round(t, 3), "end": round(t + d, 3)})
        t += d
    return out


# ---------------------------------------------------------------- 断句
copy = ("这是数字生命卡兹克最近一篇文章里的判断，值得讲一讲。事情的起点，是一个开发者被Adobe的退订违约金恶心到了。"
        "光是对应Photoshop的那个项目，不到十天，就拿了四万六千个星标。接着就有人把苹果的隔空投送搬到了别的系统上。"
        "现在，AI把这个成本打下来了。")
tokens = ["这是", "数字", "生命", "卡兹克", "最近", "一篇", "文章", "里的", "判断", "值得", "讲一讲", "事情的", "起点", "是", "一个", "开发者",
          "被", "Adobe", "的", "退订", "违约金", "恶心", "到了", "光是", "对应", "Photoshop", "的", "那个", "项目", "不到", "十天", "就", "拿了",
          "四万", "六千个", "星标", "接着", "就", "有人", "把", "苹果的", "隔空投送", "搬到了", "别的", "系统", "上", "现在", "AI", "把这个",
          "成本", "打下来了"]
raw = C.build(fake_words(tokens), copy)
texts = [r[0] for r in raw]
print("   断句：" + " | ".join(texts))
check("字幕拼起来和文案逐字一致", re.sub(C.STRIP, "", "".join(texts)) == re.sub(C.STRIP, "", copy))
check("每条都在一行以内", all(C.width(t) <= C.MAX_W + C.SLACK for t in texts), [t for t in texts if C.width(t) > C.MAX_W + C.SLACK])
check("不跨句合并：上一句的结尾和下一句的开头不在同一条里",
      not any("讲一讲" in t and "事情" in t for t in texts) and not any("星标" in t and "接着" in t for t in texts))
check("不断在词中间：隔空投送、Photoshop、四万六千 都完整", any("隔空投送" in t for t in texts) and any("Photoshop" in t for t in texts)
      and any("四万六千" in t for t in texts))
check("没有一条以“的”这类字开头", not any(t[:1] in C.BAD_START for t in texts), texts)
check("句末句号去掉，句中逗号保留", not any(t.endswith("。") for t in texts) and any("，" in t for t in texts))
check("每条的时间先后不乱", all(a[1] <= b[1] for a, b in zip(raw, raw[1:])))
cues = C.cues_from(raw, None, 60.0)
check("中文和英文之间留空格", any("被 Adobe 的" in c["text"] for c in cues) and any("AI 把这个" in c["text"] for c in cues))
check("相邻两条不重叠", all(x["end"] <= y["start"] + 1e-6 for x, y in zip(cues, cues[1:])))

# ---------------------------------------------------------------- 专有名词不拆开
c2 = "大幅降低对英伟达与AMD的算力依赖，挑战英伟达霸权。同日，国星宇航以一箭八星成功发射卫星星座。"
w2 = fake_words(["大幅", "降低", "对", "英", "伟", "达", "与", "AMD", "的", "算力", "依赖", "挑战", "英", "伟", "达", "霸权", "同日", "国", "星",
                 "宇", "航", "以", "一箭八星", "成功", "发射", "卫星", "星座"])
t2 = [x[0] for x in C.build(w2, c2, max_w=8, terms=["国星宇航"])]
print("   断句：" + " | ".join(t2))
check("专有名词不拆开：重复出现的“英伟达”自动保护，--terms 给的“国星宇航”也不拆",
      not any(t.endswith("对英") or t.startswith("伟达") for t in t2) and not any(t.endswith("国星") for t in t2), t2)

# ---------------------------------------------------------------- 识别有错字也能对上时间
ws = fake_words(["你电脑", "里装的", "每一个", "软件"]) + fake_words(["可能", "都要", "被迫", "开元了"], t0=3.0)       # “开源”识别成“开元”
r2 = C.build(ws, "你电脑里装的每一个软件，可能都要被迫开源了。")
check("识别有同音错字：文字仍是原文，时间对到识别结果上", [x[0] for x in r2] == ["你电脑里装的每一个软件", "可能都要被迫开源了"]
      and abs(r2[1][1] - 3.0) < 0.05 and r2[1][2] > 4.0, r2)

# ---------------------------------------------------------------- 跳剪后的时间换算
mapping = [{"src_start": 0.0, "src_end": 2.0, "out_start": 0.0}, {"src_start": 2.5, "src_end": 5.0, "out_start": 2.0}]
check("原片时间换算到跳剪后：保留的部分平移", abs(C.to_out(3.0, mapping, "start") - 2.5) < 1e-9)
check("落在被剪掉的静音里：起点挪到下一截开头，终点挪到上一截结尾",
      abs(C.to_out(2.2, mapping, "start") - 2.0) < 1e-9 and abs(C.to_out(2.2, mapping, "end") - 2.0) < 1e-9)

# ---------------------------------------------------------------- 整体：合成一条视频，预览和烧录
src = os.path.join(TMP, "口播.mp4")
subprocess.run([_util.ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=432x768:rate=24:duration=12",
                "-f", "lavfi", "-i", "sine=frequency=220:duration=12", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", src],
               check=True)
cp, wp = os.path.join(TMP, "copy.txt"), os.path.join(TMP, "words.json")
open(cp, "w", encoding="utf-8").write("你电脑里装的每一个软件，可能都要被迫开源了。这是数字生命卡兹克最近一篇文章里的判断。")
json.dump({"words": fake_words(["你电脑", "里装的", "每一个", "软件", "可能", "都要", "被迫", "开源了", "这是", "数字", "生命", "卡兹克",
                                "最近", "一篇", "文章", "里的", "判断"], t0=0.3, rate=0.25, gaps={8: 0.6})}, open(wp, "w", encoding="utf-8"),
          ensure_ascii=False)
out = os.path.join(TMP, "口播_字幕.mp4")


def run(*args):
    r = subprocess.run([sys.executable, CAP, *args, "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        j = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
    except ValueError:
        j = {}
    return r, j


r, j = run("--video", src, "--copy", cp, "--words", wp, "--out", out)
check("不加 --yes：只预览字幕和位置，不出文件", r.returncode == 0 and j.get("preview") is True and j.get("cues", 0) >= 3
      and not os.path.isfile(out), r.stderr[-300:])
check("字幕整行落在画面 68%–80% 高度", 0.68 <= (j.get("center_y") or 0) <= 0.80, j.get("center_y"))
r, j = run("--video", src, "--copy", cp, "--words", wp, "--out", out, "--yes")
check("加 --yes：烧录成功，自检都过", r.returncode == 0 and os.path.isfile(out) and all(c["ok"] for c in j.get("checks", [])), r.stderr[-400:])
srt = open(os.path.splitext(out)[0] + ".srt", encoding="utf-8").read()
check(".srt 的条数和字幕一致、带时间", srt.count(" --> ") == j.get("cues") and "00:00:00," in srt)
check(".ass 里是一行一条、微软雅黑（或系统字体）", "Style: Sub," in open(os.path.splitext(out)[0] + ".ass", encoding="utf-8").read())
check("抽帧图写出来了", j.get("check_sheet") and os.path.isfile(j["check_sheet"]))
check("画面时长没变、声音原样带过来", abs((_util.media_seconds(out) or 0) - 12.0) < 0.15)
r, j = run("--video", src, "--copy", cp, "--words", wp, "--out", src, "--yes")
check("输出写成原片：退出码 2", r.returncode == 2)
r, j = run("--video", src, "--out", out)
check("--video 时缺 --copy / --words：退出码 2", r.returncode == 2)

# ---------------------------------------------------------------- 项目目录模式
wd = os.path.join(TMP, "proj")
os.makedirs(os.path.join(wd, "avatar"))
os.makedirs(os.path.join(wd, "out"))
shutil.copy2(cp, os.path.join(wd, "copy.txt"))
shutil.copy2(wp, os.path.join(wd, "out", "words.json"))
r, j = run("--workdir", wd)
check("还没跳剪：退出码 1，提示先 jumpcut", r.returncode == 1 and "jumpcut" in (j.get("error") or ""))
shutil.copy2(src, os.path.join(wd, "avatar", "final_jumpcut.mp4"))
time.sleep(0.05)
shutil.copy2(src, os.path.join(wd, "avatar", "final_avatar.mp4"))
os.utime(os.path.join(wd, "avatar", "final_avatar.mp4"), None)
r, j = run("--workdir", wd)
check("人物视频比跳剪版新（改过没重跳剪）：退出码 1", r.returncode == 1 and "jumpcut" in (j.get("error") or ""), j.get("error"))
os.utime(os.path.join(wd, "avatar", "final_jumpcut.mp4"), (time.time() + 5, time.time() + 5))
json.dump({"map": [{"src_start": 0.0, "src_end": 12.0, "out_start": 0.0}]}, open(os.path.join(wd, "avatar", "jumpcut.json"), "w"))
json.dump({"id": "x"}, open(os.path.join(wd, "meta.json"), "w"))
r, j = run("--workdir", wd, "--yes")
check("项目目录模式：写 avatar/final_subtitled.mp4、subtitles.srt，meta.json 记下路径",
      r.returncode == 0 and os.path.isfile(os.path.join(wd, "avatar", "final_subtitled.mp4")) and os.path.isfile(os.path.join(wd, "avatar", "subtitles.srt"))
      and json.load(open(os.path.join(wd, "meta.json"), encoding="utf-8")).get("avatar_video_subtitled"), r.stderr[-400:])

# ---- 译文字幕：英文配音、中文字幕
en = "Wall Street saw a pullback today, as inflation data poured cold water on the market. See you tomorrow!"
ew = [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.35} for i, w in enumerate(re.findall(r"[A-Za-z]+", en))]
units = [{"src": "Wall Street saw a pullback today,", "text": "华尔街今天出现回调，"},
         {"src": "as inflation data poured cold water on the market.", "text": "最新通胀数据高于预期，给近来火热的市场泼了冷水。"},
         {"src": "See you tomorrow!", "text": "明天见！"}]
raw = C.build_translated(ew, units)
check("译文字幕：每条一行，文字拼起来等于译文", all(C.width(t) <= C.MAX_W + C.SLACK for t, _, _ in raw)
      and re.sub(C.STRIP, "", "".join(t for t, _, _ in raw)) == re.sub(C.STRIP, "", "".join(u["text"] for u in units)), raw)
check("译文字幕：时间跟着各句原文（第一句从 0 开始，第二句从 as 开始，最后一句从 See 开始）",
      abs(raw[0][1]) < 1e-6 and abs([x for x in raw if x[0].startswith("最新")][0][1] - 6 * 0.4) < 1e-6
      and abs(raw[-1][1] - 15 * 0.4) < 1e-6, raw)
check("译文字幕：时间顺序递增、不重叠", all(a[2] <= b[1] + 1e-6 and a[1] < a[2] for a, b in zip(raw, raw[1:])), raw)
tp = os.path.join(TMP, "tr.json")
json.dump({"units": units[:2]}, open(tp, "w", encoding="utf-8"), ensure_ascii=False)
try:
    C.load_translation(tp, en)
    check("译文字幕：src 漏了一句时拒绝", False)
except SystemExit as e:
    check("译文字幕：src 漏了一句时拒绝", e.code == 1, e.code)

print("\n通过 %d/%d" % (sum(cases), len(cases)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(cases) else 1)
