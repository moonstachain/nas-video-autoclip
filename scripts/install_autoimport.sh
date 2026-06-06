#!/usr/bin/env bash
# install_autoimport.sh [--uninstall]
# 装 launchd 代理：每次有卷挂载(StartOnMount)就跑 auto_import.sh。
# 效果：DJI Pocket 3 插 Mac USB-C / 卡插读卡器 → 自动把新片吸入 → 推 NAS 入库。你只需插一下。
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LABEL="com.moonstachain.nas-autoclip-import"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/.nas-autoclip-queue/autoimport.log"

if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"; echo "✅ 已卸载自动入库代理"; exit 0
fi
mkdir -p "$(dirname "$LOG")" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$HERE/auto_import.sh</string></array>
  <key>StartOnMount</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST" 2>/dev/null || launchctl load "$PLIST"
echo "✅ 自动入库代理已装：插入 DJI 相机/卡即自动吸片入 NAS"
echo "   入库目录: $(cat "$HOME/.nas-autoclip-ingest.conf" 2>/dev/null || echo '未配置(见下)')"
echo "   日志: $LOG ｜ 卸载: bash $HERE/install_autoimport.sh --uninstall"
