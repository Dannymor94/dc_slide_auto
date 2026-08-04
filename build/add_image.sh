#!/usr/bin/env bash
# Add one song image to dc-deck. Usage: add_image.sh <song-number>
# Prereq: drop <N>.png (or .webp/.jpg) into deck/assets/songs/ first.
# Does: png->webp (q85) -> rsync webp to BOTH deck/ and dist/ on the VPS -> verify.
set -euo pipefail

N="${1:-}"
if ! [[ "$N" =~ ^[0-9]+$ ]]; then
  echo "usage: add_image.sh <song-number>"
  echo "  (сначала положи <N>.png/.webp/.jpg в deck/assets/songs/)"
  exit 1
fi

REPO=/Users/danny/Documents/DC_slids-auto
DIR="$REPO/deck/assets/songs"
VPS=root@147.45.251.134
SSHRUN="ssh -p 2222 -i $HOME/.ssh/vnedrum -o BatchMode=yes"
cd "$REPO"

# 1) find the source file for N
src=""
for ext in webp png jpg jpeg; do
  [ -f "$DIR/$N.$ext" ] && { src="$DIR/$N.$ext"; break; }
done
if [ -z "$src" ]; then
  echo "ERROR: нет $DIR/$N.{png,webp,jpg} — сначала положи картинку туда"
  exit 1
fi

# 2) png -> webp if possible (hybrid prefers webp; lighter for the projector)
ship="$src"
if [[ "$src" == *.png ]] && command -v cwebp >/dev/null 2>&1; then
  cwebp -q 85 -quiet "$src" -o "$DIR/$N.webp"
  ship="$DIR/$N.webp"
  echo "converted -> $N.webp ($(du -h "$DIR/$N.webp" | cut -f1))"
elif [[ "$src" == *.png ]]; then
  echo "cwebp нет — шлю png как есть ($(du -h "$src" | cut -f1))"
fi
name="$(basename "$ship")"

# 3) rsync to BOTH dirs on the VPS: deck/ (for /api/song-images scan) + dist/ (Caddy serves)
for target in deck dist; do
  rsync -avz -e "$SSHRUN" "$ship" \
    "$VPS:/opt/projects/dc-deck/$target/assets/songs/$name"
done

# 4) verify on the VPS
code=$(curl -s -o /dev/null -w "%{http_code}" "https://dc.vnedrum.ru/assets/songs/$name")
inmap=$(curl -s https://dc.vnedrum.ru/api/song-images \
  | python3 -c "import sys,json;print('$N' in json.load(sys.stdin))")
echo "GET /assets/songs/$name -> $code | /api/song-images has $N -> $inmap"
if [ "$code" = "200" ] && [ "$inmap" = "True" ]; then
  echo "OK: №$N готов. Оператор выбирает №$N -> слайд с картинкой."
else
  echo "FAIL: проверь вручную (обе папки на VPS, имя файла = номер)"
  exit 1
fi
