#!/usr/bin/env bash
# archive_to_nas.sh <NAS项目根> <成片> [原始素材目录] [字幕srt] [预览图] [剪映草稿目录]
# 在 NAS 上按团队标准结构(00-05)归档一个剪辑项目。复用「NAS团队协作攻略」的目录约定。
# NAS项目根示例: "/Volumes/团队共享盘/01_项目进行中/2026/2026-06_客户_项目"
set -euo pipefail
PROJ="${1:?用法: archive_to_nas.sh <NAS项目根> <成片> [原始目录] [srt] [预览图] [草稿目录]}"
FINAL="${2:?需要成片路径}"
RAWDIR="${3:-}"
SRT="${4:-}"
PREVIEW="${5:-}"
DRAFT="${6:-}"

# 前置检查：NAS 是否挂载
mp="${PROJ%%/01_*}"; mp="${mp%%/02_*}"
if [[ "$PROJ" == /Volumes/* ]]; then
  vol="/$(echo "$PROJ" | cut -d/ -f2-3)"   # /Volumes/<share>
  mountpoint -q "$vol" 2>/dev/null || mount | grep -q " $vol " || {
    echo "⚠️ NAS 卷似乎未挂载: $vol — 请先在 Finder 连接 smb://<nas-ip>"; }
fi

mkdir -p "$PROJ/00_策划脚本" "$PROJ/01_拍摄原始_只读勿改" \
         "$PROJ/03_剪辑工程" "$PROJ/04_导出成片" "$PROJ/05_已交付发布"

cp "$FINAL" "$PROJ/04_导出成片/" && echo "✓ 成片 -> 04_导出成片"
[ -n "$RAWDIR" ]  && cp -n "$RAWDIR"/*.{mp4,mov,m4v,MP4,MOV} "$PROJ/01_拍摄原始_只读勿改/" 2>/dev/null && echo "✓ 原始素材 -> 01_拍摄原始"
[ -n "$SRT" ]     && [ -f "$SRT" ]     && cp "$SRT" "$PROJ/00_策划脚本/" && echo "✓ 字幕 -> 00_策划脚本"
[ -n "$PREVIEW" ] && [ -f "$PREVIEW" ] && cp "$PREVIEW" "$PROJ/00_策划脚本/成片预览_9帧.jpg" && echo "✓ 预览图 -> 00_策划脚本"
[ -n "$DRAFT" ]   && [ -d "$DRAFT" ]   && cp -R "$DRAFT" "$PROJ/03_剪辑工程/剪映草稿_$(basename "$DRAFT")" && echo "✓ 剪映草稿备份 -> 03_剪辑工程"

echo "=== NAS 项目现状 ==="
find "$PROJ" -maxdepth 2 -type f ! -name '.DS_Store' | sed "s|$PROJ/||" | sort
