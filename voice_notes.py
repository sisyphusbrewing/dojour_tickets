"""
Sisyphus - voice notes, Sam's own Pocket-style recorder (Nov 5 2026).

Sam records a conversation, meeting or idea on staff.sisyphusbrewing.com/voice/.
The page uploads the audio in one-minute pieces to the private "voice-notes"
bucket and starts the "Voice notes" action, which runs this:

  1. joins the pieces and transcribes them here on GitHub (faster-whisper,
     free, nothing leaves GitHub but the text),
  2. asks the voice-summary edge function to have Claude write a title,
     summary, decisions and to-dos,
  3. emails the notes, with the full transcript attached, to whoever recorded
     it (the email on their voice_users row; Sam's go to sam@).

The notes and transcript stay on the /voice/ page. The audio is deleted after
KEEP_AUDIO_DAYS. A recording whose phone died mid-way (still "recording" after
two hours) is processed with whatever pieces made it up.

    python voice_notes.py                 process everything waiting
    NOTE_ID=<uuid> python voice_notes.py  redo one note
    DRY_RUN=1 ...                         transcribe and summarize, don't email
    TEST_SPEECH=1 ...                     make a short spoken test meeting (espeak-ng)
                                          and run it through the whole thing
"""
import html
import os
import smtplib
import ssl
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo

import requests

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "https://idsdwkubqnavkazlteis.supabase.co").rstrip("/")
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
SMTP_HOST = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
SMTP_USER = (os.environ.get("SMTP_USER") or "").strip()
SMTP_PASS = (os.environ.get("SMTP_PASS") or "").replace(" ", "").strip()
FROM_EMAIL = (os.environ.get("FROM_EMAIL") or SMTP_USER).strip()
# Each person's notes go to the email on their voice_users row (Sam: sam@,
# Lindsey: her own; Sam, Nov 5 2026). VOICE_NOTES_TO overrides it for testing.
TO_OVERRIDE = [a.strip() for a in (os.environ.get("VOICE_NOTES_TO") or "").split(",") if a.strip()]
FALLBACK_TO = ["sam@sisyphusbrewing.com"]
NOTE_ID = (os.environ.get("NOTE_ID") or "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")
MODEL = os.environ.get("WHISPER_MODEL") or "small.en"
BUCKET = "voice-notes"
PAGE = "https://staff.sisyphusbrewing.com/voice/"
KEEP_AUDIO_DAYS = 30
CHICAGO = ZoneInfo("America/Chicago")
H = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}


# ---------- Supabase ----------

def rows(params):
    r = requests.get(f"{SUPABASE_URL}/rest/v1/voice_notes", headers=H, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def update(note_id, **fields):
    requests.patch(f"{SUPABASE_URL}/rest/v1/voice_notes", params={"id": f"eq.{note_id}"},
                   headers={**H, "Content-Type": "application/json", "Prefer": "return=minimal"},
                   json=fields, timeout=30).raise_for_status()


def list_parts(note_id):
    r = requests.post(f"{SUPABASE_URL}/storage/v1/object/list/{BUCKET}", headers=H,
                      json={"prefix": f"{note_id}/", "limit": 1000, "sortBy": {"column": "name", "order": "asc"}},
                      timeout=30)
    r.raise_for_status()
    # Storage lists names relative to the folder; return full paths.
    return sorted(f"{note_id}/{o['name']}" for o in r.json() if o.get("name") and o.get("id"))


def download(path, dest):
    with requests.get(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{path}", headers=H, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "ab") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)


def delete_audio(note_id):
    names = list_parts(note_id)
    if names:
        requests.delete(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}", headers=H,
                        json={"prefixes": names}, timeout=30).raise_for_status()


# ---------- Audio ----------

def to_wav(parts, ext, workdir):
    """Pieces from one phone recording are one stream cut into chunks, so
    joining the bytes gives a playable file. If that ever fails, decode each
    piece on its own and join the audio instead."""
    wav = os.path.join(workdir, "audio.wav")
    joined = os.path.join(workdir, f"joined.{ext}")
    for p in parts:
        download(p, joined)
    ff = ["ffmpeg", "-loglevel", "error", "-y"]
    if subprocess.run(ff + ["-i", joined, "-ac", "1", "-ar", "16000", wav]).returncode == 0 and os.path.getsize(wav) > 1000:
        return wav
    print("  joined file didn't decode; decoding pieces one by one")
    listing = os.path.join(workdir, "list.txt")
    with open(listing, "w") as lf:
        for i, p in enumerate(parts):
            src = os.path.join(workdir, f"p{i}.{ext}")
            download(p, src)
            out = os.path.join(workdir, f"p{i}.wav")
            if subprocess.run(ff + ["-i", src, "-ac", "1", "-ar", "16000", out]).returncode == 0:
                lf.write(f"file '{out}'\n")
    subprocess.run(ff + ["-f", "concat", "-safe", "0", "-i", listing, "-c", "copy", wav], check=True)
    return wav


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                         capture_output=True, text=True).stdout.strip()
    try:
        return int(float(out))
    except ValueError:
        return 0


