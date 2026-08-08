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
from datetime import datetime
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
    status = {"program": None, "money": None, "video": None, "news": None,
              "urokimeditacii": None, "songs": None, "deploy": None, "ts": None}

    # ── News (Airtable) ──
    try:
        news = fetch_news()
        manifest["news"] = news
        status["news"] = _ok(str(len(news)))
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
                manifest["program"] = prog
                status["program"] = _ok(f"{len(prog)} пунктов")
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
            manifest["raised"], manifest["plan"] = None, None
            status["money"] = _fail("пост финансов не найден")

        # song numbers (regex, no LLM)
        songs = posts.get("songs", [])
        manifest["suggested_songs"] = songs
        try:
            missing = find_new_songs(songs)
        except Exception:
            missing = []
        status["songs"] = {"suggested": songs, "missing": missing}

    # ── Dada video (СВАДХЬЯЯ) ──
    try:
        vid = fetch_dada_video()
        manifest["video_url"] = vid["video_url"]
        status["video"] = _ok(vid["video_url"] or "—")
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
        for k in ("program", "money", "video", "news", "deploy"))
        + f" | songs={status['songs']} | {status['ts']}", file=sys.stderr)


if __name__ == "__main__":
    main()
