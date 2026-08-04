# DEPLOY — dc-deck на vnedrum-prod

Разворачивание по `PLATFORM-CONTRACT.md`. Проект — **native (systemd)**, порт **8013**,
домен `dc.vnedrum.ru`. Главный `/etc/caddy/Caddyfile` не трогаем: блок кладёт
`register-site.sh` в `/etc/caddy/sites/`.

Границы платформы (что общее, что наше):
- **Postgres** — общий инстанс на хосте; у нас своя БД+юзер (`new-db.sh`).
- **Caddy** — единый вход; у нас свой блок в `sites/` (`register-site.sh`).
- **Порт 8013** — следующий свободный после YCab (8012); бэкенд слушает `127.0.0.1:8013`.

---

## Один статичный root: `dist/`

Caddy отдаёт **только** `/opt/projects/dc-deck/dist`. Поэтому `manifest.json` и
`theme.json` должны лежать **внутри dist**, а не отдаваться из `data/` кастомным handle.
Деплой собирает `dist = deck/* + manifest.json + theme.json`.

boot.js фетчит относительно (`theme.json`, `manifest.json`) и same-origin (`/api/*`) —
всё резолвится под одним origin `dc.vnedrum.ru`, хардкода localhost нет.

---

## Конвейер

```bash
# 0. Порт — убедиться, что 8013 свободен
ss -tlnp | grep -E '80[0-9][0-9]'          # 8010/8011/8012 заняты → берём 8013

# 1. БД (платформенный скрипт: GRANT ON SCHEMA + ALTER OWNER + печатает connection string)
bash /opt/scripts/new-db.sh dc-deck        # СОХРАНИТЬ connection string (пароль 1 раз, буквы+цифры)

# 2. Папки (родительские заранее — rsync цепочку не создаёт)
mkdir -p /opt/projects/dc-deck/{dist,uploads}

# 3. Код с Мака (whitelist, .env исключён)
rsync -avz -e "ssh -p 2222" \
  --exclude='.env*' --exclude='uploads/' --exclude='__pycache__' \
  --exclude='.venv' --exclude='.git' \
  ./ root@147.45.251.134:/opt/projects/dc-deck/

# 4. Собрать dist = статика дека + manifest + theme (единый root)
cp -rL /opt/projects/dc-deck/deck/*             /opt/projects/dc-deck/dist/
cp     /opt/projects/dc-deck/data/manifest.json /opt/projects/dc-deck/dist/
cp     /opt/projects/dc-deck/theme.json         /opt/projects/dc-deck/dist/
grep -rn localhost /opt/projects/dc-deck/dist/  # должно быть пусто

# 5. Секреты на сервере (имена ровно как читает код: DATABASE_URL, OPERATOR_USER, OPERATOR_PASS)
cd /opt/projects/dc-deck
cp infra/dc-deck.env.example .env && nano .env && chmod 600 .env
#   DATABASE_URL = connection string из шага 1; OPERATOR_USER/PASS — свои. Без inline-комментов.

# 6. venv + таблицы ДО сида + сид + сервис
python3 -m venv .venv
./.venv/bin/pip install -r server/requirements.txt
# init_db и seed запускаем ИЗ server/ — main.py/db.py используют непакетные импорты
set -a; . ./.env; set +a
( cd server && ../.venv/bin/python -c "from db import init_db; init_db()" )   # таблицы
./.venv/bin/python server/seed_songs.py                                        # 2 песни (№1, №63)
cp infra/dc-deck.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now dc-deck
journalctl -u dc-deck -n 50

# 7. Домен + TLS (кладёт блок в sites/, главный Caddyfile не трогает)
bash /opt/scripts/register-site.sh dc-deck 8013 dc.vnedrum.ru /opt/projects/dc-deck/dist

# 8. Проверка
bash /opt/scripts/healthcheck.sh dc-deck 8013 dc.vnedrum.ru
curl -sI https://dc.vnedrum.ru/ | head -3

# 9. Реестр §3 (8013) + таблица проектов §13 + бэкап БД в cron
```

Приложение и само создаёт таблицы на старте (`lifespan` → `init_db`), но шаг 6 создаёт
их **до** сида, потому что `seed_songs.py` пишет в `song` раньше первого запуска сервиса.

---

## Дек и API — под одним origin

| Путь | Кто отдаёт | Auth |
|---|---|---|
| `/`, `/boot.js`, `/slides/*`, `/manifest.json`, `/theme.json` | Caddy `file_server` из `dist/` | — |
| `GET /api/catalog` | FastAPI (proxy) | открыто (дек читает) |
| `GET /api/selection` | FastAPI (proxy) | открыто (дек читает) |
| `POST /api/selection` | FastAPI (proxy) | basic-auth (FastAPI) |
| `GET /api/operator` | FastAPI (proxy) | basic-auth (FastAPI) |

Форма оператора — `https://dc.vnedrum.ru/api/operator`. basic-auth только в FastAPI;
в Caddy-блоке `basicauth` нет.

---

## Еженедельное обновление (задел под M4)

Мак-билд пересобирает `data/manifest.json` и пушит его в **обслуживаемый root**:

```
push.sh → /opt/projects/dc-deck/dist/manifest.json     # НЕ в data/ — дек читает dist/
```

Иначе дек не увидит обновление недели. `selection`/`overrides` живут в Postgres и
пересборку manifest переживают (мердж `overrides || EXCLUDED.overrides` в `POST /api/selection`).

---

## Стоп-гейт M0 (проверить после деплоя)

1. `https://dc.vnedrum.ru` рендерит все слайды из `manifest.json` + пустого selection.
2. В форме выбрал песню №1 → карточка резолвится из каталога → слайд песни появился.
3. Правка строки программы в форме → в `overrides` → пережила повторную заливку manifest.
4. Пустое видео → слайд «видео нет». Сервер недоступен → дек по manifest + баннер «нет связи».
5. Граница слайда 1: program[0].time `11:59` → утреннее приветствие; `12:00` → дневное.
