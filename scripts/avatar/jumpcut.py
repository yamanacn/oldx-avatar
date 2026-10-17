"""跳剪：剪掉成片里说话之间的停顿，只留两头一点余量，节奏更紧（真人口播的常规剪法）。原片不动。

  python jumpcut.py --workdir <项目目录>                 # 预览：会剪几处、剪成多长，不出文件
  python jumpcut.py --workdir <项目目录> --user-approved "用户回复的原话" --yes   # avatar/final_avatar.mp4 → avatar/final_jumpcut.mp4
  python jumpcut.py --video <任意视频> --out <输出.mp4> --user-approved "用户回复的原话" --yes   # 别处做好的口播视频也能剪

前提：用户已经看过 final_avatar.mp4、确认人物视频没问题（嘴、手、画面都不用再重跑）。跳剪之后再改某一段，
要从 finalize 重来，所以先确认、再剪。不加 --yes 只预览。
用户确认这一步写在代码里，不只是说明：--yes 必须同时给 --user-approved，内容是用户在对话里回复的原话
（例如“没问题，开始跳剪”；用户一开始就说过“不用给我看，直接剪”也算，填那句话）。用户还没回复就停下等，不能自己编。
项目里会把这句话和当时的 final_avatar.mp4 记进 avatar/review.json；之后只要 final_avatar.mp4 没变，重跑不用再给；
final_avatar.mp4 重新拼过（换了版本、重跑了某段），旧的确认作废，要请用户再看一次。

规则（2026-10-14 用户看片后定）：
  * 停顿用的是和逐词对齐同一个检测（_util.detect_pauses：连续低于 95 分位音量 5% 的低能量段），开头、结尾的静音也算。
  * 两段静音之间只隔着不到 0.1 秒的声音（气声、咔哒），算同一个停顿。否则停顿被劈成两半，后一半不够长就漏剪，
    成片里会留下一个明显的小停顿（实测：0.76 秒的停顿中间夹 0.04 秒杂音，剪完还剩约 0.5 秒）。
    合并时至少一边是 0.25 秒以上的真停顿；几处很短的静音连在一起不合并，免得剪掉说话中间的音。
  * 0.3 秒以上的停顿剪掉，前后各留 0.08 秒，句子不显得赶；短于 0.3 秒的不动，那是句子里自然的气口。
  * 画面先统一成恒定帧率，切点落在帧边界上，声音和画面在同一时刻切：每一截的帧数和音频长度严格相等，口型不会错位。
    每个接口的声音做 8 毫秒淡入淡出，防止爆音。
  * 剪辑点前后画面会跳一下（主要是手），这是跳剪的正常现象，不补救；跳得明显的剪辑点（前后帧差超过全片中位数 3 倍）
    列在结果里，并出一张前后对比图。
  * final_avatar.mp4 的时间轴和 words_final.json、anomalies.json 对应，后期包装仍用它；剪后和剪前的时间对应在 jumpcut.json 的 map 里。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import _cli  # noqa: E402
import _util  # noqa: E402

DETECT_MIN = 0.25    # 真停顿的下限（和逐词对齐的停顿一样）
PIECE_MIN = 0.1      # 被杂音劈开的半截停顿，短到这么长也要找出来，才能和旁边的真停顿合并
MIN_PAUSE = 0.3      # 这么长以上的停顿才剪
PAD = 0.08           # 剪掉的停顿两头各留这么多
MERGE_GAP = 0.1      # 两段静音之间隔着的声音短于这个，算同一个停顿
FADE = 0.008         # 每个接口声音的淡入淡出
JUMP_RATIO = 3.0     # 剪辑点前后帧差超过全片中位数这么多倍，算“跳得明显”
SHEET_MAX = 3        # 对比图最多放几处


def find_pauses(wav, min_pause, merge_gap):
    """要剪的停顿。先找 ≥PIECE_MIN 的静音片段，隔着的声音不到 merge_gap 就合并；
    合并后里面至少要有一段 ≥DETECT_MIN 的真停顿才算——几处很短的静音连在一起不算，免得剪掉说话中间的音。"""
    merged = []
    for p in _util.detect_pauses(wav, PIECE_MIN, edges=True):
        p = dict(p, long=p["end"] - p["start"] >= DETECT_MIN)
        last = merged[-1] if merged else None
        if last and p["start"] - last["end"] <= merge_gap and (last["long"] or p["long"]):
            last["end"], last["long"] = p["end"], True
        else:
            merged.append(p)
    return [{"start": p["start"], "end": p["end"]} for p in merged if p["long"] and p["end"] - p["start"] >= min_pause]


def plan_keep(pauses, total, fps, pad):
    """要保留的区间（原片时间，都在帧边界上）。开头、结尾的静音不留余量外的部分。"""
    snap = lambda t: round(t * fps) / fps
    end = snap(total)
    keep, t = [], 0.0
    for p in pauses:
        s = p["start"] + (pad if p["start"] > 0 else 0.0)
        e = p["end"] - (pad if p["end"] < total - 0.02 else 0.0)
        s, e = snap(s), snap(min(e, total))
        if e - s < 1 / fps:
            continue
        if s - t >= 1 / fps:
            keep.append((t, s))
        t = max(t, e)
    if end - t >= 1 / fps:
        keep.append((t, end))
    return keep


def render(ff, src, dst, keep, fps, tmpdir):
    parts = ["[0:v]fps=%g,split=%d%s" % (fps, len(keep), "".join("[s%d]" % k for k in range(len(keep))))]
    labels = []
    for k, (s, e) in enumerate(keep):
        parts.append("[s%d]trim=start=%.4f:end=%.4f,setpts=PTS-STARTPTS[v%d]" % (k, s, e, k))
        parts.append("[0:a]atrim=start=%.4f:end=%.4f,asetpts=PTS-STARTPTS,afade=t=in:d=%.3f,afade=t=out:st=%.4f:d=%.3f[a%d]"
                     % (s, e, FADE, max(0.0, e - s - FADE), FADE, k))
        labels.append("[v%d][a%d]" % (k, k))
    fc = ";".join(parts) + ";" + "".join(labels) + "concat=n=%d:v=1:a=1[v][a]" % len(keep)
    script = os.path.join(tmpdir, "filter.txt")
    open(script, "w", encoding="utf-8").write(fc)
    subprocess.run([ff, "-y", "-v", "error", "-i", src, "-filter_complex_script", script, "-map", "[v]", "-map", "[a]",
                    "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", "%g" % fps,
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", dst], check=True)


def jumps(video, cut_points, sheet):
    """顺序解码成片，量每个剪辑点前后的帧差；跳得明显的几处拼一张前后对比图（每行一处：切点前两帧、后两帧）。"""
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    want = {}
    for c, t in enumerate(cut_points):
        k = int(round(t * fps))
        for j in (k - 2, k - 1, k, k + 1):
            want.setdefault(j, []).append(c)
    thumbs, diffs, prev, i = {}, [], None, 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        g = cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (160, int(160 * f.shape[0] / f.shape[1]))).astype(np.float32)
        if prev is not None:
            diffs.append(float(np.abs(g - prev).mean()))
        prev = g
        if i in want:
            thumbs[i] = cv2.resize(f, (200, int(200 * f.shape[0] / f.shape[1])))
        i += 1
    cap.release()
    frames = i
    if not diffs:
        return [], frames / fps, None
    med = float(np.median(diffs)) or 1e-6
    res = []
    for t in cut_points:
        k = int(round(t * fps))
        if 1 <= k <= len(diffs):
            res.append({"t": round(t, 3), "ratio": round(diffs[k - 1] / med, 2)})
    big = sorted([r for r in res if r["ratio"] > JUMP_RATIO], key=lambda r: -r["ratio"])
    out_sheet = None
    if big:
        rows = []
        for r in big[:SHEET_MAX]:
            k = int(round(r["t"] * fps))
            cells = [thumbs.get(j) for j in (k - 2, k - 1, k, k + 1)]
            if any(c is None for c in cells):
                continue
            cells = [c.copy() for c in cells]
            for n, c in enumerate(cells):
                cv2.rectangle(c, (0, 0), (150, 28), (0, 0, 0), -1)
                cv2.putText(c, "%.2fs %s" % (r["t"], "before" if n < 2 else "after"), (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
            rows.append(cv2.hconcat(cells))
        if rows:
            _util.imwrite(sheet, cv2.vconcat(rows))
            out_sheet = sheet
    return big, frames / fps, out_sheet


REVIEW = "review.json"
WAIT_NEXT = ("停下，不要运行跳剪：把 %s 的路径、时长和质检结果发给用户，问视频有没有问题、能不能跳剪，等用户回复。"
             "用户回复确认后，再用 --user-approved \"用户回复的原话\" --yes 执行")


def video_sig(path):
    st = os.stat(path)
    return {"size": st.st_size, "mtime": round(st.st_mtime, 3)}


def check_approval(a, src):
    """--yes 之前核对用户确认过：本次给了 --user-approved（项目里记进 review.json），或者 review.json 里有对这一版
    final_avatar.mp4 的确认。都没有就以 need_user 退出，不剪。返回用户的原话。"""
    text = (a.user_approved or "").strip()
    rp = os.path.join(a.workdir, "avatar", REVIEW) if a.workdir else None
    if text:
        if rp:
            json.dump({"approved": text, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "video": os.path.abspath(src), **video_sig(src)},
                      open(rp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return text
    if rp and os.path.isfile(rp):
        try:
            rec = json.load(open(rp, encoding="utf-8"))
        except (OSError, ValueError):
            rec = {}
        if rec.get("approved") and rec.get("size") == video_sig(src)["size"] and rec.get("mtime") == video_sig(src)["mtime"]:
            return rec["approved"]
        why = "final_avatar.mp4 在用户确认之后重新拼过，旧的确认作废，要请用户再看一次"
    else:
        why = "还没有用户确认的记录"
    _cli.report(next=WAIT_NEXT % src, wait_for_user=True)
    _cli.fail(_cli.NEED_USER, "跳剪要用户先看过人物视频并确认（%s）。--yes 必须带 --user-approved \"用户回复的原话\"；"
                              "用户还没回复就停下等，不要自己填。" % why)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", help="项目目录：剪 avatar/final_avatar.mp4，写 avatar/final_jumpcut.mp4")
    ap.add_argument("--video", help="不在项目里的视频：直接给路径")
    ap.add_argument("--out", help="输出路径（给了 --video 时用；不给就在原视频旁边加 _跳剪）")
    ap.add_argument("--min-pause", type=float, default=MIN_PAUSE, help="这么长以上的停顿才剪（默认 %.2f 秒）" % MIN_PAUSE)
    ap.add_argument("--pad", type=float, default=PAD, help="剪掉的停顿两头各留多少（默认 %.2f 秒）" % PAD)
    ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--user-approved", default="", help="用户确认可以跳剪时在对话里回复的原话（--yes 必须带上）")
    ap.add_argument("--yes", action="store_true", help="用户已经确认人物视频没问题，开始剪。不加就只预览")
    a = ap.parse_args()
    if bool(a.workdir) == bool(a.video):
        _cli.fail(_cli.USAGE, "--workdir 和 --video 二选一")
    if a.workdir:
        od = os.path.join(a.workdir, "avatar")
        src, dst = os.path.join(od, "final_avatar.mp4"), os.path.join(od, "final_jumpcut.mp4")
        record, sheet = os.path.join(od, "jumpcut.json"), os.path.join(od, "jumpcut_points.jpg")
        if not os.path.isfile(src):
            _cli.fail(_cli.ERROR, "没有 %s：先运行 finalize.py" % src)
    else:
        src = a.video
        if not os.path.isfile(src):
            _cli.fail(_cli.USAGE, "视频不存在：%s" % src)
        dst = a.out or os.path.splitext(src)[0] + "_跳剪.mp4"
        base = os.path.splitext(dst)[0]
        record, sheet = base + "_剪辑记录.json", base + "_剪辑点.jpg"
    if os.path.abspath(src) == os.path.abspath(dst):
        _cli.fail(_cli.USAGE, "输出不能覆盖原片")
    if a.pad * 2 >= a.min_pause:
        _cli.fail(_cli.USAGE, "--pad 的两倍要小于 --min-pause，否则剪不掉东西")
    approved = check_approval(a, src) if a.yes else None

    ff = _util.ffmpeg_exe()
    tmpdir = tempfile.mkdtemp(prefix="jumpcut_")
    try:
        wav = os.path.join(tmpdir, "audio.wav")
        subprocess.run([ff, "-y", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", wav], check=True)
        total = _util.wav_seconds(wav)
        pauses = find_pauses(wav, a.min_pause, MERGE_GAP)
        keep = plan_keep(pauses, total, a.fps, a.pad)
        if not keep:
            _cli.fail(_cli.ERROR, "整条都是静音，没有可保留的内容：%s" % src)
        if not a.yes:
            plan_s = sum(e - s for s, e in keep)
            print("[预览] %s：%.1f 秒 → 约 %.1f 秒，剪掉 %.1f 秒，%d 个剪辑点。没有出文件。" % (src, total, plan_s, total - plan_s, len(keep) - 1))
            print("跳剪之前先停下：把 %s 的路径、时长和质检结果发给用户，问视频有没有问题、能不能跳剪，等用户回复。" % src)
            print("用户回复确认后，用 --user-approved \"用户回复的原话\" --yes 执行。")
            _cli.report(next=WAIT_NEXT % src, wait_for_user=True, preview=True, source=os.path.abspath(src), source_seconds=round(total, 3), out_seconds=round(plan_s, 3),
                        removed_seconds=round(total - plan_s, 3), cuts=len(keep) - 1)
            return
        tmp_out = os.path.join(tmpdir, "out.mp4")
        render(ff, src, tmp_out, keep, a.fps, tmpdir)
        aw = os.path.join(tmpdir, "out.wav")
        subprocess.run([ff, "-y", "-v", "error", "-i", tmp_out, "-vn", "-ac", "1", "-c:a", "pcm_s16le", aw], check=True)
        audio_s = _util.wav_seconds(aw)
        locked = None
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        try:
            shutil.move(tmp_out, dst)
        except PermissionError:
            locked = dst
            dst = os.path.splitext(dst)[0] + "_新.mp4"
            shutil.move(tmp_out, dst)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    out_s = sum(e - s for s, e in keep)
    cut_points, acc, mapping = [], 0.0, []
    for s, e in keep:
        mapping.append({"src_start": round(s, 3), "src_end": round(e, 3), "out_start": round(acc, 3)})
        acc += e - s
        cut_points.append(round(acc, 3))
    cut_points = cut_points[:-1]
    big, video_s, sheet_out = jumps(dst, cut_points, sheet)
    checks = [("画面时长", "%.3f 秒（应为 %.3f）" % (video_s, out_s), abs(video_s - out_s) <= 1.5 / a.fps),
              ("音画同步", "音频 %.3f 秒、画面 %.3f 秒" % (audio_s, video_s), abs(audio_s - video_s) <= 0.05)]
    rec = {"approved_by_user": approved, "source": os.path.abspath(src), "out": os.path.abspath(dst), "source_seconds": round(total, 3), "out_seconds": round(out_s, 3),
           "removed_seconds": round(total - out_s, 3), "cuts": len(cut_points), "rule": {"min_pause": a.min_pause, "pad": a.pad,
           "merge_gap": MERGE_GAP, "fps": a.fps}, "pauses_cut": pauses, "map": mapping, "cut_points": cut_points,
           "big_jumps": big, "jump_sheet": sheet_out, "checks": [{"name": n, "value": v, "ok": ok} for n, v, ok in checks]}
    json.dump(rec, open(record, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if a.workdir:
        mp = os.path.join(a.workdir, "meta.json")
        if os.path.isfile(mp):
            m = json.load(open(mp, encoding="utf-8"))
            m["avatar_video_jumpcut"] = os.path.abspath(dst)
            json.dump(m, open(mp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("跳剪：%s" % dst)
    print("原长 %.1f 秒 → %.1f 秒，剪掉 %.1f 秒，%d 个剪辑点" % (total, out_s, total - out_s, len(cut_points)))
    for n, v, ok in checks:
        print("%s %s：%s" % ("✓" if ok else "✗", n, v))
    if big:
        print("跳得明显的剪辑点 %d 处（主要是手的位置跳一下，跳剪正常现象）：%s" % (len(big), "、".join("%.1f 秒" % r["t"] for r in big)))
        if sheet_out:
            print("前后对比图：%s" % sheet_out)
    print("剪辑记录：%s" % record)
    _cli.report(approved_by_user=approved, out=os.path.abspath(dst), record=record, source_seconds=round(total, 3), out_seconds=round(out_s, 3),
                removed_seconds=round(total - out_s, 3), cuts=len(cut_points), big_jumps=big, jump_sheet=sheet_out,
                checks=[{"name": n, "value": v, "ok": ok} for n, v, ok in checks])
    if locked:
        print("%s 被其他程序占用（多半是播放器），新的已另存为 %s。关掉播放器后重跑同一条命令即可。" % (locked, dst))
        _cli.report(locked=locked)
        sys.exit(_cli.FILE_LOCKED)
    if not all(ok for _, _, ok in checks):
        sys.exit(_cli.ERROR)


if __name__ == "__main__":
    _cli.run(main)
