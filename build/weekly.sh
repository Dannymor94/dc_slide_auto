#!/usr/bin/env bash
# dc-deck weekly autobuild: build manifest on the Mac (Telegram/Airtable/Groq are
# reachable only here, not on the RU VPS) and ship it to the VPS dist/.
# Idempotent: safe to re-run (build overwrites, rsync overwrites).
set -euo pipefail
cd /Users/danny/Documents/DC_slids-auto
source .venv/bin/activate

# build manifest (Telegram + Airtable + Groq -> data/manifest.json)
python build/build_manifest.py >> "$HOME/dc-deck-build.log" 2>&1

# deliver ONLY manifest.json to the served root dist/ on the VPS (NOT data/).
# Absolute SSH key path — launchd runs in a stripped env without shell vars.
rsync -avz -e "ssh -p 2222 -i $HOME/.ssh/vnedrum" \
  data/manifest.json \
  root@147.45.251.134:/opt/projects/dc-deck/dist/manifest.json \
  >> "$HOME/dc-deck-build.log" 2>&1

echo "[$(date)] weekly build done" >> "$HOME/dc-deck-build.log"
