"""
Sisyphus - play each comic's walk-on song from the showroom Stream Deck (Sam,
Nov 19 2026: "Before a show we should let comics pick a walk up song and we can
integrate that into the deck").

Comics pick their song on the walk-on page (walkon/?s=...) or in the advance;
the database keeps it (supabase/migrations/20261119230000_walkon_songs.sql).
This runs all day on the office PC (DESKTOP-8QOGQGK), next to Spotify, which
plays the showroom music into the mixer's MUSIC channel. setup.ps1 next to this
file starts it at sign-in.

What the deck does with it (av/companion/build_companion_config.py):
  START SHOW    calls /walkon/load: tonight's people in running order (host,
                feature, headliner) with their songs, starting at the top.
  WALK-ON key   shows who is up next and their song. A tap calls /walkon/play:
                Spotify jumps to that comic's song, from the second they picked,
                and the deck brings the MUSIC fader back up.
                A second tap (or START CLOCK, or a minute going by) fades the
                MUSIC fader out and calls /walkon/stop: once the fade is done,
                Spotify goes back to the playlist it was playing, where it was,
                under the faded fader, so END SHOW brings the house music back
                exactly as before. The key moves on to the next comic.
  THEN key      shows who comes after; a tap skips the one up next (they're
                not here, or the host already came up). It wraps around.
A comic with no song: the tap just brings the house music back up, which is
what the walk-on push did before this.

It tells the deck what to show through Companion custom variables:
  walkon_count   people tonight (0 = nobody: the keys stay blank)
  walkon_name    who is up next, walkon_role (Host, Feature, Headliner)
  walkon_song    their song's title ('' = none picked)
  walkon_then    who comes after them
  walkon_playing 1 while a walk-on song is playing

Spotify: it uses Spotify's own Web API to say "play this song on this PC from
2:10". That needs Spotify Premium and a one-time "Allow" at the PC:
    python walkon.py --connect    (setup.ps1 does this)
opens Spotify's page in the browser; the sign-in and the key it hands back are
kept only in %USERPROFILE%\\.sisyphus\\spotify.json, never in the repo.

    python walkon.py            run until stopped (port 8793, this PC only)
    python walkon.py --once     print tonight's walk-ons and what Spotify finds
"""
import base64
import hashlib
import json
import os
import re
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SUPABASE_URL = "https://idsdwkubqnavkazlteis.supabase.co"
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imlkc2R3a3VicW5hdmthemx0ZWlzIiwicm9sZSI6ImFub24iLCJpYXQiOjE3OTAwOTA2MTMsImV4cCI6MjEwNTY2NjYxM30.EUnNEOHYlNup7nBFvs--pCiyis-NYPiL_TeoiMEjDRQ"  # public anon key, same as staff.js
PORT = 8793
REDIRECT = f"http://127.0.0.1:{PORT}/callback"
SCOPES = "user-read-playback-state user-modify-playback-state"
# Companion listens on the PC's network address only (see av/door-count/door_count.py).
COMPANION_ADDRESSES = ["http://192.168.86.42:8000", "http://127.0.0.1:8000"]
WALKON_KEY = "/api/location/2/0/1/press"   # SHOW page, the WALK-ON key: pressed while playing = fade out
LONGEST = 60          # seconds a walk-on song plays before the helper fades it itself
FADE_WAIT = 3.3       # the deck's music fade is 3 s; Spotify goes back to the playlist after it
REFRESH_EVERY = 120   # seconds between re-reading tonight's picks (a comic can pick at the bar)
STATE_DIR = Path(os.environ.get("USERPROFILE") or Path.home()) / ".sisyphus"
SPOTIFY_FILE = STATE_DIR / "spotify.json"
LOG = STATE_DIR / "walkon.log"
ROLES = {"host": "Host", "feature": "Feature", "headliner": "Headliner"}


