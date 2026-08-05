# DEPLOY — dc-deck

Модель развёртывания (что где живёт и почему):

```
МАК (открытый интернет)                    VPS vnedrum.ru (РФ, без VPN)
━━━━━━━━━━━━━━━━━━━━━━━━━                  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
cron сб 12:00 → build_manifest.py          Caddy → dist/ (дек + manifest + theme)
  ├ Telegram (программа/деньги/видео)       FastAPI :8014 (форма, selection, catalog)
  ├ Airtable (новости)                      Postgres (каталог песен, selection)
  └ Groq (LLM программы)
        └ rsync manifest.json → dist/
        ───────────────────────────────────────────────────►

НА ПОКАЗЕ (VPN включён)
━━━━━━━━━━━━━━━━━━━━━━
браузер открывает dc.vnedrum.ru
  ├ дек грузится с VPS (РФ, ok)
  └ YouTube-iframe грузится НАПРЯМУЮ через VPN проектора
```

Ключевые принципы:
- **VPS наружу не ходит.** Всё блокируемое (Telegram/Airtable/Groq) — на Маке. VPS только отдаёт готовый manifest + форму + БД.
- **YouTube на показе идёт напрямую** через VPN проектора — сервер видео не проксирует, не перезаливает. iframe грузится в браузере проектора.
- Платформенные скрипты (`new-db.sh`, `register-site.sh`) — не изобретать своё. Главный Caddyfile НЕ трогать. Полный контракт инфры — `/opt/PLATFORM-CONTRACT.md` на VPS.

---

## ЧАСТЬ 1 — Разовый деплой на VPS

Выполняется один раз. Все команды — с Мака (SSH внутри).
SSH: `ssh -p 2222 -i ~/.ssh/vnedrum root@147.45.251.134`

### 1.0 Порт свободен
```bash
ssh -p 2222 root@147.45.251.134 "ss -tlnp | grep -E '80[0-9][0-9]'"
```
Планировался 8013 (следующий после YCab 8012), но **8013 оказался занят** живым node-процессом → берём следующий свободный **8014**. Всегда проверять фактически, не по плану.

### 1.1 База данных (платформенный скрипт)
```bash
ssh -p 2222 root@147.45.251.134 "bash /opt/scripts/new-db.sh dc_deck"
# ⚠️ имя БД — dc_deck (ПОДЧЁРКИВАНИЕ). new-db.sh отклоняет дефис (dc-deck).
# СОХРАНИ connection string (пароль печатается ОДИН раз, буквы+цифры).
# new-db.sh сам делает GRANT ON SCHEMA public + ALTER OWNER (Postgres 16).
```
Папка проекта и домен остаются `dc-deck` (дефис) — расходится только имя БД.

### 1.2 Папки проекта
```bash
ssh -p 2222 root@147.45.251.134 "mkdir -p /opt/projects/dc-deck/{dist,uploads}"
```

### 1.3 Код с Мака (rsync WHITELIST — только явные пути)
Per CLAUDE.md rsync идёт whitelist, не blacklist: пушим ровно нужное, `build/` (Мак-сторона) на VPS не нужен, `.env`/`.session`/`.venv`/`.git` физически не попадают.
```bash
cd /Users/danny/Documents/DC_slids-auto
rsync -avz -e "ssh -p 2222 -i ~/.ssh/vnedrum" \
  --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
  --exclude='*.session' --exclude='.env*' \
  deck server data infra theme.json \
  root@147.45.251.134:/opt/projects/dc-deck/
```
После пуша проверить, что не утекло лишнего:
```bash
ssh -p 2222 root@147.45.251.134 'cd /opt/projects/dc-deck && find . \( -name ".env*" -o -name "*.session" -o -name ".git" \)'   # пусто
```

### 1.4 dist = дек + manifest + theme (единый static-root)
```bash
ssh -p 2222 root@147.45.251.134 '
  cd /opt/projects/dc-deck
  cp -rL deck/* dist/
  cp data/manifest.json dist/
  cp theme.json dist/
  grep -rn "localhost\|127.0.0.1\|:8000" dist/ && echo "!!! ЕСТЬ localhost — исправить" || echo "dist чист"
'
```
`-L` разыменовывает симлинк `deck/theme.json → ../theme.json`.

