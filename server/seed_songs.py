#!/usr/bin/env python3
"""Load data/songs_seed.json into the song table. Safe to rerun (upsert)."""
import json
import os
import pathlib
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import psycopg

DATABASE_URL = os.environ["DATABASE_URL"]
SEED_PATH = pathlib.Path(__file__).parent.parent / "data" / "songs_seed.json"


def main():
    songs = json.loads(SEED_PATH.read_text())
    with psycopg.connect(DATABASE_URL) as conn:
        for s in songs:
            conn.execute(
                """
                INSERT INTO song
                    (number, title_translit, subtitle, first_line_translit,
                     translation_first_line, stanzas, footnote, lang, background_ref)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                ON CONFLICT (number) DO UPDATE SET
                    title_translit         = EXCLUDED.title_translit,
                    subtitle               = EXCLUDED.subtitle,
                    first_line_translit    = EXCLUDED.first_line_translit,
                    translation_first_line = EXCLUDED.translation_first_line,
                    stanzas                = EXCLUDED.stanzas,
                    footnote               = EXCLUDED.footnote,
                    lang                   = EXCLUDED.lang,
                    background_ref         = EXCLUDED.background_ref
                """,
                (
                    s["number"],
                    s["title_translit"],
                    s.get("subtitle"),
                    s.get("first_line_translit"),
                    s.get("translation_first_line"),
                    json.dumps(s.get("stanzas", []), ensure_ascii=False),
                    s.get("footnote"),
                    s.get("lang", "translit"),
                    s.get("background_ref"),
                ),
            )
        conn.commit()
    print(f"Seeded {len(songs)} songs.")


if __name__ == "__main__":
    main()