def log(line):
    text = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {line}"
    print(text)
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------
# Small pieces with no network, tested in test_walkon.py
# --------------------------------------------------------------------------
_START = re.compile(r"\b(?:start(?:s|ing)?(?:\s+at)?|from|@)\s*:?\s*(\d{1,2}):([0-5]\d)\b", re.I)


def read_typed(text):
    """An older advance answer typed by hand, e.g. "Song: Lacrimosa - Artist: Mozart. START AT: 2:10",
    becomes (search words, start second): ("Lacrimosa Mozart", 130)."""
    text = text or ""
    start = 0
    m = _START.search(text)
    if m:
        start = int(m.group(1)) * 60 + int(m.group(2))
        text = text[:m.start()] + text[m.end():]
    text = re.sub(r"\b(song|artist|title|by)\s*:|\sby\s", " ", text, flags=re.I)
    text = re.sub(r"[\"“”()\[\].,;:!?/\\|]+|\s[-–—]\s|\s+-$", " ", text)
    return " ".join(text.split()), start


def lineup(answer):
    """walkon_tonight()'s answer as the list the deck walks through."""
    out = []
    for p in (answer or {}).get("people") or []:
        song = p.get("song") or {}
        query, start = "", int(song.get("start_sec") or 0)
        if song.get("title"):
            query = song["title"] + (" " + song["artist"] if song.get("artist") else "")
        elif p.get("query"):
            query, start = read_typed(p["query"])
        out.append({"name": p.get("name") or "", "role": ROLES.get(p.get("role"), (p.get("role") or "").title()),
                    "title": song.get("title") or (query and "their pick") or "", "artist": song.get("artist") or "",
                    "start_sec": start, "query": query})
    return out


def keep_place(old, new, pos):
    """Tonight's list re-read: stay on the same comic if they are still on it."""
    if not new:
        return 0
    if old and 0 <= pos < len(old):
        for i, p in enumerate(new):
            if p["name"].lower() == old[pos]["name"].lower():
                return i
    return min(pos, len(new) - 1)


def deck_values(people, pos, playing):
    """The custom variables the WALK-ON and THEN keys read."""
    if not people:
        return {"walkon_count": 0, "walkon_name": "", "walkon_role": "", "walkon_song": "", "walkon_then": "", "walkon_playing": 0}
    now = people[pos % len(people)]
    then = people[(pos + 1) % len(people)] if len(people) > 1 else None
    return {"walkon_count": len(people), "walkon_name": now["name"], "walkon_role": now["role"],
            "walkon_song": now["title"], "walkon_then": then["name"] if then else "", "walkon_playing": 1 if playing else 0}


def search_query(person):
    """Spotify search words: exact title and artist when the comic picked from the list."""
    if person["artist"] and person["title"] and person["title"] != "their pick":
        return f'track:"{person["title"]}" artist:"{person["artist"]}"'
    return person["query"]


def pick_track(items, person):
    """Of Spotify's answers, the one whose title and artist match the pick (not a karaoke or
    cover version); else the first."""
    def norm(s):
        return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()
    title, artist = norm(person["title"]), norm(person["artist"])
    cover = re.compile(r"karaoke|tribute|cover|instrumental|made famous", re.I)
    good = [t for t in items if t and not cover.search(t.get("name", "") + " " + " ".join(a.get("name", "") for a in t.get("artists", [])))]
    for t in good:
        if norm(t.get("name")).startswith(title) and (not artist or any(norm(a.get("name")) == artist for a in t.get("artists", []))):
            return t
    return (good or [t for t in items if t] or [None])[0]


def pick_device(devices, hostname):
    """This PC's Spotify: the device named after the computer, else the active computer."""
    computers = [d for d in devices if (d.get("type") or "").lower() == "computer"]
    for d in computers:
        if (d.get("name") or "").lower() == hostname.lower():
            return d
    return next((d for d in computers if d.get("is_active")), computers[0] if computers else None)


