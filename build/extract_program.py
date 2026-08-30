#!/usr/bin/env python3
"""Extract a day schedule from a program post (M2 MVP, Mac build-side).

THE SINGLE LLM POINT of the whole pipeline (project rule: one LLM call, here;
everything else deterministic). OpenAI-compatible chat API via `requests`
(no provider SDK dependency).

Providers, tried in order until one succeeds:
    1. Groq        (GROQ_API_KEY,        GROQ_MODEL       default llama-3.3-70b-versatile)
    2. OpenRouter  (OPENROUTER_API_KEY,  OPENROUTER_MODEL default meta-llama/llama-3.3-70b-instruct)

Input : program-post text (file, argument, or stdin).
Output: JSON list of schedule items:
    [{ "time": "HH:MM", "title": str, "note": str|null,
       "is_practice_end": false, "_llm_uncertain": bool }]

- note      : the italic/explanatory line under an item (e.g. under «Сатсанг»).
- _llm_uncertain: true when the model isn't sure about the time/structure → the
  operator form highlights the row yellow. Also forced true on a non-HH:MM time.
- is_practice_end: always false here — the human sets it in the form.

MVP scope: text in, JSON out. NO Telethon / channel auto-pull (backlog).

Fallback: no keys / both providers fail → empty program + warning, never raises.
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
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"


# Models known to handle structured JSON extraction / instruct output correctly,
# in PRIORITY order (picker takes the first that /models reports live).
# Do NOT extend with whisper/embedding/guard models — they hallucinate schedules.
# The whitelist goes stale as Groq retires models (the llama-3.3 line 404s now);
# refresh it by checking live ids at https://console.groq.com/docs/models — add
# real instruct models to the top. Empty match → picker returns None → provider
# skipped, never a random model.
GROQ_MODEL_WHITELIST = (
    "openai/gpt-oss-120b",    # largest, strict JSON — primary
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
    # ── retired on Groq (kept for history; picker skips unavailable ids) ──
    "llama-3.3-70b-versatile",
    "llama-3.1-70b-versatile",
    "llama3-70b-8192",
    "llama-3.3-70b-specdec",
    "llama-3.1-8b-instant",
)


def _pick_groq_model(key: str) -> str | None:
    """Return the best whitelisted Groq model available, or None if none found.
    None → caller skips Groq entirely (better empty ❌ than whisper hallucination)."""
    try:
        resp = requests.get(GROQ_MODELS_URL,
                            headers={"Authorization": f"Bearer {key}"},
                            timeout=10)
        resp.raise_for_status()
        available = {m["id"] for m in resp.json().get("data", [])}
        for candidate in GROQ_MODEL_WHITELIST:
            if candidate in available:
                print(f"[info] groq models: выбрана {candidate}", file=sys.stderr)
                return candidate
        print(f"[warn] groq models: ни одна из whitelist-моделей недоступна "
              f"(доступны: {sorted(available)}) — Groq пропускаю.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[warn] groq models list: {e} — использую default {DEFAULT_GROQ_MODEL}",
              file=sys.stderr)
        return DEFAULT_GROQ_MODEL

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")

SYSTEM_PROMPT = """Ты детерминированный парсер расписания дня. На вход — текст поста с программой.
Верни СТРОГО один JSON-объект: {"program": [ ... ]}, без пояснений и markdown.

Каждый пункт:
  "time": строка "ЧЧ:ММ" в 24-часовом формате. Нормализуй («в 8:45», «8.45» → "08:45").
  "title": ПОЛНЫЙ текст названия пункта, дословно как в тексте (без времени).
           Длинные названия («Сатсанг с Дадой и настройка на Южный ретрит») целиком
           идут в title — не обрезай, не переименовывай.
  "note": пояснительная строка на ОТДЕЛЬНОЙ строке ПОД пунктом (например под «Сатсанг»:
          "Немного поговорим о том, как у кого дела..."). Если её нет — null.
          Часть названия пункта в note не выносить.
  "_llm_uncertain": true, если время в тексте НЕ указано явно, неоднозначно,
                    или ты не уверен в структуре пункта; иначе false.

