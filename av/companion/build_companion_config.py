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
    row 2         the touch strip, one segment above each knob
    row 3         the 4 knobs (turn = rotate actions, push = press actions)
"""

import json
import pathlib

OUT = pathlib.Path(__file__).with_name("sisyphus-deck.companionconfig")

# Connections the buttons use. On import, map XAIR to your existing X-Air
# connection; let Companion create HTTP as a new connection.
XAIR = "xair"
HTTP = "http"
OBS = "obs"
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


MUTED = {"bgcolor": RED, "color": WHITE}


def volume_knob(name, fader_action, mute_action, mute_feedback, level_var, step=2,
                strip=None, mute_strip=None, feedback_strip=None):
    """A knob that turns a fader up/down by `step` percent and mutes on push.

    `strip` picks a numbered strip (e.g. {"type": "/ch/", "num": 1}); Main LR
    and Aux in need none.
    """
    fade = dict(duration=0, faderLim=True, **(strip or {}))  # never push past 0 dB
    return button(
        f"{name}\\n$(xair:{level_var}) dB",
        turn_right=[action(XAIR, fader_action, ticks=str(step), **fade)],
        turn_left=[action(XAIR, fader_action, ticks=str(-step), **fade)],
        press=[action(XAIR, mute_action, mute="2", **(mute_strip or {}))],
        feedbacks=[feedback(XAIR, mute_feedback, MUTED, state="1", **(feedback_strip or {}))],
        size="14",
    )


def channel_knob(name, channel, step=2):
    """Volume knob for a mic channel; push mutes it."""
    return volume_knob(
        name, "fad_a", "mute", "ch", f"f_ch{channel}_d", step,
        strip={"type": "/ch/", "num": channel},
        mute_strip={"type": "/ch/", "num": channel},
        feedback_strip={"theChannel": channel},
    )


def channel_mute_key(channel):
    """A key that toggles a mic channel's mute and turns red while muted."""
    return button(
        f"$(xair:l_ch{channel})",
        press=[action(XAIR, "mute", type="/ch/", num=channel, mute="2")],
        feedbacks=[feedback(XAIR, "ch", MUTED, state="1", theChannel=channel)],
        bgcolor=DARK,
    )


def music_mute_key():
    """A key that toggles the music (Aux in) mute and turns red while muted."""
    return button(
        "MUSIC\\nMUTE",
        press=[action(XAIR, "usbMute", mute="2")],
        feedbacks=[feedback(XAIR, "rtn_aux", MUTED, state="1")],
        bgcolor=DARK,
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
    return supabase_key("MENU\\nREFRESH", "bump_menu_refresh")


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
    return shell_key("PRINT\\nMENU", PRINT_MENU_COMMAND)


def record_key():
    """Starts/stops OBS recording; red with the running time while recording."""
    return button(
        "REC\\n$(obs:recording_timecode)",
        press=[action(OBS, "StartStopRecording")],
        feedbacks=[feedback(OBS, "recording",
                            fg=WHITE, bg=RED, fg_paused=WHITE, bg_paused=0xFF8800)],
        bgcolor=DARK,
    )


PAGE_UP = {"type": "pageup"}
PAGE_NUMBER = {"type": "pagenum"}

# --------------------------------------------------------------------------
# PAGES: edit here. Keys are (row, column).
# --------------------------------------------------------------------------

PAGES = {
    1: {
        "name": "SHOW",
        "controls": {
            (0, 0): PAGE_UP,
            (1, 0): PAGE_NUMBER,
            (0, 2): channel_mute_key(1),
            (0, 3): music_mute_key(),
            (1, 1): record_key(),
            # knob 1: main stage mic (channel 1). The house (Main LR) level
            # stays where it is set in X AIR Edit, never on a knob (Sam, Oct 16 2026).
            (3, 0): channel_knob("MIC 1", 1),
            # knob 2: second stage mic (channel 2)
            (3, 1): channel_knob("MIC 2", 2),
            # knob 3: music (XR18 Aux in 17/18)
            (3, 2): volume_knob("MUSIC", "usbFad_a", "usbMute", "rtn_aux", "f_rtn_aux_d"),
            # knob 4: god mic (channel 5, wired, in the office)
            (3, 3): channel_knob("GOD MIC", 5),
        },
    },
    2: {
        "name": "BAR",
        "controls": {
            (0, 0): PAGE_UP,
            (1, 0): PAGE_NUMBER,
            (0, 1): menu_refresh_key(),
            (0, 2): print_menu_key(),
        },
    },
    3: {
        "name": "TIMER",
        "controls": {
            (0, 0): PAGE_UP,
            (1, 0): PAGE_NUMBER,
            (0, 1): timer_key("5\\nMIN", "timer_start", {"minutes": 5}),
            (0, 2): timer_key("7\\nMIN", "timer_start", {"minutes": 7}),
            (0, 3): timer_key("10\\nMIN", "timer_start", {"minutes": 10}),
            (1, 1): timer_key("15\\nMIN", "timer_start", {"minutes": 15}),
            (1, 2): timer_key("+1\\nMIN", "timer_add", {"seconds": 60}, bgcolor=DARK),
            (1, 3): timer_key("STOP", "timer_stop", bgcolor=RED),
            # touch strip, above knob 1: tap to flash the light by hand
            (2, 0): timer_key("LIGHT", "timer_light", bgcolor=0x7A5A00),
        },
    },
}

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
