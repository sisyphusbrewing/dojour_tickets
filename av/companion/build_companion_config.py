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
CONNECTIONS = {
    XAIR: {"label": "xair", "moduleId": "behringer-xair", "lastUpgradeIndex": 5},
    HTTP: {"label": "http", "moduleId": "generic-http", "lastUpgradeIndex": 3},
}

WHITE = 0xFFFFFF
BLACK = 0x000000
RED = 0xC00000
DARK = 0x202020
MENU_BLUE = 0x1E4C7A

SUPABASE = "https://idsdwkubqnavkazlteis.supabase.co"
SUPABASE_KEY = "sb_publishable_c77Jm5yL_nrOJmxxNe-_pg_mkvDHpJb"

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
    return {
        "type": "action",
        "id": _next_id("a"),
        "connectionId": connection,
        "definitionId": definition,
        "options": _opts(options),
        "upgradeIndex": CONNECTIONS[connection]["lastUpgradeIndex"],
    }


def feedback(connection, definition, style, **options):
    return {
        "type": "feedback",
        "id": _next_id("f"),
        "connectionId": connection,
        "definitionId": definition,
        "options": _opts(options),
        "isInverted": False,
        "style": style,
        "upgradeIndex": CONNECTIONS[connection]["lastUpgradeIndex"],
    }


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


def volume_knob(name, fader_action, mute_action, mute_feedback, level_var, step=2):
    """A knob that turns a fader up/down by `step` percent and mutes on push."""
    fade = dict(duration=0, faderLim=True)  # never push past 0 dB
    return button(
        f"{name}\\n$(xair:{level_var}) dB",
        turn_right=[action(XAIR, fader_action, ticks=str(step), **fade)],
        turn_left=[action(XAIR, fader_action, ticks=str(-step), **fade)],
        press=[action(XAIR, mute_action, mute="2")],
        feedbacks=[feedback(XAIR, mute_feedback, MUTED, state="1")],
        size="14",
    )


def channel_mute_key(channel):
    """A key that toggles a mic channel's mute and turns red while muted."""
    return button(
        f"$(xair:l_ch{channel})",
        press=[action(XAIR, "mute", type="/ch/", num=channel, mute="2")],
        feedbacks=[feedback(XAIR, "ch", MUTED, state="1", theChannel=channel)],
        bgcolor=DARK,
    )


def menu_refresh_key():
    """Tells the taproom TV menu board to reload."""
    return button(
        "MENU\\nREFRESH",
        press=[action(
            HTTP, "post",
            url=f"{SUPABASE}/rest/v1/rpc/bump_menu_refresh",
            body="{}",
            header=json.dumps({"apikey": SUPABASE_KEY}),
            contenttype="application/json",
            jsonResultDataVariable="",
            result_stringify=True,
            statusCodeVariable="",
        )],
        bgcolor=MENU_BLUE,
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
            # knob 1: room volume (Main LR)
            (3, 0): volume_knob("ROOM", "mFad_a", "mMute", "lr", "f_lr_d"),
            # knob 3: music (XR18 Aux in 17/18)
            (3, 2): volume_knob("MUSIC", "usbFad_a", "usbMute", "rtn_aux", "f_rtn_aux_d"),
        },
    },
    2: {
        "name": "BAR",
        "controls": {
            (0, 0): PAGE_UP,
            (1, 0): PAGE_NUMBER,
            (0, 1): menu_refresh_key(),
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