_model = None


def transcribe(wav):
    global _model
    # small.en keeps every word (the distil models drop some); the batched
    # pipeline runs ~15x faster than real time on GitHub's 4 cores.
    from faster_whisper import BatchedInferencePipeline, WhisperModel
    if _model is None:
        _model = BatchedInferencePipeline(WhisperModel(MODEL, device="cpu", compute_type="int8", cpu_threads=os.cpu_count() or 4))
    segments, _ = _model.transcribe(wav, batch_size=8, language="en")
    # One paragraph per pause, with a timestamp, so it reads like a conversation.
    paras, cur, start, last_end = [], [], 0.0, 0.0
    for s in segments:
        if cur and (s.start - last_end > 1.5 or s.end - start > 90):
            paras.append((start, " ".join(cur)))
            cur = []
        if not cur:
            start = s.start
        cur.append(s.text.strip())
        last_end = s.end
    if cur:
        paras.append((start, " ".join(cur)))
    return "\n\n".join(f"[{int(t // 3600):d}:{int(t % 3600 // 60):02d}:{int(t % 60):02d}] {txt}" if t >= 3600
                       else f"[{int(t // 60):02d}:{int(t % 60):02d}] {txt}" for t, txt in paras)


# ---------- Claude ----------

def summarize(note_id):
    last = None
    for effort in ("medium", "low"):
        try:
            r = requests.post(f"{SUPABASE_URL}/functions/v1/voice-summary", headers={**H, "Content-Type": "application/json"},
                              json={"id": note_id, "effort": effort}, timeout=300)
            if r.ok:
                return r.json()["summary"]
            last = f"{r.status_code} {r.text[:300]}"
        except requests.RequestException as e:
            last = str(e)
        print(f"  summary try ({effort}) failed: {last}")
        time.sleep(5)
    raise RuntimeError(f"Claude summary failed: {last}")


# ---------- Email ----------

def li(items):
    return "".join(f"<li style='margin:0 0 6px'>{x}</li>" for x in items)


def section(title, body):
    return (f"<h3 style='font:700 13px/1.2 Arial,sans-serif;letter-spacing:.1em;text-transform:uppercase;"
            f"color:#4a6a8a;margin:22px 0 8px'>{title}</h3>{body}")


