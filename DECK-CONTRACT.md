# DECK-CONTRACT — контракт данных dc-deck

Единственный источник истины по именам полей, слотам и правилам слияния.
Правишь данные или шаблоны — сверяйся здесь. Переименовал поле — обнови и шаблон, и этот файл.

---

## Слой 1 — `manifest.json` (Мак-билд, еженедельно)

```json
{
  "date": "2026-08-02",
  "program": [
    { "time": "08:30", "title": "Сбор в джагрити", "note": null },
    { "time": "08:45", "title": "Дхармачакра", "note": null },
    { "time": "11:00", "title": "Сатсанг (Индранатха)", "note": "Немного поговорим о том, как у кого дела…" }
  ],
  "news": [
    "15 августа — книжный клуб «Война и мир»",
    "2–6 сентября — Южный семинар в Лоо"
  ],
  "dada_comment": "Наш Дада даст комментарий на следующей неделе.",
  "final_music_url": null,
  "suggested_songs": [50, 1041]
}
```

- `program[].time` — строка `"HH:MM"`, трактуется как **МСК**.
- `program[].note` — опционально, курсивная подпись под пунктом.
- `final_music_url` — YouTube для финального слайда; `null` → блок музыки скрыт.
- `suggested_songs` — номера ПС из поста Rostov Unit (regex «ПС N» / «Прабхат Самгит N», порядок в тексте = порядок слайдов). **Только подсказка** оператору: форма предзаполняет пикер, если оператор ещё не выбрал; итог живёт в `selection.song_numbers`. Пусто/нет поста → оператор выбирает вручную.

## Слой 2 — `selection` (Postgres на VPS, форма `/operator`)

```json
{
  "song_numbers": [1, 63],
  "video_url": "",
  "raised": 8500,
  "plan": 30000,
  "overrides": {
    "program": null,
    "news": null,
    "news_manual": null,
    "practice_end": null,
    "dada_comment": null
  }
}
```

- `song_numbers` — номера из каталога; резолвятся в карточки/слайды.
- `video_url` — пусто → слайд «видео нет».
- `overrides.*` — `null` = берём авто из manifest; не-`null` = ручная правка перекрывает.

## Слой 3 — `theme.json` (репозиторий, редко)

```json
{
  "accent": "#…",
  "font_heading": "…",
  "font_body": "…",
  "song_background": "assets/backgrounds/…"
}
```

---

## Правила слияния (effective-данные)

```
program      = overrides.program      ?? manifest.program
practice_end = overrides.practice_end                 // "HH:MM" границы кол. части; пункт с этим time → is_practice_end=true (накладывается на program, НЕ хранится в нём). Пусто/нет совпадения → continuation показывает всё
continuation = program после пункта-границы (см. practice_end)
news         = overrides.news         ?? manifest.news
dada_comment = overrides.dada_comment ?? manifest.dada_comment ?? DEFAULT_DADA
songs        = resolve(selection.song_numbers)   // приоритет картинки: assets/songs/N.{webp,png,jpg} есть → image_path; иначе текст из каталога → stanzas; иначе заглушка «№N нет»
             // форма: пусто в selection.song_numbers → пикер предзаполняется manifest.suggested_songs (подсказка из ТГ). Номер без картинки И без текста → пометка оператору «добавь картинку в assets/songs/N.webp» (не блокирует)
video        = selection.video_url || manifest.video_url  // форма-оверрайд → авто из СВАДХЬЯЯ (свежая youtube-ссылка); пусто → слайд-заглушка «видео от Дады не будет»
raised       = selection.raised ?? manifest.raised   // форма-оверрайд → авто из ТГ-поста финансов
plan         = selection.plan   ?? manifest.plan      // план пуст/0 → бар скрыт
```

**Правило слайда Дады:** есть встраиваемое видео (`video_url` резолвится в YouTube-embed)
→ слайд Дады **не показывается** (видео его замещает). Нет видео → слайд Дады на месте.

Оверрайд — **слой поверх**, не перезапись manifest. Кнопка «сбросить к авто» ставит поле обратно в `null`.

---

## Слоты → шаблоны

| Слайд | Файл | Слоты | Пусто → |
|---|---|---|---|
| welcome | `slides/welcome.js` | greeting (правило!) | утренний дефолт |
| program | `slides/program.js` | program[] | «программа не задана» |
| news | `slides/news.js` | news[] | «нет событий» |
| song | `slides/song.js` | image_path **или** stanzas | «№N нет» |
| video | `slides/video.js` | video | «видео нет» |
| dada | `slides/dada.js` | dada_comment, `assets/dada.jpg` | DEFAULT_DADA; нет файла фото → заглушка |
| final | `slides/final.js` | progress, final_music_url, dada_comment | бар/музыка скрыты |

---

## Правило слайда 1 (welcome) — НЕ поле формы

Обе приветственные строки — **константы в шаблоне** (всегда одни и те же):

- `GREETING_MORNING` — вариант с «Маунавратой».
- `GREETING_DAY` — вариант без неё.

Выбор:

```
start = effective.program[0].time      // "HH:MM", МСК
hour  = parseInt(start.split(":")[0])
if (program пуст || start не распознан)  → GREETING_MORNING   // дефолт
else if (hour < 12)                      → GREETING_MORNING
else                                     → GREETING_DAY
```

Сравнение по **МСК из строки расписания**, НЕ по `datetime.now()` сервера.
Порог 12:00 — константа `MORNING_CUTOFF_HOUR = 12`.

---

## Boot дека

1. `fetch` `theme.json` + `manifest.json` (статика) + `GET /api/selection` + `GET /api/catalog` + `GET /api/song-images` (карта {номер → путь картинки}, read-only скан `deck/assets/songs/`).
2. Слить в effective по правилам выше.
3. Отрендерить слайды в фиксированном порядке.
4. `/api/*` недоступен → рендерить по `manifest` + дефолтам + баннер «нет связи с формой, показываю авто».

## Валидация

- Мак-билд валидирует `manifest.json` по `data/manifest.schema.json`; предупреждает о лишних/недостающих полях.
- Дек: любой пустой/битый слот → заглушка слота, никогда не краш всего дека.
