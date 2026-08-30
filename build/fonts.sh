#!/usr/bin/env bash
# Refresh the self-hosted Manrope subset in deck/assets/fonts/.
# Downloads ONLY the weights the deck uses (400/500/600/700) and ONLY the
# latin + cyrillic subsets (all text is Russian; latin covers t.me/… and digits).
# Run on the Mac (open internet). The @font-face block is hand-maintained in
# deck/index.html — if weights/subsets change here, update it there too.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=deck/assets/fonts
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36'
mkdir -p "$OUT"

CSS=$(curl -fsS -H "User-Agent: $UA" \
  "https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap")

OUT="$OUT" python3 - "$CSS" <<'PY'
import os, re, sys, urllib.request
css = sys.argv[1]; out = os.environ["OUT"]
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36'}
n = 0
for block in re.split(r'(?=/\* )', css):
    m = re.match(r'/\* ([a-z-]+) \*/', block)
    if not m or m.group(1) not in ('latin', 'cyrillic'):
        continue
    sub = m.group(1)
    w = re.search(r'font-weight:\s*(\d+)', block).group(1)
    url = re.search(r'url\((https://[^)]+\.woff2)\)', block).group(1)
    data = urllib.request.urlopen(urllib.request.Request(url, headers=UA)).read()
    open(f'{out}/manrope-{sub}-{w}.woff2', 'wb').write(data)
    print(f'  ✓ manrope-{sub}-{w}.woff2 ({len(data)//1024} KB)')
    n += 1
print(f'{n} файлов в {out}')
assert n == 8, f'ожидалось 8 файлов (4 веса × latin+cyrillic), получено {n}'
PY
