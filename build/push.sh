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
  assets          # recursive: ships assets/fonts/ (self-hosted Manrope), backgrounds, etc.
)                 # (only assets/songs/ is excluded below — images are add_image.sh's job)

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
  rsync -aziL $DRY -e "$SSHRUN" \
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

# ── Verify: what's LIVE matches what we just pushed ──────────────────────────────
# "rsync rc=0" only proves the transfer ran — not that Caddy serves the new bytes
# (stale cache, wrong dist path, a file that never shipped). So md5-compare the
# actually-served response against the local source for every path that has bitten
# us. Each entry is "<local deck path>|<live URL path>". Add a file here the moment
# a page depends on it being fresh in prod. operator*.js earned their slots by
# shipping to server/templates/ while Caddy served the stale dist/ copy.
echo "→ verify live (served bytes == local source)"
md5of() { md5 -q 2>/dev/null || md5sum | cut -d' ' -f1; }   # mac | linux
VERIFY=(
  "boot.js|boot.js"
  "assets/operator.js|assets/operator.js"
  "assets/operator-init.js|assets/operator-init.js"
)
fail=0
for entry in "${VERIFY[@]}"; do
  src="deck/${entry%%|*}"; url="$LIVE/${entry##*|}"
  [[ -e "$src" ]] || { echo "  ✗ local source missing: $src" >&2; fail=1; continue; }
  local_md5=$(md5of < "$src")
  live_md5=$(curl -fsS "$url" | md5of) || { echo "  ✗ $url unreachable" >&2; fail=1; continue; }
  if [[ "$local_md5" == "$live_md5" ]]; then
    echo "  ✓ ${entry##*|} matches local ($local_md5)"
  else
    echo "  ✗ ${entry##*|} DIFFERS (local $local_md5 vs live $live_md5) — not shipped / stale cache / wrong dist path" >&2
    fail=1
  fi
done
[[ "$fail" == 0 ]] || { echo "→ VERIFY FAILED: live does not match source. Deploy is a lie." >&2; exit 4; }
code=$(curl -fsS -o /dev/null -w '%{http_code}' "$LIVE/")
echo "  ✓ $LIVE/ → HTTP $code"

# ── Smoke check: assert OUTCOMES, not completion ─────────────────────────────────
# Bytes-match proves delivery; it does NOT prove the code runs. We have burned
# three times on "step reported success but result was wrong":
#   - deploy ok without delivering operator.js    → empty catalog, dead buttons
#   - bytes verified but init() call was absent   → form stuck on "загрузка…"
# So: assert functional outcomes from live endpoints.
echo "→ smoke check (outcome assertions)"

# 1. Catalog is non-empty (backend alive, song table has rows, API route maps).
#    /api/catalog is public (no auth) — safe to call from any machine.
catalog_count=$(curl -fsS "$LIVE/api/catalog" \
  | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null || echo 0)
if [[ "$catalog_count" -gt 0 ]]; then
  echo "  ✓ /api/catalog → $catalog_count songs (backend alive)"
else
  echo "  ✗ /api/catalog returned empty or failed (DB down? API broken?)" >&2; exit 5
fi

# 2. Live operator.js ends with a top-level init() call.
#    Checks the DELIVERED file — would have caught today's regression where init()
#    was absent from the file itself (bytes-match alone didn't catch it because the
#    source we compared against also lacked the call at the time of the bug).
#    Grep on the source = useless; grep on the live download = real outcome.
live_init=$(curl -fsS "$LIVE/assets/operator.js" | tail -5 | grep -c 'init();' || echo 0)
if [[ "$live_init" -gt 0 ]]; then
  echo "  ✓ /assets/operator.js ends with init() call (form will boot)"
else
  echo "  ✗ /assets/operator.js missing top-level init() call — form will be dead" >&2; exit 5
fi

# 3. /api/operator returns 200 and references /assets/operator.js.
#    Needs VPS creds (OPERATOR_USER/PASS). Read from .env; if absent or wrong → warn,
#    don't hard-fail (creds are VPS-side; local .env may legitimately differ).
ENV_FILE="$(dirname "$0")/../.env"
OPUSER=$(grep -m1 '^OPERATOR_USER=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d "'\"")
OPPASS=$(grep -m1 '^OPERATOR_PASS=' "$ENV_FILE" 2>/dev/null | cut -d= -f2 | tr -d "'\"")
if [[ -n "$OPUSER" && -n "$OPPASS" ]]; then
  op_code=$(curl -sS -o /tmp/_op_html -w '%{http_code}' -u "$OPUSER:$OPPASS" "$LIVE/api/operator" 2>/dev/null)
  if [[ "$op_code" == "200" ]]; then
    op_ref=$(grep -o 'assets/operator\.js' /tmp/_op_html | head -1)
    if [[ "$op_ref" == "assets/operator.js" ]]; then
      echo "  ✓ /api/operator → 200, references /assets/operator.js"
    else
      echo "  ✗ /api/operator → 200 but missing reference to /assets/operator.js" >&2; exit 5
    fi
  elif [[ "$op_code" == "401" ]]; then
    echo "  ~ /api/operator: local .env creds differ from VPS — skipping template check (not a deploy failure)"
  else
    echo "  ✗ /api/operator → HTTP $op_code" >&2; exit 5
  fi
else
  echo "  ~ /api/operator: no creds in local .env — skipping template check"
fi

echo "done. Hard-refresh the deck (Cmd+Shift+R) to bypass the browser cache."
