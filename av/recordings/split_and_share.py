"""
Sisyphus - cut each night's show recording into one clip per comic and put
it on Google Drive (Sam, Nov 4 2026).

Runs on the office PC (DESKTOP-8QOGQGK) every morning at 4 AM from Task
Scheduler (setup.ps1 makes the task). For every OBS recording it hasn't
handled yet:

1. Finds the show it belongs to (public.show_nights) and the stage timer
   presses during it (public.stage_timer_events): START when a comic goes
   up, STOP CLOCK when they're off.
2. Cuts one clip per set with ffmpeg (no re-encode, 15 s padding each side).
   The longest set is the headliner. A START with no STOP runs to the next
   START or the end of the recording. If nobody pressed START at all, the
   whole show goes up as "unsorted" and booking@ hears about it.
3. Uploads the full show and every clip with rclone to
   gdrive:Sisyphus Recordings/<date> <show> <time>/, makes a view-only link,
   and adds a row to public.recordings. recording_mail.py (GitHub Actions,
   9 AM) emails the headliner their link.
4. Deletes Drive recordings older than 60 days and local recordings 7 days
   after they were uploaded.

Settings live in %USERPROFILE%\\.sisyphus\\recordings.env (never in the repo):
    RECORDER_PASSWORD=...      password of the staff login "recorder"
    OBS_DIR=C:\\Users\\Sam\\Videos  (where OBS saves recordings)

    python split_and_share.py            do it
    python split_and_share.py --dry-run  print what it would cut and upload
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

SUPABASE_URL = "https://idsdwkubqnavkazlteis.supabase.co"
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlkc2R3a3VicW5hdmthemx0ZWlzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwOTA2MTMsImV4cCI6MjEwNTY2NjYxM30.EUnNEOHYlNup7nBFvs--pCiyis-NYPiL_TeoiMEjDRQ"  # public anon key, same as staff.js
LOGIN = "recorder@sisyphusbrewing.com"
REMOTE = "gdrive:Sisyphus Recordings"
CHICAGO = ZoneInfo("America/Chicago")
PAD = timedelta(seconds=15)
MIN_SET = timedelta(seconds=60)       # shorter than this was a mis-press
KEEP_DRIVE_DAYS = 60
KEEP_LOCAL_DAYS = 7
HOME = Path(os.environ.get("USERPROFILE") or Path.home())
STATE_DIR = HOME / ".sisyphus"
DONE_FILE = STATE_DIR / "recordings-done.json"
OUT_DIR = HOME / "Videos" / "Sisyphus clips"
VIDEO = (".mkv", ".mp4", ".mov")
DRY = "--dry-run" in sys.argv


def load_env():
    env = STATE_DIR / "recordings.env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def sign_in():
    r = requests.post(f"{SUPABASE_URL}/auth/v1/token?grant_type=password",
                      headers={"apikey": ANON_KEY, "Content-Type": "application/json"},
                      json={"email": LOGIN, "password": os.environ["RECORDER_PASSWORD"]}, timeout=30)
    r.raise_for_status()
    return {"apikey": ANON_KEY, "Authorization": "Bearer " + r.json()["access_token"]}


def rest(h, table, params):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=h, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def recording_start(path):
    """OBS names files by their start time: 2026-11-06 19-02-11.mkv (local time)."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[ _](\d{2})-(\d{2})-(\d{2})", path.stem)
    if m:
        return datetime(*map(int, m.groups()), tzinfo=CHICAGO)
    return datetime.fromtimestamp(path.stat().st_ctime, CHICAGO)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout.strip()
    return timedelta(seconds=float(out))


def find_sets(events, rec_start, rec_end):
    """Pairs each START with the STOP (or next START) after it."""
    sets, current = [], None
    for e in events:
        at = ts(e["at"])
        if e["kind"] == "start":
            if current and at - current < MIN_SET:
                continue  # pressed again to pick another length: same set
            if current:
                sets.append((current, at))
            current = at
        elif current:
            sets.append((current, at))
            current = None
    if current:
        sets.append((current, rec_end))
    return [(max(a - PAD, rec_start), min(b + PAD, rec_end)) for a, b in sets if b - a >= MIN_SET]


def slug(text):
    return re.sub(r"[^A-Za-z0-9 ,'&()-]+", "", text).strip()[:80]


def cut(src, rec_start, a, b, dest):
    if DRY:
        print(f"  cut {a - rec_start} to {b - rec_start} -> {dest.name}")
        return
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str((a - rec_start).total_seconds()), "-i", str(src),
                    "-t", str((b - a).total_seconds()), "-c", "copy", "-movflags", "+faststart", str(dest)], check=True)


