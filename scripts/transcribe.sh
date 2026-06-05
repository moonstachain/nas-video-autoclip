#!/usr/bin/env bash
# transcribe.sh <输出目录> <视频...> — whisper 转写(中文), 出 srt+txt。
# 内置「代理截断模型」自愈：whisper 首次会下模型，国内代理常把它下成残缺包
# 导致 SHA256 校验失败。本脚本先校验 small.pt 完整性，残缺则直连重下。
set -euo pipefail
OUTDIR="${1:?用法: transcribe.sh <输出目录> <视频...>}"; shift
MODEL="${WHISPER_MODEL:-small}"
mkdir -p "$OUTDIR"

# --- 模型完整性自愈（仅对 small 内置正确 URL；其它模型交给 whisper 自行处理） ---
CACHE="$HOME/.cache/whisper"
if [ "$MODEL" = "small" ]; then
  PT="$CACHE/small.pt"
  if [ ! -f "$PT" ] || [ "$(stat -f%z "$PT" 2>/dev/null || echo 0)" -lt 400000000 ]; then
    echo "[transcribe] small 模型缺失/残缺，直连重下(绕过代理)..."
    mkdir -p "$CACHE"; rm -f "$PT"
    curl -L --noproxy '*' -s -o "$PT" \
      "https://openaipublic.azureedge.net/main/whisper/models/9ecf779972d90ba49c06d968637d720dd632c55bbf19d441fb42bf17a411e794/small.pt" \
      -w "[transcribe] HTTP %{http_code} 下载 %{size_download} bytes\n"
  fi
fi

for f in "$@"; do
  echo "[transcribe] $(basename "$f")"
  whisper "$f" --model "$MODEL" --language "${WHISPER_LANG:-zh}" --task transcribe \
    --output_format srt --output_format txt --output_dir "$OUTDIR" \
    --fp16 False --verbose False 2>&1 | tail -2
done
echo "[transcribe] 完成 -> $OUTDIR"
