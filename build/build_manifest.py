#!/usr/bin/env python3
"""Assemble data/manifest.json (Mac build-side).

Sources this build manages (all independent — one failing never blocks another):
    news            ← fetch_news()                     (M3, Airtable)
    program         ← extract_program(TG program post) (M2, Groq — single LLM point)
    raised / plan   ← extract_progress(TG finance post)(M2, regex — deterministic)
    video_url       ← fetch_dada_video(СВАДХЬЯЯ chat)   (M2, newest YouTube link)

Program & finance come from the Rostov Unit chat; the Dada video from the
СВАДХЬЯЯ chat — both via Telethon (reused Crosspost session).

Safety:
    - Rostov Telethon unavailable (connected=False) → program & progress LEFT
      UNTOUCHED (don't wipe good data on a misconfig / transient error).
    - Connected but a post not found → that field emptied + warning.
    - video_url: any failure / no link in window → "" (the deck shows its
      «видео от Дады не будет» stub; empty video is a valid state, unlike program).

date / dada_comment / final_music_url assembly stays out of scope and preserved.
All sources degrade gracefully and never raise; the build always completes.
"""
import json
import sys
from pathlib import Path

from extract_program import extract_program
from extract_progress import extract_progress
from fetch_news import fetch_news
from fetch_telegram import fetch_dada_video, fetch_posts
from song_alerts import notify_new_songs

MANIFEST_PATH = Path(__file__).parent.parent / "data" / "manifest.json"


def _guard(fn, fallback, label):
    """Run fn(); on any unexpected exception warn and return fallback (never crash)."""
    try:
        return fn()
    except Exception as e:
        print(f"[warn] build_manifest: {label} упал ({e}) — использую пустое значение.",
              file=sys.stderr)
        return fallback


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())

    # ── News (M3) ──
    manifest["news"] = _guard(fetch_news, [], "fetch_news")

    # ── Program + progress (M2, Rostov Unit) ──
    posts = _guard(fetch_posts,
                   {"connected": False, "program": None, "finance": None, "songs": []},
                   "fetch_posts")
    if not posts["connected"]:
        print("[warn] build_manifest: Telethon (Rostov) недоступен — программу и прогресс не трогаю.",
              file=sys.stderr)
    else:
        if posts["program"]:
            manifest["program"] = _guard(
                lambda: extract_program(posts["program"]), [], "extract_program")
        else:
            print("[warn] build_manifest: пост программы не найден — программа пустая.",
                  file=sys.stderr)
            manifest["program"] = []

        if posts["finance"]:
            prog = _guard(lambda: extract_progress(posts["finance"]),
                          {"raised": None, "plan": None}, "extract_progress")
            manifest["raised"], manifest["plan"] = prog["raised"], prog["plan"]
        else:
            print("[warn] build_manifest: пост финансов не найден — прогресс пустой.",
                  file=sys.stderr)
            manifest["raised"], manifest["plan"] = None, None

        # Song numbers (regex «ПС N» / «Прабхат Самгит N», no LLM) — a suggestion
        # the operator picker prefills; connected but none found → empty list.
        manifest["suggested_songs"] = posts.get("songs", [])

        # New-song alerts (Б Telegram + В macOS) — idempotent, independent of
        # program/news/video; a failure here never blocks the build.
        _guard(lambda: notify_new_songs(posts.get("songs", [])), None, "song_alerts")

    # ── Dada video (M2, СВАДХЬЯЯ) — independent; any failure → "" (deck shows stub) ──
    vid = _guard(fetch_dada_video, {"connected": False, "video_url": ""}, "fetch_dada_video")
    manifest["video_url"] = vid["video_url"]

    manifest.setdefault("suggested_songs", [])   # always present (disconnected → keep prior)
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(f"manifest обновлён: news={len(manifest.get('news', []))}, "
          f"program={len(manifest.get('program', []))}, raised={manifest.get('raised')}, "
          f"songs={manifest.get('suggested_songs')}, "
          f"video_url={manifest.get('video_url') or '—'} → {MANIFEST_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
