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
    OBS: {"label": "obs", "moduleId": "obs-studio", "lastUpgradeIndex": 10},  # module v4.0.0-beta.4
}

WHITE = 0xFFFFFF
BLACK = 0x000000
RED = 0xC00000
DARK = 0x202020
MENU_BLUE = 0x1E4C7A
TIMER_GREEN = 0x1F5F2E

SUPABASE = "https://idsdwkubqnavkazlteis.supabase.co"
SUPABASE_KEY = "sb_publishable_c77Jm5yL_nrOJmxxNe-_pg_mkvDHpJb"

# Prints today's taproom menu on the office printer: Edge renders menu/print.html to a PDF, SumatraPDF
# prints it (winget installs it the first time). Plain cmd, no PowerShell and nothing downloaded and run,
# because Defender flags the old "download a script and run it" PowerShell line as a virus (Oct 28 2026).
# Files live in C:\Users\Public\sisyphus-menu (no spaces, so no quotes are needed). The ^& are escaped so
# the outer cmd hands the whole chain to the detached `cmd /c` that shell_key starts.
MENU_COPIES = 5  # one press prints a stack for the bar (Sam, Oct 29 2026)
_MENU = r"%PUBLIC%\sisyphus-menu"
_SUMATRA = r"%LOCALAPPDATA%\SumatraPDF\SumatraPDF.exe"
PRINT_MENU_COMMAND = " ^& ".join([
    f"cmd /c md {_MENU}",
    rf"del /q {_MENU}\taproom-menu.pdf",
    'start "" /wait /min msedge --headless=new --disable-gpu --no-first-run'
    rf" --user-data-dir={_MENU}\profile --no-pdf-header-footer --virtual-time-budget=15000"
    rf" --print-to-pdf={_MENU}\taproom-menu.pdf"
    " https://staff.sisyphusbrewing.com/menu/print.html?t=%RANDOM%",
    f"(if not exist {_SUMATRA} winget install -e --id SumatraPDF.SumatraPDF --silent"
    " --accept-package-agreements --accept-source-agreements)",
    rf"{_SUMATRA} -print-to-default -print-settings noscale,{MENU_COPIES}x -silent {_MENU}\taproom-menu.pdf",
])

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
    }
    if connection in CONNECTIONS:  # Companion's internal feedbacks carry no upgrade index
        fb["upgradeIndex"] = CONNECTIONS[connection]["lastUpgradeIndex"]
    if style is not None:
        fb["style"] = style
    return fb


def button(text, *, press=(), release=(), turn_left=(), turn_right=(), feedbacks=(),
           color=WHITE, bgcolor=BLACK, size="auto", expression=False):
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
            "textExpression": expression,
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
    """A key that mutes/unmutes; green ON, red MUTED. Two short lines so the
    longest name (GOD MIC) still fits the key at a readable size."""
    return button(
        f"{name}\\nON\\ntap to mute",
        press=[action(XAIR, mute_action, mute="2", **(mute_strip or {}))],
        feedbacks=[feedback(XAIR, mute_feedback, muted(f"{name}\\nMUTED"),
                            state="1", **(feedback_strip or {}))],
        bgcolor=LIVE_GREEN,
    )


# What each knob controls. The house (Main LR) level stays where it is set in
# X AIR Edit, never on a knob (Sam, Oct 16 2026).
CHANNEL = lambda n: dict(  # noqa: E731
    fader_action="fad_a", mute_action="mute", mute_feedback="ch", level_var=f"f_ch{n}_d",
    strip={"type": "/ch/", "num": n}, mute_strip={"type": "/ch/", "num": n},
    feedback_strip={"theChannel": n},
)
# Pre-show music comes from the office PC over USB into channels 3/4 (linked, named MUSIC):
# Windows plays to "OUT 3-4", and on the XR18 a channel's USB return only hears the PC output
# with its own number. USB playback into the board was silent until the XR18 firmware went
# from 1.19 to 1.26 (Oct 29 2026); it replaces the headphone-jack cable into Aux In.
MUSIC = CHANNEL(3)
# Mics 3 and 4 are on channels 9 and 10 for nights with more people on stage (Oct 29 2026).
# The deck has a 2-mic and a 4-mic layout (MICS key on the SHOW page): with 4 mics the knobs
# ride the four mics instead of music and the god mic.
SOURCES_2 = [("MIC 1", CHANNEL(1)), ("MIC 2", CHANNEL(2)), ("MUSIC", MUSIC), ("GOD MIC", CHANNEL(5))]
SOURCES_4 = [("MIC 1", CHANNEL(1)), ("MIC 2", CHANNEL(2)), ("MIC 3", CHANNEL(9)), ("MIC 4", CHANNEL(10))]


