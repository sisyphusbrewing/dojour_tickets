"""Hubspace helper: lets the Companion deck drive the taproom's Hubspace lights.

Sam's LED string lights in the taproom are Hubspace (Home Depot's smart-home
brand), not Govee (Sam, Nov 20 2026). Hubspace has no local control, so this
talks to Hubspace's cloud through aioafero, the same library the Home
Assistant plugin uses. It runs a tiny web server on 127.0.0.1:8794 that only
the office PC can reach:

    GET /devices
        Lists the lights (and plugs) on the account: name, id, model, and what
        each one supports. No account details.
    GET /set?name=Patio String&on=1&brightness=60&color=FF8800
        Sets one device (or every device with that name). Every parameter but
        name is optional. color is RRGGBB for a color, or a white temperature
        like 2700K. id=<device id> works in place of name.
    GET /all?on=0
        Turns every light and plug off (or on=1 for all on).

The login lives in Windows Credential Locker under "sisyphus-hubspace", never
in this repo. Sam runs set-login.ps1 once to store it. Hubspace hands back a
refresh token that changes over time; this saves the newest one so the login
keeps working without the password. Nothing personal is printed or logged.

    py hubspace.py              run the server (run-hubspace.ps1 does this)
    py hubspace.py --store      set-login.ps1 pipes email and password in here
    py hubspace.py --login      log in once, asking for an emailed code if needed
"""

import asyncio
import logging
import sys

import aiohttp
from aiohttp import web
import keyring

from aioafero import InvalidAuth, OTPRequired
from aioafero.v1 import AferoAuth, AferoBridgeV1

SERVICE = "sisyphus-hubspace"
HOST, PORT = "127.0.0.1", 8794
CHUNK = 1000  # Credential Locker caps each entry, so long tokens are split

log = logging.getLogger("hubspace")


def secret_get(key):
    count = keyring.get_password(SERVICE, f"{key}#parts")
    if count is None:
        return keyring.get_password(SERVICE, key)
    return "".join(keyring.get_password(SERVICE, f"{key}#{i}") or "" for i in range(int(count)))


def secret_set(key, value):
    parts = [value[i:i + CHUNK] for i in range(0, len(value), CHUNK)] or [""]
    for i, part in enumerate(parts):
        keyring.set_password(SERVICE, f"{key}#{i}", part)
    keyring.set_password(SERVICE, f"{key}#parts", str(len(parts)))


async def fresh_refresh_token(session, interactive):
    """Log in with the stored email and password and return a refresh token."""
    email, password = secret_get("email"), secret_get("password")
    if not email or not password:
        raise SystemExit("No Hubspace login stored. Run set-login.ps1 first.")
    auth = AferoAuth.for_login(session, email, password)
    try:
        tokens = await auth.login()
    except OTPRequired:
        if not interactive:
            raise SystemExit("Hubspace wants an emailed code. Run set-login.ps1 again.")
        while True:
            code = input("Hubspace emailed you a code. Type it here: ").strip()
            try:
                tokens = await auth.submit_otp(code)
                break
            except Exception:
                print("That code didn't work. Try again (or check for a newer email).")
    secret_set("refresh_token", tokens.refresh_token)
    return tokens.refresh_token


async def login():
    async with aiohttp.ClientSession() as session:
        try:
            await fresh_refresh_token(session, interactive=True)
        except InvalidAuth:
            raise SystemExit("Hubspace said no to that email/password. Run set-login.ps1 again.")
    print("Logged in. The helper can take it from here.")


def store():
    lines = sys.stdin.read().splitlines()
    if len(lines) < 2 or not lines[0].strip() or not lines[1]:
        raise SystemExit("Need an email and a password.")
    secret_set("email", lines[0].strip())
    secret_set("password", lines[1])


def describe(dev, kind):
    info = dev.device_information
    out = {"name": info.name, "id": dev.id, "kind": kind, "model": info.model,
           "on": dev.on.on if dev.on else None, "available": dev.available}
    if kind == "light":
        out["brightness"] = dev.dimming.brightness if dev.dimming else None
        out["supports"] = {
            "brightness": dev.supports_dimming,
            "color": dev.supports_color,
            "white_temps_k": dev.color_temperature.supported if dev.color_temperature else None,
            "effects": sorted({e for es in dev.effect.effects.values() for e in es}) if dev.effect else None,
        }
    return out