Правила:
- Сохраняй порядок пунктов как в тексте.
- Не добавляй пункты, которых нет в тексте. Ничего не выдумывай.
- Заголовки разделов («Полезные ссылки», «Контакты» и т.п.) — НЕ пункты расписания, пропусти их.
- Поле is_practice_end не ставь — это сделает человек.
"""


# ── Providers ───────────────────────────────────────────────────────────────────
def _providers() -> list[tuple]:
    """(name, url, key, model, extra_headers) for each configured provider, in order."""
    provs = []
    gk = os.environ.get("GROQ_API_KEY")
    if gk:
        model = os.environ.get("GROQ_MODEL") or _pick_groq_model(gk)
        if model:
            provs.append(("Groq", GROQ_URL, gk, model, {}))
    ork = os.environ.get("OPENROUTER_API_KEY")
    if ork:
        provs.append((
            "OpenRouter", OPENROUTER_URL, ork,
            os.environ.get("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL),
            {"HTTP-Referer": "https://dc.vnedrum.ru", "X-Title": "dc-deck"},
        ))
    return provs


def _extract_json(content: str) -> dict:
    """Parse the model's message content into a dict, tolerating markdown fences
    or prose around the JSON object."""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n", "", content)
        content = re.sub(r"\n```$", "", content).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _call(url: str, key: str, model: str, text: str, extra_headers: dict) -> dict:
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }
    headers = {"Authorization": f"Bearer {key}", **extra_headers}
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return _extract_json(content)


# ── Normalisation (deterministic, defensive) ────────────────────────────────────
def _normalize(raw) -> list[dict]:
    items = raw.get("program") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        title = (it.get("title") or "").strip()
        if not title:
            continue
        time = (it.get("time") or "").strip()
        note = it.get("note")
        note = note.strip() if isinstance(note, str) and note.strip() else None
        # uncertain if the model flagged it OR the time is not valid HH:MM
        uncertain = bool(it.get("_llm_uncertain", False)) or not _TIME_RE.match(time)
        out.append({
            "time": time,
            "title": title,
            "note": note,
            "is_practice_end": False,   # human sets this in the form
            "_llm_uncertain": uncertain,
        })
    return out


# ── Deterministic validator ─────────────────────────────────────────────────────
_SRC_TIME_RE = re.compile(r"\b([01]?\d|2[0-3])[:.h]([0-5]\d)\b")

# Characters to strip when normalising text for word extraction
_WORD_RE = re.compile(r"[а-яёa-z]{4,}", re.IGNORECASE)

# How many chars after a time marker to scan for the item's title words
_TITLE_WINDOW = 200


def _src_times(text: str) -> set[str]:
    """All HH:MM times that actually appear in the source text (normalised)."""
    return {f"{int(h):02d}:{m}" for h, m in _SRC_TIME_RE.findall(text)}


def _sig_words(s: str) -> set[str]:
    """Significant words (≥4 chars, lower-cased) from a string."""
    return {w.lower() for w in _WORD_RE.findall(s)}


def _text_window_after_time(text: str, hhmm: str) -> str:
    """Text between `hhmm` and the next time marker in source (≤ _TITLE_WINDOW chars).

    This is the actual title region for a schedule item — it stops at the next
    time marker so that later sections (e.g. «Полезные ссылки») don't bleed in.
    """
    h, m = hhmm.split(":")
    candidates = [hhmm, f"{int(h)}:{m}"]
    best = len(text)
    for pat in candidates:
        idx = text.find(pat)
        if 0 <= idx < best:
            best = idx
    if best == len(text):
        return ""
    start = best + len(hhmm)
    chunk = text[start: start + _TITLE_WINDOW]
    # stop at the next time-like pattern (next schedule item or section)
    m2 = _SRC_TIME_RE.search(chunk)
    if m2:
        chunk = chunk[: m2.start()]
    return chunk


def _validate(program: list[dict], text: str, provider: str,
              strict_titles: bool = True) -> str | None:
    """Return None if output looks clean, else a short error string.

    Rules (deterministic, no LLM):
    1. Every output time must appear in the source text.
    2. Output item count must not exceed source time count.
    3. Every timed item's title must share at least one significant word (≥4 chars)
       with the text immediately following that time in the source.
       Catches substituted/hallucinated titles like «Полезные ссылки» at 12:00.
    Items without a valid time (uncertain) are exempt from all rules.

    strict_titles=False skips rule 3 (the regex path takes titles verbatim from the
    source, so it can't substitute — and rule 3 then only false-positives, as it did
    on the 2026-02-13 all-night program's «Завершение» in the historical run).
    """
    src = _src_times(text)
    timed = [p for p in program if _TIME_RE.match(p["time"])]

    # Rule 1: no hallucinated times
    hallucinated = [p["time"] for p in timed if p["time"] not in src]
    if hallucinated:
        return (f"галлюцинация: времена {hallucinated} отсутствуют в исходном тексте "
                f"(источник содержит: {sorted(src)})")

    # Rule 2: count check
    if src and len(timed) > len(src):
        return (f"слишком много пунктов: {len(timed)} > {len(src)} временны́х строк в источнике")

    # Rule 3: title proximity check (LLM path only — see strict_titles docstring)
    if not strict_titles:
        return None
    for p in timed:
        title_words = _sig_words(p["title"])
        if not title_words:
            continue   # all words < 4 chars — skip (e.g. "ДЧ", "ОМ")
        window = _text_window_after_time(text, p["time"])
        window_words = _sig_words(window)
        if not (title_words & window_words):
            snippet = window[:60].replace("\n", " ").strip()
            print(f"[warn] validate: {p['time']} «{p['title'][:50]}» — "
                  f"нет пересечения с текстом источника после этого времени "
                  f"(окно: «{snippet}…», слова названия: {sorted(title_words)})",
                  file=sys.stderr)
            return (f"подменённое название: {p['time']} «{p['title'][:40]}» "
                    f"не совпадает с текстом источника рядом с этим временем")

    return None


# ── Deterministic parser (primary path — no LLM) ─────────────────────────────────
# The ДЧ program post has a rigid shape: one item per line, «[маркер] HH:MM [—] Название».
# A regex parses it exactly; the LLM validators we wrote against hallucination are
# more complex than the parser itself — a sign the LLM was the wrong tool here.
#
#   08:30 — Сбор в джагрити            → {time:"08:30", title:"Сбор в джагрити"}
#   🔸 11:00 - Сатсанг (Индранатха)    → marker + spaced dash tolerated
#   Немного поговорим о том…           → note: attached to the item above (no time)
#   Полезные ссылки                    → section header (no time) → ignored
#
# Line = [leading marker/bullet] HH:MM [dash/·/:] Title-to-end-of-line.
# Marker: any run of non-digit, non-letter chars (🔸 • - ✅ etc.). Dash after the
# time: — – - · : or none. Title taken WHOLE to end of line, never truncated.
_LINE_TIME_RE = re.compile(
    r"^\s*[^\wЀ-ӿ]*\s*"          # optional leading marker/bullet/emoji
    r"(?:в\s+)?"                            # optional «в 8:45»
    r"([01]?\d|2[0-3])[:.]([0-5]\d)"       # HH:MM (or HH.MM)
    r"\s*[—–\-:·•]*\s*"                     # optional separator dash/colon/bullet
    r"(.*)$",                               # title: whole rest of line
    re.IGNORECASE,
)

# Untimed lines that are section headers, not item notes. Extend from real posts.
# ponytail: substring blocklist, cheap. If a real post puts a header right under an
# item and it slips through, it lands as that item's note — the validators still run.
_SECTION_HEADER_HINTS = (
    "полезные ссылки", "контакты", "ссылки", "чат", "донат", "реквизит",
    "поддержать", "расписание", "программа", "приглашаем",
)


def _looks_like_header(line: str) -> bool:
    low = line.lower().strip(" :•—–-")
    return any(h in low for h in _SECTION_HEADER_HINTS)


def parse_program(text: str) -> list[dict]:
    """Deterministic schedule parse — the PRIMARY path, no LLM, no network.

    Each timed line → one item. An untimed non-header line directly under an item
    becomes that item's `note` (first one only). Untimed lines before the first item,
    or matching a section-header hint, are ignored. Output schema identical to the
    LLM path, so `_validate` applies unchanged. Empty/no-match → []."""
    out: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _LINE_TIME_RE.match(line)
        if m:
            h, mm, title = m.group(1), m.group(2), m.group(3).strip()
            if not title or not re.search(r"[а-яёА-ЯЁ]", title):
                continue                       # bare time, or a non-Cyrillic title
                                               # («17:20 → 18:56» in a train post) → not a schedule item
            out.append({
                "time": f"{int(h):02d}:{mm}",
                "title": title,
                "note": None,
                "is_practice_end": False,      # human sets this in the form
                "_llm_uncertain": False,       # deterministic parse is certain
            })
        elif out and out[-1]["note"] is None and not _looks_like_header(line):
            out[-1]["note"] = line             # explanatory line under the last item
    return out


# ── Public API ──────────────────────────────────────────────────────────────────
def extract_program(text: str) -> list[dict]:
    """Schedule items from post text. Never raises; empty list on any failure.

    PRIMARY path is the deterministic regex parser (`parse_program`) — the ДЧ post
    format is rigid («HH:MM — Название») and proved 100 % stable across 400 days of
    real posts (57/57 real program posts parsed fully). The LLM path below is KEPT
    but no longer called (project rule: format stable → regex primary, LLM out of
    the path). To resurrect it as a fallback, gate on `len(program) <= 1`.
    """
    text = (text or "").strip()
    if not text:
        print("[warn] extract_program: пустой вход — программа пустая.", file=sys.stderr)
        return []

    program = parse_program(text)
    err = _validate(program, text, "regex", strict_titles=False)
    if err:
        print(f"[warn] extract_program: regex — {err}.", file=sys.stderr)
    print(f"[info] extract_program: regex-парсер — пунктов={len(program)}.", file=sys.stderr)
    return program


def _extract_program_llm(text: str) -> list[dict]:
    """DORMANT LLM path — kept for reference, no longer on the main path.
    See extract_program docstring. Formerly the single LLM point of the pipeline."""
    providers = _providers()
    if not providers:
        print("[warn] extract_program: нет ключей (GROQ_API_KEY/OPENROUTER_API_KEY) — "
              "программа пустая (заглушка).", file=sys.stderr)
        return []

    for name, url, key, model, extra in providers:
        # one retry per provider on validation failure
        for attempt in (1, 2):
            try:
                raw = _call(url, key, model, text, extra)
                program = _normalize(raw)
                err = _validate(program, text, name)
                if err:
                    print(f"[warn] extract_program: {name} попытка {attempt} — {err}.",
                          file=sys.stderr)
                    if attempt == 1:
                        continue        # retry same provider
                    # second failure → fall through to next provider
                    print(f"[warn] extract_program: {name} обе попытки провалили валидацию "
                          f"— пробую следующий провайдер.", file=sys.stderr)
                    break
                n_unc = sum(1 for p in program if p["_llm_uncertain"])
                print(f"[info] extract_program: провайдер {name} ({model}), "
                      f"попытка {attempt} — ок, пунктов={len(program)}, неуверенных={n_unc}",
                      file=sys.stderr)
                return program
            except requests.HTTPError as e:
                r = e.response
                code = r.status_code if r is not None else "?"
                body = (r.text or "")[:200] if r is not None else ""
                print(f"[warn] extract_program: {name} HTTP {code}: {body} "
                      f"— пробую следующий провайдер.", file=sys.stderr)
                break   # HTTP errors don't benefit from retry
            except Exception as e:
                print(f"[warn] extract_program: {name} ошибка ({e}) "
                      f"— пробую следующий провайдер.", file=sys.stderr)
                break

    print("[warn] extract_program: все LLM-провайдеры недоступны или не прошли валидацию "
          "— программа пустая.", file=sys.stderr)
    return []


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Post text → schedule JSON (single LLM point)")
    ap.add_argument("text", nargs="?", help="текст поста; или '-' / без аргумента → stdin")
    ap.add_argument("--file", type=Path, help="файл с текстом поста")
    args = ap.parse_args()

    if args.file:
        text = args.file.read_text()
    elif args.text and args.text != "-":
        text = args.text
    else:
        text = sys.stdin.read()

    program = extract_program(text)
    print(json.dumps(program, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
