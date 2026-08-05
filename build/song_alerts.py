#!/usr/bin/env python3
"""New-song alerts (Mac build-side). A song number posted in the Rostov chat is
"new" if it has NEITHER an image (deck/assets/songs/N.*) NOR catalog text
(data/songs_seed.json). Each newly-seen new number is alerted ONCE via:
    Channel Б — Telegram message to TELEGRAM_ALERT_CHAT (fetch_telegram.send_alert)
    Channel В — macOS notification (osascript)
Idempotent via build/alerted_songs.json — a number is alerted only once and never
re-sent on the next weekly build. Channel А (the form banner) is separate and
passive (server-side, always shown until the image/text appears).

Everything degrades gracefully and never raises — a failed alert never blocks the
build, and the three channels are independent of each other.
"""
from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SONGS_DIR = ROOT / "deck" / "assets" / "songs"
SEED_PATH = ROOT / "data" / "songs_seed.json"
ALERTED_PATH = Path(__file__).parent / "alerted_songs.json"
IMG_EXTS = ("webp", "png", "jpg", "jpeg")
_TITLE = "dc-deck: новая песня"


# ── "in base?" — reuse of the hybrid rule: image OR catalog text ────────────────
def has_image(n: int) -> bool:
    return any((SONGS_DIR / f"{n}.{ext}").exists() for ext in IMG_EXTS)


def catalog_numbers() -> set[int]:
    """Numbers present as text in data/songs_seed.json (list of {number,...})."""
    try:
        data = json.loads(SEED_PATH.read_text())
        return {int(s["number"]) for s in data if isinstance(s, dict) and "number" in s}
    except Exception:
        return set()


def is_in_base(n: int, catalog: set[int] | None = None) -> bool:
    catalog = catalog_numbers() if catalog is None else catalog
    return has_image(n) or (n in catalog)


def find_new_songs(numbers) -> list[int]:
    """Numbers with neither image nor catalog text, order preserved."""
    catalog = catalog_numbers()
    return [n for n in numbers if not is_in_base(n, catalog)]


# ── idempotency store ───────────────────────────────────────────────────────────
def load_alerted() -> set[int]:
    try:
        return {int(x) for x in json.loads(ALERTED_PATH.read_text()).get("alerted", [])}
    except Exception:
        return set()


def save_alerted(numbers: set[int]) -> None:
    ALERTED_PATH.write_text(
        json.dumps({"alerted": sorted(numbers)}, ensure_ascii=False, indent=2) + "\n")


# ── Channel В: macOS notification ────────────────────────────────────────────────
def notify_macos(numbers: list[int]) -> bool:
    """osascript notification. Tries the user's GUI session first (works from
    launchd), then a plain call. Non-macOS / failure → warning + False."""
    if platform.system() != "Darwin":
        print("[warn] song_alerts: не macOS — уведомление В пропущено.", file=sys.stderr)
        return False
    nums = ", ".join(f"№{n}" for n in numbers)
    body = (f"Песня {nums} — нет в базе, добавь картинку в assets/songs/{numbers[0]}.webp"
            if len(numbers) == 1
            else f"Новые песни: {nums} — добавь картинки в assets/songs/")
    script = (f"display notification {json.dumps(body, ensure_ascii=False)} "
              f"with title {json.dumps(_TITLE, ensure_ascii=False)} sound name \"default\"")
    uid = str(os.getuid())
    for cmd in (["launchctl", "asuser", uid, "osascript", "-e", script],
                ["osascript", "-e", script]):
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=10)
            return True
        except Exception:
            continue
    print("[warn] song_alerts: osascript не показал уведомление (launchd без GUI-сессии?) — "
          "В пропущено (А и Б работают).", file=sys.stderr)
    return False


# ── Channel Б: Telegram message via the shared StringSession ─────────────────────
def notify_telegram(numbers: list[int]) -> bool:
    try:
        from fetch_telegram import send_alert
    except Exception as e:
        print(f"[warn] song_alerts: send_alert недоступен ({e}) — Б пропущено.", file=sys.stderr)
        return False
    if len(numbers) == 1:
        n = numbers[0]
        text = f"🎵 Новая песня №{n} — в базе нет. Добавь картинку в assets/songs/{n}.webp"
    else:
        lst = ", ".join(f"№{n}" for n in numbers)
        text = f"🎵 Новые песни, нет в базе: {lst}. Добавь картинки в assets/songs/<N>.webp"
    return send_alert(text)


# ── orchestrator ─────────────────────────────────────────────────────────────────
def notify_new_songs(numbers) -> dict:
    """Among `numbers`, find not-in-base ones, and for those not yet alerted send
    Б+В once, then persist. Returns a summary dict. Never raises."""
    try:
        numbers = [int(n) for n in (numbers or [])]
        new = find_new_songs(numbers)
        alerted = load_alerted()
        to_alert = [n for n in new if n not in alerted]     # idempotency filter
        result = {"new": new, "alerted_now": to_alert, "tg": False, "macos": False}
        if to_alert:
            result["tg"] = notify_telegram(to_alert)
            result["macos"] = notify_macos(to_alert)
            # mark once at least one active channel delivered (else retry next build)
            if result["tg"] or result["macos"]:
                save_alerted(alerted | set(to_alert))
        return result
    except Exception as e:
        print(f"[warn] song_alerts: notify_new_songs упал ({e}) — алерты пропущены.", file=sys.stderr)
        return {"new": [], "alerted_now": [], "tg": False, "macos": False}


if __name__ == "__main__":
    nums = [int(a) for a in sys.argv[1:] if a.isdigit()]
    print(json.dumps(notify_new_songs(nums), ensure_ascii=False))
