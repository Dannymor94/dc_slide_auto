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
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"
DEFAULT_OPENROUTER_MODEL = "meta-llama/llama-3.3-70b-instruct"

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")

SYSTEM_PROMPT = """Ты детерминированный парсер расписания дня. На вход — текст поста с программой.
Верни СТРОГО один JSON-объект: {"program": [ ... ]}, без пояснений и markdown.

Каждый пункт:
  "time": строка "ЧЧ:ММ" в 24-часовом формате. Нормализуй («в 8:45», «8.45» → "08:45").
  "title": краткое название пункта (без времени и без заметки).
  "note": пояснительная/курсивная строка под пунктом (например у «Сатсанг»:
          "Немного поговорим о том, как у кого дела..."). Если её нет — null.
  "_llm_uncertain": true, если время в тексте НЕ указано явно, неоднозначно,
                    или ты не уверен в структуре пункта; иначе false.

Правила:
- Сохраняй порядок пунктов как в тексте.
- Не добавляй пункты, которых нет в тексте. Ничего не выдумывай.
- Заметка относится к пункту выше неё (отдельная строка под названием).
- Поле is_practice_end не ставь — это сделает человек.
"""


# ── Providers ───────────────────────────────────────────────────────────────────
def _providers() -> list[tuple]:
    """(name, url, key, model, extra_headers) for each configured provider, in order."""
    provs = []
    gk = os.environ.get("GROQ_API_KEY")
    if gk:
        provs.append((
            "Groq", GROQ_URL, gk,
            os.environ.get("GROQ_MODEL", DEFAULT_GROQ_MODEL), {},
        ))
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


# ── Public API ──────────────────────────────────────────────────────────────────
def extract_program(text: str) -> list[dict]:
    """Schedule items from post text. Never raises; empty list on any failure."""
    text = (text or "").strip()
    if not text:
        print("[warn] extract_program: пустой вход — программа пустая.", file=sys.stderr)
        return []

    providers = _providers()
    if not providers:
        print("[warn] extract_program: нет ключей (GROQ_API_KEY/OPENROUTER_API_KEY) — "
              "программа пустая (заглушка).", file=sys.stderr)
        return []

    raw = None
    for name, url, key, model, extra in providers:
        try:
            raw = _call(url, key, model, text, extra)
            print(f"[info] extract_program: провайдер {name} ({model}) — ок.", file=sys.stderr)
            break
        except requests.HTTPError as e:
            r = e.response
            code = r.status_code if r is not None else "?"
            body = (r.text or "")[:200] if r is not None else ""
            print(f"[warn] extract_program: {name} HTTP {code}: {body} — пробую следующий провайдер.",
                  file=sys.stderr)
        except Exception as e:
            print(f"[warn] extract_program: {name} ошибка ({e}) — пробую следующий провайдер.",
                  file=sys.stderr)

    if raw is None:
        print("[warn] extract_program: все LLM-провайдеры недоступны — программа пустая.",
              file=sys.stderr)
        return []

    program = _normalize(raw)
    n_unc = sum(1 for p in program if p["_llm_uncertain"])
    print(f"[info] extract_program: пунктов={len(program)}, неуверенных={n_unc}", file=sys.stderr)
    return program


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
