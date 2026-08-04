#!/usr/bin/env python3
"""Extract fundraising progress from the finance post (M2, Mac build-side).

Deterministic, NO LLM. Finds the number next to «ДЧ донаты» → raised.
plan is a config constant (DC_PLAN in .env, default 30000).

The finance post lists one category per line, e.g.
    + 44 161 ₽  Субаренда;
    + 18 700 ₽  ДЧ донаты;
    + 17 800 ₽  Асана-класс;
so the amount sits on the SAME line as its label — the number↔phrase gap must
NOT cross a newline, or we'd grab a neighbouring line's amount.

    → {"raised": 18700, "plan": 30000}

Fallback: no «ДЧ донаты»+number / empty input → {"raised": None, "plan": None}
+ warning. Never raises.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DEFAULT_PLAN = int(os.environ.get("DC_PLAN", "30000"))   # config constant

_PHRASE = r"ДЧ\s*донаты"
# a number split only by in-line separators (space / nbsp / thin space) — NOT newline
_NUM = r"\d[\d \t  ]*\d|\d"
# gap between number and phrase: same line only (no newline), ≤15 non-digit chars
_GAP = r"[^\d\n]{0,15}"
_AFTER = re.compile(_PHRASE + _GAP + "(" + _NUM + ")", re.IGNORECASE)
_BEFORE = re.compile("(" + _NUM + ")" + _GAP + _PHRASE, re.IGNORECASE)


def extract_progress(text: str, plan: int | None = None) -> dict:
    """{"raised": int|None, "plan": int|None}. raised from the «ДЧ донаты» amount;
    plan is the constant when raised is found, else None (no bar)."""
    plan = DEFAULT_PLAN if plan is None else plan
    if not text or not text.strip():
        print("[warn] extract_progress: пустой вход — прогресс пустой.", file=sys.stderr)
        return {"raised": None, "plan": None}

    m = _AFTER.search(text) or _BEFORE.search(text)
    if not m:
        print("[warn] extract_progress: «ДЧ донаты» с числом не найдено — raised пустой.",
              file=sys.stderr)
        return {"raised": None, "plan": None}

    raised = int(re.sub(r"\D", "", m.group(1)))   # strip in-line separators
    return {"raised": raised, "plan": plan}


def main() -> None:
    if len(sys.argv) >= 2:
        arg = sys.argv[1]
        text = Path(arg).read_text() if Path(arg).exists() else arg
    else:
        text = sys.stdin.read()
    print(json.dumps(extract_progress(text), ensure_ascii=False))


if __name__ == "__main__":
    main()
