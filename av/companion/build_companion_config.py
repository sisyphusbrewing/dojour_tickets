#!/usr/bin/env python3
"""Build the Sisyphus showroom Stream Deck + config for Bitfocus Companion.

Edit the PAGES section below, run this script, then import the file it writes
(sisyphus-deck.companionconfig) on Companion's Import / Export tab.

    python3 build_companion_config.py

The file is written in Companion's older "version 12" button format on purpose:
Companion upgrades it to its current format on import, so this script does not
have to track Companion's newer, much more verbose button layout.

Stream Deck + grid in Companion (4 columns):
    row 0, row 1  the 8 keys
    row 2         the touch strip, one segment above each knob; it is the only
                  screen the knobs have, so it labels them. Tap = press actions.
                  A sideways swipe changes page (Surfaces settings can turn that off).
    row 3         the 4 knobs (turn = rotate actions, push = press actions; no screen)
"""

import json
import pathlib

OUT = pathlib.Path(__file__).with_name("sisyphus-deck.companionconfig")

# Connections the buttons use. On import, map XAIR to your existing X-Air
# connection; let Companion create HTTP as a new connection.
XAIR = "xair"
HTTP = "http"
OBS = "obs"
# Hallway Govee bulbs (R14C0 Smart Edison, no LAN Control), driven through Govee's cloud
# API. The API key is not in this file: it lives in a Companion custom variable named
# govee_key (Variables > Custom Variables), which the request header reads.
GOVEE_URL = "https://openapi.api.govee.com/router/api/v1/device/control"
HALL_BULBS = {
    "Hallway 1": "20:48:B0:A6:04:30:E2:FC",
    "Hallway 2": "E0:49:B0:A6:04:30:C2:68",
    "Middle hallway": "02:AF:B0:A6:04:33:26:CC",
}
# Sam's pre-show look, read off the bulbs Oct 19 2026: (brightness %, RGB colour or white in K)
HALL_PRESHOW = {
    "Hallway 1": (100, {"rgb": 0x0000FF}),
    "Hallway 2": (11, {"kelvin": 2700}),
    "Middle hallway": (47, {"rgb": 0xFF8000}),
}
INTERNAL = "internal"  # Companion's own actions; not a connection, never exported
CONNECTIONS = {
    XAIR: {"label": "xair", "moduleId": "behringer-xair", "lastUpgradeIndex": 5},
    HTTP: {"label": "http", "moduleId": "generic-http", "lastUpgradeIndex": 3},
    OBS: {"label": "obs", "moduleId": "obs-studio", "lastUpgradeIndex": 5},
}

WHITE = 0xFFFFFF
BLACK = 0x000000
RED = 0xC00000
DARK = 0x202020
MENU_BLUE = 0x1E4C7A
TIMER_GREEN = 0x1F5F2E

SUPABASE = "https://idsdwkubqnavkazlteis.supabase.co"
SUPABASE_KEY = "sb_publishable_c77Jm5yL_nrOJmxxNe-_pg_mkvDHpJb"

# Prints today's taproom menu on the office printer (menu/print-menu.ps1, fetched fresh each press)
PRINT_MENU_COMMAND = (
    'powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([scriptblock]::Create('
    "(New-Object Net.WebClient).DownloadString("
    "'https://sisyphusbrewing.github.io/dojour_tickets/menu/print-menu.ps1')))\""
)

# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

_ids = 0


def _next_id(prefix):
    global _ids
    _ids += 1
    return f"{prefix}{_ids:04d}"


def _opts(options):
    # Companion stores every option as {value, isExpression}
    return {k: {"value": v, "isExpression": False} for k, v in options.items()}


def action(connection, definition, **options):
    act = {
        "type": "action",
        "id": _next_id("a"),
        "connectionId": connection,
        "definitionId": definition,
        "options": _opts(options),
    }
    if connection in CONNECTIONS:  # Companion's internal actions carry no upgrade index
        act["upgradeIndex"] = CONNECTIONS[connection]["lastUpgradeIndex"]
    return act


def feedback(connection, definition, style=None, **options):
    """`style` for on/off feedbacks; leave it out for ones that set colors themselves."""
    fb = {
        "type": "feedback",
        "id": _next_id("f"),
        "connectionId": connection,
        "definitionId": definition,
        "options": _opts(options),
        "isInverted": False,
        "upgradeIndex": CONNECTIONS[connection]["lastUpgradeIndex"],
    }
    if style is not None:
        fb["style"] = style
    return fb


