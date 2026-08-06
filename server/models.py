CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS song (
    number                  INTEGER PRIMARY KEY,
    title_translit          TEXT    NOT NULL,
    subtitle                TEXT,
    first_line_translit     TEXT,
    translation_first_line  TEXT,
    stanzas                 JSONB   NOT NULL DEFAULT '[]',
    footnote                TEXT,
    lang                    TEXT    NOT NULL DEFAULT 'translit',
    background_ref          TEXT
);

CREATE TABLE IF NOT EXISTS selection (
    week_date       DATE        PRIMARY KEY,
    song_numbers    INTEGER[]   NOT NULL DEFAULT '{}',
    video_url       TEXT        NOT NULL DEFAULT '',
    final_video_url TEXT        NOT NULL DEFAULT '',
    bg_music_url    TEXT        NOT NULL DEFAULT '',
    raised          INTEGER,
    plan            INTEGER,
    overrides       JSONB       NOT NULL DEFAULT '{}'
);

-- Idempotent migration for DBs created before bg_music_url existed (runs on startup).
ALTER TABLE selection ADD COLUMN IF NOT EXISTS bg_music_url TEXT NOT NULL DEFAULT '';
"""
