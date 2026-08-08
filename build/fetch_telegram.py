#!/usr/bin/env python3
"""Read Telegram chat history via Telethon (M2 backlog — Mac build-side).

Two independent pulls, both over the reused Crosspost session (read-only):
  • fetch_posts()       — Rostov Unit chat → program post + finance post
  • fetch_dada_video()  — СВАДХЬЯЯ chat   → newest YouTube link (Dada video)

REUSES the existing Crosspost session & credentials — never starts a new auth.
Resolved dc-deck names first, Crosspost names as fallback:
    api_id   : TELEGRAM_API_ID   → TG_API_ID
    api_hash : TELEGRAM_API_HASH  → TG_API_HASH
    session  : TELEGRAM_SESSION   → TG_SESSION_PATH
Crosspost's own .env (CROSSPOST_ENV, default runtime/.env) is loaded as a fallback
layer. Crosspost stores a **StringSession** as text; we load it into memory and
never write it back, so its file stays untouched (SQLite .session also supported).

dc-deck .env chats (NOT in Crosspost config):
    TELEGRAM_CHAT             Rostov Unit chat — id or @username        (for fetch_posts)
    TELEGRAM_SENDER           Rostov Unit channel — filter (optional)
    TELEGRAM_HISTORY_DAYS     Rostov PROGRAM window, days (default 7 — program is weekly)
    TELEGRAM_FINANCE_DAYS     Rostov FINANCE window, days (default 30 — report is monthly)
    TELEGRAM_SVADHYAYA_CHAT   СВАДХЬЯЯ chat — id or @username           (for fetch_dada_video)
    TELEGRAM_SVADHYAYA_DAYS   video window, days (default 6)

⚠ The session/auth is shared with Crosspost — run only when Crosspost is idle to
avoid a duplicate-auth (AUTH_KEY_DUPLICATED) that would log Crosspost out.

Both fetchers never raise; on any failure they degrade (empty result + warning).
"""
from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Fallback layer: Crosspost's own env (dc-deck values already loaded take precedence).
CROSSPOST_ENV = os.environ.get("CROSSPOST_ENV", "/Users/danny/Documents/crosspost/runtime/.env")
_CROSSPOST_ROOT = Path(CROSSPOST_ENV).resolve().parent.parent   # runtime/.env → crosspost/
if Path(CROSSPOST_ENV).exists():
    load_dotenv(CROSSPOST_ENV, override=False)

_TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d\b")
_PROGRAM_KEYS = ("программа", "джагрити", "воскресну")
_FINANCE_KEYS = ("дч донаты", "пост о финансах")
# ONLY youtu.be / youtube.com/watch — RuTube, Teletype, etc. ignored. Captures the video id.
_YT_RE = re.compile(r"(?:youtu\.be/|youtube\.com/watch\?(?:\S*&)?v=)([\w-]+)", re.IGNORECASE)
# Song numbers people post in the Rostov chat: «ПС 50» / «Прабхат Самгит 1041».
# One prefix may head a comma/«и»-separated list («ПС 50, 1041» → [50, 1041]).
# Lookbehind blocks a mid-word «пс» (e.g. «Гопсвами»); \s* allows «ПС50».
_SONG_PREFIX_RE = re.compile(r"(?<![а-яёa-z])(?:прабхат\s+самгит|пс)", re.IGNORECASE)
_SONG_FIRST_RE = re.compile(r"\s*(?:№|#)?\s*(\d+)")
_SONG_NEXT_RE = re.compile(r"\s*(?:,|;|/|\+|и)\s*(?:№|#)?\s*(\d+)", re.IGNORECASE)


def _env(*names: str) -> str | None:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return None


def _coerce(v: str | None):
    """Chat/sender may be a numeric id (possibly -100…) or an @username."""
    if v is None:
        return None
    v = v.strip()
    return int(v) if re.fullmatch(r"-?\d+", v) else v


def _session_path() -> Path:
    """Absolute path to the session file (a relative TG_SESSION_PATH is resolved
    against the Crosspost project root). The .session suffix is ensured."""
    raw = _env("TELEGRAM_SESSION", "TG_SESSION_PATH")
    p = Path(raw)
    if not p.is_absolute():
        p = _CROSSPOST_ROOT / p
    return p if p.suffix == ".session" else p.with_suffix(".session")


def build_session():
    """StringSession from Crosspost's text file (read-only), or a SQLite session name."""
    p = _session_path()
    if not p.exists():
        print(f"[warn] fetch_telegram: session-файл не найден: {p}", file=sys.stderr)
        return str(p.with_suffix(""))
    if p.read_bytes()[:15] == b"SQLite format 3":
        return str(p.with_suffix(""))
    from telethon.sessions import StringSession
    return StringSession(p.read_text().strip())


