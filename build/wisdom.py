#!/usr/bin/env python3
"""Closing 'wisdom' line for the Уроки-медитации slide — the feature's single
bounded LLM point (Mac build-side only; the VPS never calls out).

Contract (agreed M2):
  • Groq (primary) → OpenRouter (fallback), OpenAI-compatible chat via requests.
  • seed = ISO week (perturbed per retry), temperature 0.8, max_tokens ≤ 40.
  • NO <hint>/context is passed — the ДЧ program post has nothing about the
    Уроки-медитации КМ, so feeding it would only mislead. Prompt is standalone.
  • Raw output is NEVER trusted: a deterministic validator gates it
    (6–14 words, ≤90 chars, ≤1 terminal mark; reject emoji/digits/latin/quotes/
    url/list-marker/trailing dash), then dedup vs wisdom_history.json (~8 weeks).
  • 3 attempts → deterministic fallback pool (rotates by iso_week). The slide
    ALWAYS gets a line: network down → offline fallback, never raises.
  • The used line is appended to wisdom_history.json (Mac-only runtime state).

This module produces a validated STRING; urokimeditacii.py bakes it into
manifest.urokimeditacii.wisdom. No raw LLM text ever reaches the deck.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

HISTORY_PATH = Path(__file__).parent / "wisdom_history.json"
DEDUP_WEEKS = 8            # don't repeat a line used in the last ~8 builds
HISTORY_KEEP = 30         # trim stored history to the last N entries
MAX_TOKENS = 40           # per contract (≤40)
TEMPERATURE = 0.8
ATTEMPTS = 3

SYSTEM_PROMPT = (
    "Ты пишешь одну тёплую завершающую фразу-напутствие для слайда о медитации "
    "(проект «Уроки медитации»). Верни РОВНО одну короткую фразу на русском языке, "
    "простыми словами, от 6 до 12 слов. Тон спокойный, добрый, вдохновляющий — о "
    "внутренней практике, тишине, дыхании, присутствии. Без кавычек, эмодзи, цифр, "
    "латинских букв, ссылок и знаков списка. Не начинай с тире. Верни только саму "
    "фразу, без пояснений и без markdown."
)
USER_PROMPT = "Дай напутствие для этой недели."

# Deterministic offline pool. Rotated by iso_week; every line passes validate().
# These are project constants — edit freely (keep them validator-clean).
FALLBACK_POOL = [
    "Тишина внутри рождается, когда ум перестаёт спорить с настоящим.",
    "Дыхание всегда возвращает нас домой, к самому простому присутствию.",
    "Свет сознания не нужно искать, его нужно лишь перестать заслонять.",
    "Каждый вдох тихо напоминает, что мы всё ещё живы.",
    "Покой приходит не из тишины вокруг, а из согласия внутри.",
    "Ум успокаивается, когда мы перестаём цепляться за каждую мысль.",
    "Медитация не убирает волны, она учит быть глубиной под ними.",
    "Настоящее мгновение это единственное место, где нас можно встретить.",
    "Доброта к себе открывает дверь, которую строгость держала закрытой.",
    "Сердце становится тише, когда мы слушаем, не торопясь ответить.",
]

# ── validator character classes ──────────────────────────────────────────────
_LATIN = re.compile(r"[A-Za-z]")
_DIGIT = re.compile(r"[0-9]")
_QUOTES = set("\"'«»“”„`")
_TERMINAL = set(".!?…")
# Emoji / pictographs / arrows / regional-indicator / variation-selector.
# Deliberately EXCLUDES General Punctuation (…, —, ·, «») which the deck allows.
_EMOJI = re.compile(
    "[\U0001F000-\U0001FAFF"   # symbols & pictographs, emoji, supplemental
    "\U00002600-\U000027BF"    # misc symbols + dingbats
    "\U0001F1E6-\U0001F1FF"    # regional indicators
    "\U00002190-\U000021FF"    # arrows
    "\U00002B00-\U00002BFF"    # misc symbols & arrows
    "\U0000FE00-\U0000FE0F]"   # variation selectors
)
_LIST_MARKER = ("-", "*", "•", "–", "—", "·", "‣", "◦")
_DASH_END = ("—", "–", "-")


def validate(line: str) -> tuple[bool, str]:
    """Deterministic gate. (ok, reason). reason='' when ok."""
    if not isinstance(line, str):
        return False, "не строка"
    s = line.strip()
    if not s:
        return False, "пусто"
    if len(s) > 90:
        return False, f"длина {len(s)}>90"
    words = s.split()
    if not (6 <= len(words) <= 14):
        return False, f"слов {len(words)} (нужно 6-14)"
    if _LATIN.search(s):
        return False, "латиница"
    if _DIGIT.search(s):
        return False, "цифры"
    if any(ch in _QUOTES for ch in s):
        return False, "кавычки"
    if _EMOJI.search(s):
        return False, "эмодзи/спец-символ"
    low = s.lower()
    if "http" in low or "www." in low or "://" in s:
        return False, "url"
    if s[0] in _LIST_MARKER:
        return False, "маркер списка в начале"
    if s.endswith(_DASH_END):
        return False, "тире в конце"
    if sum(1 for ch in s if ch in _TERMINAL) > 1:
        return False, "больше одного терминального знака"
    return True, ""


def _normalize(line: str) -> str:
    """Fold for dedup: keep Cyrillic letters + single spaces, lowercase."""
    return " ".join(re.sub(r"[^а-яёА-ЯЁ ]", " ", line).lower().split())


# ── history (Mac-only runtime state) ─────────────────────────────────────────
def _load_history(path: Path) -> list[dict]:
    try:
        d = json.loads(path.read_text())
        used = d.get("used", [])
        return used if isinstance(used, list) else []
    except Exception:
        return []


def _append_history(path: Path, iso_year: int, iso_week: int, text: str) -> None:
    used = _load_history(path)
    used.append({"iso_year": iso_year, "iso_week": iso_week, "text": text})
    used = used[-HISTORY_KEEP:]
    try:
        path.write_text(json.dumps({"used": used}, ensure_ascii=False, indent=2) + "\n")
    except Exception as e:
        print(f"[warn] wisdom: не смог записать историю ({e}).", file=sys.stderr)


# ── providers (mirrors extract_program) ──────────────────────────────────────
def _providers() -> list[tuple]:
    provs = []
    gk = os.environ.get("GROQ_API_KEY")
    if gk:
        provs.append(("Groq", GROQ_URL, gk,
                      os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL), {}))
    ork = os.environ.get("OPENROUTER_API_KEY")
    if ork:
        provs.append(("OpenRouter", OPENROUTER_URL, ork,
                      os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
                      {"HTTP-Referer": "https://dc.vnedrum.ru", "X-Title": "dc-deck"}))
    return provs


def _clean(raw: str) -> str:
    """First non-empty line, stripped of stray fences/leading bullets/quotes."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    s = s.splitlines()[0].strip() if s else ""
    return s.strip().strip("«»\"'`").strip()