def restore_body(saved):
    """What to send Spotify to go back to the playlist the room was on, where it was."""
    item = (saved or {}).get("item") or {}
    if not item.get("uri"):
        return None
    pos = int(saved.get("progress_ms") or 0)
    ctx = ((saved.get("context") or {}).get("uri")) or ""
    if ctx and not ctx.startswith("spotify:artist:"):
        return {"context_uri": ctx, "offset": {"uri": item["uri"]}, "position_ms": pos}
    return {"uris": [item["uri"]], "position_ms": pos}


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------
def http(url, method="GET", body=None, headers=None, form=None, timeout=15):
    data = None
    hdrs = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode()
    return json.loads(text) if text.strip().startswith(("{", "[")) else text


def tonight():
    return http(f"{SUPABASE_URL}/rest/v1/rpc/walkon_tonight", "POST", body={},
                headers={"apikey": ANON_KEY, "Authorization": "Bearer " + ANON_KEY})


class Spotify:
    """Spotify's Web API for this PC's Spotify app. Signed in once with --connect."""

    def __init__(self):
        self.conf = json.loads(SPOTIFY_FILE.read_text()) if SPOTIFY_FILE.exists() else {}
        self.token, self.until = "", 0

    @property
    def ready(self):
        return bool(self.conf.get("client_id") and self.conf.get("refresh_token"))

    def _save(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        SPOTIFY_FILE.write_text(json.dumps(self.conf))

    def _access(self):
        if time.time() < self.until - 60:
            return self.token
        t = http("https://accounts.spotify.com/api/token", "POST", form={
            "grant_type": "refresh_token", "refresh_token": self.conf["refresh_token"], "client_id": self.conf["client_id"]})
        self.token, self.until = t["access_token"], time.time() + int(t.get("expires_in", 3600))
        if t.get("refresh_token") and t["refresh_token"] != self.conf["refresh_token"]:
            self.conf["refresh_token"] = t["refresh_token"]
            self._save()
        return self.token

    def api(self, path, method="GET", body=None):
        try:
            return http("https://api.spotify.com/v1" + path, method, body=body,
                        headers={"Authorization": "Bearer " + self._access()})
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:300]
            raise RuntimeError(f"Spotify said {e.code} to {method} {path.split('?')[0]}: {detail}") from None

    def find(self, person):
        q = search_query(person)
        if not q:
            return None
        items = (self.api("/search?" + urllib.parse.urlencode({"q": q, "type": "track", "limit": 10, "market": "from_token"}))
                 .get("tracks") or {}).get("items") or []
        if not items and q.startswith("track:"):   # an odd title: try plain words
            items = (self.api("/search?" + urllib.parse.urlencode({"q": person["query"], "type": "track", "limit": 10, "market": "from_token"}))
                     .get("tracks") or {}).get("items") or []
        return pick_track(items, person)

    def device(self):
        return pick_device(self.api("/me/player/devices").get("devices") or [], socket.gethostname())

    def now_playing(self):
        p = self.api("/me/player")
        return p if isinstance(p, dict) else None

    def play(self, device_id, body):
        self.api("/me/player/play?device_id=" + urllib.parse.quote(device_id), "PUT", body)

    def pause(self, device_id):
        self.api("/me/player/pause?device_id=" + urllib.parse.quote(device_id), "PUT")


