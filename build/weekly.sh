#!/usr/bin/env bash
# dc-deck weekly autobuild. build_manifest.py now does everything — build the
# manifest (Telegram/Airtable/Groq), deploy it to the VPS, write the build status,
# and report over Telegram + macOS. weekly.sh only schedules the run and logs.
# Absolute paths — launchd runs this in a stripped env.
set -euo pipefail
cd /Users/danny/Documents/DC_slids-auto
source .venv/bin/activate

python build/build_manifest.py >> "$HOME/dc-deck-build.log" 2>&1

echo "[$(date)] weekly build done" >> "$HOME/dc-deck-build.log"
