#!/usr/bin/env bash
# archive_to_nas.sh <NAS项目根> <成片> [原始素材目录] [字幕srt] [预览图] [剪映草稿目录]
# 在 NAS 上按团队标准结构(00-05)归档。NAS 不可达(外地/断网)时自动入队，下次 flush 补传——「断网不丢」。
# NAS项目根示例: "/Volumes/团队共享盘/01_项目进行中/2026/2026-06_客户_项目"
# 薄壳：转发到 nas_sync.py（真正逻辑在那）。需要原声/批量同步直接用 nas_sync.py。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ="${1:?用法: archive_to_nas.sh <NAS项目根> <成片> [原始目录] [srt] [预览图] [草稿目录]}"
FINAL="${2:?需要成片路径}"
RAWDIR="${3:-}"; SRT="${4:-}"; PREVIEW="${5:-}"; DRAFT="${6:-}"

args=(archive --proj "$PROJ" --final "$FINAL")
[ -n "$RAWDIR" ]  && args+=(--raw-dir "$RAWDIR")
[ -n "$SRT" ]     && args+=(--srt "$SRT")
[ -n "$PREVIEW" ] && args+=(--preview "$PREVIEW")
[ -n "$DRAFT" ]   && args+=(--draft "$DRAFT")

python3 "$HERE/nas_sync.py" "${args[@]}"
