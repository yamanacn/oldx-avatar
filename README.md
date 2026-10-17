# OLDX Avatar

[中文](#中文) · [English](#english)

**效果演示 / Demo**：<https://www.bilibili.com/video/BV1beJY6oELV/>

---

## 中文

### 它能做什么

把一段文案，变成一条**用你自己的声音、由你的照片开口说话**的口播视频。

- 声音：复刻你本人的音色，按文案念出来；
- 画面：你提供的一张人物照片开口说话，手势跟着内容走；
- 剪辑：自动剪掉说话之间的停顿；
- 字幕：需要的话，可以自动加底部字幕（可选）。

适合知识口播、产品介绍、直播带货片段、课程讲解等场景。

效果演示：[B 站视频](https://www.bilibili.com/video/BV1beJY6oELV/)

它是一个给 AI 助手用的"技能"（Skill）。你不需要写代码、不需要会剪辑：装好以后，用聊天的方式告诉 AI 你要做什么，剩下的由它完成。

### 你需要准备的材料

| 材料 | 说明 |
|---|---|
| **文案** | 你要说的话。AI 不会改动你的文字，价格、数字、型号会原样保留。 |
| **一段 10–20 秒的录音** | 你平时正常说话的声音，安静环境、只有你一个人说话。只在第一次需要，之后会沿用。 |
| **一张人物照片** | 近景、半身、全身都可以。嘴闭着、表情平静、双手自然放在身前的照片效果最好。如果要在视频里展示商品，商品必须已经在照片里（拿在手上或摆在旁边）。 |

### 需要的 API Key（两个）

| 平台 | 用来做什么 | 去哪里获取 |
|---|---|---|
| **阿里云百炼** | 复刻声音、合成配音、识别核对每个字的时间 | <https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key> |
| **RunningHub** | 让照片开口说话、生成人物视频 | <https://www.runninghub.cn?inviteCode=150e26b6>（通过此链接注册可额外获得 1000 RH 币）。登录后在页面上方选择"API"→"获取密钥"→新建密钥 |

- 拿到后**直接粘贴到对话框发给 AI**，它会保存在你自己的电脑上，只有你的账户能读，之后不用再发。
- 两个平台都按用量收费，费用记在你自己的账号上。生成人物视频之前，AI 会先告诉你分几段、大概要花多少，**你同意了才会开始**。
- 实测参考：在 zcode 上跑一条 30 秒的视频，花费不到 1 元。
- 只做配音的话，只需要百炼的 Key。

### 怎么用

1. **安装**：把这个文件夹整个放进 AI 助手的技能目录（Claude Code 是用户目录下的 `.claude/skills/`），然后重新打开 AI 助手。也可以放进其他支持 Skills 的 AI 助手。电脑上需要有 Python 3；其余缺的工具，它会在第一次使用时自动装好。
2. **开始**：对 AI 说，例如："用 oldx-avatar 把下面这段文案做成口播视频"，然后把文案、录音、照片发给它。缺什么它会一次问齐。
3. **跟着它确认几次**，其余步骤它自己完成：
   - **配音做好后**：给你试听。配音定了再做视频，因为配音一改，视频就要重新花钱生成。
   - **生成视频前**：告诉你段数和预计费用，你同意才提交。
   - **视频生成后**：请你看一遍，没问题再剪掉停顿；需要的话再加字幕。
4. **拿到成片**：一条剪好停顿的人物视频。如果还想加图形动画、标题、音效等包装，可以交给配套的包装技能继续做。

### 需要你自己确认的

AI 听不了声音，也看不了连续播放的画面。音色像不像、语气合不合适、口型准不准、手势自不自然，请你自己看一遍、听一遍。哪一段不满意，告诉它，它只重做那一段。

### 注意

- 请只使用你本人、或已获授权的声音和照片。
- API Key 相当于账号密码，不要发到公开场合；如果在聊天里发过，用完可以到平台上重新生成一个。

---

## English

### What it does

Turns a script into a talking-head video **in your own voice, with your own photo speaking**.

- Voice: clones your voice and reads the script;
- Picture: the person in your photo speaks, with hand gestures that follow the content;
- Editing: pauses between sentences are cut out automatically;
- Subtitles: optional burned-in captions at the bottom.

Good for explainers, product introductions, live-commerce clips and course videos.

Demo: [video on Bilibili](https://www.bilibili.com/video/BV1beJY6oELV/)

It is a **Skill** for AI assistants. You don't need to code or edit video: install it, tell the assistant what you want in plain language, and it does the rest.

### What you need to prepare

| Material | Notes |
|---|---|
| **Script** | What you want to say. The assistant never rewrites your text; prices, numbers and model names are kept exactly as written. |
| **A 10–20 second voice recording** | Your normal speaking voice, in a quiet room, with only you talking. Needed only the first time; it is reused afterwards. |
| **A photo of the person** | Close-up, half-body or full-body all work. Best results: mouth closed, calm expression, hands resting in front. To show a product in the video, the product must already be in the photo (held or placed nearby). |

### API keys you need (two)

| Platform | Used for | Where to get it |
|---|---|---|
| **Alibaba Cloud Bailian (Model Studio)** | Voice cloning, speech synthesis, and checking the timing of every word | <https://bailian.console.aliyun.com/cn-beijing/model/settings/api-key> |
| **RunningHub** | Making the photo talk and generating the video | <https://www.runninghub.cn?inviteCode=150e26b6> (signing up through this link gives an extra 1000 RH coins). After logging in, choose "API" at the top → "Get key" → create a new key |

- Just **paste the key into the chat**. The assistant stores it on your own computer, readable only by your user account, so you only need to send it once.
- Both platforms charge by usage, billed to your own account. Before generating the video, the assistant tells you how many segments there are and the estimated cost, and **only starts after you agree**.
- For reference: a 30-second test video run on zcode cost less than 1 yuan (RMB).
- For voice-over only, you just need the Bailian key.

### How to use it

1. **Install**: put this whole folder into your AI assistant's skills folder (for Claude Code: `.claude/skills/` in your user folder), then restart the assistant. Other assistants that support Skills work too. Your computer needs Python 3; anything else that is missing is installed automatically the first time.
2. **Start**: say something like "Use oldx-avatar to turn this script into a talking-head video", and send the script, recording and photo. If anything is missing, it asks for everything in one message.
3. **Confirm a few times**; it handles all the other steps:
   - **After the voice-over**: listen to it first. Lock the voice before the video, because changing the voice later means paying to regenerate the video.
   - **Before generating the video**: it shows the number of segments and the estimated cost; it only submits after you agree.
   - **After the video is generated**: watch it, then it cuts the pauses and, if you want, adds subtitles.
4. **Get the result**: a talking-head video with pauses removed. For motion graphics, titles or sound effects on top, hand it to a companion packaging skill.

### What you should check yourself

The assistant can't hear audio or watch continuous playback. Please watch and listen yourself: does the voice sound like you, is the tone right, is the lip-sync accurate, do the gestures look natural? If a part isn't right, tell it, and it redoes only that segment.

### Please note

- Only use your own voice and photos, or ones you have permission to use.
- An API key is like a password. Don't post it publicly; if you pasted it into a chat, you can regenerate it on the platform afterwards.

---

## 许可 / License

MIT，见 [LICENSE](LICENSE)。/ MIT, see [LICENSE](LICENSE).