### 1.5 .env на сервере (секреты только тут; Airtable/Telegram/Groq НЕ нужны на VPS)
```bash
# Имена ровно как читает код (grep os.environ server/): DATABASE_URL, OPERATOR_USER, OPERATOR_PASS.
# БЕЗ inline-комментов (systemd EnvironmentFile берёт всю строку как значение).
# Порт НЕ через .env — он зашит в ExecStart юнита (--port 8014).
ssh -p 2222 root@147.45.251.134 'umask 077; cat > /opt/projects/dc-deck/.env <<EOF
DATABASE_URL=<connection string из 1.1>
OPERATOR_USER=operator
OPERATOR_PASS=<стойкий, буквы+цифры>
EOF
chmod 600 /opt/projects/dc-deck/.env'
```

### 1.6 venv + таблицы + сид + сервис
```bash
ssh -p 2222 root@147.45.251.134 '
  cd /opt/projects/dc-deck
  python3 -m venv .venv
  ./.venv/bin/pip install -r server/requirements.txt        # incl. python-dotenv (db.py/main.py его импортят)
  set -a; . ./.env; set +a
  ( cd server && ../.venv/bin/python -c "from db import init_db; init_db()" )   # таблицы ДО сида; запуск ИЗ server/
  ./.venv/bin/python server/seed_songs.py                                       # сид каталога песен
  cp infra/dc-deck.service /etc/systemd/system/
  systemctl daemon-reload && systemctl enable --now dc-deck
  systemctl is-active dc-deck && journalctl -u dc-deck -n 30 --no-pager
'
```
Проверь в юните: `WorkingDirectory=/opt/projects/dc-deck/server`, `EnvironmentFile=.../.env`,
`ExecStart=.../uvicorn main:app --host 127.0.0.1 --port 8014`.
`seed_songs.py` пишет в `song` до первого запуска сервиса — поэтому `init_db` идёт раньше сида.

### 1.7 Домен + TLS (блок в sites/, главный Caddyfile НЕ трогать)
> ⚠️ **`register-site.sh` на этом деплое сгенерировал НЕВАЛИДНЫЙ блок** (директиву
> `handle /api/* { reverse_proxy … }` в одну строку — Caddy это не принимает, `caddy validate`
> падает). Это баг платформенного скрипта (см. PLATFORM-CONTRACT §6/§11, требует починки).
> **До починки — писать блок ВРУЧНУЮ** по образцу рабочего `sites/ycab.caddy` (многострочно):

```bash
ssh -p 2222 root@147.45.251.134 'cat > /etc/caddy/sites/dc-deck.caddy <<EOF
dc.vnedrum.ru {
    encode gzip
    handle /api/* {
        reverse_proxy 127.0.0.1:8014
    }
    handle {
        root * /opt/projects/dc-deck/dist
        try_files {path} {path}/index.html {path}.html /index.html
        file_server
    }
}
EOF'
# ОБЯЗАТЕЛЬНО валидировать ДО применения; невалидно → удалить блок, НЕ применять:
ssh -p 2222 root@147.45.251.134 'caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile'
# только reload (НЕ restart — restart уронит живые сайты на секунды):
ssh -p 2222 root@147.45.251.134 'systemctl reload caddy'
```
После reload — проверить, что **соседи живы** (не только dc): `curl -sI https://vnedrum.ru https://ycab.vnedrum.ru https://zo.vnedrum.ru`. Любой упал → `rm /etc/caddy/sites/dc-deck.caddy` + `systemctl reload caddy` немедленно.

### 1.8 Проверка
```bash
# ACME: первый серт выписывается не мгновенно — при TLS-ошибке подожди 30с, повтори.
curl -sI https://dc.vnedrum.ru/ | head -3
curl -s https://dc.vnedrum.ru/manifest.json | head -c 100
curl -s https://dc.vnedrum.ru/api/catalog | python3 -c "import sys,json;print(len(json.load(sys.stdin)),'песен')"
curl -sI https://dc.vnedrum.ru/api/operator | head -1   # 401 без auth — норма
```
- дек открывается, manifest отдаётся, каталог непустой → деплой удался.
- форма: `https://dc.vnedrum.ru/api/operator` (basic-auth в FastAPI).
- `healthcheck.sh dc-deck 8014 dc.vnedrum.ru` ложно пишет «базы dc-deck нет» — ищет по имени с дефисом, а БД `dc_deck`. БД рабочая.

### 1.9 Обнови контракт
- `/opt/PLATFORM-CONTRACT.md` §3 реестр портов: dc-deck → 8014
- §13 таблица проектов: dc-deck | dc.vnedrum.ru | 8014 | dc_deck | deployed
- бэкап БД dc_deck в общий cron (`/opt/scripts/backup-db.sh`)

