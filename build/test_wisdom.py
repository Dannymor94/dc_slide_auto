#!/usr/bin/env python3
"""Offline unit tests for wisdom.py — validator on hostile outputs, the fallback
pool's own cleanliness, deterministic rotation, dedup, and the offline path
(no network → slide still gets a line). Plain asserts, no pytest.

Run:  python3 build/test_wisdom.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import wisdom
from wisdom import FALLBACK_POOL, _fallback, _normalize, generate_wisdom, validate

_fails = []


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        _fails.append(msg)


# ── 1. hostile outputs must be REJECTED ──────────────────────────────────────
BAD = {
    "эмодзи": "Дыши спокойно и будь здесь и сейчас всегда 🙏",
    "цифры": "Сделай пять вдохов, а лучше 5, и почувствуй покой",
    "латиница": "Просто дыши and be present в каждом мгновении жизни",
    "кавычки": "«Тишина внутри рождается, когда ум перестаёт спорить»",
    "url": "Заходи на example.ru и медитируй с нами каждый тихий вечер",
    "маркер списка": "- Дыши спокойно и оставайся в настоящем моменте всегда",
    "тире в конце": "Покой всегда рядом, стоит лишь замедлиться и услышать —",
    "слишком коротко": "Дыши и будь здесь",
    "слишком длинно": ("Дыши медленно и глубоко и почувствуй как тело мягко "
                        "расслабляется а ум наконец затихает совсем полностью"),
    ">90 символов": ("Тишина внутри тебя рождается ровно тогда когда беспокойный "
                     "ум окончательно перестаёт спорить с этим миром"),
    "два терминала": "Дыши. Будь здесь и почувствуй покой внутри себя сейчас.",
}
print("[1] злые выводы должны отклоняться:")
for label, text in BAD.items():
    ok, reason = validate(text)
    check(not ok, f"«{label}» → reject ({reason or 'но прошло!'})")


# ── 2. good lines must PASS (the fallback pool is the golden set) ─────────────
print("[2] фолбэк-пул чист (каждая строка валидна):")
for i, line in enumerate(FALLBACK_POOL):
    ok, reason = validate(line)
    check(ok, f"pool[{i}] ({reason or 'ok'})")
check(len({_normalize(x) for x in FALLBACK_POOL}) == len(FALLBACK_POOL),
      "в пуле нет дублей")


# ── 3. boundary word counts (6 and 14 ok; 5 and 15 reject) ───────────────────
print("[3] границы длины по словам:")
check(validate("один два три четыре пять шесть")[0], "6 слов — ok")
check(validate(" ".join(["слово"] * 14))[0], "14 слов — ok")
check(not validate("один два три четыре пять")[0], "5 слов — reject")
check(not validate(" ".join(["слово"] * 15))[0], "15 слов — reject")


# ── 4. deterministic rotation + dedup in _fallback ───────────────────────────
print("[4] фолбэк детерминирован и уважает dedup:")
check(_fallback(36, set()) == _fallback(36, set()), "одна неделя → та же строка")
n = len(FALLBACK_POOL)
check(_fallback(0, set()) == FALLBACK_POOL[0], "iso_week=0 → pool[0]")
check(_fallback(n + 1, set()) == FALLBACK_POOL[1], "ротация по модулю N")
recent0 = {_normalize(FALLBACK_POOL[0])}
check(_fallback(0, recent0) != FALLBACK_POOL[0],
      "pool[0] недавняя → берётся другая")


# ── 5. offline path: no providers → pool line, no raise, history appended ─────
print("[5] офлайн-фолбэк (сеть недоступна):")
with tempfile.TemporaryDirectory() as td:
    hp = Path(td) / "hist.json"
    line = generate_wisdom(2026, 36, history_path=hp, providers=[])
    check(validate(line)[0], "офлайн вернул валидную строку")
    check(line in FALLBACK_POOL, "офлайн-строка из пула")
    check(hp.exists() and _normalize(line) in
          {_normalize(h["text"]) for h in wisdom._load_history(hp)},
          "строка записана в историю")
    # next build same week now sees it as recent → must rotate to a different line
    line2 = generate_wisdom(2026, 36, history_path=hp, providers=[])
    check(_normalize(line2) != _normalize(line), "дубль недели не повторяется")


print()
if _fails:
    print(f"ПРОВАЛЕНО: {len(_fails)}")
    for m in _fails:
        print(f"  - {m}")
    sys.exit(1)
print("ВСЕ ТЕСТЫ ПРОШЛИ")


if __name__ == "__main__":
    pass
