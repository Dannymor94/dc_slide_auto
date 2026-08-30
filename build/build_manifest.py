#!/usr/bin/env python3
"""Assemble data/manifest.json, deploy it to the VPS, collect a per-source build
STATUS, and report the run over three channels (see song_alerts): Telegram summary
(Б) + macOS traffic-light (В), plus the form status line (А) via the delivered
data/last_build_status.json.

Every source degrades independently — a failed source becomes ❌ in the status and
NEVER crashes the build. The build always completes and always reports.

Deploy lives here (not weekly.sh) so `status.deploy` is truthful; set DC_NO_DEPLOY=1
to build + report without touching the VPS (local testing).
"""
import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from extract_program import extract_program
from extract_progress import extract_progress
from fetch_news import fetch_news
from fetch_telegram import fetch_dada_video, fetch_posts
from song_alerts import find_new_songs, report_build
from urokimeditacii import build_urokimeditacii

ROOT = Path(__file__).parent.parent
MANIFEST_PATH = ROOT / "data" / "manifest.json"
STATUS_PATH = ROOT / "data" / "last_build_status.json"
MSK = ZoneInfo("Europe/Moscow")


def nearest_sunday(today: date) -> date:
    """Nearest Sunday on or after today (if today IS Sunday → today)."""
    return today + timedelta(days=(6 - today.weekday()) % 7)


def _iso_week_year(date_str):
    """(ISO year, ISO week) for a YYYY-MM-DD string, or None on failure."""
    if not date_str:
        return None
    try:
        ic = date.fromisoformat(date_str).isocalendar()
        return (ic[0], ic[1])          # (year, week) — isocalendar() is a tuple in py3.9
    except (ValueError, TypeError):
        return None


def _fetch_selection():
    """Fetch current selection from the live VPS API. Returns dict or None."""
    import urllib.request
    try:
        with urllib.request.urlopen(
            "https://dc.vnedrum.ru/api/selection", timeout=10
        ) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[warn] fetch_selection: {e}", file=sys.stderr)
        return None


def _parse_date_override():
    """Read DC_MANIFEST_DATE env or --date CLI arg. Returns ISO string or None."""
    env = os.environ.get("DC_MANIFEST_DATE")
    if env:
        return env
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg == "--date" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--date="):
            return arg[7:]
    return None

# ── deploy target (kept here so status.deploy reflects the real rsync) ───────────
VPS = "root@147.45.251.134"
SSH_E = f"ssh -p 2222 -i {os.path.expanduser('~/.ssh/vnedrum')} -o BatchMode=yes"
DIST = "/opt/projects/dc-deck/dist"
VPS_DATA = "/opt/projects/dc-deck/data"


def _ok(value):
    return {"ok": True, "value": value, "error": None}


def _fail(error):
    return {"ok": False, "value": None, "error": str(error)[:180]}


