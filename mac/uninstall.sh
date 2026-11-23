#!/bin/bash
set -euo pipefail
PLIST="$HOME/Library/LaunchAgents/cz.obecni-byty.zabovresky.plist"
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
rm -f "$PLIST" "$HOME/Library/Application Support/obecni-byty/fetch-zabovresky.sh"
echo "Odinstalováno. Pomocnou kopii repozitáře můžete smazat: rm -rf ~/.obecni-byty-sync"
