#!/usr/bin/env bash
# install_autoflush.sh [--uninstall]
# 装一个 launchd 后台代理：每 30 分钟自动 flush 一次待同步队列。
# 效果：你在外地剪完→入队；回家/连上VPN后，无需手动，30分钟内自动补传进 NAS。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.moonstachain.nas-autoclip-flush"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/.nas-autoclip-queue/autoflush.log"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"; echo "✅ 已卸载自动补传代理"; exit 0
fi

mkdir -p "$(dirname "$LOG")" "$HOME/Library/LaunchAgents"
PY="$(command -v python3)"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$HERE/nas_sync.py</string>
    <string>flush</string>
  </array>
  <key>StartInterval</key><integer>1800</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load "$PLIST"
echo "✅ 自动补传代理已装：每 30 分钟扫一次队列，NAS 可达即补传"
echo "   日志: $LOG"
echo "   卸载: bash $HERE/install_autoflush.sh --uninstall"
