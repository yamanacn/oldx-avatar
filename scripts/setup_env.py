"""检查这个技能要用到的东西，缺什么就自动下载安装什么，不用问用户。

  python scripts/setup_env.py                    # 两个阶段要用的全部
  python scripts/setup_env.py --stage voice      # 只管某一阶段：voice / avatar
  python scripts/setup_env.py --check            # 只看缺什么，不安装

会自动装的：
- Python 包（numpy、opencv-python、Pillow、imageio-ffmpeg、librosa、jieba）——用当前这个 Python 的 pip；
- ffmpeg——不单独装，用 imageio-ffmpeg 自带的那份。

不会自动处理的：两个密钥（必须由用户提供）。

输出 JSON：ok 是不是都齐了；installed 这次新装了什么（要告诉用户）；failed 没装上的和原因（要告诉用户怎么办）。
退出码：0 都齐了；7 有东西没装上。
"""
import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _cli


# 模块名 -> pip 包名，按阶段
PY = {
    "voice": {"numpy": "numpy", "imageio_ffmpeg": "imageio-ffmpeg", "librosa": "librosa"},
    "avatar": {"numpy": "numpy", "cv2": "opencv-python", "PIL": "Pillow", "imageio_ffmpeg": "imageio-ffmpeg",
               "jieba": "jieba"},                        # jieba：加字幕时断句用的中文分词
}


def run(cmd, cwd=None, timeout=1800):
    r = subprocess.run(cmd, cwd=cwd, shell=isinstance(cmd, str), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)[-500:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", choices=["voice", "avatar", "all"], default="all")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    stages = ["voice", "avatar"] if a.stage == "all" else [a.stage]
    present, installed, failed, missing = [], [], [], []

    def need(name, ok, install, how_if_failed):
        """ok 为真就算有；否则（不是 --check 时）调 install() 去装，装完再判断一次"""
        if ok():
            present.append(name)
            return True
        if a.check:
            missing.append(name)
            return False
        code, tail = install()
        if code == 0 and ok():
            installed.append(name)
            return True
        failed.append({"what": name, "tell_user": how_if_failed, "detail": tail.strip()[-300:]})
        return False

    # ---- Python 包
    pkgs = {}
    for s in stages:
        pkgs.update(PY[s])
    for mod, pip_name in pkgs.items():
        need(f"Python 包 {pip_name}", lambda m=mod: importlib.util.find_spec(m) is not None,
             lambda p=pip_name: (importlib.invalidate_caches(), run([sys.executable, "-m", "pip", "install", "--quiet", p]))[1],
             f"请在命令行运行：{Path(sys.executable).name} -m pip install {pip_name}")

    # ---- ffmpeg：PATH 里没有就用 imageio-ffmpeg 自带的，脚本本来就会这样找
    def ffmpeg_ok():
        if shutil.which("ffmpeg"):
            return True
        try:
            import imageio_ffmpeg
            return bool(imageio_ffmpeg.get_ffmpeg_exe())
        except Exception:
            return False
    need("ffmpeg", ffmpeg_ok, lambda: run([sys.executable, "-m", "pip", "install", "--quiet", "--force-reinstall", "imageio-ffmpeg"]),
         "请安装 ffmpeg 并确保命令行里能运行 ffmpeg")

    out = {"ok": not failed and not missing, "stage": a.stage, "present": present, "installed": installed, "failed": failed}
    if a.check:
        out["missing"] = missing
    print(json.dumps(out, ensure_ascii=False, indent=1))
    _cli.report(**{k: v for k, v in out.items() if k != "ok"})
    sys.exit(_cli.DEPS if failed else _cli.OK)


if __name__ == "__main__":
    _cli.run(main)