def make_client():
    """A TelegramClient built from the reused Crosspost session & credentials."""
    from telethon.sync import TelegramClient
    api_id = _env("TELEGRAM_API_ID", "TG_API_ID")
    api_hash = _env("TELEGRAM_API_HASH", "TG_API_HASH")
    return TelegramClient(build_session(), int(api_id), api_hash)


def _creds_ok() -> bool:
    return bool(_env("TELEGRAM_API_ID", "TG_API_ID") and _env("TELEGRAM_API_HASH", "TG_API_HASH")
                and _env("TELEGRAM_SESSION", "TG_SESSION_PATH"))


# ── Rostov Unit: program + finance posts ────────────────────────────────────────
def _config() -> dict | None:
    chat = _env("TELEGRAM_CHAT")
    if not (_creds_ok() and chat):
        missing = [n for n, v in (("creds", _creds_ok()), ("TELEGRAM_CHAT", chat)) if not v]
        print(f"[warn] fetch_telegram: не хватает конфигурации: {', '.join(missing)} — "
              f"Telethon пропущен.", file=sys.stderr)
        return None
    return {
        "chat": _coerce(chat),
        "sender": _coerce(os.environ.get("TELEGRAM_SENDER")),
        "days": int(os.environ.get("TELEGRAM_HISTORY_DAYS", "7")),
        "finance_days": int(os.environ.get("TELEGRAM_FINANCE_DAYS", "30")),
    }


def is_program_post(text: str) -> bool:
    t = text.lower()
    return bool(_TIME_RE.search(text)) and any(k in t for k in _PROGRAM_KEYS)


def is_finance_post(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in _FINANCE_KEYS)


def extract_song_numbers(text: str) -> list[int]:
    """Ordered, de-duplicated Prabhat Samgita numbers from a chat post — NO LLM.
    «ПС 50 и Прабхат Самгит 1041» → [50, 1041]; a single prefix may head a list,
    «ПС 50, 1041» → [50, 1041]. Order in the text = order of the song slides.
    No match / empty input → []."""
    if not text:
        return []
    out: list[int] = []
    seen: set[int] = set()

    def _add(n: int) -> None:
        if n not in seen:
            seen.add(n)
            out.append(n)

    for pm in _SONG_PREFIX_RE.finditer(text):
        fm = _SONG_FIRST_RE.match(text, pm.end())
        if not fm:                                   # bare «ПС» with no number
            continue
        _add(int(fm.group(1)))
        i = fm.end()
        while (nm := _SONG_NEXT_RE.match(text, i)):   # comma/«и»-separated tail
            _add(int(nm.group(1)))
            i = nm.end()
    return out


def fetch_posts(days: int | None = None, finance_days: int | None = None) -> dict:
    """Newest program post (last `days`) + newest finance report (last `finance_days`).

    Program is weekly → short window. The finance report is MONTHLY (rarer than
    weekly), so it gets its own wider window; a 7-day window would often miss it
    entirely and leave the progress bar stale. iter_messages is newest-first, so
    the FIRST finance match within the window is the latest report."""
    cfg = _config()
    if cfg is None:
        return {"connected": False, "program": None, "finance": None, "songs": []}
    try:
        from telethon import utils
    except ImportError:
        print("[warn] fetch_telegram: telethon не установлен — Telethon пропущен.", file=sys.stderr)
        return {"connected": False, "program": None, "finance": None, "songs": []}

    days = days if days is not None else cfg["days"]
    finance_days = finance_days if finance_days is not None else cfg["finance_days"]
    now = datetime.now(timezone.utc)
    program_cutoff = now - timedelta(days=days)
    finance_cutoff = now - timedelta(days=max(finance_days, days))   # the wider window
    program = finance = songs = None
    try:
        with make_client() as client:
            sender_id = None
            if cfg["sender"] is not None:
                try:
                    sender_id = utils.get_peer_id(client.get_entity(cfg["sender"]))
                except Exception as e:
                    print(f"[warn] fetch_telegram: sender {cfg['sender']} не резолвится "
                          f"({e}) — фильтр отправителя отключён.", file=sys.stderr)
            for msg in client.iter_messages(cfg["chat"]):
                # newest-first; stop once past the wider (finance) window
                if msg.date and msg.date < finance_cutoff:
                    break
                if sender_id is not None and msg.sender_id != sender_id:
                    continue
                text = (msg.message or "").strip()
                if not text:
                    continue
                in_prog_window = msg.date is not None and msg.date >= program_cutoff
                if program is None and in_prog_window and is_program_post(text):
                    program = text          # newest program post, short window only
                elif finance is None and is_finance_post(text):
                    finance = text          # newest finance report, month window
                if songs is None and in_prog_window:
                    nums = extract_song_numbers(text)
                    if nums:
                        songs = nums        # newest post carrying song numbers (weekly)
                if program and finance:
                    break
        return {"connected": True, "program": program, "finance": finance, "songs": songs or []}
    except Exception as e:
        print(f"[warn] fetch_telegram: ошибка Telethon ({e}) — Telethon пропущен.", file=sys.stderr)
        return {"connected": False, "program": None, "finance": None, "songs": []}