class Walkon:
    def __init__(self, spotify):
        self.spotify = spotify
        self.people, self.pos, self.playing = [], 0, False
        self.saved, self.device_id, self.started = None, None, 0
        self.tracks = {}            # search words -> Spotify track (or None), found once a night
        self.lock = threading.RLock()

    # the deck
    def tell_deck(self):
        values = deck_values(self.people, self.pos, self.playing)
        for address in COMPANION_ADDRESSES:
            try:
                for name, value in values.items():
                    http(f"{address}/api/custom-variable/{name}/value?value={urllib.parse.quote(str(value))}", "POST", timeout=5)
                return
            except urllib.error.HTTPError as e:
                log(f"Companion refused a variable ({e.code}); are the walkon_* variables on the deck?")
                return
            except OSError:
                continue
        log("Companion did not answer")

    def press_walkon_key(self):
        for address in COMPANION_ADDRESSES:
            try:
                http(address + WALKON_KEY, "POST", timeout=5)
                return
            except OSError:
                continue

    # tonight's list
    def load(self, reset):
        new = lineup(tonight())
        with self.lock:
            self.pos = 0 if reset else keep_place(self.people, new, self.pos)
            self.people = new
            if reset:
                self.tracks = {}
        if self.spotify.ready:
            for p in new:
                self.track_for(p)
        self.tell_deck()
        return new

    def track_for(self, person):
        key = search_query(person)
        if not key:
            return None
        if key not in self.tracks:
            try:
                self.tracks[key] = self.spotify.find(person)
                t = self.tracks[key]
                log(f"{person['role']}: {'found' if t else 'NOT FOUND on Spotify'}"
                    + (f" {t['name']} - {', '.join(a['name'] for a in t['artists'])}" if t else ""))
            except Exception as e:   # no internet, Spotify down: try again next time
                log(f"Spotify search failed: {e}")
                return None
        return self.tracks[key]

    # the keys
    def play(self):
        with self.lock:
            if not self.people or self.playing:
                return "nothing to play" if not self.people else "already playing"
            person = self.people[self.pos % len(self.people)]
            self.playing, self.started = True, time.time()
        self.tell_deck()
        if not self.spotify.ready:
            return "Spotify is not connected; house music only"
        track = self.track_for(person)
        if not track:
            return "no song for them; house music only"
        try:
            dev = self.spotify.device()
            if not dev:
                return "Spotify isn't open on this PC"
            self.device_id = dev["id"]
            self.saved = self.spotify.now_playing()
            self.spotify.play(self.device_id, {"uris": [track["uri"]], "position_ms": person["start_sec"] * 1000})
            log(f"playing the {person['role'].lower()}'s walk-on")
            return "playing"
        except Exception as e:
            self.saved = None
            log(f"could not play: {e}")
            return f"could not play: {e}"

    def stop(self):
        """The deck has started fading the music out: once it is quiet, put the playlist back
        and move on to the next comic."""
        with self.lock:
            if not self.playing:
                return "not playing"
            self.playing = False
            if self.people:
                self.pos = (self.pos + 1) % len(self.people)
            saved, device_id, self.saved = self.saved, self.device_id, None
        self.tell_deck()
        if saved is not None and device_id:
            threading.Thread(target=self._put_back, args=(saved, device_id), daemon=True).start()
        return "stopped"

    def _put_back(self, saved, device_id):
        time.sleep(FADE_WAIT)
        try:
            body = restore_body(saved)
            if body:
                try:
                    self.spotify.play(device_id, body)
                except RuntimeError:
                    if "context_uri" not in body:
                        raise
                    self.spotify.play(device_id, {"uris": [saved["item"]["uri"]], "position_ms": body["position_ms"]})
                if not saved.get("is_playing"):
                    time.sleep(0.5)
                    self.spotify.pause(device_id)
            else:
                self.spotify.pause(device_id)
            log("back to the playlist")
        except Exception as e:
            log(f"could not go back to the playlist: {e}")

    def skip(self):
        with self.lock:
            if self.people and not self.playing:
                self.pos = (self.pos + 1) % len(self.people)
        self.tell_deck()
        return "skipped"

    def status(self):
        return {"people": self.people, "pos": self.pos, "playing": self.playing, "spotify": self.spotify.ready}

    # all day
    def watch(self):
        last = 0
        while True:
            try:
                if self.playing and time.time() - self.started > LONGEST:
                    log("walk-on ran a minute: fading it out")
                    self.press_walkon_key()   # the key's fade-out choice: fader down, then /walkon/stop
                    time.sleep(10)
                    if self.playing:          # the deck didn't answer: at least move on
                        self.stop()
                if not self.playing and time.time() - last > REFRESH_EVERY:
                    last = time.time()
                    self.load(reset=False)
            except Exception as e:
                log(f"refresh failed: {e}")
            time.sleep(5)