def button(text, *, press=(), release=(), turn_left=(), turn_right=(), feedbacks=(),
           color=WHITE, bgcolor=BLACK, size="auto"):
    rotary = bool(turn_left or turn_right)
    action_sets = {"down": list(press), "up": list(release)}
    if rotary:
        action_sets["rotate_left"] = list(turn_left)
        action_sets["rotate_right"] = list(turn_right)
    return {
        "type": "button",
        "options": {"stepProgression": "auto", "rotaryActions": rotary},
        "style": {
            "text": text,
            "textExpression": False,
            "size": size,
            "alignment": "center:center",
            "pngalignment": "center:center",
            "color": color,
            "bgcolor": bgcolor,
            "show_topbar": "default",
            "png64": None,
        },
        "feedbacks": list(feedbacks),
        "steps": {"0": {"action_sets": action_sets, "options": {"runWhileHeld": []}}},
        "localVariables": [],
    }


LIVE_GREEN = 0x1E5E2A
SHOW_COLOR = 0x5A2A82
BAR_COLOR = MENU_BLUE
TIMER_COLOR = TIMER_GREEN


def muted(text):
    """Style for an on/off feedback: red, and the text says it is muted."""
    return {"bgcolor": RED, "color": WHITE, "text": text}


def volume_knob(fader_action, mute_action, strip=None, mute_strip=None, step=2):
    """A knob: turn for volume (`step` percent per click), push to mute.

    The knobs have no screen; the touch strip segment above each one is its label
    (see strip_label). `strip` picks a numbered strip (e.g. {"type": "/ch/", "num": 1}).
    """
    fade = dict(duration=0, faderLim=True, **(strip or {}))  # never push past 0 dB
    return button(
        "",
        turn_right=[action(XAIR, fader_action, ticks=str(step), **fade)],
        turn_left=[action(XAIR, fader_action, ticks=str(-step), **fade)],
        press=[action(XAIR, mute_action, mute="2", **(mute_strip or {}))],
    )


def strip_label(name, level_var, mute_action, mute_feedback, mute_strip=None, feedback_strip=None):
    """The touch strip segment above a knob: what it controls and its level; tap mutes.

    Turns red and says MUTED while muted.
    """
    return button(
        f"{name}\\n$(xair:{level_var}) dB\\nturn knob",
        press=[action(XAIR, mute_action, mute="2", **(mute_strip or {}))],
        feedbacks=[feedback(XAIR, mute_feedback, muted(f"{name}\\nMUTED\\ntap to unmute"),
                            state="1", **(feedback_strip or {}))],
        bgcolor=DARK,
        size="14",
    )


def mute_key(name, mute_action, mute_feedback, mute_strip=None, feedback_strip=None):
    """A key that mutes/unmutes; green ON, red MUTED."""
    return button(
        f"{name}\\nON\\npress to mute",
        press=[action(XAIR, mute_action, mute="2", **(mute_strip or {}))],
        feedbacks=[feedback(XAIR, mute_feedback, muted(f"{name}\\nMUTED\\npress for on"),
                            state="1", **(feedback_strip or {}))],
        bgcolor=LIVE_GREEN,
        size="14",
    )


# What each knob controls. The house (Main LR) level stays where it is set in
# X AIR Edit, never on a knob (Sam, Oct 16 2026).
CHANNEL = lambda n: dict(  # noqa: E731
    fader_action="fad_a", mute_action="mute", mute_feedback="ch", level_var=f"f_ch{n}_d",
    strip={"type": "/ch/", "num": n}, mute_strip={"type": "/ch/", "num": n},
    feedback_strip={"theChannel": n},
)
# Pre-show music comes from the office PC's headphone jack into Aux in 17/18 (source set
# to the analog jacks). USB playback into channels 15/16 never passed audio (Oct 19 2026).
MUSIC = dict(fader_action="usbFad_a", mute_action="usbMute", mute_feedback="rtn_aux",
             level_var="f_rtn_aux_d")
