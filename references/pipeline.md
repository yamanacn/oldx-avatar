# 项目目录和两个阶段之间的交接

两个阶段不直接互相调用，只通过一个共用的项目目录交接：配音把产物写进去，数字人从里面读。所以任何一步断了都能接着做，用户也可以只从数字人阶段进来。

## 项目目录

每份文案对应一个项目目录，默认在 `~/.digital-human/projects/<日期-哈希前8位>/`（Windows 是 `%USERPROFILE%\.digital-human\projects\...`；环境变量 `DH_WORKSPACE` 可以改根目录）。下文称 `workdir`。文案去掉空白后相同就算同一个项目，会直接命中已有的目录。

```
workdir/
├── copy.txt, meta.json          文案原文（一个字不改）和它的哈希、字数
├── voice.json, paragraphs.json  用的哪个音色；配音的拆段
├── emotions.json                语气描述和情绪标签规则（格式见 references/voice/emotions.example.json）
├── cache/                       各段配音的缓存
├── out/
│   ├── merged.wav               ★ 整条配音
│   ├── words.json               ★ 逐词时间和停顿
│   └── timeline.json            每段配音的起止
├── out_prev/<时间>/             重新合成出了不同结果时，上一版自动存在这里（可以对着听）
└── avatar/
    ├── image.png                处理过的人物图片
    ├── plan.json, prompt_src.json, prompts/   分段和提示词
    ├── clips/, result.json      各段原始视频、任务号和费用
    ├── takes/seg_NN/            各段的历史版本：重跑前自动收进来，带种子、工作流版本、提示词（takes.py 列出、换回）
    ├── final_avatar.mp4         人物视频，时间轴和 words_final.json、anomalies.json 对应——后期包装用它
    ├── finalize.json, words_final.json, voice_final.wav   拼接时每段开头裁掉的帧和时间对应；换算到成片上的逐词时间；和成片对齐的配音（后期包装用这两份）
    ├── final_jumpcut.mp4        ★ 跳剪后的成片（剪掉了说话之间的停顿）——本技能的最终交付
    ├── jumpcut.json, jumpcut_points.jpg   跳剪记录（剪前剪后的时间对应）和画面跳得明显的剪辑点
    ├── final_subtitled.mp4      加了底部字幕的成片（附加功能，用户要才有）
    ├── subtitles.srt/.ass/.json, subtitles_check.jpg   字幕文件、字幕记录和抽帧检查图
    ├── sheets/, seams.png       全片总览图（每 0.5 秒一格）和接缝图
    └── qa.json, qc_frames.json, anomalies.json  ★ 质检结果（嘴、手、色彩；镜头、接缝）和异常时间段清单
```

根目录 `~/.digital-human/` 下还有：`latest.json`（最近一个项目）、`voice.json`（用户的默认音色，新项目不给样本就沿用）、`voice_history.json`（复刻过的所有音色，可用 `clone_voice.py --list`、`--use` 换回）。两个密钥分别在 `~/.bailian/api_key` 和 `~/.runninghub/api_key`，由各阶段的检查脚本去找。

这个目录和 oldx-oneshot 技能是同一个：两边的密钥、音色、项目互相通用。

## 交接物

| 从 | 到 | 文件 | 用来做什么 |
|---|---|---|---|
| 配音 | 数字人 | `out/merged.wav` | 分段后逐段送去驱动人物；成片的声音也用它 |
| 配音 | 数字人 | `out/words.json` 的 `pauses` | 只能在停顿处切段 |
| 配音 | 数字人 | `out/words.json` 的 `words` | 动作编排按词对时间 |
| 配音 | 数字人 | `emotions.json` | 每一处的语气，是选动作的线索 |

带 ★ 的文件是判断“这一阶段做完没有”的依据，`scripts/status.py` 就是按它们判断的。

## 看进度、接着做

```
python scripts/status.py            # 最近一个项目走到哪了、下一步是什么
python scripts/status.py --list     # 所有项目
```

每个阶段内部也都能断点续做：配音按“文字+音色+指令”缓存，只补变动或失败的段；数字人的任务号一提交就落盘，重跑同一条命令会续上云端的任务，不重复计费。所以**中断后先跑 `status.py`，不要从头来**。

## 重做时，后面的要不要跟着重做

| 改了什么 | 后面要重做什么 |
|---|---|
| 文案 | 全部（这是一个新项目，目录也会是新的） |
| 音色、语气、配音 | 数字人全部重做（嘴型和时长都变了，要重新花钱） |
| 人物图片 | 数字人从处理图片开始重做；配音不用动 |
| 某几段的动作编排 | 只用 `--only <段号>` 重跑那几段，再拼接、质检 |
| 想换回某段以前的版本 | `takes.py --use 段号=版本号`，不用重新生成；再拼接、质检 |
| 云端工作流改过 | 先 `check_setup.py --set-workflow` 记一个版本标签；已生成的段不一定要重跑，但混用不同工作流版本的片段时留意前后是否一致 |

## 用户从中间进来

| 用户手里有什么 | 从哪开始 |
|---|---|
| 只有文案 | 配音阶段 |
| 文案加自己录好的配音（真人录音、别处合成的都算） | 没有逐词时间就没法切段和排动作：先建项目（`scripts/voice/project.py init`），把音频转成 wav 放到 `out/merged.wav`，按 `references/voice/guide.md` 第 5 步做逐词对齐，再进数字人阶段 |
| 已有项目，只想换一张图或换一个人物 | 数字人阶段，从处理图片开始 |

## 做完之后交给谁

`avatar/final_jumpcut.mp4` 是跳剪后的成片，可以直接用；用户要了字幕的，`final_subtitled.mp4` 是带字幕的版本。还要加分段时间轴、图形动画、音效、画中画的话，交给做包装的技能（包装用没剪停顿的 `final_avatar.mp4`，配的逐词时间要用 **`avatar/words_final.json`**——拼接时裁掉了每段开头几帧，成片比配音短，`out/words.json` 是配音的时间轴，越往后差得越多；要包装跳剪版，再用 `avatar/jumpcut.json` 的 `map` 换算）：oldx-oneshot 的包装阶段读的就是这个项目目录（`final_avatar.mp4`、逐词时间、`avatar/anomalies.json`），不需要搬文件；visual-broll-director 也可以直接拿这条视频做。
