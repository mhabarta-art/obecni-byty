#!/bin/bash
# Downloads the public RSS feed of Brno-Žabovřesky and pushes it to the repo.
# Runs on the Mac because zabovresky.cz does not answer servers outside the Czech Republic.
set -euo pipefail
SYNC_DIR="$HOME/.obecni-byty-sync"
URL="${ZAB_RSS_URL:-https://www.zabovresky.cz/rss/}"
echo "--- $(date '+%F %T')"
cd "$SYNC_DIR"
git pull --rebase --quiet
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsS --max-time 60 -A "obecni-byty-watch/1.0 (osobni hlidani nabidek obecnich bytu)" "$URL" -o "$tmp"
if ! grep -q "<rss" "$tmp"; then echo "Odpověď není RSS – nic neukládám."; exit 1; fi
cp "$tmp" data/zabovresky_rss.xml
git add data/zabovresky_rss.xml
if git diff --cached --quiet; then echo "Beze změny."; exit 0; fi
git commit --quiet -m "data: RSS Žabovřesky $(date '+%F %H:%M')"
git push --quiet || { git pull --rebase --quiet && git push --quiet; }
echo "Nahráno."