class Helper:
    def __init__(self, bridge):
        self.bridge = bridge

    def devices(self):
        return ([("light", d) for d in self.bridge.lights.items]
                + [("switch", d) for d in self.bridge.switches.items])

    async def apply(self, kind, dev, on, brightness, color):
        if kind == "switch":
            if on is not None:
                await (self.bridge.switches.turn_on if on else self.bridge.switches.turn_off)(dev.id)
            return
        if on is False or brightness == 0:
            await self.bridge.lights.set_state(dev.id, on=False)
            return
        kw = {"on": True} if on or brightness is not None or color else {}
        if brightness is not None:
            kw["brightness"] = brightness
        if color:
            c = color.lstrip("#").upper()
            if c.endswith("K"):
                kw.update(temperature=int(c[:-1]), color_mode="white")
            else:
                kw.update(color=(int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)), color_mode="color")
        if kw:
            await self.bridge.lights.set_state(dev.id, **kw)

    async def handle_devices(self, request):
        return web.json_response([describe(d, k) for k, d in self.devices()])

    async def handle_set(self, request):
        q = request.query
        name, dev_id = q.get("name", "").strip().lower(), q.get("id")
        targets = [(k, d) for k, d in self.devices()
                   if d.id == dev_id or (name and (d.device_information.name or "").lower() == name)]
        if not targets:
            return web.json_response({"error": "no device by that name"}, status=404)
        try:
            on, brightness, color = parse(q)
        except ValueError as err:
            return web.json_response({"error": str(err)}, status=400)
        for k, d in targets:
            await self.apply(k, d, on, brightness, color)
        return web.json_response({"ok": True, "set": [d.device_information.name for _, d in targets]})

    async def handle_all(self, request):
        on = request.query.get("on", "0") == "1"
        for k, d in self.devices():
            await self.apply(k, d, on, None, None)
        return web.json_response({"ok": True, "on": on, "count": len(self.devices())})


def parse(q):
    on = {"1": True, "0": False}.get(q.get("on")) if "on" in q else None
    brightness = None
    if "brightness" in q:
        brightness = int(q["brightness"])
        if not 0 <= brightness <= 100:
            raise ValueError("brightness is 0-100")
    color = q.get("color") or None
    if color:
        c = color.lstrip("#").upper()
        ok = (c.endswith("K") and c[:-1].isdigit()) or (len(c) == 6 and all(ch in "0123456789ABCDEF" for ch in c))
        if not ok:
            raise ValueError("color is RRGGBB or a temperature like 2700K")
    return on, brightness, color


async def keep_token_saved(bridge):
    saved = secret_get("refresh_token")
    while True:
        await asyncio.sleep(60)
        if bridge.refresh_token and bridge.refresh_token != saved:
            secret_set("refresh_token", bridge.refresh_token)
            saved = bridge.refresh_token


async def serve():
    session = aiohttp.ClientSession()
    email = secret_get("email") or ""
    token = secret_get("refresh_token") or await fresh_refresh_token(session, interactive=False)
    try:
        bridge = await AferoBridgeV1.open(email, token, session, polling_interval=30)
    except InvalidAuth:
        token = await fresh_refresh_token(session, interactive=False)
        bridge = await AferoBridgeV1.open(email, token, session, polling_interval=30)
    secret_set("refresh_token", bridge.refresh_token)
    helper = Helper(bridge)
    app = web.Application()
    app.router.add_get("/devices", helper.handle_devices)
    app.router.add_get("/set", helper.handle_set)
    app.router.add_get("/all", helper.handle_all)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, HOST, PORT).start()
    log.warning("Hubspace helper listening on http://%s:%s (%d devices)", HOST, PORT, len(helper.devices()))
    await keep_token_saved(bridge)


if __name__ == "__main__":
    # The library names its loggers after the account email, so keep logger names out.
    logging.basicConfig(level=logging.WARNING, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s")
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg == "--store":
        store()
    elif arg == "--login":
        asyncio.run(login())
    else:
        asyncio.run(serve())
