# nas-video-autoclip

> 端到端「PC 找素材 → 智能剪辑 → 归档 NAS」的 Claude Code / Agent Skill。
> An end-to-end Claude Agent Skill: find footage on your PC → intelligently edit → archive to your NAS.

把散在电脑里的拍摄素材，一条龙变成 **NAS 项目库里的高级感竖屏成片**（小红书 / 抖音 / 视频号）。
本 skill 是**编排层**：它串起转写、看画面、ffmpeg 成片、剪映草稿生成、NAS 归档，固化成一条可复用流程。

## 它做什么

```
[PC 素材文件夹] → ① 扫描挑素材(画幅/时长)
              → ② whisper 转写听懂内容
              → ③ 抽关键帧看画面(高审美的关键)
              → ④ 智能选段定叙事(三段式)
              → ⑤ ffmpeg 出高级感成片(统一画幅+电影调色+柔转场+暗角+静音待配乐)
              → ⑥ 生成剪映草稿(带字幕/滤镜, 人工加 BGM 导出) + 按团队结构归档 NAS
```

## 设计理念

1. **剪辑是视觉活** — 必须抽帧看画面再选段，不靠转写文字瞎切。
2. **「高级感」= 画面 + 调色 + 转场 + 音乐 + 精字幕** — 前四项 skill 自动做到位（静音粗剪基底），音乐与审美收口留给人在剪映完成。诚实，不假装全自动。
3. **字幕重写而非照搬转写** — 凝练成文案，但绝不杜撰未发生的事实。

## 依赖

- `ffmpeg` / `ffprobe` (`brew install ffmpeg`)
- `whisper` CLI (openai-whisper)
- [capcut-jianying](https://github.com/DogeCoding/capcut-skill) skill（剪映草稿引擎，本 skill 的搭子）
- 一台挂载好的 NAS（Finder 连 `smb://<ip>`，盘出现在 `/Volumes/<share>`）

## 脚本

| 脚本 | 作用 |
|---|---|
| `scripts/assemble.py` | **核心**：把剪辑计划 `plan.json` 编译成高级感成片（统一画幅 + 调色预设 + 柔转场 + 淡入淡出 + 暗角 + 静音） |
| `scripts/transcribe.sh` | whisper 中文转写，内置「代理截断模型」自愈（直连重下） |
| `scripts/keyframe_grid.sh` | 抽帧成联系表，供 agent 看画面选段 |
| `scripts/probe_folder.sh` | 扫描文件夹内视频的画幅/时长 |
| `scripts/archive_to_nas.sh` | 按团队 00-05 结构归档到 NAS（薄壳，转发到 nas_sync.py） |
| `scripts/nas_sync.py` | **断网不丢**归档器：NAS 可达直传，不可达入队，`flush` 自动补传 |
| `scripts/install_autoflush.sh` | 装 launchd 代理，每 30 分钟自动 flush 队列（回家/连 VPN 后无感补传） |

完整流程与避坑见 [`SKILL.md`](SKILL.md) 与 [`references/recipes-and-pitfalls.md`](references/recipes-and-pitfalls.md)。

## 安装

```bash
git clone https://github.com/moonstachain/nas-video-autoclip.git ~/Documents/nas-video-autoclip
ln -s ~/Documents/nas-video-autoclip ~/.claude/skills/nas-video-autoclip
```

## License

MIT
