#!/usr/bin/env bash
# probe_folder.sh <文件夹> — 列出文件夹内所有视频 + 时长/分辨率/画幅，判断是否需要重排版
# 输出每条: 文件名 | WxH | 画幅(竖/横/方) | 时长s | 大小
set -euo pipefail
DIR="${1:?用法: probe_folder.sh <视频文件夹>}"
shopt -s nullglob nocaseglob
found=0
for f in "$DIR"/*.{mp4,mov,m4v,mkv,avi}; do
  [ -f "$f" ] || continue
  found=1
  read W H DUR < <(ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height -show_entries format=duration \
    -of default=noprint_wrappers=1:nokey=1 "$f" | paste -sd' ' -)
  ar="横屏"; [ "$W" -lt "$H" ] && ar="竖屏"; [ "$W" -eq "$H" ] && ar="方形"
  sz=$(du -h "$f" | cut -f1)
  printf "%s | %sx%s | %s | %.1fs | %s\n" "$(basename "$f")" "$W" "$H" "$ar" "$DUR" "$sz"
done
[ "$found" = 1 ] || { echo "(该文件夹没有可识别的视频文件)"; exit 0; }