# ── Уроки медитации: weekly meeting schedule post ────────────────────────────────
# The КМ meeting schedule lives in a SEPARATE post of the Уроки-медитации channel
# (t.me/urokimeditacii_rnd) — the day-of invitation ("План мероприятий" /
# "Расписание мероприятия"), NOT the multi-day "Афиша недели" (that is already the
# Airtable calendar) and NOT the ДЧ program post the main deck parses. We pick the
# post COVERING the КМ date (same ISO week) and parse its schedule lines.
#
# Two real line shapes on the channel:
#   "✅ Коллективная медитация — 11:00"      (name — time)
#   "🧘11:00 — Коллективная медитация"        (time — name, richer posts)
# Intro prose also contains a time ("…в 11:00 в студии…") → excluded: a schedule
# line either starts with a bullet/emoji or has its time at the very edge.
from zoneinfo import ZoneInfo as _ZoneInfo

_MSK_TG = _ZoneInfo("Europe/Moscow")
_WD_ABBR = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_RU_MON_GEN = {1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
               7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря"}
_KM_MARKER_TG = "коллективная медитац"
_CYR = "А-Яа-яЁё"


def _is_schedule_line(line: str, tstart: int, tend: int) -> bool:
    """A real schedule row (not intro prose): starts with a bullet/emoji, or the
    time sits at the very start/end of the line."""
    head = line.lstrip()[:1]
    starts_bullet = bool(head) and not re.match(f"[{_CYR}]", head)
    return starts_bullet or tstart <= 3 or (len(line) - tend) <= 3


def _clean_meeting_name(line: str, tstart: int, tend: int) -> str:
    """Strip the time + leading bullets/emoji + trailing dashes/punct → event name."""
    name = line[:tstart] + line[tend:]
    name = re.sub(f"^[^{_CYR}«(]+", "", name)          # drop leading emoji/✅/dash/digits
    name = re.sub(f"[^{_CYR}»).!]+$", "", name)        # drop trailing dash/emoji/punct/space
    name = re.sub(r"\s{2,}", " ", name).strip()
    return name


def parse_um_meeting(text: str) -> list[dict]:
    """Schedule items from a Уроки-медитации meeting post. Deterministic, no LLM.
    Returns [{time, name, km}] in CHRONOLOGICAL order (a schedule reads by the
    clock). The km flag drives styling only, not position. [] if none."""
    items: list[dict] = []
    for line in (text or "").splitlines():
        m = _TIME_RE.search(line)
        if not m:
            continue
        if not _is_schedule_line(line, m.start(), m.end()):
            continue
        name = _clean_meeting_name(line, m.start(), m.end())
        if len(name) < 2 or not re.search(f"[{_CYR}]", name):
            continue
        hh, mm = m.group(0).split(":")
        time = f"{int(hh):02d}:{mm}"
        km = _KM_MARKER_TG in name.lower()
        items.append({"time": time, "name": name, "km": km})
    # Strict chronological order — HH:MM is zero-padded, so a lexical sort == time
    # sort. (The "КМ first" rule applies only to calendar cells, which have no times.)
    items.sort(key=lambda i: i["time"])
    return items


def fetch_um_meeting(km_date, channel: str) -> dict | None:
    """Meeting card for the КМ day from the Уроки channel, or None (no card drawn).

    Picks the post in km_date's ISO week that is NOT the weekly «Афиша недели»,
    carries a parseable schedule, and contains the КМ line. Never raises: missing
    creds / telethon / channel error / no matching post / no times → None.
    `channel` may be 't.me/name', '@name' or 'name'.
    """
    if km_date is None:
        return None
    uname = channel.strip().rsplit("/", 1)[-1].lstrip("@")
    if not (_creds_ok() and uname):
        print("[warn] fetch_um_meeting: нет creds/канала — расписание встречи пропущено.",
              file=sys.stderr)
        return None
    try:
        import telethon  # noqa: F401
    except ImportError:
        print("[warn] fetch_um_meeting: telethon не установлен — расписание пропущено.", file=sys.stderr)
        return None

    monday = km_date - timedelta(days=km_date.weekday())   # Monday of the КМ week
    week_end = monday + timedelta(days=7)
    try:
        with make_client() as client:
            scanned = 0
            for msg in client.iter_messages(uname):
                scanned += 1
                if scanned > 200:
                    break
                if not msg.date:
                    continue
                d = msg.date.astimezone(_MSK_TG).date()
                if d >= week_end:
                    continue          # newer than the КМ week → keep scanning back
                if d < monday:
                    break             # older than the КМ week → done
                text = (msg.message or "").strip()
                if not text or "афиша недели" in text.lower():
                    continue          # skip the multi-day weekly poster
                items = parse_um_meeting(text)
                if not items or not any(i["km"] for i in items):
                    continue          # a meeting post must carry the КМ line
                label = f"{_WD_ABBR[km_date.weekday()]} {km_date.day} {_RU_MON_GEN[km_date.month]}"
                print(f"[info] fetch_um_meeting: пост id={msg.id} ({d}), пунктов={len(items)}",
                      file=sys.stderr)
                return {"date_label": label, "items": items}
        print("[info] fetch_um_meeting: пост встречи на неделю КМ не найден — карточки нет.",
              file=sys.stderr)
        return None
    except Exception as e:
        print(f"[warn] fetch_um_meeting: ошибка Telethon ({e}) — расписание пропущено.", file=sys.stderr)
        return None


# ── СВАДХЬЯЯ: newest Dada YouTube link ───────────────────────────────────────────
def youtube_url(text: str) -> str | None:
    """Clean https://youtu.be/<id> for the first youtu.be / youtube.com/watch link
    in `text`; None for other domains (RuTube, Teletype, …) or no link.
    Tracking params (e.g. '?is=…') are dropped."""
    if not text:
        return None
    m = _YT_RE.search(text)
    return f"https://youtu.be/{m.group(1)}" if m else None


def fetch_dada_video(days: int = 6) -> dict:
    """Newest YouTube link in the СВАДХЬЯЯ chat within `days`.
    Returns {"connected": bool, "video_url": str}; video_url "" if none.
    Independent of fetch_posts. Never raises — any failure → video_url ""."""
    chat = _env("TELEGRAM_SVADHYAYA_CHAT")
    if not (_creds_ok() and chat):
        missing = [n for n, v in (("creds", _creds_ok()), ("TELEGRAM_SVADHYAYA_CHAT", chat)) if not v]
        print(f"[warn] fetch_dada_video: не хватает конфигурации: {', '.join(missing)} — "
              f"видео пропущено.", file=sys.stderr)
        return {"connected": False, "video_url": ""}
    try:
        import telethon  # noqa: F401
    except ImportError:
        print("[warn] fetch_dada_video: telethon не установлен — видео пропущено.", file=sys.stderr)
        return {"connected": False, "video_url": ""}

    days = int(os.environ.get("TELEGRAM_SVADHYAYA_DAYS", days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    try:
        with make_client() as client:
            # newest-first → the first YouTube link found is the latest
            for msg in client.iter_messages(_coerce(chat)):
                if msg.date and msg.date < cutoff:
                    break
                url = youtube_url(msg.message or "")
                if url:
                    return {"connected": True, "video_url": url}
            return {"connected": True, "video_url": ""}
    except Exception as e:
        print(f"[warn] fetch_dada_video: ошибка Telethon ({e}) — видео пропущено.", file=sys.stderr)
        return {"connected": False, "video_url": ""}


# ── Alerts group: outgoing message over the same StringSession (NOT a bot) ───────
def send_alert(text: str) -> bool:
    """Send `text` to the alerts group (TELEGRAM_ALERT_CHAT) via client.send_message
    over the reused StringSession. Returns True on success; never raises — any
    failure → warning + False (so the build never breaks on a failed alert)."""
    chat = _env("TELEGRAM_ALERT_CHAT")
    if not (_creds_ok() and chat):
        print("[warn] send_alert: нет TELEGRAM_ALERT_CHAT / creds — Telegram-алерт пропущен.",
              file=sys.stderr)
        return False
    try:
        with make_client() as client:
            client.send_message(_coerce(chat), text)
        return True
    except Exception as e:
        print(f"[warn] send_alert: ошибка отправки ({e}) — Telegram-алерт пропущен.", file=sys.stderr)
        return False


def main() -> None:
    posts = fetch_posts()
    print(f"[posts] connected={posts['connected']}", file=sys.stderr)
    for key in ("program", "finance"):
        val = posts[key]
        head = (val[:120] + "…") if val and len(val) > 120 else (val or "— не найден")
        print(f"\n[{key}]\n{head}")
    vid = fetch_dada_video()
    print(f"\n[dada_video] connected={vid['connected']} → {vid['video_url'] or '— нет'}")


if __name__ == "__main__":
    main()
