#!/usr/bin/env python3
"""Add or update one song in data/songs_seed.json (build-side, Mac only).

Input is the "two blocks" format: a transliteration block and a translation
block. A blank line separates stanzas; lines within a stanza keep their order.
The two blocks are paired stanza-by-stanza into the seed schema:

    stanzas[i] = { "translit": [...lines], "translation": [...lines] }

This tool ONLY edits the seed file. It never touches the VPS. To publish the
catalog after editing the seed, run the normal seeder:

    python server/seed_songs.py

Per the data contract: the operator form writes only `selection`; the song
catalog is filled exclusively by the seed on the Mac side. There is deliberately
NO server endpoint that writes to the `song` table.

Usage
-----
From files (song text saved on disk):

    python build/add_song.py \
        --number 342 \
        --title "Шумукхер пане чоле джабо ами" \
        --first-line "Я буду идти вперёд, повторяя Твоё имя" \
        --background cosmic-radiance \
        --translit-file translit.txt \
        --translation-file translation.txt

Interactive (paste): omit --translit-file/--translation-file and paste each
block, ending it with a line containing only `///` (or Ctrl-D). Any metadata
flag left out is asked for interactively.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SEED_PATH = Path(__file__).parent.parent / "data" / "songs_seed.json"
END_MARKER = "///"


def parse_block(text: str) -> list[list[str]]:
    """Split raw text into stanzas. Blank line = stanza break; consecutive or
    leading/trailing blanks are collapsed so no empty stanzas are produced."""
    stanzas: list[list[str]] = []
    current: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if current:
                stanzas.append(current)
                current = []
        else:
            current.append(line)
    if current:
        stanzas.append(current)
    return stanzas


def build_stanzas(translit_text: str, translation_text: str) -> list[dict]:
    """Pair translit and translation stanzas by index. Line counts within a
    stanza may differ (the slide renders each column independently); only the
    stanza count is expected to match — a mismatch is warned about, not fatal."""
    t = parse_block(translit_text)
    r = parse_block(translation_text)
    if len(t) != len(r):
        print(
            f"[warn] число строф не совпадает: транслит={len(t)}, перевод={len(r)}. "
            f"Недостающая сторона останется пустой — проверь разбивку пустыми строками.",
            file=sys.stderr,
        )
    n = max(len(t), len(r))
    out = []
    for i in range(n):
        out.append({
            "translit": t[i] if i < len(t) else [],
            "translation": r[i] if i < len(r) else [],
        })
    return out


def read_pasted_block(label: str) -> str:
    print(
        f"\nВставь {label}. Заверши строкой «{END_MARKER}» (или Ctrl-D):",
        file=sys.stderr,
    )
    lines: list[str] = []
    for line in sys.stdin:
        if line.rstrip("\n") == END_MARKER:
            break
        lines.append(line.rstrip("\n"))
    return "\n".join(lines)


def prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{label}{suffix}: ").strip() or (default or "")


def load_seed() -> list[dict]:
    return json.loads(SEED_PATH.read_text()) if SEED_PATH.exists() else []


def save_seed(songs: list[dict]) -> None:
    songs.sort(key=lambda s: s["number"])
    SEED_PATH.write_text(json.dumps(songs, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Add/update a song in data/songs_seed.json")
    ap.add_argument("--number", type=int)
    ap.add_argument("--title", help="title_translit")
    ap.add_argument("--first-line", dest="first_line", help="translation_first_line")
    ap.add_argument("--subtitle")
    ap.add_argument("--footnote")
    ap.add_argument("--background", help="background_ref (без .jpg)")
    ap.add_argument("--translit-file", type=Path)
    ap.add_argument("--translation-file", type=Path)
    args = ap.parse_args()

    # ── Metadata (interactive fallback for anything not passed as a flag) ──
    number = args.number if args.number is not None else int(prompt("Номер песни"))
    title = args.title or prompt("Название (транслит)")
    first_line = args.first_line or prompt("Перевод первой строки")
    subtitle = args.subtitle if args.subtitle is not None else (prompt("Подзаголовок (опц.)") or None)
    footnote = args.footnote if args.footnote is not None else (prompt("Сноска (опц.)") or None)
    background = args.background if args.background is not None else (prompt("Фон background_ref (опц.)") or None)

    # ── Text blocks (from files, else pasted) ──
    translit_text = args.translit_file.read_text() if args.translit_file else read_pasted_block("ТРАНСЛИТ")
    translation_text = args.translation_file.read_text() if args.translation_file else read_pasted_block("ПЕРЕВОД")

    stanzas = build_stanzas(translit_text, translation_text)
    if not stanzas:
        sys.exit("[error] пустой текст — нечего сохранять.")

    first_line_translit = stanzas[0]["translit"][0] if stanzas[0]["translit"] else None
    if not first_line:
        first_line = stanzas[0]["translation"][0] if stanzas[0]["translation"] else None

    song = {
        "number": number,
        "title_translit": title,
        "subtitle": subtitle,
        "first_line_translit": first_line_translit,
        "translation_first_line": first_line,
        "stanzas": stanzas,
        "footnote": footnote,
        "lang": "translit",
        "background_ref": background,
    }

    songs = load_seed()
    idx = next((i for i, s in enumerate(songs) if s["number"] == number), None)
    if idx is not None:
        songs[idx] = song
        action = "обновлена"
    else:
        songs.append(song)
        action = "добавлена"
    save_seed(songs)

    print(f"✓ Песня №{number} «{title}» {action} в {SEED_PATH} ({len(stanzas)} строф).")
    print("→ Загрузить в каталог: python server/seed_songs.py")


if __name__ == "__main__":
    main()
