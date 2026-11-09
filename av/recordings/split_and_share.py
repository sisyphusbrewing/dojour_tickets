"""
Sisyphus - cut each night's show recording into one clip per comic and put
it on Google Drive (Sam, Nov 4 2026).

Runs on the office PC (DESKTOP-8QOGQGK) every morning at 4 AM from Task
Scheduler (setup.ps1 makes the task). For every OBS recording it hasn't
handled yet:

1. Finds the show it belongs to (public.show_nights) and the stage timer
   presses during it (public.stage_timer_events): START when a comic goes
   up, STOP CLOCK when they're off.
2. If nobody pressed START, finds the sets from the audio instead: it
   transcribes the recording (faster-whisper) and splits at the host's
   intros ("give it up for ... everybody"), naming each clip after the comic
   the host names. Only if that finds nothing does the whole show go up as
   "unsorted" for booking@ to trim.
3. Cuts one clip per set with ffmpeg (no re-encode, 15 s padding each side).
   The longest set is the headliner.
4. Checks the picture 5 minutes in: nearly black, or not looking like the
   stage (%USERPROFILE%\\.sisyphus\\stage-reference.png), gets a CAMERA note
   so booking@ is told and the headliner isn't sent a black video.
5. Uploads the full show and every clip with rclone to
   gdrive:Sisyphus Recordings/<date> <show> <time>/, makes a view-only link,
   and adds a row to public.recordings. recording_mail.py (GitHub Actions,
   9 AM) emails the headliner their link.
6. Deletes Drive recordings older than 60 days and local recordings 7 days
   after they were uploaded.

Settings live in %USERPROFILE%\\.sisyphus\\recordings.env (never in the repo):
    RECORDER_PASSWORD=...      password of the staff login "recorder"
    OBS_DIR=C:\\Users\\Sam\\Videos  (where OBS saves recordings)

    python split_and_share.py            do it
    python split_and_share.py --dry-run  print what it would cut and upload
"""
import difflib
import glob
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
STAGE_REF = STATE_DIR / "stage-reference.png"  # a good stage frame, 320x180 gray
COMICS_FILE = STATE_DIR / "comics.txt"          # comics who play here, one per line, to fix Whisper's spelling
OUT_DIR = HOME / "Videos" / "Sisyphus clips"
VIDEO = (".mkv", ".mp4", ".mov")
DRY = "--dry-run" in sys.argv

# Host intros: "please give a warm welcome to the very funny Mike Lester, everybody!"
INTRO = re.compile(r"welcome|give it up|make (it|some|a lot of) (loud|noise)|make it loud|round of applause|"
                   r"hands together|next comic|keep it loud for your", re.I)
NOT_INTRO = re.compile(r"comedy (debut|review)|one more time|everyone we|friends we", re.I)
OUTRO = re.compile(r"one more time for|keep it (going|loud) for|good ?night|thank(s| you)( all| guys)?( so much)? for "
                   r"coming", re.I)
EVERYBODY = re.compile(r"everybody|everyone|y'all", re.I)
NAME_BEFORE = re.compile(r"([A-Z][\w'-]+(?: [A-Z][\w'-]+){1,2}),? (?:everybody|everyone)")
NAME_AFTER = re.compile(r"(?:for|to|welcome) ([A-Z][\w'-]+(?: [A-Z][\w'-]+){1,2})")
SELF_NAME = re.compile(r"(?i:my name is|I'm) ([A-Z][\w'-]+(?: [A-Z][\w'-]+)?)")
OUTRO_NAME = re.compile(r"(?:one more time for|keep it (?:going|loud) for|[Cc]ome on,?) ([A-Z][\w'-]+(?: [A-Z][\w'-]+){1,2})")
AUDIO_MIN_SET = 150    # s; anything shorter between intros is the host's bit, folded into the set before
BREAK = 240            # s without speech = the show's over (or it's the break between shows)
MUSIC = 120            # s; Whisper writes walk-in music as one endless "lyric" line, real speech lines are short
ONE_SET_MAX = 90 * 60  # a file with no intros shorter than this is one set (OBS was restarted at the walk-on)
CAMERA_DARK = 15       # mean brightness (0-255) 5 min in; a lit stage is ~65, a dead camera ~0
CAMERA_SIMILAR = 0.2   # SSIM against the stage reference; good nights 0.34-0.74, Nov 8 (aimed at a table) 0.002


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


