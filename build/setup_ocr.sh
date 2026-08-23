#!/usr/bin/env bash
# Download self-hosted Tesseract.js assets into deck/assets/ocr/.
# Run once on Mac before the first push.sh that should include OCR.
# Requires: node/npm (any modern version), curl.
#
# What it downloads:
#   tesseract.js@5        — main library + worker (~580KB total)
#   tesseract.js-core@5   — WASM-compiled Tesseract engine (~4–5MB)
#   rus.traineddata (fast) — Cyrillic OCR model (~3.8MB)
#   eng.traineddata (fast) — Latin/English OCR model (~1.4MB)
#
# After running: build/push.sh to deploy the assets to the VPS.
# No traineddata is re-downloaded if the file already exists.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OCR_DIR="$REPO/deck/assets/ocr"
LANGS_DIR="$OCR_DIR/langs"
mkdir -p "$OCR_DIR" "$LANGS_DIR"

echo "→ Installing Tesseract.js via npm (temporary directory)…"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cd "$TMP"
# Minimal package.json so npm doesn't complain
printf '{"private":true}\n' > package.json
npm install --silent --no-save tesseract.js@5 tesseract.js-core@5

# ── Main library (runs in the page) ─────────────────────────────────────────
cp node_modules/tesseract.js/dist/tesseract.min.js "$OCR_DIR/"
echo "  ✓ tesseract.min.js ($(du -h "$OCR_DIR/tesseract.min.js" | cut -f1))"

# ── Worker script (runs in Web Worker) ──────────────────────────────────────
cp node_modules/tesseract.js/dist/worker.min.js "$OCR_DIR/"
echo "  ✓ worker.min.js    ($(du -h "$OCR_DIR/worker.min.js" | cut -f1))"

# ── WASM core (loaded by the worker) ────────────────────────────────────────
# tesseract.js-core may ship the wasm embedded in a .js file, or separately as
# a .wasm binary, or both.  Copy everything so the worker can find whatever it needs.
CORE_SRC="node_modules/tesseract.js-core"
for f in "$CORE_SRC"/*.js "$CORE_SRC"/*.wasm; do
  [ -f "$f" ] || continue
  cp "$f" "$OCR_DIR/"
  echo "  ✓ $(basename "$f")  ($(du -h "$OCR_DIR/$(basename "$f")" | cut -f1))"
done

cd "$REPO"

# ── Traineddata (tessdata_fast — smaller, faster, good enough for slide text) ─
echo ""
echo "→ Downloading traineddata (tessdata_fast)…"
for lang in rus eng; do
  DEST="$LANGS_DIR/$lang.traineddata"
  if [ -f "$DEST" ]; then
    echo "  $lang.traineddata already present ($(du -h "$DEST" | cut -f1)) — skipping"
    continue
  fi
  curl -fSL \
    "https://github.com/tesseract-ocr/tessdata_fast/raw/main/${lang}.traineddata" \
    -o "$DEST"
  echo "  ✓ $lang.traineddata ($(du -h "$DEST" | cut -f1))"
  # Browser Tesseract.js v5 requests the .gz variant; create it alongside the plain file
  # (CLI tesseract uses the plain .traineddata; both are kept)
  gzip -k -f "$DEST"
  echo "  ✓ $lang.traineddata.gz ($(du -h "${DEST}.gz" | cut -f1))"
done

echo ""
echo "✓ OCR assets ready in deck/assets/ocr/"
echo ""
echo "  JS/WASM:"
ls -1 "$OCR_DIR"/*.js 2>/dev/null | while read -r f; do printf '    %-40s %s\n' "$(basename "$f")" "$(du -h "$f" | cut -f1)"; done || true
ls -1 "$OCR_DIR"/*.wasm 2>/dev/null | while read -r f; do printf '    %-40s %s\n' "$(basename "$f")" "$(du -h "$f" | cut -f1)"; done || true
echo ""
echo "  traineddata:"
ls -1 "$LANGS_DIR/" 2>/dev/null | while read -r f; do printf '    %-40s %s\n' "$f" "$(du -h "$LANGS_DIR/$f" | cut -f1)"; done || true
echo ""
echo "Next: build/push.sh  (assets/ocr/ is in the WHITELIST, will be deployed)"
