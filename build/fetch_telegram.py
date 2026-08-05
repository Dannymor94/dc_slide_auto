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