def email_html(note, s):
    when = datetime.fromisoformat(note["created_at"].replace("Z", "+00:00")).astimezone(CHICAGO)
    mins = max(1, round((note.get("duration_s") or 0) / 60))
    e = html.escape
    parts = [f"<p style='color:#666;margin:0 0 4px'>{when:%A, %B %-d, %-I:%M %p} · {mins} min"
             + (f" · {e(note['label'])}" if note.get("label") else "") + "</p>",
             f"<p style='font-size:16px;margin:0 0 4px'><b>{e(s.get('gist', ''))}</b></p>"]
    if s.get("todos_sam"):
        parts.append(section("Your to-dos", "<ul style='padding-left:20px;margin:0'>" + li(
            e(t["task"]) + (f" <span style='color:#888'>({e(t['when'])})</span>" if t.get("when") else "")
            for t in s["todos_sam"]) + "</ul>"))
    if s.get("todos_others"):
        parts.append(section("Other people's to-dos", "<ul style='padding-left:20px;margin:0'>" + li(
            f"<b>{e(t['who'])}</b>: {e(t['task'])}" + (f" <span style='color:#888'>({e(t['when'])})</span>" if t.get("when") else "")
            for t in s["todos_others"]) + "</ul>"))
    if s.get("decisions"):
        parts.append(section("Decided", "<ul style='padding-left:20px;margin:0'>" + li(e(d) for d in s["decisions"]) + "</ul>"))
    if s.get("key_details"):
        parts.append(section("Worth keeping", "<ul style='padding-left:20px;margin:0'>" + li(e(d) for d in s["key_details"]) + "</ul>"))
    if s.get("summary"):
        parts.append(section("Summary", "".join(f"<p style='margin:0 0 10px'>{e(p)}</p>"
                                                 for p in s["summary"].split("\n\n") if p.strip())))
    parts.append(f"<p style='color:#888;font-size:13px;margin-top:24px'>Full transcript attached. "
                 f"All your notes: <a href='{PAGE}'>{PAGE.replace('https://', '')}</a></p>")
    return ("<div style='font:15px/1.5 Arial,sans-serif;color:#222;max-width:640px'>" + "".join(parts) + "</div>")


def recipients(note):
    if TO_OVERRIDE:
        return TO_OVERRIDE
    if note.get("created_by"):
        found = requests.get(f"{SUPABASE_URL}/rest/v1/voice_users", headers=H, timeout=30,
                             params={"user_id": f"eq.{note['created_by']}", "select": "email"})
        if found.ok and found.json():
            return [found.json()[0]["email"]]
    return FALLBACK_TO


def send(to, subject, body_html, attachment=None):
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = f"Sisyphus Voice Notes <{FROM_EMAIL}>"
    msg["To"] = ", ".join(to)
    msg.attach(MIMEText(body_html, "html"))
    if attachment:
        name, text = attachment
        part = MIMEApplication(text.encode("utf-8"), Name=name)
        part["Content-Disposition"] = f'attachment; filename="{name}"'
        msg.attach(part)
    if DRY_RUN:
        print(f"  DRY RUN: would email {to}: {subject}")
        return
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, to, msg.as_string())


# ---------- Test ----------

TEST_LINES = [
    ("en-us", "Okay, Grace, quick check in before the weekend. How are we on kombucha?"),
    ("en-us+f3", "We have two cases left. I will reorder on Monday so we have it before the Longfellow shows."),
    ("en-us", "Good. Also the crowler quote from Lagersmith should land this week. If it is under forty cents a can, let's do the full pallet."),
    ("en-us+f3", "Got it. Can you send me the new door schedule by Friday? Morgan asked for Saturdays off in December."),
    ("en-us", "Yes, I will send it Thursday night. And let's move the staff meeting to Tuesday at four."),
]


def test_owner():
    """TEST_AS=Lindsey makes the test note hers (pair it with DRY_RUN so she gets no robot email)."""
    name = (os.environ.get("TEST_AS") or "").strip()
    if not name:
        return None
    r = requests.get(f"{SUPABASE_URL}/rest/v1/voice_users", headers=H, timeout=30,
                     params={"name": f"ilike.{name}", "select": "user_id"})
    r.raise_for_status()
    return r.json()[0]["user_id"] if r.json() else None


