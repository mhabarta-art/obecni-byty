#!/bin/bash
# Installs a macOS background job (launchd) that fetches the Žabovřesky RSS 3× a day.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_URL="$(git -C "$HERE/.." remote get-url origin)"
SYNC_DIR="$HOME/.obecni-byty-sync"
APP_DIR="$HOME/Library/Application Support/obecni-byty"
PLIST="$HOME/Library/LaunchAgents/cz.obecni-byty.zabovresky.plist"
LOG="$HOME/Library/Logs/obecni-byty-zabovresky.log"

[ -d "$SYNC_DIR/.git" ] || git clone --quiet "$REPO_URL" "$SYNC_DIR"
mkdir -p "$APP_DIR" "$HOME/Library/LaunchAgents"
install -m 755 "$HERE/fetch-zabovresky.sh" "$APP_DIR/fetch-zabovresky.sh"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>cz.obecni-byty.zabovresky</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$APP_DIR/fetch-zabovresky.sh</string></array>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StartCalendarInterval</key><array>
    <dict><key>Hour</key><integer>5</integer><key>Minute</key><integer>50</integer></dict>
    <dict><key>Hour</key><integer>11</integer><key>Minute</key><integer>50</integer></dict>
    <dict><key>Hour</key><integer>17</integer><key>Minute</key><integer>50</integer></dict>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
PLIST

launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Hotovo. Stahování běží v 5:50, 11:50 a 17:50 (a po probuzení Macu, pokud se čas zmeškal)."
echo "Log: $LOG"