SOURCES = [("MIC 1", CHANNEL(1)), ("MIC 2", CHANNEL(2)), ("MUSIC", MUSIC), ("GOD MIC", CHANNEL(5))]


def sound_controls():
    """Knobs, touch strip labels and mute keys, identical on every page so the
    knobs always do the same thing whatever page the deck is on."""
    controls = {}
    for col, (name, s) in enumerate(SOURCES):
        controls[(2, col)] = strip_label(name, s["level_var"], s["mute_action"], s["mute_feedback"],
                                         s.get("mute_strip"), s.get("feedback_strip"))
        controls[(3, col)] = volume_knob(s["fader_action"], s["mute_action"],
                                         s.get("strip"), s.get("mute_strip"))
    return controls


def show_mute_keys():
    """Bottom key row: one mute key above each knob, same order."""
    return {(1, col): mute_key(name, s["mute_action"], s["mute_feedback"],
                               s.get("mute_strip"), s.get("feedback_strip"))
            for col, (name, s) in enumerate(SOURCES)}


def page_key(this_page, next_page, number, color):
    """Top-left key on every page: names the page you are on; press for the next one."""
    return button(
        f"{this_page} page\\n\\nnext: {next_page}",
        press=[action(INTERNAL, "set_page", surfaceId="self", page=number)],
        bgcolor=color,
        size="14",
    )


def supabase_key(text, rpc, body=None, bgcolor=MENU_BLUE):
    """A key that calls one of our Supabase functions (menu board, stage timer)."""
    return button(
        text,
        press=[action(
            HTTP, "post",
            url=f"{SUPABASE}/rest/v1/rpc/{rpc}",
            body=json.dumps(body or {}),
            header=json.dumps({"apikey": SUPABASE_KEY}),
            contenttype="application/json",
            jsonResultDataVariable="",
            result_stringify=True,
            statusCodeVariable="",
        )],
        bgcolor=bgcolor,
    )


def menu_refresh_key():
    """Tells the taproom TV menu board to reload."""
    return supabase_key("REFRESH\\nTV MENU", "bump_menu_refresh")


def timer_key(text, rpc, body=None, bgcolor=TIMER_GREEN):
    """Stage timer (sisyphusbrewing.github.io/dojour_tickets/timer/, see timer/README.md)."""
    return supabase_key(text, rpc, body, bgcolor)


def shell_key(text, command, bgcolor=MENU_BLUE):
    """A key that runs a command on the office PC.

    Needs Companion's launcher settings, "Dangerous Features", shell commands on.
    Companion stops a command after at most 20 s, so `start` detaches it to run
    as long as it needs.
    """
    return button(
        text,
        press=[action(INTERNAL, "exec", path=f'start "" /min {command}', cwd="",
                      timeout=5000, targetVariable="")],
        bgcolor=bgcolor,
    )


def print_menu_key():
    """Prints today's taproom menu (menu/print-menu.ps1)."""
    return shell_key("PRINT\\nMENU\\n(paper)", PRINT_MENU_COMMAND)


def govee(bulb, kind, instance, value):
    """One Govee cloud command to one hallway bulb."""
    return action(
        HTTP, "post",
        url=GOVEE_URL,
        body=json.dumps({"requestId": "deck", "payload": {
            "sku": "R14C0", "device": HALL_BULBS[bulb],
            "capability": {"type": f"devices.capabilities.{kind}", "instance": instance, "value": value}}}),
        header=json.dumps({"Govee-API-Key": "$(internal:custom_govee_key)"}),
        contenttype="application/json",
        jsonResultDataVariable="",
        result_stringify=True,
        statusCodeVariable="",
    )


def hall_preshow(bulb):
    level, colour = HALL_PRESHOW[bulb]
    colour_cmd = (govee(bulb, "color_setting", "colorRgb", colour["rgb"]) if "rgb" in colour
                  else govee(bulb, "color_setting", "colorTemperatureK", colour["kelvin"]))
    return [govee(bulb, "on_off", "powerSwitch", 1), colour_cmd, govee(bulb, "range", "brightness", level)]