def make_test_note():
    """A short fake meeting spoken by two robot voices, uploaded like a phone recording."""
    with tempfile.TemporaryDirectory() as tmp:
        listing = os.path.join(tmp, "list.txt")
        with open(listing, "w") as lf:
            for i, (voice, line) in enumerate(TEST_LINES):
                w = os.path.join(tmp, f"{i}.wav")
                subprocess.run(["espeak-ng", "-v", voice, "-s", "150", "-w", w, line], check=True)
                lf.write(f"file '{w}'\n")
        m4a = os.path.join(tmp, "test.m4a")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", listing,
                        "-ac", "1", "-c:a", "aac", "-b:a", "48k", m4a], check=True)
        r = requests.post(f"{SUPABASE_URL}/rest/v1/voice_notes", headers={**H, "Content-Type": "application/json",
                          "Prefer": "return=representation"},
                          json={"label": "Test recording", "ext": "m4a", "status": "recording", "parts": 1,
                                "created_by": test_owner()}, timeout=30)
        r.raise_for_status()
        note = r.json()[0]
        with open(m4a, "rb") as f:
            requests.post(f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{note['id']}/part-0000.m4a",
                          headers={**H, "Content-Type": "audio/mp4"}, data=f.read(), timeout=60).raise_for_status()
        update(note["id"], status="uploaded")
        print(f"Made test note {note['id']}")
        return note["id"]


# ---------- Main ----------

def process(note):
    nid = note["id"]
    print(f"Note {nid} ({note['status']}, {note.get('parts')} pieces)")
    update(nid, status="transcribing", error=None)
    parts = list_parts(nid)
    if not parts:
        raise RuntimeError("No audio was uploaded.")
    with tempfile.TemporaryDirectory() as tmp:
        wav = to_wav(parts, note.get("ext") or "m4a", tmp)
        secs = duration(wav)
        t0 = time.time()
        text = transcribe(wav)
        print(f"  transcribed {secs}s of audio in {time.time() - t0:.0f}s, {len(text.split())} words")
    if not text.strip():
        text = "(No speech was heard in this recording.)"
    update(nid, status="summarizing", transcript=text, duration_s=secs)
    note = {**note, "duration_s": secs}
    s = summarize(nid)
    when = datetime.fromisoformat(note["created_at"].replace("Z", "+00:00")).astimezone(CHICAGO)
    send(recipients(note), f"🎙️ {s.get('title') or 'Voice note'}", email_html(note, s),
         (f"transcript-{when:%Y-%m-%d-%H%M}.txt", f"{s.get('title', '')}\n{when:%A, %B %-d %Y, %-I:%M %p}\n\n{text}\n"))
    update(nid, status="done", **({} if DRY_RUN else {"emailed_at": datetime.now(timezone.utc).isoformat()}))


def main():
    if os.environ.get("TEST_SPEECH", "").strip().lower() in ("1", "true", "yes"):
        todo = rows({"id": f"eq.{make_test_note()}", "select": "*"})
    elif NOTE_ID:
        todo = rows({"id": f"eq.{NOTE_ID}", "select": "*"})
    else:
        stale = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        todo = rows({"select": "*", "order": "created_at",
                     "or": f"(status.eq.uploaded,and(status.eq.recording,parts.gt.0,created_at.lt.{stale}),"
                           f"and(status.in.(transcribing,summarizing),created_at.lt.{stale}))"})
    print(f"{len(todo)} note(s) to process")
    failed = 0
    for note in todo:
        try:
            process(note)
        except Exception as ex:
            failed += 1
            traceback.print_exc()
            update(note["id"], status="error", error=str(ex)[:500])
            try:
                send(recipients(note), "🎙️ A voice note didn't go through",
                     f"<p style='font:15px Arial'>The recording from "
                     f"{datetime.fromisoformat(note['created_at'].replace('Z', '+00:00')).astimezone(CHICAGO):%a %b %-d, %-I:%M %p}"
                     f" hit a snag: {html.escape(str(ex)[:300])}</p><p style='font:15px Arial'>The audio is still saved. "
                     f"Tap <b>Try again</b> on it at <a href='{PAGE}'>{PAGE}</a>.</p>")
            except Exception:
                traceback.print_exc()

    # Audio is only kept a while; the notes and transcript stay.
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_AUDIO_DAYS)).isoformat()
    for old in rows({"select": "id", "status": "eq.done", "audio_deleted_at": "is.null", "created_at": f"lt.{cutoff}"}):
        delete_audio(old["id"])
        update(old["id"], audio_deleted_at=datetime.now(timezone.utc).isoformat())
        print(f"Deleted audio for {old['id']}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