### 1.10 Картинки песен (разовая доставка, ОТДЕЛЬНО от weekly.sh)
Слайд песни — гибрид: для номера N дек ищет `assets/songs/N.{webp,png,jpg}` → есть
картинка показывает на весь слайд; нет → текст из каталога; нет ни того → заглушка
«№N нет». Картинки статичны — доставляются РАЗОВО (weekly.sh шлёт только manifest).

⚠️ **Две папки на VPS, не только dist!**
- `deck/assets/songs/` — по ней сканирует FastAPI `/api/song-images`
  (`SONGS_ASSET_DIR = ROOT/deck/...`), чтобы дек узнал, у каких номеров есть картинка;
- `dist/assets/songs/` — из неё Caddy отдаёт сами байты.
Доставка только в `dist/` НЕ сработает: эндпоинт вернёт `{}` и дек не покажет картинки.

```bash
# 1) png -> webp (1.5-2МБ -> ~100-150КБ; гибрид ищет webp первым). cwebp нет → оставить png.
for f in deck/assets/songs/*.png; do cwebp -q 85 -quiet "$f" -o "${f%.png}.webp"; done

# 2) webp в ОБЕ папки на VPS
for target in deck dist; do
  rsync -avz -e "ssh -p 2222 -i ~/.ssh/vnedrum" --include='*.webp' --exclude='*' \
    deck/assets/songs/ \
    root@147.45.251.134:/opt/projects/dc-deck/$target/assets/songs/
done

# 3) проверка
curl -sI https://dc.vnedrum.ru/assets/songs/1.webp | head -1        # HTTP/2 200
curl -s https://dc.vnedrum.ru/api/song-images | python3 -c "import sys,json;print(len(json.load(sys.stdin)),'картинок')"
```
Новую песню с картинкой добавляют так же: положить `N.png` в `deck/assets/songs/` →
convert → rsync в обе папки. Эндпоинт подхватит на лету (скан на каждый запрос, рестарт не нужен).

---

## ЧАСТЬ 2 — Еженедельный автопрожиг (Мак: launchd + pmset + alias)

Данные печёт МАК (там открыт Telegram/Airtable/Groq), затем rsync manifest на VPS в `dist/`.
Три слоя надёжности: **launchd** (основной) + **pmset** (будильник) + **alias** (ручной резерв).

### 2.1 Скрипт прожига — `build/weekly.sh` (в репо, chmod +x)
weekly.sh лишь запускает `build/build_manifest.py`, который делает ВСЁ:
- собирает manifest (Telegram/Airtable/Groq → `data/manifest.json`);
- **деплоит** сам: `data/manifest.json → dist/manifest.json` и
  `data/last_build_status.json → data/` на VPS (сервер отдаёт дек из dist);
- пишет `data/last_build_status.json` (статус каждого источника + `deploy` + `ts`);
- **шлёт сводку прожига** — Telegram (полная) + macOS (светофор), см. §2.7.

Пути к venv/ключу — **абсолютные** (launchd — урезанное окружение). Лог `~/dc-deck-build.log`.
Вручную: `bash build/weekly.sh` (или `dcbuild`). `DC_NO_DEPLOY=1` — собрать без заливки на VPS.

### 2.7 Сводка прожига — 3 канала (детали в DECK-CONTRACT.md)
После сборки `build_manifest` отчитывается:
- **Telegram** (`TELEGRAM_ALERT_CHAT` в `.env`) — полная сводка ✅/❌/⚠️ по источникам, КАЖДЫЙ прожиг;
- **macOS** — короткий светофор (✅ успех / ❌ сбой / ⚠️ новая песня), КАЖДЫЙ прожиг;
- **форма** `/api/operator` — строка «Последняя сборка … ✅/⚠️» из `GET /api/build-status`.

Статус прожига шлётся каждый раз; флаг «новая песня №N» — один раз на номер (`build/alerted_songs.json`).
Любой источник упал → ❌ в сводке, но прожиг ЗАВЕРШАЕТСЯ (не краш). Нет `TELEGRAM_ALERT_CHAT` →
Telegram-канал пропускается, остальные работают.

### 2.2 launchd — основной планировщик (наверстывает пропуск при пробуждении)
Почему launchd, а не cron: если Мак спал в субботу 12:00, launchd **выполнит пропущенную задачу
при пробуждении**; cron молча пропустит.

Файл `~/Library/LaunchAgents/ru.vnedrum.dcdeck.build.plist` (НЕ в репо — конфиг Мака):
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>ru.vnedrum.dcdeck.build</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>/Users/danny/Documents/DC_slids-auto/build/weekly.sh</string></array>
  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>6</integer><key>Hour</key><integer>12</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/Users/danny/dc-deck-build.log</string>
  <key>StandardErrorPath</key><string>/Users/danny/dc-deck-build.log</string>
  <key>RunAtLoad</key><false/>
