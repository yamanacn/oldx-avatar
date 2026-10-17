"""跳剪（avatar/jumpcut.py）的离线测试：用合成的视频（画面在动、声音是一段一段的音加停顿）跑一遍。
  python tests/avatar/test_jumpcut.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import wave

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "..", "scripts")
JC = os.path.join(SCRIPTS, "avatar", "jumpcut.py")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, os.path.join(SCRIPTS, "avatar"))
import _util          # noqa: E402

TMP = tempfile.mkdtemp(prefix="jumpcut_test_")
cases = []


def check(name, ok, extra=""):
    print("✓" if ok else "✗", name, "" if ok else extra)
    cases.append(bool(ok))


SR = 48000
# 开头静音 0.5；词 1.0；停顿 0.2（气口，不剪）；词；两处 0.16 的短静音夹 0.04 的音（都不是真停顿，不能连起来剪）；词；停顿 0.6（剪）；词；停顿 0.46 + 杂音 0.04 + 0.26（算一个 0.76 的停顿；后一半单独不够剪）；词；停顿 0.5；词；结尾静音 0.6
LAYOUT = [("q", 0.5), ("w", 1.0), ("q", 0.2), ("w", 1.0), ("q", 0.16), ("blip", 0.04), ("q", 0.16), ("w", 1.0), ("q", 0.6), ("w", 1.0), ("q", 0.46), ("blip", 0.04), ("q", 0.26),
          ("w", 1.0), ("q", 0.5), ("w", 1.0), ("q", 0.6)]


def make_video(path):
    parts = []
    for k, (kind, d) in enumerate(LAYOUT):
        n = int(d * SR)
        t = np.arange(n) / SR
        if kind == "w":
            parts.append(np.sin(t * 2 * np.pi * (180 + 20 * k)) * 9000)
        elif kind == "blip":
            parts.append(np.sin(t * 2 * np.pi * 900) * 6000)
        else:
            parts.append(np.zeros(n))
    x = np.concatenate(parts).astype(np.int16)
    wav = os.path.join(TMP, "src.wav")
    w = wave.open(wav, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(x.tobytes())
    w.close()
    dur = len(x) / SR
    subprocess.run([_util.ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=24:duration=%.3f" % dur,
                    "-i", wav, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", path], check=True)
    return dur


def run(*args):
    r = subprocess.run([sys.executable, JC, *args, "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        j = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
    except ValueError:
        j = {}
    return r, j


def audio_of(video):
    wav = os.path.join(TMP, os.path.basename(video) + ".wav")
    subprocess.run([_util.ffmpeg_exe(), "-y", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", wav], check=True)
    return wav


src = os.path.join(TMP, "口播.mp4")
dur = make_video(src)
sha = _util.file_sha(src)
out = os.path.join(TMP, "口播_剪.mp4")
r, j = run("--video", src, "--out", out)
check("不加 --yes：只预览（报剪几处、剪成多长），不出文件", r.returncode == 0 and j.get("preview") is True and j.get("cuts") == 3
      and not os.path.isfile(out), r.stderr[-300:])
r, j = run("--video", src, "--out", out, "--yes")
check("--yes 不带 --user-approved：退出码 5（need_user），不剪、不出文件，结果里 wait_for_user",
      r.returncode == 5 and j.get("wait_for_user") is True and not os.path.isfile(out) and "停下" in (j.get("next") or ""), (r.returncode, j))
r, j = run("--video", src, "--out", out, "--user-approved", "没问题，开始跳剪", "--yes")
# 预计剪掉：开头 0.5（前面不留余量，只留 0.08）0.42 + 0.6→0.44 + 0.76→0.60 + 0.5→0.34 + 结尾 0.6→0.52 = 2.32
check("跳剪成功，两项自检都过", r.returncode == 0 and all(c["ok"] for c in j.get("checks", [])), r.stderr[-300:])
check("剪掉的时长对（约 2.3 秒）", abs((j.get("removed_seconds") or 0) - 2.32) < 0.15, j.get("removed_seconds"))
check("剪辑点数对：中间 3 处停顿各一个（开头、结尾的静音不算剪辑点）", j.get("cuts") == 3, j.get("cuts"))
rest = _util.detect_pauses(audio_of(out), 0.3, edges=True)
check("成片里不再有 0.3 秒以上的静音（包括被杂音劈成两半的那一处）", rest == [], rest)
short = [p for p in _util.detect_pauses(audio_of(out), 0.15) if 0.15 <= p["end"] - p["start"] < 0.3]
check("0.2 秒的气口原样保留", len(short) >= 1, short)
src_len = _util.wav_seconds(audio_of(src)) - _util.wav_seconds(audio_of(out))
check("两处短静音夹着一下音：不合并、不剪（剪掉的总量里没有它）", abs(src_len - 2.32) < 0.15, src_len)
rec = json.load(open(os.path.splitext(out)[0] + "_剪辑记录.json", encoding="utf-8"))
check("剪辑记录里有用户确认的原话", rec.get("approved_by_user") == "没问题，开始跳剪", rec.get("approved_by_user"))
check("剪辑记录里有时间对应（map）和剪辑点", len(rec["map"]) == 4 and len(rec["cut_points"]) == 3 and rec["map"][0]["out_start"] == 0)
merged = [p for p in rec["pauses_cut"] if 0.7 <= p["end"] - p["start"] <= 0.82]
check("中间夹着 0.04 秒杂音的两段静音合成一个停顿剪掉（不合并的话后一半 0.26 秒会漏剪）", len(merged) == 1, rec["pauses_cut"])
check("原片没被改动", _util.file_sha(src) == sha)

r, j = run("--video", src, "--out", src)
check("输出写成原片：退出码 2", r.returncode == 2)
r, j = run("--video", src, "--workdir", TMP)
check("--video 和 --workdir 同时给：退出码 2", r.returncode == 2)
r, j = run("--video", src, "--out", out, "--pad", "0.2")
check("--pad 太大（两倍不小于 --min-pause）：退出码 2", r.returncode == 2)

# ---------------------------------------------------------------- 项目目录模式
wd = os.path.join(TMP, "proj")
os.makedirs(os.path.join(wd, "avatar"))
r, j = run("--workdir", wd)
check("项目里还没有 final_avatar.mp4：退出码 1，提示先 finalize", r.returncode == 1 and "finalize" in (j.get("error") or ""))
shutil.copy2(src, os.path.join(wd, "avatar", "final_avatar.mp4"))
json.dump({"id": "x"}, open(os.path.join(wd, "meta.json"), "w"))
r, j = run("--workdir", wd, "--yes")
check("项目目录模式，没有确认记录：退出码 5，不剪", r.returncode == 5 and not os.path.isfile(os.path.join(wd, "avatar", "final_jumpcut.mp4")), r.returncode)
r, j = run("--workdir", wd, "--user-approved", "可以，剪吧", "--yes")
review = json.load(open(os.path.join(wd, "avatar", "review.json"), encoding="utf-8"))
check("项目目录模式：确认的原话记进 avatar/review.json", review.get("approved") == "可以，剪吧" and review.get("size"), review)
check("项目目录模式：写 avatar/final_jumpcut.mp4 和 avatar/jumpcut.json，meta.json 记下路径",
      r.returncode == 0 and os.path.isfile(os.path.join(wd, "avatar", "final_jumpcut.mp4")) and os.path.isfile(os.path.join(wd, "avatar", "jumpcut.json"))
      and json.load(open(os.path.join(wd, "meta.json"), encoding="utf-8")).get("avatar_video_jumpcut"), r.stderr[-300:])
check("final_avatar.mp4 保留不动（后期包装要用它的时间轴）", _util.file_sha(os.path.join(wd, "avatar", "final_avatar.mp4")) == sha)
r, j = run("--workdir", wd, "--yes")
check("人物视频没变：沿用 review.json 里的确认，不用再给原话", r.returncode == 0 and j.get("approved_by_user") == "可以，剪吧", (r.returncode, j.get("error")))
import time as _t  # noqa: E402
_t.sleep(1.1)
shutil.copy2(src, os.path.join(wd, "avatar", "final_avatar.mp4"))          # 重新拼过（修改时间变了）
os.utime(os.path.join(wd, "avatar", "final_avatar.mp4"), None)
r, j = run("--workdir", wd, "--yes")
check("人物视频重新拼过：旧的确认作废，退出码 5", r.returncode == 5 and "作废" in (j.get("error") or ""), (r.returncode, j.get("error")))

# ---------------------------------------------------------------- 输出文件被播放器占用：另存，退出码 6
import jumpcut as J    # noqa: E402
real_move = J.shutil.move
target = os.path.join(TMP, "占用.mp4")


def locked_move(a, b):
    if os.path.abspath(b) == os.path.abspath(target):
        raise PermissionError(13, "locked")
    return real_move(a, b)


J.shutil.move = locked_move
sys.argv = ["jumpcut.py", "--video", src, "--out", target, "--user-approved", "好", "--yes"]
try:
    J.main()
    code = 0
except SystemExit as e:
    code = e.code
J.shutil.move = real_move
check("输出被占用：另存为 *_新.mp4，退出码 6", code == 6 and os.path.isfile(os.path.join(TMP, "占用_新.mp4")), code)

# ---------------------------------------------------------------- status.py：质检做完、还没跳剪时，下一步是跳剪
for f in ("copy.txt", "voice.json", "paragraphs.json", "out/merged.wav", "out/words.json", "avatar/image.png", "avatar/plan.json",
          "avatar/prompt_src.json", "avatar/qa.json"):
    p = os.path.join(TMP, "st", f)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write("{}")
shutil.copy2(src, os.path.join(TMP, "st", "avatar", "final_avatar.mp4"))
r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "status.py"), "--workdir", os.path.join(TMP, "st"), "--json"],
                   capture_output=True, text=True, encoding="utf-8", errors="replace")
st = json.loads(r.stdout.strip().splitlines()[-1])
check("status：质检做完、还没跳剪 → 下一步是停下请用户看片，用户确认后才跳剪", st.get("stage") == "avatar" and "跳剪" in (st.get("next") or "")
      and "停下" in (st.get("next") or "") and "--user-approved" in (st.get("next") or ""), st.get("next"))

print("\n通过 %d/%d" % (sum(cases), len(cases)))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(0 if all(cases) else 1)
