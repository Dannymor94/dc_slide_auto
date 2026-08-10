#!/usr/bin/env bash
# Deploy the deck's STATIC code to the VPS (Caddy serves dist/).
#
# Whitelist, NOT blacklist: only the paths in WHITELIST ship. Nothing else can leak.
#   - NEVER ships manifest.json  → owned by the weekly build_manifest.py deploy;
#                                   overwriting it with the local dev copy would wipe
#                                   the real week's program/news.
#   - NEVER ships preview*.html  → dev-only preview harnesses.
#   - NEVER ships .DS_Store      → macOS junk.
#   - NEVER ships assets/songs/  → song images are add_image.sh's job: it webp-converts
#                                   the local PNG and ships the .webp. Pushing the raw
#                                   PNGs here would duplicate them and bloat the VPS.
#   - No --delete → a code push never removes anything already on the VPS (a live site
#     is never torn down). Renamed/removed slide files must be cleaned up by hand.
#
# Usage:
#   build/push.sh            # deploy
#   build/push.sh -n         # dry-run: show what WOULD transfer, change nothing
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

VPS=root@147.45.251.134
SSHRUN="ssh -p 2222 -i $HOME/.ssh/vnedrum -o BatchMode=yes"
DIST=/opt/projects/dc-deck/dist
LIVE=https://dc.vnedrum.ru

# Explicit whitelist — deck code + slide templates + theme + static assets. Each entry
# is a path under deck/. Add new top-level deck files here to have them deploy.
WHITELIST=(
  boot.js
  merge.js
  index.html
  theme.json
  slides
  assets
)

DRY=""
[[ "${1:-}" == "-n" || "${1:-}" == "--dry-run" ]] && DRY="--dry-run"

# Guard: manifest.json must never be in the whitelist (belongs to build_manifest.py).
for p in "${WHITELIST[@]}"; do
  if [[ "$p" == "manifest.json" ]]; then
    echo "REFUSING: manifest.json is owned by the weekly build, not this deploy." >&2
    exit 2
  fi
done

echo "→ deck deploy → $VPS:$DIST ${DRY:+(dry-run)}"
for path in "${WHITELIST[@]}"; do
  [[ -e "deck/$path" ]] || { echo "  skip (missing): deck/$path"; continue; }
  # -L follows the theme.json symlink → ships the real file, not a dangling link.
  # --exclude guards the junk even if it ever lands inside a whitelisted dir.
  rsync -azL $DRY -e "$SSHRUN" \
    --exclude '.DS_Store' \
    --exclude 'preview*.html' \
    --exclude 'songs' \
    "deck/$path" "$VPS:$DIST/"
  echo "  ✓ $path"
done

[[ -n "$DRY" ]] && { echo "dry-run done — nothing changed."; exit 0; }

# ── Leak check: assert nothing forbidden reached the VPS ─────────────────────────
echo "→ leak check"
leaked=$($SSHRUN "$VPS" \
  "ls -1 $DIST $DIST/slides 2>/dev/null | grep -E 'preview.*\.html|\.DS_Store' || true")
if [[ -n "$leaked" ]]; then
  echo "  ✗ LEAK: forbidden files on the VPS:" >&2
  echo "$leaked" >&2
  exit 3
fi
echo "  ✓ no preview/junk on the VPS"

# ── Verify: live boot.js matches what we just pushed, index.html serves 200 ──────
echo "→ verify live"
local_md5=$(md5 -q deck/boot.js 2>/dev/null || md5sum deck/boot.js | cut -d' ' -f1)
live_md5=$(curl -fsS "$LIVE/boot.js" | (md5 -q 2>/dev/null || md5sum | cut -d' ' -f1))
if [[ "$local_md5" == "$live_md5" ]]; then
  echo "  ✓ live boot.js matches local ($local_md5)"
else
  echo "  ✗ live boot.js differs (local $local_md5 vs live $live_md5) — CDN/proxy cache?" >&2
  exit 4
fi
code=$(curl -fsS -o /dev/null -w '%{http_code}' "$LIVE/")
echo "  ✓ $LIVE/ → HTTP $code"

echo "done. Hard-refresh the deck (Cmd+Shift+R) to bypass the browser cache."
