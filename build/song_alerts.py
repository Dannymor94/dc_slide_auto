#!/usr/bin/env python3
"""Build-run reporting (Mac build-side), three channels driven by one status:
    Channel Б — Telegram FULL summary to TELEGRAM_ALERT_CHAT, EVERY build.
    Channel В — macOS traffic-light (osascript), EVERY build (✅/❌; ⚠️ new-song
                once per number via alerted_songs.json).
    Channel А — the form status line (server-side, reads last_build_status.json).

"New song" = a chat number with NEITHER an image (deck/assets/songs/N.*) NOR
catalog text (data/songs_seed.json) — same hybrid rule as the song slide.

Split of idempotency (per the contract):
    build STATUS  → sent every build (run status; weekly dup is expected)
    "new song №N" → once per number (alerted_songs.json), so a re-run doesn't
                    re-panic about an already-known song.

Everything degrades gracefully and never raises — a failed channel never blocks
the build, and the channels are independent.
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


# ── "in base?" — image OR catalog text ──────────────────────────────────────────
def has_image(n: int) -> bool:
    return any((SONGS_DIR / f"{n}.{ext}").exists() for ext in IMG_EXTS)


def catalog_numbers() -> set:
    try:
        data = json.loads(SEED_PATH.read_text())
        return {int(s["number"]) for s in data if isinstance(s, dict) and "number" in s}
    except Exception:
        return set()


def is_in_base(n: int, catalog: set | None = None) -> bool:
    catalog = catalog_numbers() if catalog is None else catalog
    return has_image(n) or (n in catalog)


def find_new_songs(numbers) -> list:
    """Numbers with neither image nor catalog text, order preserved."""
    catalog = catalog_numbers()
    return [n for n in numbers if not is_in_base(n, catalog)]


# ── idempotency store (Mac-side runtime state, gitignored) ───────────────────────
def load_alerted() -> set:
    try:
        return {int(x) for x in json.loads(ALERTED_PATH.read_text()).get("alerted", [])}
    except Exception:
        return set()


def save_alerted(numbers: set) -> None:
    ALERTED_PATH.write_text(
        json.dumps({"alerted": sorted(numbers)}, ensure_ascii=False, indent=2) + "\n")


# ── Channel В: one macOS notification with a given body ──────────────────────────
def notify_macos_text(body: str, title: str = "dc-deck: прожиг") -> bool:
    """osascript notification. Tries the user's GUI session first (works from
    launchd via `launchctl asuser`), then a plain call. Non-macOS / failure →
    warning + False (never blocks the build)."""
    if platform.system() != "Darwin":
        print("[warn] song_alerts: не macOS — канал В пропущен.", file=sys.stderr)
        return False
    script = (f"display notification {json.dumps(body, ensure_ascii=False)} "
              f"with title {json.dumps(title, ensure_ascii=False)} sound name \"default\"")
    uid = str(os.getuid())
    for cmd in (["launchctl", "asuser", uid, "osascript", "-e", script],
                ["osascript", "-e", script]):
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=10)
            return True
        except Exception:
            continue
    print("[warn] song_alerts: osascript не показал (launchd без GUI-сессии?) — В пропущен.",
          file=sys.stderr)
    return False


# ── Channel Б: full Telegram summary text ────────────────────────────────────────
_EMOJI = {True: "✅", False: "❌", None: "⏭"}


def _nums(seq) -> str:
    return ", ".join(f"№{n}" for n in seq)


def _line(label: str, st) -> str:
    if not st:
        return f"⏭ {label}: —"
    val = st.get("value") or st.get("error") or "—"
    return f"{_EMOJI.get(st.get('ok'))} {label}: {val}"


def build_summary_text(status: dict) -> str:
    lines = [f"🔨 Прожиг dc-deck · {status.get('ts') or '—'}",
             _line("Программа", status.get("program")),
             _line("Деньги", status.get("money")),
             _line("Видео", status.get("video")),
             _line("Новости", status.get("news"))]
    songs = status.get("songs") or {}
    sug, miss = songs.get("suggested") or [], songs.get("missing") or []
    if sug:
        tail = (f" · ⚠️ нет в базе: {_nums(miss)}" if miss else " · все в базе")
        lines.append(f"{'⚠️' if miss else '✅'} Песни: предложены {_nums(sug)}{tail}")
    else:
        lines.append("➖ Песни: из чата не заданы")
    lines.append(_line("Деплой", status.get("deploy")))
    lines.append("подробности: ~/dc-deck-build.log")
    return "\n".join(lines)


def _build_failed(status: dict) -> bool:
    return any((status.get(k) or {}).get("ok") is False
               for k in ("program", "money", "video", "news", "deploy"))


# ── orchestrator: Б summary (always) + В traffic-light (always; ⚠️ once) ──────────
def report_build(status: dict) -> dict:
    """Send the full Telegram summary (Б, every build) and the macOS traffic-light
    (В, every build; ⚠️ new-song once per number). Returns a summary dict. Never
    raises. STATUS is per-run (dup expected weekly); the new-song ⚠️ is idempotent."""
    result = {"tg": False, "macos": False, "new": []}
    # Channel Б — full summary, every build
    try:
        from fetch_telegram import send_alert
        result["tg"] = send_alert(build_summary_text(status))
    except Exception as e:
        print(f"[warn] song_alerts: Telegram-сводка не ушла ({e}).", file=sys.stderr)

    # new (not-yet-alerted) missing songs — the once-per-number flag
    missing = [int(n) for n in ((status.get("songs") or {}).get("missing") or [])]
    alerted = load_alerted()
    new = [n for n in missing if n not in alerted]
    result["new"] = new

    # Channel В — macOS traffic-light, priority ❌ > ⚠️(new) > ✅
    try:
        if _build_failed(status):
            result["macos"] = notify_macos_text("❌ Прожиг не прошёл — смотри Telegram/лог")
        elif new:
            result["macos"] = notify_macos_text(f"⚠️ Новая песня {_nums(new)} — нет в базе, добавь")
            save_alerted(alerted | set(new))     # mark only when the ⚠️ actually showed
        else:
            result["macos"] = notify_macos_text("✅ Прожиг прошёл успешно")
    except Exception as e:
        print(f"[warn] song_alerts: macOS-светофор не показан ({e}).", file=sys.stderr)
    return result


if __name__ == "__main__":
    demo = {"program": {"ok": True, "value": "6 пунктов", "error": None},
            "money": {"ok": True, "value": "18700/30000", "error": None},
            "video": {"ok": True, "value": "youtu.be/x", "error": None},
            "news": {"ok": True, "value": "4", "error": None},
            "songs": {"suggested": [50, 1041], "missing": [1041]},
            "deploy": {"ok": True, "value": "manifest → dist", "error": None},
            "ts": "demo"}
    print(build_summary_text(demo))
