# dc-deck

Веб-дек еженедельной Дхармачакры. Рендерится из данных, а не правится вручную.
Заменяет ручную сборку Google Slides.

## Быстрый старт для Claude Code
1. `CLAUDE.md` — принципы, конвенции, карта репозитория.
2. `PLAN.md` — вехи со стоп-гейтами. Делай только активную (`← ТЕКУЩАЯ`).
3. `DECK-CONTRACT.md` — имена полей, слоты, правила слияния. Сверяйся до правки данных.

## Модель
`dc.vnedrum.ru` (Caddy → статика дека + reverse_proxy на FastAPI/Postgres).
Данные: `manifest.json` (Мак, еженедельно) ∪ `selection` (VPS-форма, без VPN) ∪ `theme.json` (репо).
VPS наружу не ходит; всё блокируемое — на Мак-билде.

## Структура
- `deck/` — reveal.js, статика, один файл = один слайд
- `server/` — FastAPI + Postgres, форма `/operator`
- `build/` — Мак-сторона: LLM-извлечение программы, Airtable, сборка manifest
- `data/` — manifest, схема, сид песен, sample
- `infra/` — Caddyfile, systemd
- `theme.json` — тема
# dc_slide_auto