def sound_controls(sources):
    """Knobs, touch strip labels and mute keys, identical on every page so the
    knobs always do the same thing whatever page the deck is on."""
    controls = {}
    for col, (name, s) in enumerate(sources):
        controls[(2, col)] = strip_label(name, s["level_var"], s["mute_action"], s["mute_feedback"],
                                         s.get("mute_strip"), s.get("feedback_strip"))
        controls[(3, col)] = volume_knob(s["fader_action"], s["mute_action"],
                                         s.get("strip"), s.get("mute_strip"))
    return controls


def show_mute_keys(sources):
    """Bottom key row: one mute key above each knob, same order."""
    return {(1, col): mute_key(name, s["mute_action"], s["mute_feedback"],
                               s.get("mute_strip"), s.get("feedback_strip"))
            for col, (name, s) in enumerate(sources)}


def page_key(this_page, next_page, number, color):
    """Top-left key on every page: press for the next page (Sam: "it should always just
    say next page"). The page colour tells you which page you're on."""
    return button(
        "NEXT\\nPAGE >",
        press=[action(INTERNAL, "set_page", surfaceId="self", page=number)],
        bgcolor=color,
        size="14",
    )


def supabase_call(rpc, body=None):
    """Calls one of our Supabase functions (menu board, stage timer)."""
    return action(
        HTTP, "post",
        url=f"{SUPABASE}/rest/v1/rpc/{rpc}",
        body=json.dumps(body or {}),
        header=json.dumps({"apikey": SUPABASE_KEY}),
        contenttype="application/json",
        jsonResultDataVariable="",
        result_stringify=True,
        statusCodeVariable="",
    )


def supabase_key(text, rpc, body=None, bgcolor=MENU_BLUE):
    """A key that calls one of our Supabase functions."""
    return button(text, press=[supabase_call(rpc, body)], bgcolor=bgcolor)


def menu_refresh_key():
    """Tells the taproom TV menu board to reload."""
    return supabase_key("REFRESH\\nTV MENU\\nscreen", "bump_menu_refresh")


def timer_actions(rpc, body=None):
    """Stage timer (staff.sisyphusbrewing.com/timer/, see timer/README.md).

    Calls the Supabase rpc and also updates Companion's own copy of the timer (custom
    variables timer_t0 / timer_len / timer_wrap) so the TIMER page readout can show it."""
    body = body or {}
    if rpc == "timer_start":
        sets = {"timer_t0": "$(internal:time_unix)", "timer_len": str(body["minutes"] * 60), "timer_wrap": "0"}
    elif rpc == "timer_add":  # the rpc never goes below a 1-minute set; match it
        new_len = f"$(custom:timer_len) + {body['seconds']}"
        sets = {"timer_len": f"{new_len} < 60 ? 60 : {new_len}", "timer_wrap": "0"}
    elif rpc == "timer_stop":
        sets = {"timer_t0": "0", "timer_wrap": "0"}
    else:  # timer_light = WRAP IT UP toggle
        sets = {"timer_wrap": "1 - $(custom:timer_wrap)"}
    acts = [supabase_call(rpc, body)]
    # Companion 5.1 ignores the old "custom_variable_set_expression" on import (its upgrade
    # script doesn't run on our imports), so use "custom_variable_set_value" with the
    # value marked as an expression.
    for name, expr in sets.items():
        act = action(INTERNAL, "custom_variable_set_value", name=name, value=expr)
        act["options"]["value"]["isExpression"] = True
        acts.append(act)
    return acts


def timer_key(text, rpc, body=None, bgcolor=TIMER_GREEN):
    return button(text, press=timer_actions(rpc, body), bgcolor=bgcolor)


# TIMER page (2-mic layout): the GOD MIC knob becomes TIME (nobody makes announcements
# mid-set). Sam, Oct 29 2026: "one of the knobs on the timer page adjust the timer".
TIME_STEP = 15  # seconds per click (Sam, Oct 29 2026)


