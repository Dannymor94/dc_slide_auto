#!/usr/bin/env python3
"""Fetch unit news from Airtable for the manifest (M3, Mac build-side).

Deterministic, NO LLM. Blocking integrations live on the Mac side only; the
VPS never calls out.

Pipeline:
    1. GET published records whose Дата falls in the MSK window
       [today … end of this calendar month].
    2. Drop ghost rows that have no Name (from Название).
    3. Show-dictionary (build/news_show.json):
         routine  → skip
         announce → keep
         unknown  → keep + flag as "new type" (logged to stderr, never hidden)
    4. Fold identical Names into one line; dates collapsed per month, MSK.
       "Асана-класс — 6, 13, 20 августа"

Dates: Airtable returns ISO UTC timestamps ('…Z'). We convert to MSK BEFORE
taking .date(), so a late-evening event doesn't slip to the wrong calendar day.

HTTP uses `requests`: it percent-encodes UTF-8 query params (Cyrillic field
names like {Дата} in filterByFormula) and keeps headers ASCII, avoiding
urllib's latin-1 header encoding.

Resilience: no token or any Airtable error → returns [] and prints a warning.
Never raises — the manifest build must degrade to empty news, never crash.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime, timedelta
from itertools import groupby
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── Airtable identifiers ────────────────────────────────────────────────────────
BASE_ID = "appgi18TrXayt3VSG"
TABLE_ID = "tbl5P4t8CTqEE8sLv"
API_URL = f"https://api.airtable.com/v0/{BASE_ID}/{TABLE_ID}"

# Field IDs (used with returnFieldsByFieldId=true when reading records).
FIELD_NAME = "fldVK7klidt4z84OB"   # Name (from Название) — lookup, value is a list
FIELD_DATE = "fldWA3TKUvyWJsNqv"   # Дата

SHOW_DICT_PATH = Path(__file__).parent / "news_show.json"
MSK = ZoneInfo("Europe/Moscow")

RU_MONTHS = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая", 6: "июня",
    7: "июля", 8: "августа", 9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}


# ── MSK date window: [today … end of this calendar month] ───────────────────────
def msk_window() -> tuple[date, date]:
    """(today, first_of_next_month) in MSK. Window includes today and the
    month's last day (i.e. strictly before first_of_next_month)."""
    today = datetime.now(MSK).date()
    first_next = (
        date(today.year + 1, 1, 1)
        if today.month == 12
        else date(today.year, today.month + 1, 1)
    )
    return today, first_next


def window_formula(today: date, first_next: date) -> str:
    """filterByFormula uses field NAMES ({status}, {Дата}). Bounds are exclusive
    one day outside the window, so today..last-day-of-month are included."""
    yesterday = today - timedelta(days=1)
    return (
        "AND("
        "{status}='published',"
        f"IS_AFTER({{Дата}}, '{yesterday.isoformat()}'),"
        f"IS_BEFORE({{Дата}}, '{first_next.isoformat()}')"
        ")"
    )


# ── Show dictionary (step 3) ────────────────────────────────────────────────────
def load_show_dict() -> tuple[set, set]:
    """(announce, routine) name sets. Missing/broken file → empty sets, so every
    name counts as 'unknown' (kept + flagged) — never silently hidden."""
    if SHOW_DICT_PATH.exists():
        try:
            d = json.loads(SHOW_DICT_PATH.read_text())
            return set(d.get("announce", [])), set(d.get("routine", []))
        except Exception as e:
            print(f"[warn] news_show.json нечитаем ({e}) — словарь считаю пустым.",
                  file=sys.stderr)
    return set(), set()


