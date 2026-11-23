"""Keep the kitchen page on the kitchen Nest Hub (Sam, Nov 22 2026).

A Google Nest Hub can't open a web page on its own, so this runs on Sam's
Mac every few minutes (launchd, see setup.sh) and casts the kitchen page
(/home/kitchen/?k=...) to the Hub with Google's "DashCast" web page receiver.

It is careful not to get in anyone's way:
  - it only casts when the Hub is idle (its photo frame or clock), never over
    music, a video, a call or anything else someone put on it;
  - it leaves the Hub alone overnight (10 PM to 6 AM), so the screen can go
    dark;
  - if the page is already up, it does nothing.
When the Mac is asleep or away from home, nothing happens and the Hub goes
back to its own screen; the page comes back on the next run once the Mac is
home and awake.

The page address carries the house board's key, so it is kept only on the
Mac, in ~/.sisyphus/kitchen.json: {"url": "https://...", "name": "Kitchen display"}.
Prints no addresses or keys.
"""
import datetime
import json
import os
import sys
import time

import pychromecast
from pychromecast.controllers.dashcast import DashCastController

CONFIG = os.path.expanduser("~/.sisyphus/kitchen.json")
DASHCAST_APP = "84912283"
# What the Hub shows when nobody is using it: its photo frame ("Backdrop") or nothing.
IDLE_APPS = {None, "", "E8C28D3C"}
QUIET_FROM, QUIET_TO = 22, 6   # 10 PM to 6 AM, Mac's local time (Central)


def quiet_now(hour):
    return hour >= QUIET_FROM or hour < QUIET_TO


def decide(app_id, hour, force=False):
    """What to do, from what the Hub is running now. Returns 'cast' or a reason to skip."""
    if app_id == DASHCAST_APP:
        return "already showing"
    if quiet_now(hour) and not force:
        return "overnight"
    if app_id not in IDLE_APPS and not force:
        return "in use"
    return "cast"


def main():
    force = "--force" in sys.argv
    cfg = json.load(open(CONFIG))
    name = cfg.get("name", "Kitchen display")
    casts, browser = pychromecast.get_listed_chromecasts(friendly_names=[name], timeout=10)
    try:
        if not casts:
            print("Kitchen display not found on this network (Mac away from home?)")
            return 0
        cast = casts[0]
        cast.wait(timeout=10)
        app = cast.status.app_id if cast.status else None
        what = decide(app, datetime.datetime.now().hour, force)
        print("Kitchen display:", what if what != "cast" else "putting the kitchen page up")
        if what != "cast":
            return 0
        dash = DashCastController()
        cast.register_handler(dash)
        dash.load_url(cfg["url"], force=True)
        time.sleep(8)
        print("Now showing:", "kitchen page" if cast.status and cast.status.app_id == DASHCAST_APP else "something else")
        return 0
    finally:
        browser.stop_discovery()


if __name__ == "__main__":
    sys.exit(main())
