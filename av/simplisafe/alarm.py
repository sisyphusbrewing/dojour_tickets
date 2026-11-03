"""SimpliSafe for the Companion deck: a tiny local service on the office PC.

    python alarm.py login   one time: opens Edge, Sam signs in to SimpliSafe himself, the token is saved
    python alarm.py serve   runs at startup (Startup shortcut), listens on 127.0.0.1:8791

Deck keys send plain GETs:   /alarm/away   /alarm/home   /alarm/status
There is deliberately no disarm route: the deck sits on the bar (Sam, Nov 3 2026).

The service polls the system once a minute and after every press, and writes the state to the
Companion custom variable alarm_state (OFF, HOME, AWAY, ARMING, ALARM!, ...), which the deck keys show.

SimpliSafe has no public API. This uses simplisafe-python (the library Home Assistant uses), which
signs in the way the SimpliSafe phone app does. If SimpliSafe changes their side it can break; the
keys then show ERROR and nothing else is affected. Sam's password is never stored: only the refresh
token, in %USERPROFILE%\\.simplisafe\\token.json, which this script rotates as SimpliSafe issues new ones.
"""
import asyncio
import json
import os
import pathlib
import sys
import urllib.parse
import urllib.request

from aiohttp import ClientSession, web
from simplipy import API
from simplipy.system import SystemStates
from simplipy.util.auth import get_auth0_code_challenge, get_auth0_code_verifier, get_auth_url

TOKEN = pathlib.Path(os.environ.get("USERPROFILE", pathlib.Path.home())) / ".simplisafe" / "token.json"
PORT = 8791
COMPANION = "http://127.0.0.1:8000"
POLL = 60  # seconds; SimpliSafe rate-limits hard polling

LABELS = {
    SystemStates.OFF: "OFF",
    SystemStates.HOME: "HOME",
    SystemStates.AWAY: "AWAY",
    SystemStates.HOME_COUNT: "ARMING",
    SystemStates.AWAY_COUNT: "ARMING",
    SystemStates.EXIT_DELAY: "ARMING",
    SystemStates.ENTRY_DELAY: "DOOR OPEN",
    SystemStates.ALARM_COUNT: "ALARM!",
    SystemStates.ALARM: "ALARM!",
    SystemStates.TEST: "TEST",
}


def save_token(token):
    TOKEN.parent.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(json.dumps({"refresh_token": token}))


# ---------------------------------------------------------------- login (one time)
async def login():
    from playwright.async_api import async_playwright

    verifier = get_auth0_code_verifier()
    url = get_auth_url(get_auth0_code_challenge(verifier))
    found = asyncio.get_running_loop().create_future()

    def watch(request):
        # SimpliSafe sends the browser back to the phone app's address with ?code=...; catch it here.
        if request.url.startswith("com.simplisafe.mobile://") and not found.done():
            code = urllib.parse.parse_qs(urllib.parse.urlparse(request.url).query).get("code", [None])[0]
            if code:
                found.set_result(code)

    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="msedge", headless=False)
        context = await browser.new_context()
        context.on("request", watch)
        page = await context.new_page()
        await page.goto(url)
        print("Sign in to SimpliSafe in the Edge window (and approve the email/text if it asks).")
        code = await asyncio.wait_for(found, timeout=900)
        await browser.close()

    async with ClientSession() as session:
        api = await API.async_from_auth(code, verifier, session=session)
        save_token(api.refresh_token)
        systems = await api.async_get_systems()
        for system in systems.values():
            print(f"Signed in. System {system.system_id} at {system.address}: {system.state.name}")
    print(f"Token saved to {TOKEN}")


# ---------------------------------------------------------------- service
class Alarm:
    def __init__(self):
        self.api = None
        self.system = None
        self.state = "?"
        self.lock = asyncio.Lock()

    async def connect(self, session):
        token = json.loads(TOKEN.read_text())["refresh_token"]
        self.api = await API.async_from_refresh_token(token, session=session)
        self.api.add_refresh_token_callback(save_token)
        save_token(self.api.refresh_token)
        systems = await self.api.async_get_systems()
        self.system = next(iter(systems.values()))

    def publish(self, label):
        self.state = label
        q = urllib.parse.urlencode({"value": label})
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"{COMPANION}/api/custom-variable/alarm_state/value?{q}", method="POST"), timeout=5)
        except OSError as e:
            print("companion:", e, flush=True)

    async def refresh(self):
        try:
            await self.system.async_update(include_subscription=False, include_settings=False,
                                           include_devices=False, cached=False)
            self.publish(LABELS.get(self.system.state, self.system.state.name))
        except Exception as e:  # noqa: BLE001  keep running; the key shows ERROR
            print("refresh:", repr(e), flush=True)
            self.publish("ERROR")

    async def arm(self, mode):
        async with self.lock:
            try:
                await (self.system.async_set_away() if mode == "away" else self.system.async_set_home())
            except Exception as e:  # noqa: BLE001
                print("arm:", repr(e), flush=True)
                self.publish("ERROR")
                return
            self.publish("ARMING")
        # exit delay: check again shortly so the key flips to AWAY/HOME without waiting a minute
        for delay in (5, 30, 70):
            await asyncio.sleep(delay)
            await self.refresh()


async def serve():
    alarm = Alarm()
    async with ClientSession() as session:
        await alarm.connect(session)
        await alarm.refresh()

        async def handle(request):
            what = request.match_info["what"]
            if what in ("away", "home"):
                asyncio.create_task(alarm.arm(what))
                return web.json_response({"ok": True, "arming": what})
            if what == "status":
                await alarm.refresh()
                return web.json_response({"state": alarm.state})
            return web.json_response({"error": "use /alarm/away, /alarm/home or /alarm/status"}, status=404)

        app = web.Application()
        app.router.add_get("/alarm/{what}", handle)
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", PORT).start()
        print(f"SimpliSafe deck service on http://127.0.0.1:{PORT}/alarm/", flush=True)
        while True:
            await asyncio.sleep(POLL)
            await alarm.refresh()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    asyncio.run(login() if cmd == "login" else serve())
