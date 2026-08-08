#!/usr/bin/env python3
"""Optional 'Уроки медитации' welcome slide — data build (Mac side, M1).

Appended to the END of the deck ONLY on weeks whose «Коллективная медитация»
(the Уроки-медитации КМ, Тип УМ) falls on a SUNDAY. Most weeks it is on
Saturday → no slide. This module is DETERMINISTIC and does NOT render, does NOT
call an LLM (the single LLM point — the closing wisdom line — is M2, added
later). It parses Airtable and bakes `manifest.urokimeditacii` (or returns None).

Trigger (agreed, pure Airtable — no news/program corroboration):
    append ⇔ ∃ published «Коллективная медитация» (Тип УМ) event whose MSK date
    is a Sunday AND is in the same ISO week as the ДЧ (`manifest.date`).

Calendar: ALL published events of the ДЧ's month, one cell per day. `kind` is
derived from the event Name via build/urokimeditacii.json (fallback 'other').
On a day with the КМ, the КМ token comes first, then same-day events in Airtable
ROW ORDER (no time sorting — event times are unreliable); max 2 shown then '+N'.
highlight_day = the Sunday КМ day.

Airtable errors → returns None (no slide), never raises. VPS never runs this.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

from fetch_news import API_URL, _msk_date, window_formula
from fetch_telegram import fetch_um_meeting
from wisdom import generate_wisdom

CONFIG_PATH = Path(__file__).parent / "urokimeditacii.json"

# Airtable field NAMES (this module reads by name, not by field-id, to reach
# Тип/Заголовок which have no known field-id here).
F_NAME = "Name (from Название)"   # lookup → list; the event name for kind mapping
F_DATE = "Дата"
F_TIP = "Тип"                     # ["УМ"] / ["АМ"] — direction, used ONLY to pin the КМ
F_ZAG = "Заголовок"              # short label (ДЧ/КМ/СШ…) shown in the calendar cell

# Nominative Russian months (month_label = "август 2026"). fetch_news.RU_MONTHS
# is genitive ("августа") for prose lines — different case, kept separate.
RU_MONTHS_NOM = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель", 5: "май", 6: "июнь",
    7: "июль", 8: "август", 9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}

# Cell accent = the day's most significant kind (a day may hold several events).
KIND_PRIORITY = {"km": 0, "asana": 1, "fk": 2, "charity": 3, "other": 4}


def _load_config() -> dict:
    """Config constants (channel, greeting, schedule_note, kinds). Broken/missing →
    safe defaults so the build never crashes (empty kinds → everything 'other')."""
    try:
        d = json.loads(CONFIG_PATH.read_text())
    except Exception as e:
        print(f"[warn] urokimeditacii.json нечитаем ({e}) — дефолты, kinds пусты.",
              file=sys.stderr)
        d = {}
    return {
        "channel": d.get("channel", ""),
        "greeting": d.get("greeting", ""),
        "schedule_note": d.get("schedule_note", ""),
        "kinds": d.get("kinds", {}),
    }


def _month_bounds(d: date) -> tuple[date, date]:
    """(first day of d's month, first day of next month)."""
    first = d.replace(day=1)
    first_next = (date(d.year + 1, 1, 1) if d.month == 12
                  else date(d.year, d.month + 1, 1))
    return first, first_next


def _fetch_month(token: str, formula: str) -> list[dict]:
    """All published records in the month window, fields keyed by NAME (so Тип /
    Заголовок are reachable). Airtable's returned order = row order (preserved)."""
    headers = {"Authorization": f"Bearer {token}"}
    records: list[dict] = []
    offset: str | None = None
    while True:
        params = {"filterByFormula": formula, "pageSize": 100}
        if offset:
            params["offset"] = offset
        resp = requests.get(API_URL, params=params, headers=headers, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        records.extend(data.get("records", []))
        offset = data.get("offset")
        if not offset:
            return records


def _name_of(fields: dict) -> str | None:
    v = fields.get(F_NAME)
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, str):
        v = v.strip()
    return v or None


def _zag_of(fields: dict) -> str | None:
    v = fields.get(F_ZAG)
    if isinstance(v, list):
        v = v[0] if v else None
    if isinstance(v, str):
        v = v.strip()
    return v or None


def _tip_list(fields: dict) -> list[str]:
    v = fields.get(F_TIP)
    if isinstance(v, str):
        return [v.strip()]
    if isinstance(v, list):
        return [str(x).strip() for x in v]
    return []


def _classify_kind(name: str, kinds_map: dict) -> str:
    """First matching kind by config order; fallback 'other'. km listed first."""
    low = name.lower()
    for kind, keys in kinds_map.items():
        if any(k in low for k in keys):
            return kind
    return "other"


def build_urokimeditacii(manifest_date: str | None) -> dict | None:
    """Bake manifest.urokimeditacii for the ДЧ week, or None (no slide).

    Verbose to stderr (M1 is 'log, no render'). Never raises: any failure →
    None so the deck simply omits the slide.
    """
    if not manifest_date:
        print("[info] urokimeditacii: manifest.date пуст — слайда нет.", file=sys.stderr)
        return None
    try:
        anchor = date.fromisoformat(manifest_date[:10])
    except ValueError:
        print(f"[warn] urokimeditacii: manifest.date={manifest_date!r} не распознан — слайда нет.",
              file=sys.stderr)
        return None

    token = os.environ.get("AIRTABLE_TOKEN")
    if not token:
        print("[info] urokimeditacii: AIRTABLE_TOKEN не задан — слайда нет (заглушка).",
              file=sys.stderr)
        return None

    cfg = _load_config()
    channel, kinds_map = cfg["channel"], cfg["kinds"]
    first, first_next = _month_bounds(anchor)
    formula = window_formula(first, first_next)   # {status}='published' AND month window

    try:
        records = _fetch_month(token, formula)
    except Exception as e:
        print(f"[warn] urokimeditacii: Airtable ({e}) — слайда нет.", file=sys.stderr)
        return None

    anchor_week = anchor.isocalendar()[:2]   # (iso_year, iso_week)

    # ── parse events (preserve Airtable row order) ──
    events: list[dict] = []
    km_sunday_days: list[int] = []
    dropped_non_um = 0
    for rec in records:
        fields = rec.get("fields", {})
        name = _name_of(fields)
        d = _msk_date(fields.get(F_DATE))
        if not name or not d or d.month != anchor.month:
            continue
        # HARD FILTER: only Тип==УМ enters the calendar. АМ events (ДЧ, Сатсанг,
        # Садхана Шивир, Ремонт, Поход…) are dropped entirely — never shown.
        if "УМ" not in _tip_list(fields):
            dropped_non_um += 1
            continue
        # Trigger and calendar colour share ONE rule: the kind classifier. An event the
        # slide paints as КМ (kind=='km') is КМ for the trigger too — no separate Name
        # match. km = any Уроки meditation meeting (routine КМ, КМ с ведущим, тематическая).
        kind = _classify_kind(name, kinds_map)
        is_km = kind == "km"
        ev = {
            "day": d.day,
            "kind": kind,
            "label": _zag_of(fields) or name,
            "is_km": is_km,
        }
        events.append(ev)
        # trigger: a km-kind УМ event in the ДЧ's ISO week, on a Sunday (Тип УМ gated above)
        if is_km and d.isocalendar()[:2] == anchor_week and d.weekday() == 6:
            km_sunday_days.append(d.day)

    print(f"[info] urokimeditacii: месяц={anchor.year}-{anchor.month:02d}, "
          f"УМ-событий={len(events)}, отброшено-не-УМ={dropped_non_um}, "
          f"КМ-вс-в-неделе-ДЧ={sorted(set(km_sunday_days))}", file=sys.stderr)

    if not km_sunday_days:
        print("[info] urokimeditacii: воскресной КМ на неделе ДЧ нет — слайда нет.",
              file=sys.stderr)
        return None
    highlight_day = min(km_sunday_days)

    # ── one cell per day: КМ token first, then row order; max 2 then +N ──
    by_day: dict[int, list[dict]] = {}
    for ev in events:
        by_day.setdefault(ev["day"], []).append(ev)

    calendar = []
    for day in sorted(by_day):
        evs = by_day[day]
        # label token order: КМ marker first, then Airtable row order (stable)
        ordered = sorted(evs, key=lambda e: 0 if e["is_km"] else 1)
        tokens = [e["label"] for e in ordered]
        label = " · ".join(tokens[:2])
        if len(tokens) > 2:
            label += f" +{len(tokens) - 2}"
        # accent = the day's most significant kind (km>asana>fk>charity>other)
        cell_kind = min((e["kind"] for e in evs), key=lambda k: KIND_PRIORITY.get(k, 99))
        calendar.append({"day": day, "kind": cell_kind, "label": label})

    # Meeting schedule (separate post of the Уроки channel, covering the КМ day).
    # Resilient: not found / other format / no times → None → card simply omitted.
    km_date = date(anchor.year, anchor.month, highlight_day)
    meeting = fetch_um_meeting(km_date, channel)

    # Single bounded LLM point (Mac-only), validated + deduped + baked. Runs only
    # when the slide actually triggers. seed = the ДЧ's ISO week.
    iso_year, iso_week = anchor_week
    wisdom = generate_wisdom(iso_year, iso_week)

    obj = {
        "month_label": f"{RU_MONTHS_NOM[anchor.month]} {anchor.year}",
        "month": anchor.month,   # numeric → renderer builds the month grid in-browser
        "year": anchor.year,
        "greeting": cfg["greeting"],
        "schedule_note": cfg["schedule_note"],
        "wisdom": wisdom,
        "channel": channel,
        "highlight_day": highlight_day,   # kept in data; v11 renderer does NOT accent it
        "meeting": meeting,               # {date_label, items[]} or null → no card
        "calendar": calendar,
    }
    print(f"[info] urokimeditacii: СЛАЙД ЕСТЬ — highlight_day={highlight_day}, "
          f"ячеек={len(calendar)}, month_label={obj['month_label']!r}", file=sys.stderr)
    return obj


def main() -> None:
    """Standalone check: `python3 urokimeditacii.py [YYYY-MM-DD]`
    (default = data/manifest.json date). Prints the baked object or 'None'."""
    if len(sys.argv) > 1:
        d = sys.argv[1]
    else:
        mp = Path(__file__).parent.parent / "data" / "manifest.json"
        d = json.loads(mp.read_text()).get("date")
    print(f"anchor ДЧ = {d}", file=sys.stderr)
    obj = build_urokimeditacii(d)
    print(json.dumps(obj, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