def upload(local, folder):
    path = f"{REMOTE}/{folder}/{local.name}"
    if DRY:
        print(f"  upload {local.name} -> {path}")
        return path, None
    subprocess.run(["rclone", "copyto", str(local), path], check=True)
    link = subprocess.run(["rclone", "link", path], capture_output=True, text=True, check=True).stdout.strip()
    return path, link


def save_row(h, row):
    if DRY:
        return
    r = requests.post(f"{SUPABASE_URL}/rest/v1/recordings", params={"on_conflict": "starts_at,part"},
                      headers={**h, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"},
                      json=row, timeout=30)
    r.raise_for_status()


def handle(h, src):
    rec_start = recording_start(src)
    rec_end = rec_start + duration(src)
    r = requests.post(f"{SUPABASE_URL}/rest/v1/rpc/recording_shows", headers=h, timeout=30,
                      json={"p_from": (rec_start - timedelta(hours=2)).isoformat(), "p_to": rec_end.isoformat()})
    r.raise_for_status()
    shows = r.json()
    if not shows:
        print(f"{src.name}: no show on the calendar then, skipping")
        return True
    # The show whose start is closest to when the recording began.
    show = min(shows, key=lambda s: abs(ts(s["starts_at"]) - rec_start))
    starts = ts(show["starts_at"])
    local = starts.astimezone(CHICAGO)
    hour = f"{local.hour % 12 or 12}{'' if not local.minute else f'.{local.minute:02d}'}{'PM' if local.hour >= 12 else 'AM'}"
    folder = slug(f"{local:%Y-%m-%d} {show['title']} {hour}")
    events = rest(h, "stage_timer_events", {"select": "kind,at", "order": "at",
                                            "at": [f"gte.{rec_start.isoformat()}", f"lte.{rec_end.isoformat()}"]})
    sets = find_sets(events, rec_start, rec_end)
    print(f"{src.name}: {show['title']} {local:%a %b %d %I:%M %p}, {len(sets)} set(s)")
    out = OUT_DIR / folder
    out.mkdir(parents=True, exist_ok=True)

    full = out / f"{folder} - full show.mp4"
    cut(src, rec_start, rec_start, rec_end, full)
    parts = [("full" if sets else "unsorted", rec_start, rec_end, full)]
    if sets:
        longest = max(range(len(sets)), key=lambda i: sets[i][1] - sets[i][0])
        for i, (a, b) in enumerate(sets):
            name = "headliner" if i == longest else f"set {i + 1}"
            dest = out / f"{folder} - {name}.mp4"
            cut(src, rec_start, a, b, dest)
            parts.append((name, a, b, dest))
    for name, a, b, local_file in parts:
        path, link = upload(local_file, folder)
        save_row(h, {"show_title": show["title"], "starts_at": show["starts_at"], "part": name,
                     "clip_start": a.isoformat(), "clip_end": b.isoformat(), "drive_path": path, "link": link})
    return True


def cleanup(done):
    if DRY:
        return
    subprocess.run(["rclone", "delete", REMOTE, "--min-age", f"{KEEP_DRIVE_DAYS}d"], check=False)
    subprocess.run(["rclone", "rmdirs", REMOTE, "--leave-root"], check=False)
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_LOCAL_DAYS)
    for name, when in list(done.items()):
        if ts(when) < cutoff:
            for p in [Path(os.environ["OBS_DIR"]) / name]:
                if p.exists():
                    p.unlink()
    for folder in OUT_DIR.glob("*"):
        if folder.is_dir() and datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc) < cutoff:
            for f in folder.iterdir():
                f.unlink()
            folder.rmdir()


def main():
    load_env()
    STATE_DIR.mkdir(exist_ok=True)
    done = json.loads(DONE_FILE.read_text()) if DONE_FILE.exists() else {}
    h = sign_in()
    obs = Path(os.environ.get("OBS_DIR") or HOME / "Videos")
    # Skip a file OBS may still be writing (changed in the last 10 minutes).
    fresh = datetime.now().timestamp() - 600
    for src in sorted(p for p in obs.iterdir() if p.suffix.lower() in VIDEO):
        if src.name in done or src.stat().st_mtime > fresh:
            continue
        try:
            if handle(h, src) and not DRY:
                done[src.name] = datetime.now(timezone.utc).isoformat()
                DONE_FILE.write_text(json.dumps(done, indent=1))
        except Exception as ex:  # one bad file must not stop the rest
            print(f"{src.name}: FAILED {ex}")
    cleanup(done)


if __name__ == "__main__":
    main()
