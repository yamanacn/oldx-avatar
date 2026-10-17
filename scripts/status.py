"""看一个数字人项目走到哪一步了：配音、数字人各缺什么，下一步该做什么。不联网，不改任何文件。

  python scripts/status.py                 # 最近一个项目
  python scripts/status.py --workdir <workdir>
  python scripts/status.py --list          # 列出所有项目

输出 JSON：stage 是下一步该做的阶段（voice / avatar / done），next 是一句话的下一步。
"""
import argparse
import json
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _cli

ROOT = os.environ.get("DH_WORKSPACE", "").strip() or os.path.join(os.path.expanduser("~"), ".digital-human")
PROJECTS = os.path.join(ROOT, "projects")


def has(d, *parts):
    return os.path.isfile(os.path.join(d, *parts))


def load(d, *parts):
    try:
        return json.load(open(os.path.join(d, *parts), encoding="utf-8"))
    except (OSError, ValueError):
        return None


def status(d):
    meta = load(d, "meta.json") or {}
    words = load(d, "out", "words.json") or {}
    anomalies = load(d, "avatar", "anomalies.json")
    voice = {"copy": has(d, "copy.txt"), "voice": has(d, "voice.json"), "paragraphs": has(d, "paragraphs.json"),
             "audio": has(d, "out", "merged.wav"), "words": has(d, "out", "words.json")}
    avatar = {"image": has(d, "avatar", "image.png"), "plan": has(d, "avatar", "plan.json"), "prompts": has(d, "avatar", "prompt_src.json"),
              "video": has(d, "avatar", "final_avatar.mp4"), "qa": has(d, "avatar", "qa.json"),
              "jumpcut": has(d, "avatar", "final_jumpcut.mp4"),
              "subtitles": has(d, "avatar", "final_subtitled.mp4")}      # 附加功能，用户要才有；不算进度
    if not (voice["audio"] and voice["words"]):
        stage = "voice"
        nxt = next(n for k, n in (("copy", "收文案并建立项目"), ("voice", "复刻音色（或沿用默认音色）"), ("paragraphs", "通读文案并拆段"),
                                  ("audio", "合成配音"), ("words", "逐词对齐")) if not voice[k])
    elif not (avatar["video"] and avatar["qa"] and avatar["jumpcut"]):
        stage = "avatar"
        if avatar["video"] and avatar["qa"]:                 # 质检也做完了，只差最后的跳剪
            nxt = "停下请用户看 avatar/final_avatar.mp4；用户回复确认后才跳剪（jumpcut.py --user-approved \"用户回复的原话\" --yes）"
        elif avatar["video"]:                                # 人物视频已经有了，只差质检
            nxt = "做内容质检（qa_video.py），看嘴逐秒图和抽帧"
        else:
            nxt = next(n for k, n in (("image", "向用户要人物图片并处理"), ("plan", "分段"), ("prompts", "写提示词"),
                                      ("video", "预览、确认费用后提交生成，再拼接")) if not avatar[k])
    else:
        stage, nxt = "done", "配音和人物视频都已完成；用户要改哪一段就从那一阶段重做"
    return {"project_dir": d, "chars": meta.get("chars"), "seconds": words.get("total_seconds"),
            "voice": voice, "avatar": {**avatar, "anomalies": len(anomalies.get("anomalies", anomalies) if isinstance(anomalies, dict) else anomalies or [])},
            "stage": stage, "next": nxt}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", dest="dir", help="项目目录；不给就是最近一个项目")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        rows = []
        for name in sorted(os.listdir(PROJECTS)) if os.path.isdir(PROJECTS) else []:
            d = os.path.join(PROJECTS, name)
            if has(d, "meta.json"):
                s = status(d)
                head = open(os.path.join(d, "copy.txt"), encoding="utf-8").read(24).replace("\n", " ") if has(d, "copy.txt") else ""
                rows.append({"id": name, "copy": head, "seconds": s["seconds"], "stage": s["stage"]})
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        _cli.report(projects=rows)
        return
    d = a.dir
    if not d:
        latest = load(ROOT, "latest.json")
        if not latest:
            sys.exit("还没有任何项目：从收文案开始（scripts/voice/project.py init）")
        d = latest["dir"]
    st = status(d)
    print(json.dumps(st, ensure_ascii=False, indent=1))
    _cli.report(**st)


if __name__ == "__main__":
    _cli.run(main)