def time_knob():
    """Turn: give or take TIME_STEP seconds. Push: one more minute (never stops the clock)."""
    return button(
        "",
        turn_right=timer_actions("timer_add", {"seconds": TIME_STEP}),
        turn_left=timer_actions("timer_add", {"seconds": -TIME_STEP}),
        press=timer_actions("timer_add", {"seconds": 60}),
    )


def time_strip():
    """Touch strip above the TIME knob: the set length; tap it for one more minute too."""
    return button(
        f"concat('TIME ', secondsToTimestamp($(custom:timer_len), 'mm:ss'), '\\ntap: +1 MIN')",
        press=timer_actions("timer_add", {"seconds": 60}),
        bgcolor=TIMER_COLOR,
        size="14",
        expression=True,
    )


# What the stage clock is showing, worked out on the deck from the variables above.
# It follows deck presses (a set started from the timer web page doesn't show here).
_E = "($(internal:time_unix) - $(custom:timer_t0))"  # seconds into the set
_L = "$(custom:timer_len)"
# Companion 5.1 expressions don't join text with "+" (it adds as numbers, giving NaN), so
# the text is built with concat().
TIMER_READOUT = (
    f"$(custom:timer_t0) == 0 ? 'CLOCK\\nstopped' : "
    f"concat(secondsToTimestamp({_E}, 'mm:ss'), '\\n', "
    f"{_E} >= {_L} + 60 ? 'FAMOUS?' : "
    f"{_E} >= {_L} ? 'OVER' : "
    f"($(custom:timer_wrap) == 1 || {_L} - {_E} <= 30) ? 'WRAP IT UP' : "
    f"{_L} - {_E} <= 60 ? 'LIGHT' : "
    f"concat('of ', secondsToTimestamp({_L}, 'mm:ss')))"
)
# red from the light on (1 min left, or WRAP IT UP pressed)
TIMER_RED = (f"$(custom:timer_t0) != 0 && ($(custom:timer_wrap) == 1 || {_L} - {_E} <= 60)")
CUSTOM_VARIABLES = {
    "timer_t0": "Stage timer: unix time the set started on the deck (0 = stopped)",
    "timer_len": "Stage timer: set length in seconds",
    "timer_wrap": "Stage timer: 1 while WRAP IT UP is on",
}


def timer_readout_key():
    """TIMER page: what the comic's clock says. Display only (pressing does nothing)."""
    return button(
        TIMER_READOUT,
        feedbacks=[feedback(INTERNAL, "check_expression", style={"bgcolor": RED, "color": WHITE},
                            expression=TIMER_RED)],
        bgcolor=TIMER_COLOR,
        size="18",
        expression=True,
    )


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
    """Prints today's taproom menu (see PRINT_MENU_COMMAND)."""
    return shell_key(f"PRINT\\n{MENU_COPIES} PAPER\\nMENUS", PRINT_MENU_COMMAND)


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


# Daytime: all three soft warm white. Sam asked for 2600K; 2700K is the bulbs' warmest (Oct 20 2026).
HALL_DAYTIME = {bulb: (60, {"kelvin": 2700}) for bulb in HALL_BULBS}
# Sunset: red, orange, purple down the hallway (Sam, Oct 20 2026).
HALL_SUNSET = {
    "Hallway 1": (70, {"rgb": 0xFF2000}),
    "Middle hallway": (70, {"rgb": 0xFF6A00}),
    "Hallway 2": (70, {"rgb": 0x8A2BE2}),
}


def hall_look(look, bulb):
    level, colour = look[bulb]
    colour_cmd = (govee(bulb, "color_setting", "colorRgb", colour["rgb"]) if "rgb" in colour
                  else govee(bulb, "color_setting", "colorTemperatureK", colour["kelvin"]))
    return [govee(bulb, "on_off", "powerSwitch", 1), colour_cmd, govee(bulb, "range", "brightness", level)]