def _rsync(local: Path, remote: str) -> None:
    r = subprocess.run(["rsync", "-az", "-e", SSH_E, str(local), f"{VPS}:{remote}"],
                       capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:180] or f"rsync rc={r.returncode}")


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())
    status = {"date": None, "program": None, "money": None, "video": None, "news": None,
              "urokimeditacii": None, "songs": None, "video_stale": None,
              "deploy": None, "ts": None}

    # ── Run label: "12:00" or "21:00" (or actual hour for manual/test runs) ─────────
    now_msk = datetime.now(MSK)
    run_hour = now_msk.hour
    run_label = f"{run_hour:02d}:00"
    status["run"] = run_label

    # ── Date: nearest Sunday (auto) or explicit override ──────────────────────────
    today_msk = now_msk.date()
    nearest_sun = nearest_sunday(today_msk)
    raw_override = _parse_date_override()
    if raw_override:
        try:
            target_date = date.fromisoformat(raw_override)
        except ValueError:
            print(f"[warn] manifest.date: некорректный формат override {raw_override!r} "
                  f"— использую автоматический {nearest_sun}", file=sys.stderr)
            target_date = nearest_sun
            raw_override = None
    else:
        target_date = nearest_sun

    old_date = manifest.get("date")
    if old_date != target_date.isoformat():
        src = f"override={raw_override}" if raw_override else "авто"
        print(f"[info] manifest.date: {old_date!r} → {target_date.isoformat()} ({src})",
              file=sys.stderr)
        manifest["date"] = target_date.isoformat()
    else:
        print(f"[info] manifest.date: без изменений ({target_date.isoformat()})",
              file=sys.stderr)

    if target_date == nearest_sun:
        src_label = "override (текущая неделя)" if raw_override else "авто"
        status["date"] = _ok(f"{target_date} ({src_label})")
    else:
        status["date"] = _fail(
            f"override={target_date} — ожидалось ближайшее вс {nearest_sun}"
        )

    # ── News (Airtable) ──
    try:
        news = fetch_news()
        if news:
            manifest["news"] = news
            status["news"] = _ok(str(len(news)))
        else:
            # fetch_news() returns [] both on error AND on genuinely empty window.
            # If previous manifest already had news, keep it — a transient Airtable
            # failure on the 21:00 run must not wipe what the 12:00 run gathered.
            prev_news = manifest.get("news") or []
            if prev_news:
                status["news"] = _fail(
                    f"Airtable вернул 0 новостей — прежние {len(prev_news)} сохранены"
                )
                print("[warn] news: fetch_news() вернул [] — прежние новости сохранены (не затираю).",
                      file=sys.stderr)
            else:
                manifest["news"] = []
                status["news"] = _ok("0")
    except Exception as e:
        status["news"] = _fail(e)
        print(f"[warn] news: {e}", file=sys.stderr)

    # ── Rostov Unit: program + money + song numbers ──
    try:
        posts = fetch_posts()
    except Exception as e:
        posts = {"connected": False, "program": None, "finance": None, "songs": []}
        print(f"[warn] fetch_posts: {e}", file=sys.stderr)

    if not posts["connected"]:
        # don't wipe good manifest data on a transient/misconfig failure
        status["program"] = _fail("Telethon (Rostov) недоступен")
        status["money"] = _fail("Telethon (Rostov) недоступен")
        status["songs"] = {"suggested": [], "missing": []}
        print("[warn] Telethon (Rostov) недоступен — программу/деньги не трогаю.", file=sys.stderr)
    else:
        # program
        if posts["program"]:
            try:
                prog = extract_program(posts["program"])
                if prog:
                    manifest["program"] = prog
                    status["program"] = _ok(f"{len(prog)} пунктов")
                else:
                    # LLM returned empty list (all providers down or parse failed) →
                    # keep the previous manifest program intact, report as failure
                    status["program"] = _fail(
                        "LLM вернул пустую программу — прежняя сохранена"
                    )
                    print("[warn] program: LLM вернул [] — прежняя программа сохранена (не затираю).",
                          file=sys.stderr)
            except Exception as e:
                status["program"] = _fail(e)
                print(f"[warn] extract_program: {e}", file=sys.stderr)
        else:
            # Program post aged out of the window / not posted yet → KEEP the previous
            # manifest program. A transient window miss must NEVER wipe live data (same
            # policy as the Telethon-disconnected branch above).
            status["program"] = _fail("пост программы не найден — прежняя программа сохранена")
            print("[warn] program: пост ДЧ не найден в окне — прежняя программа сохранена (не затираю).",
                  file=sys.stderr)

        # money
        if posts["finance"]:
            try:
                pr = extract_progress(posts["finance"])
                manifest["raised"], manifest["plan"] = pr["raised"], pr["plan"]
                status["money"] = (_ok(f"{pr['raised']}/{pr['plan']}")
                                   if pr["raised"] is not None
                                   else _fail("«ДЧ донаты» не распознано"))
            except Exception as e:
                status["money"] = _fail(e)
                print(f"[warn] extract_progress: {e}", file=sys.stderr)
        else:
            # Keep previous raised/plan — same policy as missing program post.
            # A transient Telethon miss on the 21:00 run must not wipe 12:00 data.
            status["money"] = _fail("пост финансов не найден — прежние суммы сохранены")
            print("[warn] money: пост финансов не найден — raised/plan не затираю.",
                  file=sys.stderr)

        # song numbers (regex, no LLM)
        songs = posts.get("songs", [])
        manifest["suggested_songs"] = songs
        try:
            missing = find_new_songs(songs)
        except Exception:
            missing = []
        status["songs"] = {"suggested": songs, "missing": missing, "stale": None}

    # ── Dada video (СВАДХЬЯЯ) ──
    try:
        vid = fetch_dada_video()
        new_url = vid["video_url"]
        if new_url:
            manifest["video_url"] = new_url
            status["video"] = _ok(new_url)
        else:
            # Keep previous URL — a missed Telegram post on the 21:00 run must not
            # blank a URL the 12:00 run successfully fetched.
            prev_url = manifest.get("video_url") or ""
            if prev_url:
                status["video"] = _fail("видео не найдено — прежний URL сохранён")
                print("[warn] video: video_url=None — прежний URL сохранён (не затираю).",
                      file=sys.stderr)
            else:
                manifest["video_url"] = None
                status["video"] = _ok("—")
    except Exception as e:
        status["video"] = _fail(e)
        print(f"[warn] video: {e}", file=sys.stderr)

    # ── Уроки медитации (optional, appended only on Sunday-КМ weeks) ──
    # Absent key = no slide. On trigger-false or any error we DROP the key so a
    # stale slide from a previous week never lingers. M1: baked but not rendered.
    try:
        um = build_urokimeditacii(manifest.get("date"))
        if um:
            manifest["urokimeditacii"] = um
            # status from the SAME result (no recompute): день + длина расписания
            items = len((um.get("meeting") or {}).get("items") or [])
            status["urokimeditacii"] = {
                "state": "ok" if items else "warn",   # ✅ есть расписание / ⚠️ пост не спарсился
                "day": um.get("highlight_day"),
                "items": items,
            }
        else:
            manifest.pop("urokimeditacii", None)
            status["urokimeditacii"] = {"state": "skip"}   # ➖ нет воскресной КМ (норма)
    except Exception as e:
        manifest.pop("urokimeditacii", None)
        status["urokimeditacii"] = {"state": "error", "error": str(e)[:180]}   # ❌
        print(f"[warn] urokimeditacii: {e}", file=sys.stderr)

    # ── stale top-level fields: song_numbers / video_url survive across weeks by
    # design (never expired), so we WARN instead of blanking. Compare
    # selection.week_date's ISO week to the manifest's target week. ──
    sel = _fetch_selection()
    if sel:
        sel_week = _iso_week_year(sel.get("week_date"))
        manifest_week = _iso_week_year(manifest.get("date"))
        is_stale = bool(sel_week and manifest_week and sel_week != manifest_week)

        # song_numbers: no auto-source, empty is worse than old → always warn if set.
        sel_song_nums = sel.get("song_numbers") or []
        if status["songs"] is not None and is_stale and sel_song_nums:
            status["songs"]["stale"] = {
                "numbers": sel_song_nums,
                "week_date": sel.get("week_date"),
            }
            print(f"[warn] песни: selection.song_numbers={sel_song_nums} "
                  f"с недели {sel.get('week_date')} (ISO {sel_week}) ≠ "
                  f"неделя сборки (ISO {manifest_week}) — проверь.", file=sys.stderr)

        # video_url: an EMPTY override self-heals via `||` (falls to fresh auto video),
        # so we warn ONLY for a NON-EMPTY manual URL lingering from a previous week —
        # it overrides this week's auto-pulled Dada video.
        sel_video = (sel.get("video_url") or "").strip()
        if is_stale and sel_video:
            status["video_stale"] = {
                "url": sel_video,
                "week_date": sel.get("week_date"),
            }
            print(f"[warn] видео: ручной selection.video_url={sel_video!r} "
                  f"с недели {sel.get('week_date')} — перекрывает свежее авто.",
                  file=sys.stderr)

    # ── write manifest ──
    manifest.setdefault("suggested_songs", [])
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    # ── deploy manifest → VPS (status.deploy reflects THIS rsync) ──
    if os.environ.get("DC_NO_DEPLOY"):
        status["deploy"] = {"ok": None, "value": "skipped (DC_NO_DEPLOY)", "error": None}
    else:
        try:
            _rsync(MANIFEST_PATH, f"{DIST}/manifest.json")
            status["deploy"] = _ok("manifest → dist")
        except Exception as e:
            status["deploy"] = _fail(e)
            print(f"[warn] deploy: {e}", file=sys.stderr)

    status["ts"] = datetime.now(MSK).isoformat(timespec="seconds")

    # ── write + deliver the status file (best-effort, for the form's А channel) ──
    STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n")
    if not os.environ.get("DC_NO_DEPLOY"):
        try:
            _rsync(STATUS_PATH, f"{VPS_DATA}/last_build_status.json")
        except Exception as e:
            print(f"[warn] deploy status-file: {e}", file=sys.stderr)

    # ── report over channels Б (Telegram) + В (macOS) — never crashes the build ──
    try:
        report_build(status)
    except Exception as e:
        print(f"[warn] report_build: {e}", file=sys.stderr)

    print("build status: " + " | ".join(
        f"{k}={'ok' if (status.get(k) or {}).get('ok') else '—' if (status.get(k) or {}).get('ok') is None else 'FAIL'}"
        for k in ("date", "program", "money", "video", "news", "deploy"))
        + f" | songs={status['songs']} | {status['ts']}", file=sys.stderr)


if __name__ == "__main__":
    main()
