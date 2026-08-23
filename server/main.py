import json
import os
import pathlib
import secrets
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import psycopg
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from db import get_conn, init_db

# ── Auth ──────────────────────────────────────────────────────────────────────
BASIC_USER = os.environ.get("OPERATOR_USER", "operator")
BASIC_PASS = os.environ.get("OPERATOR_PASS", "operator")
_WWW_AUTH = {"WWW-Authenticate": 'Basic realm="DC Deck Operator"'}

security = HTTPBasic(auto_error=False)

def require_auth(creds: Optional[HTTPBasicCredentials] = Depends(security)):
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated", headers=_WWW_AUTH)
    ok = (
        secrets.compare_digest(creds.username.encode(), BASIC_USER.encode())
        and secrets.compare_digest(creds.password.encode(), BASIC_PASS.encode())
    )
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials", headers=_WWW_AUTH)
    return creds.username

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT = pathlib.Path(__file__).parent.parent   # project root
DECK_DIR = ROOT / "deck"
DIST_DIR = ROOT / "dist"          # prod: Caddy serves song images from here (dev: absent)
DATA_DIR = ROOT / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"
THEME_PATH = ROOT / "theme.json"
SONGS_ASSET_DIR = DECK_DIR / "assets" / "songs"
SONG_IMAGE_EXTS = ("webp", "png", "jpg")   # priority order

# ── Lifespan ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception as e:
        print(f"[warn] DB init failed: {e} — API will return empty selection")
    yield

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=str(pathlib.Path(__file__).parent / "templates"))

# ── Static data files (manifest.json, theme.json) ─────────────────────────────
# Served before the catch-all StaticFiles mount so they're reachable at /manifest.json

@app.get("/manifest.json")
def serve_manifest():
    if not MANIFEST_PATH.exists():
        raise HTTPException(404, "manifest.json not found — run build/build_manifest.py")
    return JSONResponse(json.loads(MANIFEST_PATH.read_text()))

@app.get("/theme.json")
def serve_theme():
    if not THEME_PATH.exists():
        raise HTTPException(404, "theme.json not found")
    return JSONResponse(json.loads(THEME_PATH.read_text()))

# ── API ───────────────────────────────────────────────────────────────────────

@app.get("/api/catalog")
def get_catalog():
    try:
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT number, title_translit, subtitle, first_line_translit, "
                "translation_first_line, stanzas, footnote, lang, background_ref "
                "FROM song ORDER BY number"
            ).fetchall()
        return [
            {
                "number": r[0],
                "title_translit": r[1],
                "subtitle": r[2],
                "first_line_translit": r[3],
                "translation_first_line": r[4],
                "stanzas": r[5],
                "footnote": r[6],
                "lang": r[7],
                "background_ref": r[8],
            }
            for r in rows
        ]
    except Exception as e:
        print(f"[warn] catalog DB error: {e}")
        return []

@app.get("/api/song-images")
def get_song_images():
    """Map {song_number: image_path} for images present in deck/assets/songs/.
    A read-only reflection of on-disk assets — no DB, no outbound calls.
    Extension priority webp > png > jpg; first match per number wins."""
    result: dict[int, str] = {}
    if SONGS_ASSET_DIR.is_dir():
        for ext in SONG_IMAGE_EXTS:
            for f in sorted(SONGS_ASSET_DIR.glob(f"*.{ext}")):
                if f.stem.isdigit():
                    result.setdefault(int(f.stem), f"assets/songs/{f.name}")
    return result


@app.get("/api/selection")
def get_selection():
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT week_date, song_numbers, video_url, final_video_url, raised, plan, overrides, bg_music_url "
                "FROM selection ORDER BY week_date DESC LIMIT 1"
            ).fetchone()
    except Exception as e:
        print(f"[warn] selection DB error: {e}")
        row = None

    if row is None:
        return {
            "week_date": date.today().isoformat(),
            "song_numbers": [],
            "video_url": "",
            "final_video_url": "",
            "bg_music_url": "",
            "raised": None,
            "plan": None,
            "overrides": {"program": None, "news": None, "news_manual": None, "featured_news": None, "practice_end": None, "dada_comment": None},
        }
    return {
        "week_date": row[0].isoformat() if hasattr(row[0], 'isoformat') else str(row[0]),
        "song_numbers": row[1] or [],
        "video_url": row[2] or "",
        "final_video_url": row[3] or "",
        "raised": row[4],
        "plan": row[5],
        "overrides": row[6] or {"program": None, "news": None, "news_manual": None, "featured_news": None, "practice_end": None, "dada_comment": None},
        "bg_music_url": row[7] or "",
    }

