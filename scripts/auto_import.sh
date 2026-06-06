#!/usr/bin/env bash
# auto_import.sh — DJI 相机/卡一挂载就自动吸入新素材。
# 由 launchd StartOnMount 触发：每次有卷挂载就跑一次，非 DJI 卷自动 no-op。
# 流程：识别带 DCIM + DJI_*.MP4 的卷 → 拷新片到本地暂存 → 若 NAS 入库目录可达则推过去。
# 「插一下」之外零操作；去重靠文件名(已导过不重复)。
set -uo pipefail
LOG="$HOME/.nas-autoclip-queue/autoimport.log"
mkdir -p "$(dirname "$LOG")"
STAGE="$HOME/Movies/PocketIngest"            # 本地暂存(永远先落这, 快且永不失败)
mkdir -p "$STAGE"
# NAS 入库目录: 环境变量优先, 否则读配置文件(本地, gitignore)
NAS_INGEST="${NAS_INGEST_DIR:-$(cat "$HOME/.nas-autoclip-ingest.conf" 2>/dev/null)}"

log(){ echo "[$(date '+%F %T')] $*" >> "$LOG"; }

SCAN_ROOT="${SCAN_ROOT:-/Volumes}"   # 默认扫挂载卷; 测试时可指向临时目录
imported=0
for vol in "$SCAN_ROOT"/*; do
  dcim="$vol/DCIM"
  [ -d "$dcim" ] || continue
  # 是否 DJI 卷: DCIM 下有 DJI_*.MP4
  first=$(find "$dcim" -iname 'DJI_*.MP4' -type f 2>/dev/null | head -1)
  [ -n "$first" ] || continue
  log "发现 DJI 卷: $vol"
  # 逐个吸入(去重: 暂存或NAS已存在则跳过)
  while IFS= read -r f; do
    base=$(basename "$f")
    if [ -e "$STAGE/$base" ] || { [ -n "$NAS_INGEST" ] && [ -e "$NAS_INGEST/$base" ]; }; then
      continue
    fi
    cp "$f" "$STAGE/$base" && { imported=$((imported+1)); log "吸入 $base ($(du -h "$f"|cut -f1))"; }
  done < <(find "$dcim" -iname 'DJI_*.MP4' -type f 2>/dev/null | sort)
done

[ "$imported" -eq 0 ] && { log "本次无新素材(或非DJI卷)"; exit 0; }
log "共吸入 $imported 条到暂存 $STAGE"

# 暂存 → NAS 入库(可达才推, 不可达留暂存等下次)
if [ -n "$NAS_INGEST" ] && { [ -d "$NAS_INGEST" ] || mkdir -p "$NAS_INGEST" 2>/dev/null; }; then
  pushed=0
  for f in "$STAGE"/DJI_*.MP4 "$STAGE"/DJI_*.mp4; do
    [ -e "$f" ] || continue
    base=$(basename "$f")
    [ -e "$NAS_INGEST/$base" ] && { rm -f "$f"; continue; }
    if cp "$f" "$NAS_INGEST/$base"; then rm -f "$f"; pushed=$((pushed+1)); fi
  done
  log "推到 NAS 入库 $pushed 条 -> $NAS_INGEST"
else
  log "NAS 入库目录不可达, $imported 条留在本地暂存 $STAGE, 回家后重插或手动 flush"
fi
log "完成。"