def transcribe(src):
    """[{start, end, text}] in seconds from the file start. GPU if the CUDA wheels are there, else CPU."""
    for d in glob.glob(str(Path(sys.prefix) / "Lib/site-packages/nvidia/*/bin")):
        os.add_dll_directory(d)
        os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
    import numpy as np
    from faster_whisper import WhisperModel
    try:
        model = WhisperModel("small", device="cuda", compute_type="float16")
    except Exception:
        model = WhisperModel("small", device="cpu", compute_type="int8")
    # ffmpeg decodes (the pip PyAV build doesn't match faster-whisper's decode_audio).
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le",
                          "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0
    segments, _ = model.transcribe(audio, language="en", beam_size=1, vad_filter=True,
                                   condition_on_previous_text=False)
    return [{"start": round(s.start, 1), "end": round(s.end, 1), "text": s.text.strip()} for s in segments]


def intro_name(window, known):
    m = NAME_BEFORE.search(window) or NAME_AFTER.search(window)
    return fix_name(m.group(1), known) if m else None


def fix_name(name, known):
    """Whisper spells comics creatively ("Kellyn", "Ahmaq Alaf", "Med"): snap to a known name when close."""
    full = {k.lower(): k for k in known}
    first = {k.split()[0].lower(): k for k in known if " " in k}
    pool = full if " " in name else {**first, **full}
    hit = difflib.get_close_matches(name.lower(), list(pool), n=1, cutoff=0.6)
    return pool[hit[0]] if hit else name


def find_name(segs, a, b, known):
    """No name in the intro: comics say it in the first minute and a half or in the sign-off
    ("thank you, I'm Kellen Schneider"), and the host says it on the way out ("one more time for ...")."""
    for lo, hi, pat in ((a, a + 90, SELF_NAME), (b - 90, b + 5, SELF_NAME), (b - 60, b + 30, OUTRO_NAME)):
        for s in segs:
            if lo <= s["start"] <= hi and pat.search(s["text"]):
                return fix_name(pat.search(s["text"]).group(1), known)
    return None


def audio_sets(segs, total, known=()):
    """Set boundaries from host intros: [(start_s, end_s, name or None)].

    A set starts at an intro line that names someone "... everybody" (within the
    next two lines) and runs to the next intro. Intros less than a minute and a
    half apart are one walk-on (the host's bits before the real intro), so the
    last of them wins, and anything under 2.5 minutes is folded into the set
    before. The stretch before the first intro is the host's opener. The last
    set ends at the final "one more time for ..." / "thanks for coming", and any
    set ends early at 4 minutes without speech (the break between two shows).
    A file with no intros at all is one set (OBS was restarted at the walk-on).
    """
    if not segs:
        return []
    intros = []
    for i, s in enumerate(segs):
        window = " ".join(x["text"] for x in segs[i:i + 3])
        every = EVERYBODY.search(window)
        if INTRO.search(s["text"]) and every and not NOT_INTRO.search(window[:every.end()]):
            if intros and s["start"] - intros[-1][0] < 90:
                intros.pop()
            intros.append((s["start"], intro_name(window, known)))
    if not intros and total > ONE_SET_MAX:
        return []
    first = segs[0]["start"]
    starts = [(first, None)] + intros if not intros or intros[0][0] - first >= MIN_SET.total_seconds() else intros
    raw = []
    for k, (a, name) in enumerate(starts):
        if k + 1 < len(starts):
            b = starts[k + 1][0]
        else:
            ends = [s["end"] for s in segs if s["start"] > a + MIN_SET.total_seconds() and OUTRO.search(s["text"])]
            b = min(ends[-1] + 5, total) if ends else total
        after = [s for s in segs if a + MIN_SET.total_seconds() <= s["start"] < b]
        for prev, nxt in zip(after, after[1:]):
            if nxt["start"] - prev["end"] >= BREAK or nxt["end"] - nxt["start"] >= MUSIC:
                b = prev["end"] + 5
                break
        if b - a < AUDIO_MIN_SET:
            if raw and raw[-1][1] == a:  # the host's bit right after a set: keep it with that set
                raw[-1][1] = b
            continue
        raw.append([a, b, name])
    return [(a, b, name or find_name(segs, a, b, known)) for a, b, name in raw if b - a >= MIN_SET.total_seconds()]


