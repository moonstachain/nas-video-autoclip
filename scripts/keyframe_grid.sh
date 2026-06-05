#!/usr/bin/env bash
# keyframe_grid.sh <视频> <输出.jpg> [tile=3x3] [每隔秒数=auto]
# 抽帧拼成一张联系表(contact sheet)，供 agent 用 Read 看画面后做审美选段。
# 这是「高审美」的关键一步：剪辑前必须看到画面，不能只凭转写瞎切。
set -euo pipefail
SRC="${1:?用法: keyframe_grid.sh <视频> <输出.jpg> [tile] [interval]}"
OUT="${2:?需要输出路径}"
TILE="${3:-3x3}"
INTERVAL="${4:-}"
if [ -z "$INTERVAL" ]; then
  DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SRC")
  CELLS=$(( ${TILE%x*} * ${TILE#*x} ))
  INTERVAL=$(awk "BEGIN{d=$DUR/$CELLS; print (d<1?1:d)}")
fi
ffmpeg -y -i "$SRC" -vf "fps=1/$INTERVAL,scale=240:-1,tile=$TILE" -frames:v 1 "$OUT" -loglevel error
echo "$OUT"