# --------------------------------------------------------------------------
# Signing in to Spotify once (PKCE: no secret to keep)
# --------------------------------------------------------------------------
_pending = {}


def connect_url(client_id):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    _pending.update(client_id=client_id, verifier=verifier, state=state)
    return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": client_id, "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES,
        "code_challenge_method": "S256", "code_challenge": challenge, "state": state})


def finish_connect(query, spotify):
    q = urllib.parse.parse_qs(query)
    if q.get("state", [""])[0] != _pending.get("state") or "code" not in q:
        return "That didn't work (" + q.get("error", ["no code"])[0] + "). Run the setup again."
    t = http("https://accounts.spotify.com/api/token", "POST", form={
        "grant_type": "authorization_code", "code": q["code"][0], "redirect_uri": REDIRECT,
        "client_id": _pending["client_id"], "code_verifier": _pending["verifier"]})
    spotify.conf = {"client_id": _pending["client_id"], "refresh_token": t["refresh_token"]}
    spotify._save()
    spotify.until = 0
    log("Spotify connected")
    return "Spotify is connected. You can close this tab."


def serve(walkon, spotify):
    class Handler(BaseHTTPRequestHandler):
        def _answer(self, code, text, kind="text/plain"):
            data = text.encode()
            self.send_response(code)
            self.send_header("Content-Type", kind + "; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path, _, query = self.path.partition("?")
            try:
                if path == "/walkon/load":
                    walkon.load(reset=True)
                    return self._answer(200, f"{len(walkon.people)} tonight")
                if path == "/walkon/play":
                    return self._answer(200, walkon.play())
                if path == "/walkon/stop":
                    return self._answer(200, walkon.stop())
                if path == "/walkon/skip":
                    return self._answer(200, walkon.skip())
                if path == "/walkon/status":
                    return self._answer(200, json.dumps(walkon.status(), indent=1), "application/json")
                if path == "/connect":
                    cid = urllib.parse.parse_qs(query).get("client_id", [spotify.conf.get("client_id", "")])[0]
                    if not cid:
                        return self._answer(400, "Add ?client_id=<the Spotify app's Client ID>")
                    self.send_response(302)
                    self.send_header("Location", connect_url(cid))
                    self.end_headers()
                    return
                if path == "/callback":
                    return self._answer(200, finish_connect(query, spotify))
                return self._answer(404, "no such thing")
            except Exception as e:
                log(f"{path}: {e}")
                return self._answer(500, str(e))

        do_POST = do_GET

        def log_message(self, *args):
            pass

    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


def main():
    spotify = Spotify()
    walkon = Walkon(spotify)
    if "--once" in sys.argv:
        people = lineup(tonight())
        print(f"{len(people)} walk-ons tonight; Spotify {'connected' if spotify.ready else 'NOT connected'}")
        for p in people:
            t = walkon.track_for(p) if spotify.ready else None
            print(f"  {p['role']}: {p['title'] or '(no song)'}" + (f"  ->  Spotify: {t['name']}" if t else ""))
        return
    if "--connect" in sys.argv:
        cid = sys.argv[sys.argv.index("--connect") + 1] if len(sys.argv) > sys.argv.index("--connect") + 1 else spotify.conf.get("client_id")
        if not cid:
            sys.exit("Give the Spotify app's Client ID: walkon.py --connect <client id>")
        threading.Thread(target=serve, args=(walkon, spotify), daemon=True).start()
        webbrowser.open(connect_url(cid))
        print("Spotify's page is open in the browser. Sign in and press Agree.")
        for _ in range(300):
            if spotify.ready and spotify.conf.get("client_id") == cid:
                print("Connected.")
                return
            time.sleep(1)
        sys.exit("No answer from Spotify after 5 minutes.")
    log("walk-on helper started")
    threading.Thread(target=walkon.watch, daemon=True).start()
    serve(walkon, spotify)


if __name__ == "__main__":
    main()