def known_names(h, title):
    """The headliner (show title), %USERPROFILE%\\.sisyphus\\comics.txt (one comic per line) and every comic
    we've scored, for fixing Whisper's spelling."""
    names = {title}
    if COMICS_FILE.exists():
        names |= {line.strip() for line in COMICS_FILE.read_text(encoding="utf-8").splitlines() if line.strip()}
    try:
        names |= {r["comedian"] for r in rest(h, "comic_scores", {"select": "comedian"}) if r.get("comedian")}
    except Exception:
        pass
    return sorted(names)


def camera_check(src, dur):
    """None if the picture looks like the stage 5 minutes in, else a CAMERA note."""
    at = min(300.0, dur.total_seconds() / 2)
    frame = STATE_DIR / "check-frame.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(at), "-i", str(src), "-frames:v", "1",
                    "-vf", "scale=320:180,format=gray", str(frame)], check=True)
    y = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(frame), "-vf",
                        "signalstats,metadata=print:key=lavfi.signalstats.YAVG", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    m = re.search(r"YAVG=([\d.]+)", y)
    if m and float(m.group(1)) < CAMERA_DARK:
        return f"CAMERA: the picture is nearly black {at / 60:.0f} min in (brightness {float(m.group(1)):.0f}/255)"
    if STAGE_REF.exists():
        s = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(frame), "-i", str(STAGE_REF), "-lavfi", "ssim",
                            "-f", "null", "-"], capture_output=True, text=True).stderr
        m = re.search(r"All:([\d.]+)", s)
        if m and float(m.group(1)) < CAMERA_SIMILAR:
            return f"CAMERA: the picture {at / 60:.0f} min in doesn't look like the stage (similarity {float(m.group(1)):.2f})"
    return None


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
    if not row.get("note"):
        row.pop("note", None)
    r = requests.post(f"{SUPABASE_URL}/rest/v1/recordings", params={"on_conflict": "starts_at,part"},
                      headers={**h, "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates"},
                      json=row, timeout=30)
    if r.status_code == 400 and "note" in row and "note" in r.text:  # recordings.note migration not applied yet
        print(f"  (no recordings.note column; note was: {row.pop('note')})")
        return save_row(h, row)
    r.raise_for_status()


def handle(h, src):
    rec_start = recording_start(src)
    dur = duration(src)
    rec_end = rec_start + dur
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
    out = OUT_DIR / folder
    out.mkdir(parents=True, exist_ok=True)
    events = rest(h, "stage_timer_events", {"select": "kind,at", "order": "at",
                                            "at": [f"gte.{rec_start.isoformat()}", f"lte.{rec_end.isoformat()}"]})
    sets = [(a, b, None) for a, b in find_sets(events, rec_start, rec_end)]
    notes = []
    if not sets:
        print(f"{src.name}: no stage timer presses, finding the sets from the audio")
        segs = transcribe(src)
        (out / f"{src.stem} transcript.json").write_text(json.dumps(segs, indent=0))
        found = audio_sets(segs, dur.total_seconds(), known_names(h, show["title"]))
        sets = [(max(rec_start + timedelta(seconds=a) - PAD, rec_start), min(rec_start + timedelta(seconds=b) + PAD, rec_end), n)
                for a, b, n in found]
        if sets:
            notes.append("Sets found from the host's intros (nobody pressed the stage timer); names are from the audio.")
    camera = camera_check(src, dur)
    if camera:
        notes.append(camera)
    print(f"{src.name}: {show['title']} {local:%a %b %d %I:%M %p}, {len(sets)} set(s)" + "".join(f"\n  {n}" for n in notes))

    full = out / f"{folder} - full show.mp4"
    cut(src, rec_start, rec_start, rec_end, full)
    parts = [("full" if sets else "unsorted", rec_start, rec_end, full, " ".join(notes) or None)]
    if sets:
        longest = max(range(len(sets)), key=lambda i: sets[i][1] - sets[i][0])
        for i, (a, b, name) in enumerate(sets):
            part = "headliner" if i == longest else f"set {i + 1}"
            label = slug(name) if name else part
            dest = out / f"{folder} - {label}.mp4"
            cut(src, rec_start, a, b, dest)
            parts.append((part, a, b, dest, None))
    for part, a, b, local_file, note in parts:
        path, link = upload(local_file, folder)
        save_row(h, {"show_title": show["title"], "starts_at": show["starts_at"], "part": part,
                     "clip_start": a.isoformat(), "clip_end": b.isoformat(), "drive_path": path, "link": link,
                     "note": note})
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