# ── HTTP (requests: UTF-8 query auto-encode, ASCII headers) ─────────────────────
def _fetch_raw(token: str, formula: str) -> list[dict]:
    """All matching records, following pagination offsets."""
    headers = {"Authorization": f"Bearer {token}"}
    records: list[dict] = []
    offset: str | None = None
    while True:
        params = {
            "filterByFormula": formula,
            "returnFieldsByFieldId": "true",
            "pageSize": 100,
        }
        if offset:
            params["offset"] = offset
        resp = requests.get(API_URL, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            return records


# ── Field extraction ────────────────────────────────────────────────────────────
def _name_of(fields: dict) -> str | None:
    """Name (from Название) is a lookup → value is a list. Empty/missing = ghost."""
    v = fields.get(FIELD_NAME)
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, str):
        v = v.strip()
    return v or None


def _msk_date(iso: str | None) -> date | None:
    """ISO UTC timestamp → MSK calendar date (shift BEFORE taking .date())."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(MSK).date()
    except ValueError:
        try:
            return date.fromisoformat(iso[:10])   # date-only value, no tz shift
        except ValueError:
            return None


def _format_dates(dates: list[date]) -> str:
    """Sorted, collapsed per month: '6, 13, 20 августа', '30 августа, 2 сентября'."""
    parts = []
    for (_, m), grp in groupby(sorted(dates), key=lambda d: (d.year, d.month)):
        days = [str(d.day) for d in grp]
        parts.append(f"{', '.join(days)} {RU_MONTHS[m]}")
    return ", ".join(parts)


# ── Public API ──────────────────────────────────────────────────────────────────
def fetch_news() -> list[str]:
    """Full pipeline (steps 1-4). Deck-ready lines. Never raises."""
    token = os.environ.get("AIRTABLE_TOKEN")
    if not token:
        print("[warn] fetch_news: AIRTABLE_TOKEN не задан — новости пустые (заглушка).",
              file=sys.stderr)
        return []

    today, first_next = msk_window()
    formula = window_formula(today, first_next)

    try:
        records = _fetch_raw(token, formula)
    except requests.HTTPError as e:
        r = e.response
        code = r.status_code if r is not None else "?"
        body = (r.text or "")[:300] if r is not None else ""
        print(f"[warn] fetch_news: Airtable HTTP {code}: {body} — новости пустые (заглушка).",
              file=sys.stderr)
        return []
    except Exception as e:
        print(f"[warn] fetch_news: ошибка Airtable ({e}) — новости пустые (заглушка).",
              file=sys.stderr)
        return []

    announce, routine = load_show_dict()

    # steps 2-3: filter ghosts + routine; group by name preserving first-seen order
    groups: dict[str, dict] = {}
    dropped_ghost = skipped_routine = 0
    for rec in records:
        fields = rec.get("fields", {})
        name = _name_of(fields)
        if not name:
            dropped_ghost += 1
            continue
        if name in routine:
            skipped_routine += 1
            continue
        g = groups.setdefault(name, {"dates": [], "is_new": name not in announce})
        d = _msk_date(fields.get(FIELD_DATE))
        if d:
            g["dates"].append(d)

    # step 4: fold → one line per name, chronological by earliest date
    ordered = sorted(
        groups.items(),
        key=lambda kv: min(kv[1]["dates"]) if kv[1]["dates"] else date.max,
    )
    lines = [
        f"{name} — {_format_dates(g['dates'])}" if g["dates"] else name
        for name, g in ordered
    ]

    # log-only signals (never leak into deck content)
    new_types = [name for name, g in ordered if g["is_new"]]
    print(f"[info] fetch_news: призраков={dropped_ghost}, "
          f"рутина-скрыто={skipped_routine}, строк={len(lines)}", file=sys.stderr)
    if new_types:
        print(f"[info] fetch_news: новые типы (не в словаре, показаны с флагом): "
              f"{', '.join(new_types)} — раскидай по announce/routine в news_show.json",
              file=sys.stderr)
    return lines


def main() -> None:
    today, first_next = msk_window()
    print(f"Окно МСК: [{today} … {first_next - timedelta(days=1)}]", file=sys.stderr)
    news = fetch_news()
    print(f"Новостей: {len(news)}\n", file=sys.stderr)
    for line in news:
        print(line)


if __name__ == "__main__":
    main()