def hall_keys():
    return {
        (0, 3): button("HALL LIGHTS\\nPRE-SHOW\\nlook", bgcolor=0x7A5A00, size="14",
                       press=[a for bulb in HALL_BULBS for a in hall_look(HALL_PRESHOW, bulb)]),
        (1, 0): button("HALL LIGHTS\\nDAYTIME", bgcolor=0x6A5A30, size="14",
                       press=[a for bulb in HALL_BULBS for a in hall_look(HALL_DAYTIME, bulb)]),
        (1, 1): button("HALL LIGHTS\\nSUNSET", bgcolor=0x8A2A3A, size="14",
                       press=[a for bulb in HALL_BULBS for a in hall_look(HALL_SUNSET, bulb)]),
        (1, 2): button("HALL LIGHTS\\nOFF", bgcolor=DARK, size="14",
                       press=[govee(bulb, "on_off", "powerSwitch", 0) for bulb in HALL_BULBS]),
    }


def record_key():
    """Starts/stops OBS recording; red with the running time while recording."""
    return button(
        "RECORD\\nVIDEO\\n$(obs:recording_timecode)",
        # OBS module v4 "Recording - Controls: Toggle"; page imports don't run the module's upgrade
        # scripts, so older ids (StartStopRecording, toggle_recording) import as dead actions
        press=[action(OBS, "recording", action="toggle")],
        feedbacks=[feedback(OBS, "recording", style={"color": WHITE, "bgcolor": RED}),
                   feedback(OBS, "recordingPaused", style={"color": WHITE, "bgcolor": 0xFF8800})],
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

def layout(sources, first, mics, other_first):
    """SHOW, BAR and TIMER pages for one mic layout, numbered from `first`."""
    show, bar, timer = first, first + 1, first + 2
    tag = "" if mics == 2 else " 4"  # page names: SHOW / SHOW 4 ...
    pages = {
        show: {
            "name": f"SHOW{tag}",
            "controls": {
                (0, 0): page_key(f"SHOW{tag}", "BAR", bar, SHOW_COLOR),
                (0, 1): record_key(),
                (0, 2): mics_key(mics, other_first),
                (0, 3): reset_sound_key(),
                **show_mute_keys(sources),
            },
        },
        bar: {
            "name": f"BAR{tag}",
            "controls": {
                (0, 0): page_key(f"BAR{tag}", "TIMER", timer, BAR_COLOR),
                (0, 1): menu_refresh_key(),
                (0, 2): print_menu_key(),
                **hall_keys(),
            },
        },
        timer: {
            "name": f"TIMER{tag}",
            "controls": {
                (0, 0): page_key(f"TIMER{tag}", "SHOW", show, TIMER_COLOR),
                (0, 1): timer_readout_key(),  # live readout of the stage clock
                (0, 2): timer_key("START\\n3 MIN\\nSET", "timer_start", {"minutes": 3}),
                (0, 3): timer_key("START\\n5 MIN\\nSET", "timer_start", {"minutes": 5}),
                (1, 0): timer_key("START\\n7 MIN\\nSET", "timer_start", {"minutes": 7}),
                (1, 1): timer_key("START\\n10 MIN\\nSET", "timer_start", {"minutes": 10}),
                (1, 2): timer_key("STOP\\nCLOCK", "timer_stop", bgcolor=RED),
                # WRAP IT UP on the stage clock now (timer_light); press again to clear.
                # (+1 MIN gave up its key to the readout; push the TIME knob instead.)
                (1, 3): timer_key("WRAP\\nIT UP", "timer_light", bgcolor=RED),
            },
        },
    }
    for page in pages.values():
        page["controls"].update(sound_controls(sources))
    if mics == 2:  # with 4 mics every knob is a mic, so TIMER 4 keeps them
        pages[timer]["controls"].update({(2, 3): time_strip(), (3, 3): time_knob()})
    return pages


def mics_key(mics, other_first):
    """SHOW page: which mic layout the knobs use; press to switch."""
    other = 4 if mics == 2 else 2
    return button(f"USING\\n{mics} MICS\\ntap for {other}", bgcolor=0x3A3A6A, size="14",
                  press=[action(INTERNAL, "set_page", surfaceId="self", page=other_first)])


PAGES = {**layout(SOURCES_2, 1, 2, 4), **layout(SOURCES_4, 4, 4, 1)}


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
        "custom_variables": {
            name: {"description": desc, "defaultValue": 0, "persistCurrentValue": False, "sortOrder": i}
            for i, (name, desc) in enumerate(CUSTOM_VARIABLES.items())
        },
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}")