def _call(url: str, key: str, model: str, seed: int, extra: dict) -> str:
    payload = {
        "model": model,
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "seed": seed,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": USER_PROMPT},
        ],
    }
    headers = {"Authorization": f"Bearer {key}", **extra}
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    return _clean(resp.json()["choices"][0]["message"]["content"])


def _fallback(iso_week: int, recent: set) -> str:
    """Deterministic pool pick: start at iso_week % N, step until one not in the
    dedup window (falls back to the rotated slot if all N are recent)."""
    n = len(FALLBACK_POOL)
    start = iso_week % n
    for off in range(n):
        cand = FALLBACK_POOL[(start + off) % n]
        if _normalize(cand) not in recent:
            return cand
    return FALLBACK_POOL[start]


def generate_wisdom(iso_year: int, iso_week: int, *,
                    history_path: Path = HISTORY_PATH,
                    providers=None) -> str:
    """Validated wisdom line for the given ISO week. Never raises; always returns
    a usable line (LLM if it passes gate+dedup, else deterministic fallback).
    The chosen line is appended to history."""
    provs = _providers() if providers is None else providers
    recent = {_normalize(h["text"]) for h in _load_history(history_path)[-DEDUP_WEEKS:]
              if h.get("text")}

    chosen = None
    if provs:
        for attempt in range(ATTEMPTS):
            seed = iso_week * 1000 + attempt   # deterministic, varied per retry
            line = None
            for name, url, key, model, extra in provs:
                try:
                    line = _call(url, key, model, seed, extra)
                    break
                except requests.HTTPError as e:
                    r = e.response
                    code = r.status_code if r is not None else "?"
                    print(f"[warn] wisdom: {name} HTTP {code} — следующий провайдер.",
                          file=sys.stderr)
                except Exception as e:
                    print(f"[warn] wisdom: {name} ошибка ({e}) — следующий провайдер.",
                          file=sys.stderr)
            if not line:
                continue
            ok, reason = validate(line)
            if not ok:
                print(f"[warn] wisdom: попытка {attempt+1} отклонена ({reason}): {line!r}",
                      file=sys.stderr)
                continue
            if _normalize(line) in recent:
                print(f"[warn] wisdom: попытка {attempt+1} — дубль недавней, перегенерирую.",
                      file=sys.stderr)
                continue
            chosen = line
            print(f"[info] wisdom: LLM ок (попытка {attempt+1}): {line!r}", file=sys.stderr)
            break

    if chosen is None:
        chosen = _fallback(iso_week, recent)
        print(f"[info] wisdom: фолбэк-пул (iso_week={iso_week}): {chosen!r}", file=sys.stderr)

    _append_history(history_path, iso_year, iso_week, chosen)
    return chosen


def main() -> None:
    import argparse
    from datetime import date
    ap = argparse.ArgumentParser(description="Wisdom line (single bounded LLM point)")
    ap.add_argument("--iso-week", type=int, help="ISO week number (default: 2026-08-30 week)")
    ap.add_argument("--iso-year", type=int, help="ISO year (default: 2026)")
    ap.add_argument("--offline", action="store_true", help="skip LLM, force fallback pool")
    args = ap.parse_args()
    if args.iso_week is None:
        y, w, _ = date.fromisoformat("2026-08-30").isocalendar()  # no Date.now in build
        args.iso_year, args.iso_week = args.iso_year or y, w
    line = generate_wisdom(args.iso_year or 2026, args.iso_week,
                           providers=[] if args.offline else None)
    print(line)


if __name__ == "__main__":
    main()
