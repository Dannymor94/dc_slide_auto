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


def _plural_punkt(n: int) -> str:
    m, h = n % 10, n % 100
    if 11 <= h <= 14:
        return "пунктов"
    if m == 1:
        return "пункт"
    if 2 <= m <= 4:
        return "пункта"
    return "пунктов"


def _um_line(st) -> str:
    """Уроки-медитации slide status. «Слайда нет» = ➖ (норма на большинстве недель),
    НЕ ❌ — иначе оператор паникует каждую субботнюю неделю. Данные — из результата
    модуля (highlight_day + длина meeting.items), без пересчёта."""
    st = st or {}
    s = st.get("state")
    if s == "ok":
        n = st.get("items") or 0
        # A real meeting post has ≥2 lines (КМ + чаепитие at minimum). fetch_um_meeting
        # always returns ≥1 (the КМ line), so exactly 1 means only КМ parsed and the
        # rest was lost — a likely sign the free-form post format drifted. Warn, don't ❌.
        if n <= 1:
            return (f"⚠️ Уроки медитации: расписание {n} {_plural_punkt(n)} — "
                    f"проверь, формат поста мог измениться")
        return f"✅ Уроки медитации: слайд есть (вс {st.get('day')}) · расписание {n} {_plural_punkt(n)}"
    if s == "warn":
        return f"⚠️ Уроки медитации: слайд есть (вс {st.get('day')}) · расписание не найдено"
    if s == "error":
        return "❌ Уроки медитации: ошибка — слайд не собран"
    return "➖ Уроки медитации: воскресной КМ нет — слайд не нужен"


def _date_line(st) -> str:
    """Hard date check: ❌ if manifest.date differs from the nearest Sunday."""
    if not st:
        return "⏭ Дата: —"
    if st.get("ok") is False:
        return f"❌ ДАТА: {st.get('error') or st.get('value') or '?'}"
    return f"✅ Дата: {st.get('value') or '?'}"


def build_summary_text(status: dict) -> str:
    lines = [f"🔨 Прожиг dc-deck · {status.get('ts') or '—'}",
             _date_line(status.get("date")),
             _line("Программа", status.get("program")),
             _line("Деньги", status.get("money")),
             _line("Видео", status.get("video"))]
    # video_url stale: a non-empty manual override from a previous week overrides
    # this week's fresh auto video. Not ❌ (deck still plays), just a heads-up.
    vstale = status.get("video_stale")
    if vstale:
        lines.append(f"⚠️ Видео: ручной URL с прошлой недели "
                     f"(week_date={vstale.get('week_date')}) — перекрывает свежее авто")
    lines += [_line("Новости", status.get("news")),
              _um_line(status.get("urokimeditacii"))]
    songs = status.get("songs") or {}
    sug, miss = songs.get("suggested") or [], songs.get("missing") or []
    stale = songs.get("stale")
    if sug:
        tail = (f" · ⚠️ нет в базе: {_nums(miss)}" if miss else " · все в базе")
        lines.append(f"{'⚠️' if miss else '✅'} Песни: {_nums(sug)} из чата (авто){tail}")
    elif stale:
        # No chat numbers this build, but selection carries last week's pick →
        # it will show on the deck as-is (not a break, but likely wrong).
        nums = ", ".join(f"№{n}" for n in (stale.get("numbers") or []))
        lines.append(f"⚠️ Песни: {nums} — с прошлой недели "
                     f"(week_date={stale.get('week_date')}), проверь")
    else:
        lines.append("➖ Песни: из чата не заданы")
    lines.append(_line("Деплой", status.get("deploy")))
    lines.append("подробности: ~/dc-deck-build.log")
    return "\n".join(lines)


def _build_failed(status: dict) -> bool:
    return any((status.get(k) or {}).get("ok") is False
               for k in ("date", "program", "money", "video", "news", "deploy"))


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