</dict></plist>
```
Weekday 6 = суббота. Загрузка: `launchctl load ~/Library/LaunchAgents/ru.vnedrum.dcdeck.build.plist`
(выгрузка — `unload`; проверка — `launchctl list | grep dcdeck`).

### 2.3 ⚠️ Full Disk Access для `/bin/bash` (ОБЯЗАТЕЛЬНО — иначе launchd молча падает)
Проект в `~/Documents` — папка под защитой macOS **TCC**. launchd запускает `/bin/bash` **напрямую**
(не через Терминал), поэтому:
- грант FDA на **Терминал/iTerm НЕ помогает** — их launchd не использует;
- без гранта launchd падает: `LastExitStatus 32256` (exit 126), в логе
  `/bin/bash: …/weekly.sh: Operation not permitted` (не может даже прочитать скрипт).

Выдать доступ:
1. System Settings → **Privacy & Security → Full Disk Access** → **«+»**
2. **Cmd+Shift+G** → `/bin/bash` → Open → в списке появится строка **`bash`**, тумблер **ON**
3. **Cmd+Q** (закрыть System Settings — TCC применяет грант по закрытии)

Проверка, что действует: `launchctl start` (§2.6) даёт НОВУЮ «weekly build done», а не «Operation not permitted».
Перенос проекта из Documents тоже снял бы TCC, но осиротит память сессии — не делаем.

### 2.4 pmset — будильник Мака (разбудить к субботе)
launchd наверстает пропуск при пробуждении, но чтобы Мак включился — будильник (нужен sudo):
```bash
sudo pmset repeat wakeorpoweron S 12:00:00     # каждую субботу 12:00; проверка: pmset -g sched
```
Требует питания (ноут — в адаптере). Проснётся чуть позже 12:00 — launchd всё равно наверстает.

### 2.5 alias `dcbuild` — ручной резерв
В `~/.zshrc`: `alias dcbuild='/Users/danny/Documents/DC_slids-auto/build/weekly.sh'`.
Субботним утром, если Мак проспал: `dcbuild`.

### 2.6 Проверка автопрожига целиком
```bash
# форсировать джоб сейчас (как будто наступила суббота) и убедиться, что дошло до VPS:
base=$(grep -c "weekly build done" ~/dc-deck-build.log)
launchctl start ru.vnedrum.dcdeck.build
sleep 60; grep -c "weekly build done" ~/dc-deck-build.log            # стало base+1
launchctl list ru.vnedrum.dcdeck.build | grep LastExitStatus         # = 0
curl -s https://dc.vnedrum.ru/manifest.json | python3 -c "import sys,json;d=json.load(sys.stdin);print('program',len(d['program']),'raised',d.get('raised'),'news',len(d['news']))"
# лог: tail ~/dc-deck-build.log
```

> **Backlog:** все три слоя — обход того, что прожиг привязан к Маку (TCC + «Мак спит»).
> Идеал — вынести билд на дешёвый **always-on хост вне РФ** (ни TCC, ни сна) → launchd/pmset/alias
> уходят. Для старта Мак + эти три слоя достаточно.

---

## ЧАСТЬ 3 — YouTube на показе (напрямую через VPN)

Ничего настраивать не нужно — так уже работает по архитектуре:
- `manifest.video_url` / `final_music_url` — обычные YouTube-ссылки.
- Дек рендерит их `<iframe>`. На проекторе с VPN iframe грузится НАПРЯМУЮ с YouTube.
- VPS видео не проксирует и не перезаливает — только отдаёт ссылку в разметке.

Единственная страховка (уже в деке): если iframe не поднялся (флаки-VPN) —
fallback «Открыть на YouTube» / слайд-заглушка. Никакого плеера на экране не будет.

Проверка на показе: открыть dc.vnedrum.ru при включённом VPN → видео играет.
Без VPN (тест на VPS/локали в РФ) YouTube будет штормить — это нормально,
на реальном показе VPN есть.

---

## Еженедельный цикл оператора (итог)

1. **Автоматически** (сб 12:00, Мак-cron): программа, деньги, видео Дады, новости →
   manifest → VPS. Оператор ничего не делает.
2. **Вручную** (оператор, в форме, когда угодно до показа): выбрать песни (пикер),
   при необходимости — поправить программу/новости/сумму (оверрайд), отметить границу «Далее».
3. **Показ** (проектор + VPN): открыть dc.vnedrum.ru. YouTube грузится напрямую.

Если Мак проспал субботу — запустить `build/weekly.sh` вручную.
