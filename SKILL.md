---
name: nas-video-autoclip
description: >-
  端到端「PC 找素材 → 智能剪辑 → 归档 NAS」的视频流水线。当用户给出一个本地视频文件夹（PC/Mac/下载目录）
  并想把它剪成一条短视频成片（小红书/抖音/视频号竖屏，通常 ≤60s，要「高级感/高审美」），然后存到群晖 NAS 的项目
  文件夹时，使用本 skill。它会：扫描文件夹挑素材 → whisper 转写听懂内容 → 抽关键帧看画面 → 智能选段定叙事 →
  ffmpeg 出高级感竖屏成片（统一画幅+电影调色+柔转场+暗角+静音待配乐）→ 调用 capcut-jianying 生成可精修的剪映
  草稿（带字幕+滤镜）→ 按团队结构归档到 NAS。即使用户只说「把这个文件夹的视频剪成小红书」「帮我做条高级感短视频
  存到 NAS」「自动剪辑这些素材」也应触发。NOT for：纯文章写作、单纯转写不剪辑、已有成片只做格式转换、需要逐帧
  精细特效合成（那是剪映/PR 人工活）。
---

# NAS 端到端自动剪辑流水线

把「散在 PC 上的拍摄素材」一条龙变成「NAS 项目库里的高级感竖屏成片」。本 skill 是**编排层**：
它串起转写、看图、ffmpeg 成片、`capcut-jianying`（剪映草稿引擎）和 NAS 归档，固化成一条可复用流程。

## 核心理念（先读，决定成败）

1. **剪辑是视觉活，必须先看到画面再选段。** 只靠转写文字瞎切，做不出高审美。流程里**抽关键帧→Read 看图**是硬步骤，不能跳。
2. **「高级感」= 画面叙事 + 调色 + 转场 + 音乐 + 精字幕。** 其中前四项本 skill 自动做到位（出一条静音的高级感粗剪基底）；**音乐和审美收口留给人在剪映里完成**——所以同时产一个剪映草稿。
3. **现场口语音频通常伤高级感。** 默认**静音**成片、留白给 BGM；字幕**不照搬转写原话**，而是基于转写真实信息**重写成凝练文案**（绝不杜撰未发生的事实）。
4. **macOS 限制**：pyJianYingDraft 不能自动导出成片，所以「真 MP4」由 ffmpeg 出，剪映草稿只用于人工精修+最终导出。

## 依赖

- `ffmpeg` / `ffprobe`（`brew install ffmpeg`）
- `whisper` CLI（openai-whisper；中文转写）
- `capcut-jianying` skill（剪映草稿引擎，本 skill 的搭子）+ 其 `.venv`
- 一台挂载好的群晖 NAS（Finder 连 `smb://<ip>`，盘出现在 `/Volumes/<share>`）

## 流水线（6 步）

> 所有脚本在 `scripts/`，绝对路径调用。把 `$SK` 设为本 skill 根目录。

### 第 1 步 · 扫描素材
```bash
bash "$SK/scripts/probe_folder.sh" "/Users/你/Downloads/某素材文件夹"
```
读出每条视频的 **时长 / 分辨率 / 画幅**。据此判断：竖屏直接用；横屏要裁;多条不同分辨率→统一到 1080×1920。

### 第 2 步 · 转写听懂内容（智能选段的依据之一）
```bash
bash "$SK/scripts/transcribe.sh" "$WORK/srt" video1.mp4 video2.mp4
```
出 `.srt`+`.txt`。**内置代理截断模型的自愈**（见易错坑①）。读 txt 理解：主题、关键信息、可用台词。

### 第 3 步 · 抽帧看画面（高审美的关键，别跳）
```bash
bash "$SK/scripts/keyframe_grid.sh" video1.mp4 "$WORK/frames/v1.jpg" 3x3
```
然后用 **Read 工具看这张联系表**。判断：哪条画质好、哪段是「主角镜头」、哪段适合开场/收尾。

### 第 4 步 · 定叙事 + 写剪辑计划
基于第 2、3 步，设计一条 ≤目标时长的叙事弧线，常用三段式：
**氛围开场 → 主角/高潮揭示 → 情绪收尾**。
写成 `plan.json`（按出场顺序，时间用秒）：
```json
[
  {"file":"/abs/v1.mp4","start":0,"dur":14},
  {"file":"/abs/v2.mp4","start":0,"dur":28},
  {"file":"/abs/v1.mp4","start":40,"dur":6}
]
```
画幅/调色/转场配方与更多叙事模板见 `references/recipes-and-pitfalls.md`。