def hall_keys():
    return {
        (0, 3): button("HALL LIGHTS\\nPRE-SHOW\\nlook", bgcolor=0x7A5A00, size="14",
                       press=[a for bulb in HALL_BULBS for a in hall_preshow(bulb)]),
        (1, 0): button("HALL LIGHTS\\nFULL", bgcolor=0x4A3600, size="14",
                       press=[a for bulb in HALL_BULBS for a in (govee(bulb, "on_off", "powerSwitch", 1),
                                                                 govee(bulb, "range", "brightness", 100))]),
        (1, 1): button("HALL LIGHTS\\nOFF", bgcolor=DARK, size="14",
                       press=[govee(bulb, "on_off", "powerSwitch", 0) for bulb in HALL_BULBS]),
    }


def record_key():
    """Starts/stops OBS recording; red with the running time while recording."""
    return button(
        "RECORD\\nvideo\\n$(obs:recording_timecode)",
        press=[action(OBS, "StartStopRecording")],
        feedbacks=[feedback(OBS, "recording",
                            fg=WHITE, bg=RED, fg_paused=WHITE, bg_paused=0xFF8800)],
        bgcolor=DARK,
    )


def reset_sound_key():
    """Loads XR18 snapshot 1 "SHOW", the known-good show mix saved Oct 19 2026."""
    return button(
        "RESET\\nSOUND\\nshow mix",
        press=[action(XAIR, "load_snap", snap="1")],
        bgcolor=0x7A3A00,
    )


# --------------------------------------------------------------------------
# PAGES: edit here. Keys are (row, column). Every page also gets
# sound_controls(): rows 2-3, the touch strip labels and the four knobs.
# --------------------------------------------------------------------------

PAGES = {
    1: {
        "name": "SHOW",
        "controls": {
            (0, 0): page_key("SHOW", "BAR", 2, SHOW_COLOR),
            (0, 1): record_key(),
            (0, 3): reset_sound_key(),
            # (0, 2): free, for DOORS / INTERMISSION scenes later
            **show_mute_keys(),
        },
    },
    2: {
        "name": "BAR",
        "controls": {
            (0, 0): page_key("BAR", "TIMER", 3, BAR_COLOR),
            (0, 1): menu_refresh_key(),
            (0, 2): print_menu_key(),
            **hall_keys(),
        },
    },
    3: {
        "name": "TIMER",
        "controls": {
            (0, 0): page_key("TIMER", "SHOW", 1, TIMER_COLOR),
            (0, 1): timer_key("START\\n5 MIN\\ntimer", "timer_start", {"minutes": 5}),
            (0, 2): timer_key("START\\n7 MIN\\ntimer", "timer_start", {"minutes": 7}),
            (0, 3): timer_key("START\\n10 MIN\\ntimer", "timer_start", {"minutes": 10}),
            (1, 0): timer_key("START\\n15 MIN\\ntimer", "timer_start", {"minutes": 15}),
            (1, 1): timer_key("ADD\\n1 MIN\\nto timer", "timer_add", {"seconds": 60}, bgcolor=DARK),
            (1, 2): timer_key("STOP\\ntimer", "timer_stop", bgcolor=RED),
            # flash the comic's light by hand
            (1, 3): timer_key("FLASH\\nLIGHT", "timer_light", bgcolor=0x7A5A00),
        },
    },
}
for _page in PAGES.values():
    _page["controls"].update(sound_controls())

GRID = {"minColumn": 0, "maxColumn": 3, "minRow": 0, "maxRow": 3}

# --------------------------------------------------------------------------


def build():
    pages = {}
    for number, page in PAGES.items():
        controls = {}
        for (row, col), control in page["controls"].items():
            controls.setdefault(str(row), {})[str(col)] = control
        pages[str(number)] = {"name": page["name"], "controls": controls, "gridSize": GRID}

    instances = {
        cid: {**info, "config": {}, "isFirstInit": False, "enabled": True, "sortOrder": i}
        for i, (cid, info) in enumerate(CONNECTIONS.items())
    }
    instances[OBS]["config"] = {"host": "127.0.0.1", "port": 4455, "pass": ""}
    instances[HTTP]["config"] = {
        "prefix": "", "proxyAddress": "", "authType": "none",
        "rejectUnauthorized": True, "insecureHTTPParser": False,
    }

    return {
        "version": 12,
        "type": "full",
        "companionBuild": "sisyphus-generator",
        "pages": pages,
        "instances": instances,
        "triggers": {},
        "custom_variables": {},
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}")