@app.post("/api/selection")
async def post_selection(request: Request, _: str = Depends(require_auth)):
    body = await request.json()
    week_date = body.get("week_date", date.today().isoformat())
    song_numbers = body.get("song_numbers", [])
    video_url = body.get("video_url", "")
    final_video_url = body.get("final_video_url", "")
    bg_music_url = body.get("bg_music_url", "")
    raised = body.get("raised")
    plan = body.get("plan")
    overrides = body.get("overrides", {"program": None, "news": None, "news_manual": None, "featured_news": None, "practice_end": None, "dada_comment": None})

    try:
        with get_conn() as conn:
            # Final video/music sticks: an empty submission never wipes it — it inherits
            # the last non-empty value (across any week/row), so it lives until a NEW link
            # is entered ("set once, stays until I change it manually"). Change = type a
            # new URL; leaving the field empty keeps the previous one.
            if not (final_video_url or "").strip():
                prev = conn.execute(
                    "SELECT final_video_url FROM selection "
                    "WHERE final_video_url IS NOT NULL AND final_video_url <> '' "
                    "ORDER BY week_date DESC LIMIT 1"
                ).fetchone()
                if prev:
                    final_video_url = prev[0]
            # Background music is sticky the same way (set once, lives until changed).
            if not (bg_music_url or "").strip():
                prev = conn.execute(
                    "SELECT bg_music_url FROM selection "
                    "WHERE bg_music_url IS NOT NULL AND bg_music_url <> '' "
                    "ORDER BY week_date DESC LIMIT 1"
                ).fetchone()
                if prev:
                    bg_music_url = prev[0]
            conn.execute(
                """
                INSERT INTO selection (week_date, song_numbers, video_url, final_video_url, bg_music_url, raised, plan, overrides)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (week_date) DO UPDATE SET
                    song_numbers    = EXCLUDED.song_numbers,
                    video_url       = EXCLUDED.video_url,
                    final_video_url = EXCLUDED.final_video_url,
                    bg_music_url    = EXCLUDED.bg_music_url,
                    raised          = EXCLUDED.raised,
                    plan            = EXCLUDED.plan,
                    overrides       = selection.overrides || EXCLUDED.overrides
                """,
                (week_date, song_numbers, video_url, final_video_url, bg_music_url, raised, plan,
                 json.dumps(overrides, ensure_ascii=False)),
            )
            conn.commit()
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/api/song")
async def add_song(
    number: int = Form(...),
    title: str = Form(...),
    translation: str = Form(""),
    image: UploadFile = File(...),
    _: str = Depends(require_auth),
):
    """Operator adds one image-backed Prabhat Samgita to the catalog.
    Mirrors add_image.sh's dual-write: the picture lands in BOTH deck/assets/songs/
    (scanned by /api/song-images) and dist/assets/songs/ (served by Caddy in prod),
    plus a catalog row so it searches/renders like any other song. Refuses to clobber
    an existing number (seeded text or an image already on disk) — pick a free number."""
    if number < 1:
        raise HTTPException(400, "Номер должен быть ≥ 1")
    title = title.strip()
    if not title:
        raise HTTPException(400, "Название не может быть пустым")

    ext = (pathlib.Path(image.filename or "").suffix.lower().lstrip(".")) or "png"
    if ext == "jpeg":
        ext = "jpg"
    if ext not in SONG_IMAGE_EXTS:
        raise HTTPException(400, f"Формат .{ext} не поддерживается (нужно webp/png/jpg)")

    if get_song_images().get(number):
        raise HTTPException(409, f"№{number}: картинка уже есть")
    try:
        with get_conn() as conn:
            if conn.execute("SELECT 1 FROM song WHERE number = %s", (number,)).fetchone():
                raise HTTPException(409, f"№{number} уже в каталоге")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Ошибка БД: {e}")

    data = await image.read()
    if not data:
        raise HTTPException(400, "Пустой файл")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "Картинка больше 15 МБ")

    fname = f"{number}.{ext}"
    for base in (DECK_DIR, DIST_DIR):
        if base is DIST_DIR and not DIST_DIR.is_dir():
            continue   # dev: no dist/, the deck mount serves the image directly
        songs_dir = base / "assets" / "songs"
        songs_dir.mkdir(parents=True, exist_ok=True)
        (songs_dir / fname).write_bytes(data)

    # Image-backed row: no stanzas (the slide uses the picture); title/translation
    # exist only so the catalog card shows and searches like every other song.
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO song (number, title_translit, translation_first_line, stanzas, lang) "
                "VALUES (%s, %s, %s, '[]'::jsonb, 'translit')",
                (number, title, translation.strip()),
            )
            conn.commit()
    except Exception as e:
        raise HTTPException(500, f"Ошибка БД: {e}")

    return {"ok": True, "number": number, "image_path": f"assets/songs/{fname}"}

@app.get("/api/operator", response_class=HTMLResponse)
def operator_form(request: Request, _: str = Depends(require_auth)):
    return HTMLResponse((pathlib.Path(__file__).parent / "templates" / "operator.html").read_text(encoding="utf-8"))

# ── Static deck (catch-all, LAST) ─────────────────────────────────────────────
# Mounts deck/ at "/" — boot.js, slides/*, assets/* are served from here.
@app.get("/api/build-status")
def get_build_status():
    """Last Mac-build status (data/last_build_status.json, delivered by the build).
    Feeds the operator form status line (channel А). {} until the first build."""
    try:
        return json.loads((DATA_DIR / "last_build_status.json").read_text())
    except Exception:
        return {}


# Must come after all @app.get routes.
app.mount("/", StaticFiles(directory=str(DECK_DIR), html=True), name="deck")