### 第 5 步 · 编译高级感成片 + 写精字幕
```bash
python3 "$SK/scripts/assemble.py" --plan "$WORK/plan.json" \
   --out "$WORK/成片_v01_竖屏_待配乐.mp4" \
   --width 1080 --height 1920 --fps 30 --grade cinematic-warm
```
默认产出：统一竖屏 + 电影调色 + 柔交叉转场 + 淡入淡出 + 暗角 + **静音**。
同时**手写一份凝练字幕 SRT**（基于第 2 步真实信息重写，时间对齐成片），存 `$WORK/字幕.srt`。
**验收**：对成片再跑一次 `keyframe_grid.sh` 并 Read 看图，确认观感达标再继续。

### 第 6 步 · 生成剪映草稿（搭子 capcut-jianying）+ 归档 NAS
草稿（人工加 BGM/精修/导出终版）：
```bash
CJ=~/.claude/skills/capcut-jianying
DRAFT_ROOT=$("$CJ/.venv/bin/python" "$CJ/scripts/capcut_paths.py" | python3 -c "import sys,json;print(json.load(sys.stdin)['draft_roots'][0]['path'])")
"$CJ/.venv/bin/python" "$CJ/scripts/jy_import_srt.py" \
  --draft-root "$DRAFT_ROOT" --name "项目名_高级感" \
  --video "$WORK/成片_v01_竖屏_待配乐.mp4" --srt "$WORK/字幕.srt" \
  --filter "书意" --filter-intensity 40 --intro "渐显" \
  --width 1080 --height 1920 --fps 30 --allow-replace
```
归档（NAS 项目根命名 `日期_客户_项目`）。**NAS 可达就直传；不可达(外地/断网/没连VPN)自动入队，下次补传——断网不丢**：
```bash
bash "$SK/scripts/archive_to_nas.sh" \
  "/Volumes/团队共享盘/01_项目进行中/2026/2026-06_客户_项目" \
  "$WORK/成片_v01_竖屏_待配乐.mp4" \
  "/Users/你/Downloads/某素材文件夹" \
  "$WORK/字幕.srt" "$WORK/frames/final.jpg" \
  "$DRAFT_ROOT/项目名_高级感"
```
底层是 `scripts/nas_sync.py`（archive/flush/status），归档后顺带 flush 一次历史队列。

## 在外地 / 断网也能用（随时随地剪 + 自动归档 + 断网不丢）

**关键事实**：第 1-5 步全是本地计算，**剪辑本身在任何地方都能跑，零依赖 NAS**。只有第 6 步归档碰 NAS。

- **断网不丢**：NAS 不可达时 `archive_to_nas.sh` 自动把成片/字幕/草稿暂存到 `~/.nas-autoclip-queue/` + 清单；NAS 再次可达时跑 `python3 "$SK/scripts/nas_sync.py" flush` 自动补传。`status` 看待同步项。
- **全自动补传**（可选）：`bash "$SK/scripts/install_autoflush.sh"` 装一个 launchd 代理，每 30 分钟自动 flush 一次——回家/连上 VPN 后无需手动。卸载加 `--uninstall`。
- **远程让 NAS 可达**（让外地=局域网）：首选 **Tailscale**（NAS+电脑各装一个组私有网，挂载 `smb://<tailscale-ip>` 后 `/Volumes/<share>` 照常在，skill 零改动）；次选群晖 Drive 客户端同步盘 / VPN Server。
- 强制离线测试：归档命令前加 `NAS_AUTOCLIP_FORCE_OFFLINE=1` 即可模拟断网走入队分支。

## 完成后必须对用户讲清的边界

- 成片是**静音高级感粗剪基底**；**真·高级感终版 = 打开剪映草稿加 BGM + 微调 → 导出 → 丢 05_已交付发布**。
- 字幕是**重写文案**不是原声逐字稿；如需保留原声请用 `--keep-audio`。

## 易错坑（务必内化）

1. **whisper 模型被代理下成残缺包** → SHA256 校验失败。`transcribe.sh` 已内置「<400MB 即直连 `--noproxy` 重下」自愈。
2. **多条素材分辨率不一**（如 544×960 与 720×1280）直接拼会变形。`assemble.py` 统一 `scale=...:force_original_aspect_ratio=increase,crop` 填充裁切，不留黑边；注意低分辨率源放大后偏软，优先把高清那条当主角。
3. **跳过看画面、只凭转写选段** → 出来平庸不高级。第 3 步抽帧+Read 是硬步骤。

更细的调色预设、叙事模板、N=1 实战复盘见 `references/recipes-and-pitfalls.md`。
