#!/usr/bin/env python3
"""Build the Sisyphus showroom Stream Deck + config for Bitfocus Companion.

Edit the PAGES section below, run this script, commit the file it writes
(sisyphus-deck.companionconfig), and merge. Then load it on the office PC with no
clicks: import-config.ps1 (next to this file) backs Companion up, pulls the deck from
main, swaps in only the buttons and checks the result. Add -DryRun to preview.

    python3 build_companion_config.py

How the deck works since Nov 12 2026 (Sam: "it needs to be intuitive"; staff found the old
nine pages behind one NEXT PAGE key hard to use):

  * Two screens for a whole night, and the deck moves between them by itself.
    HOME is where it sits all day: the four room looks in the order of a night
    (DAYTIME, PRE-SHOW, START SHOW, ALL OFF) and the bar keys. START SHOW brings up the
    SHOW screen (comic clock, wrap it up, end show); END SHOW asks "are you sure?" and
    then brings HOME back.
  * The four knobs are the same four things on both screens: MIC, MUSIC, LIGHTS, CLOCK.
    Turn = more or less. Push = that thing on or off (mic, play/pause, lights, clock
    start/stop). Tap the touch screen above a knob = that thing's extra choices, with BACK
    always top-left.
  * No RECORD key and nothing to hold down. Recording follows the SHOW look: START SHOW
    starts it, every other look stops it. (On Nov 12 the old "tap to start, hold 3 s to
    stop" key got five taps that did nothing, so it looked broken, and a tap after the stop
    started a second file.)
  * The comic clock just starts (START CLOCK or push the CLOCK knob). The knob sets the
    set length, before or during the set.

Buttons are written in Companion's older plain "button" style on purpose: Companion
converts them to its current layered format on import, so this script does not have to
track that much more verbose layout.

Stream Deck + grid in Companion (4 columns):
    row 0, row 1  the 8 keys (120 x 120)
    row 2         the touch screen, one 200 x 100 tile above each knob. Tap = press actions.
    row 3         the 4 knobs (turn = rotate actions, push = press actions; no screen)
"""

import json
import pathlib
from urllib.parse import quote

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
# Govee smart plugs (H5083, on/off only), switched with the hall lights (Sam, Oct 30 2026):
# ON with PRE-SHOW, OFF with HALL LIGHTS OFF.
PLUGS = {
    "Stage wall wash": "07:CF:7C:E8:B1:16:DF:50",
    "Sisyphus Sign": "0E:C4:D4:05:92:D7:D4:8C",
}
# Poster lamp + shuffleboard plugs (H5083): ON with DAYTIME and PRE-SHOW, OFF with ALL OFF (Sam, Nov 2 2026).
DAY_PLUGS = {
    "Poster Lamp": "13:BA:7C:E8:B1:07:95:64",
    "Shuffleboard": "09:CF:7C:E8:B1:04:45:40",
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
           color=WHITE, bgcolor=BLACK, size="auto", expression=False, steps=None, step_expression=""):
    """One key, touch-screen tile or knob.

    Text always sizes itself to fit (`size` is ignored): the fixed sizes used until Nov 12 2026
    chopped words on the real deck ("DAYTI ME", "RECORD ING").

    `steps` is for a control whose press depends on what is going on: a list of press-action
    lists, with `step_expression` picking which one runs (1 = the first). Turning the knob does
    the same thing in every step.
    """
    rotary = bool(turn_left or turn_right)

    def action_sets(down):
        sets = {"down": list(down), "up": list(release)}
        if rotary:
            # fresh copies so every action keeps a unique id
            sets["rotate_left"] = [dict(a, id=_next_id("a")) for a in turn_left]
            sets["rotate_right"] = [dict(a, id=_next_id("a")) for a in turn_right]
        return {"action_sets": sets, "options": {"runWhileHeld": []}}

    presses = steps if steps else [press]
    return {
        "type": "button",
        "options": {"stepProgression": "expression" if step_expression else "auto",
                    "stepExpression": step_expression, "rotaryActions": rotary},
        "style": {
            "text": text,
            "textExpression": expression,
            "size": "auto",
            "alignment": "center:center",
            "pngalignment": "center:center",
            "color": color,
            "bgcolor": bgcolor,
            "show_topbar": "default",
            "png64": None,
        },
        "feedbacks": list(feedbacks),
        "steps": {str(i): action_sets(down) for i, down in enumerate(presses)},
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


# Portable deck battery (Sam, Nov 11 2026): the Pi's UPS HAT sends its charge % to custom
# variable deck_battery every minute (av/pi-satellite-setup.sh). It only matters when it is
# low, so the top-right key (ALL OFF / END SHOW) says so at 20% or less. 0 means no reading
# yet (Pi just booted, or on wall power without the HAT).
BATTERY_LOW = "$(custom:deck_battery) > 0 && $(custom:deck_battery) <= 20"
GREY = 0x2F2F2F     # a key that is there to press but is not "on"
BACK_GREY = 0x505050


def set_var(name, value, expression=False):
    """Set one of Companion's custom variables. With expression=True the value is worked out
    when the key is pressed. (Companion 5.1 ignores the old "custom_variable_set_expression"
    on import, so this is "custom_variable_set_value" with the value marked as an expression.)"""
    act = action(INTERNAL, "custom_variable_set_value", name=name, value=value)
    act["options"]["value"]["isExpression"] = expression
    return act


def set_number(name, number):
    """Set a custom variable to a number (kept as a number, so the clock maths never sees text)."""
    return set_var(name, str(number), expression=True)


def go(page):
    """Show another page on the deck that was pressed. "back" = the page it came from."""
    return action(INTERNAL, "set_page", surfaceId="self", page=page)


def when(expr, **style):
    """Restyle a key while `expr` is true (bgcolor, color, text)."""
    return feedback(INTERNAL, "check_expression", style=style, expression=expr)


def battery_warning(name):
    return when(BATTERY_LOW, bgcolor=0xB06000, color=WHITE,
                text=f"{name}\\nPLUG IN DECK\\nbatt $(custom:deck_battery)%")


def supabase_call(rpc, body=None, raw_body=None):
    """Calls one of our Supabase functions (menu board, stage timer). `raw_body` is for a
    body with a Companion variable in it, which Companion fills in when the key is pressed."""
    return action(
        HTTP, "post",
        url=f"{SUPABASE}/rest/v1/rpc/{rpc}",
        body=raw_body if raw_body is not None else json.dumps(body or {}),
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


# --------------------------------------------------------------------------
# The comic clock (staff.sisyphusbrewing.com/timer/, see timer/README.md)
#
# Sam, Nov 12 2026: "The clock running needs to be intuitive. Right now, the clock doesn't
# work or start until you pick a time key." So START CLOCK (or a push of the CLOCK knob)
# just starts it, using the set length the deck is holding (custom variable timer_min,
# 7 minutes until someone changes it). Turning the CLOCK knob changes the length a minute at
# a time, before or during a set. The deck keeps its own copy of the clock (timer_t0 = when
# the set started, timer_wrap = WRAP IT UP is on) so the touch screen can show it; a set
# started from the timer web page does not show here.
# --------------------------------------------------------------------------
CLOCK_DEFAULT_MIN = 7
CLOCK_MAX_MIN = 90   # the timer_start rpc's own limit
CLOCK_PRESETS = [3, 5, 7, 10, 15, 20, 45]
_MIN = "$(custom:timer_min)"
_E = "($(internal:time_unix) - $(custom:timer_t0))"  # seconds into the set
_L = f"({_MIN} * 60)"                                 # set length in seconds
CLOCK_RUNNING = "$(custom:timer_t0) != 0"
# red from the light on (1 min left, or WRAP IT UP pressed)
CLOCK_RED = f"$(custom:timer_t0) != 0 && ($(custom:timer_wrap) == 1 || {_L} - {_E} <= 60)"


def clock_start():
    return [supabase_call("timer_start", raw_body='{"minutes": $(custom:timer_min)}'),
            set_var("timer_t0", "$(internal:time_unix)", expression=True),
            set_number("timer_wrap", 0)]


def clock_stop():
    return [supabase_call("timer_stop"), set_number("timer_t0", 0), set_number("timer_wrap", 0)]


def clock_wrap():
    """WRAP IT UP on the comic's clock right now; press again to clear."""
    return [supabase_call("timer_light"),
            set_var("timer_wrap", "1 - $(custom:timer_wrap)", expression=True)]


def clock_nudge(minutes):
    """One click of the CLOCK knob: a minute more or less (1 to 90). The rpc moves a running
    set by the same amount; a stopped clock gets the deck's length when it next starts.
    The rpc also clears WRAP IT UP, so the deck's copy is cleared with it (otherwise the
    WRAP IT UP key and the comic's screen end up saying opposite things)."""
    if minutes > 0:
        new = f"{_MIN} >= {CLOCK_MAX_MIN} ? {CLOCK_MAX_MIN} : {_MIN} + {minutes}"
    else:
        new = f"{_MIN} <= 1 ? 1 : {_MIN} - {-minutes}"
    return [set_var("timer_min", new, expression=True), set_number("timer_wrap", 0),
            supabase_call("timer_add", {"seconds": minutes * 60})]


# What the touch screen above the CLOCK knob says. Companion 5.1 expressions don't join text
# with "+" (it adds as numbers, giving NaN), so the text is built with concat().
CLOCK_TILE = (
    f"$(custom:timer_t0) == 0 ? concat('CLOCK\\n', {_MIN}, ' MIN SET\\npush = start') : "
    f"concat(secondsToTimestamp({_E}, 'mm:ss'), ' of ', {_MIN}, ':00\\n', "
    f"{_E} >= {_L} + 60 ? 'FAMOUS?' : "
    f"{_E} >= {_L} ? 'OVER TIME' : "
    f"($(custom:timer_wrap) == 1 || {_L} - {_E} <= 30) ? 'WRAP IT UP' : "
    f"{_L} - {_E} <= 60 ? 'LIGHT IS ON' : 'push = stop')"
)
# name: (what it is for, value a new one starts with)
CUSTOM_VARIABLES = {
    "timer_t0": ("Comic clock: unix time the set started on the deck (0 = stopped)", 0),
    "timer_min": ("Comic clock: set length in minutes (the CLOCK knob)", CLOCK_DEFAULT_MIN),
    "timer_wrap": ("Comic clock: 1 while WRAP IT UP is on", 0),
    "room_look": ("Which room look was pressed last: day, pre, show or off", "day"),
    "house_tables": ("House lights Tables level %, written by the house-lights service", 0),
    "house_bar": ("House lights Bar level %, written by the house-lights service", 0),
    "stage_look": ("Stage lights look, written by the stage-lights service (wash, show, warm, blue, ... off)", 0),
    "deck_battery": ("Portable deck battery %, written every minute by the Pi (av/pi-satellite-setup.sh)", 0),
    # Guests still to come, written every 30 s by av/door-count/door_count.py on the office PC
    "door_show": ("Door count: which show it is for, e.g. 8 PM", ""),
    "door_left": ("Door count: guests not checked in yet (-1 = no show to count)", -1),
    "door_total": ("Door count: tickets for that show", 0),
    "door_at": ("Door count: unix time of the last reading (old = don't show it)", 0),
}


def clock_tile():
    """Touch screen above the CLOCK knob: the comic's clock. Tap = the set-length choices."""
    return button(CLOCK_TILE, expression=True, press=[go(PAGE_CLOCK)], bgcolor=DARK,
                  feedbacks=[when(CLOCK_RUNNING, bgcolor=0x1F7A35, color=WHITE),
                             when(CLOCK_RED, bgcolor=RED, color=WHITE)])


def clock_knob():
    """Turn = set length. Push = start if the clock is stopped, stop if it is running."""
    return button("", turn_right=clock_nudge(1), turn_left=clock_nudge(-1),
                  steps=[clock_start(), clock_stop()],
                  step_expression="$(custom:timer_t0) == 0 ? 1 : 2")


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


def govee(bulb, kind, instance, value, sku="R14C0", device=None):
    """One Govee cloud command to one hallway bulb (or, with sku/device, any Govee device)."""
    return action(
        HTTP, "post",
        url=GOVEE_URL,
        body=json.dumps({"requestId": "deck", "payload": {
            "sku": sku, "device": device or HALL_BULBS[bulb],
            "capability": {"type": f"devices.capabilities.{kind}", "instance": instance, "value": value}}}),
        header=json.dumps({"Govee-API-Key": "$(internal:custom_govee_key)"}),
        contenttype="application/json",
        jsonResultDataVariable="",
        result_stringify=True,
        statusCodeVariable="",
    )


# Daytime: all three soft warm white. Sam asked for 2600K; 2700K is the bulbs' warmest (Oct 20 2026).
HALL_DAYTIME = {bulb: (60, {"kelvin": 2700}) for bulb in HALL_BULBS}


def hall_look(look, bulb):
    level, colour = look[bulb]
    colour_cmd = (govee(bulb, "color_setting", "colorRgb", colour["rgb"]) if "rgb" in colour
                  else govee(bulb, "color_setting", "colorTemperatureK", colour["kelvin"]))
    return [govee(bulb, "on_off", "powerSwitch", 1), colour_cmd, govee(bulb, "range", "brightness", level)]


def plugs(on, which=PLUGS):
    return [govee(None, "on_off", "powerSwitch", 1 if on else 0, sku="H5083", device=d) for d in which.values()]


# House lights: two Lutron Caséta dimmers (Tables, Bar) on a standard Smart Bridge. A small local
# service on the office PC (C:\\Users\\Sam\\sisyphus-av\\house-lights, LEAP, no cloud) takes plain GETs.
HOUSE_URL = "http://127.0.0.1:8790/house"


def house(path):
    """full = 100/100, off = 0/0 (3 s fade),
    or level?zone=tables|bar&pct=0-100&fade=seconds for one zone."""
    return action(HTTP, "get", url=f"{HOUSE_URL}/{path}", header="",
                  jsonResultDataVariable="", result_stringify=True, statusCodeVariable="")


def house_both(pct, fade=3):
    return [house(f"level?zone={z}&pct={pct}&fade={fade}") for z in ("tables", "bar")]


# Table candles (flameless LED, IR remote) through an Athom Tasmota IR blaster on the Wi-Fi,
# "Candles IR" at 192.168.86.27 (Sam, Nov 5 2026). Codes learned off the candle remote:
# NEC 32-bit. Repeat 1 sends each press twice so candles at the edge of the beam still catch it.
# ON with PRE-SHOW, stay on through SHOW, OFF with DAYTIME and ALL OFF.
CANDLE_BLASTERS = ["192.168.86.27", "192.168.86.45"]  # Candles IR, Candles IR 2
CANDLE_CODES = {True: "0x10ED00FF", False: "0x10ED40BF"}


def candles(on):
    body = quote(json.dumps({"Protocol": "NEC", "Bits": 32, "Data": CANDLE_CODES[on], "Repeat": 1},
                            separators=(",", ":")))
    return [action(HTTP, "get", url=f"http://{ip}/cm?cmnd=IRsend%20{body}", header="",
                   jsonResultDataVariable="", result_stringify=True, statusCodeVariable="")
            for ip in CANDLE_BLASTERS]


CANDLE_COLOR = 0xB06000


def candles_key():
    """Test key (Sam, Nov 5 2026): each press flips the candles. IR can't report back, so the key
    keeps its own state in two steps: step 1 sends ON, step 2 sends OFF; amber while it thinks they're on."""
    key = button("CANDLES\\nOFF\\ntap for on", bgcolor=DARK, size="18", press=candles(True),
                 feedbacks=[feedback(INTERNAL, "check_expression",
                                     style={"bgcolor": CANDLE_COLOR, "color": WHITE,
                                            "text": "CANDLES\\nON\\ntap for off"},
                                     expression="$(this:step) == 2")])
    key["steps"]["1"] = {"action_sets": {"down": candles(False), "up": []}, "options": {"runWhileHeld": []}}
    return key


# House-light dimmer knobs on the BAR pages (Sam, Nov 4 2026): knob 1 = TABLES, knob 2 = BAR.
# Turn = 5% per click, push (or tap the strip) = on/off. The house-lights service does the
# maths (/house/step, /house/toggle) and writes each zone's level into custom variables
# house_tables / house_bar so the strip shows it, including changes from the wall or the app.
DIM_STEP = 5


def dimmer_knob(zone):
    return button(
        "",
        turn_right=[house(f"step?zone={zone}&delta={DIM_STEP}")],
        turn_left=[house(f"step?zone={zone}&delta=-{DIM_STEP}")],
        press=[house(f"toggle?zone={zone}")],
    )


def dimmer_strip(zone, name):
    var = f"$(custom:house_{zone})"
    return button(
        f"{name}\\nLIGHTS {var}%\\nturn knob",
        press=[house(f"toggle?zone={zone}")],
        feedbacks=[feedback(INTERNAL, "check_expression", style={"bgcolor": 0x6A5A30, "color": WHITE},
                            expression=f"{var} > 0")],
        bgcolor=DARK,
        size="14",
    )


def bar_knobs():
    """BAR pages: two light dimmers, then MUSIC and GOD MIC as on the 2-mic pages."""
    controls = sound_controls(SOURCES_2)
    for col, (zone, name) in enumerate((("tables", "TABLES"), ("bar", "BAR"))):
        controls[(2, col)] = dimmer_strip(zone, name)
        controls[(3, col)] = dimmer_knob(zone)
    return controls


# Stage lights (Nov 5 2026): the 4 ADJ 12P Hex over a PKnight Art-Net node, driven by a small
# local service on the office PC. GET /stage/<look>?fade=seconds; it writes the look it is on
# into custom variable stage_look so the deck can light up the matching key.
STAGE_URL = "http://127.0.0.1:8792/stage"
STAGE_FADE = 2  # seconds
STAGE_COLOR = 0x2A3F6A
# PRE-SHOW = blue wash, SHOW = warm all around (Sam, Nov 5 2026)
STAGE_PRESHOW = "blue"
STAGE_SHOW = "show"  # white + warm + some amber; "warm" is the deeper amber mood look


def stage(look, fade=STAGE_FADE):
    return action(HTTP, "get", url=f"{STAGE_URL}/{look}?fade={fade}", header="",
                  jsonResultDataVariable="", result_stringify=True, statusCodeVariable="")


def stage_on(look):
    return f"$(custom:stage_look) == '{look}'"


# Look keys: (label, look, colour the key turns while that look is on)
STAGE_LOOKS = [
    ("WASH", "wash", 0x7A6A50),
    ("SHOW", "show", SHOW_COLOR),
    ("WARM", "warm", 0xB06000),
    ("WHITE", "white", 0x9A9A9A),
    ("UV", "uv", 0x4B1E8A),
]
# One COLOR key steps through these, one per press
STAGE_COLORS = [("PINK", "pink", 0xC0307A), ("BLUE", "blue", 0x1F4FC0),
                ("RED", "red", 0xC00000), ("PURPLE", "purple", 0x6A2AA0)]


def stage_look_key(label, look, lit):
    return button(f"STAGE\\n{label}", bgcolor=DARK, size="18", press=[stage(look)],
                  feedbacks=[feedback(INTERNAL, "check_expression", style={"bgcolor": lit, "color": WHITE},
                                      expression=stage_on(look))])


def stage_color_key():
    """Each press moves to the next colour (pink, blue, red, purple); lit in the colour that's on."""
    key = button("STAGE\\nCOLOR\\ntap to step", bgcolor=DARK, size="18", press=[stage(STAGE_COLORS[0][1])],
                 feedbacks=[feedback(INTERNAL, "check_expression",
                                     style={"bgcolor": lit, "color": WHITE, "text": f"STAGE\\n{label}\\ntap for next"},
                                     expression=stage_on(look)) for label, look, lit in STAGE_COLORS])
    for i, (_, look, _) in enumerate(STAGE_COLORS[1:], start=1):
        key["steps"][str(i)] = {"action_sets": {"down": [stage(look)], "up": []}, "options": {"runWhileHeld": []}}
    return key


def stage_keys():
    keys = [stage_look_key(*look) for look in STAGE_LOOKS] + [stage_color_key()]
    keys.append(button("STAGE\\nOFF", bgcolor=DARK, size="18", press=[stage("off")],
                       feedbacks=[feedback(INTERNAL, "check_expression", style={"bgcolor": RED, "color": WHITE},
                                           expression=stage_on("off"))]))
    spots = [(0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (1, 3)]
    return dict(zip(spots, keys))


# --------------------------------------------------------------------------
# The four room looks. Each one sets the hallway, plugs, house lights, candles and stage
# together (Sam, Nov 2 2026), remembers itself in room_look so its key can light up, and
# starts or stops the recording: recording runs while the SHOW look is on and at no other time.
# --------------------------------------------------------------------------
CAMERA_URL = "http://192.168.86.31/camera/sdk"  # OBSBOT Tail 2 stage camera


def record(on):
    """OBS module v4 "Recording - Controls". Start also points the camera at its Stage preset
    (preset 1, id 0), which undoes any drift: on Nov 8 it followed a front table all show."""
    if not on:
        return [action(OBS, "recording", action="stop")]
    return [action(OBS, "recording", action="start"),
            action(HTTP, "put", url=f"{CAMERA_URL}/ptz/preset", body='{"operation":"call","id":0}', header="",
                   contenttype="application/json", jsonResultDataVariable="", result_stringify=True,
                   statusCodeVariable="")]


def look_daytime():
    return ([a for bulb in HALL_BULBS for a in hall_look(HALL_DAYTIME, bulb)]
            + plugs(True, DAY_PLUGS) + [house("full")] + candles(False)
            + record(False) + [set_var("room_look", "day")])


def look_preshow():
    return ([a for bulb in HALL_BULBS for a in hall_look(HALL_PRESHOW, bulb)]
            + plugs(True) + plugs(True, DAY_PLUGS) + house_both(20) + candles(True)  # house 20% (Sam, Nov 5 2026)
            + [stage(STAGE_PRESHOW)] + record(False) + [set_var("room_look", "pre")])


def look_show():
    # house lights off (Sam, Nov 2); hallway same as PRE-SHOW (Sam, Nov 5 2026). The stage mic
    # is switched on in case it was left muted.
    return ([a for bulb in HALL_BULBS for a in hall_look(HALL_PRESHOW, bulb)]
            + house_both(0) + [stage(STAGE_SHOW)]
            + [action(XAIR, "mute", mute="1", type="/ch/", num=1)]
            + record(True) + [set_var("room_look", "show")])


def look_off():
    return ([govee(bulb, "on_off", "powerSwitch", 0) for bulb in HALL_BULBS]
            + plugs(False) + plugs(False, DAY_PLUGS) + [house("off")] + candles(False)
            + [stage("off")] + record(False) + clock_stop() + [set_var("room_look", "off")])


def look_is(look):
    return f"$(custom:room_look) == '{look}'"


# What the START SHOW key says (Sam, Nov 13 2026: "it should pull how many guests we are
# waiting on"). av/door-count/door_count.py on the office PC reads the door app's check-ins
# and writes the next show's numbers into the door_* variables, so the key reads
#     START / 8 PM SHOW / 31 TO COME      then      START / 8 PM SHOW / ALL HERE
# With no show left tonight, or a reading more than 3 minutes old (script or internet
# down), it is plain START SHOW: a stale count never sits on the deck. Lines are kept to
# 10 letters so the words stay as big as on the other keys.
DOOR_FRESH = "$(internal:time_unix) - $(custom:door_at) < 180 && $(custom:door_left) >= 0"
START_SHOW_TEXT = (
    "$(custom:room_look) == 'show' ? 'SHOW IS ON\\ntap to open' : "
    f"({DOOR_FRESH}) ? concat('START\\n', $(custom:door_show), ' SHOW\\n', "
    "$(custom:door_left) < 1 ? 'ALL HERE' : concat($(custom:door_left), ' TO COME')) : 'START\\nSHOW'"
)


def reset_sound_key():
    """Loads XR18 snapshot 1 "SHOW", the known-good show mix saved Oct 19 2026."""
    return button(
        "RESET\\nSOUND\\nshow mix",
        press=[action(XAIR, "load_snap", snap="1")],
        bgcolor=0x7A3A00,
    )


# --------------------------------------------------------------------------
# Music: Spotify on the office PC, playing into the mixer's MUSIC channel.
# Tonight's test build presses the PC's own media keys (play/pause, next, previous), so the
# deck cannot yet show the song or know whether it is playing.
# --------------------------------------------------------------------------
MEDIA_PLAY_PAUSE, MEDIA_NEXT, MEDIA_PREVIOUS = 179, 176, 177  # Windows media key codes


def media_key(code):
    command = ('powershell -NoProfile -WindowStyle Hidden -Command '
               f'"(New-Object -ComObject WScript.Shell).SendKeys([char]{code})"')
    return action(INTERNAL, "exec", path=f'start "" /min {command}', cwd="", timeout=5000, targetVariable="")


def music_unmute():
    """The old deck "paused" music by muting its channel; make sure that isn't left on."""
    return action(XAIR, "mute", mute="1", **MUSIC["mute_strip"])


def play_pause():
    return [media_key(MEDIA_PLAY_PAUSE), music_unmute()]


# --------------------------------------------------------------------------
# The four knobs and the touch-screen tile above each: MIC, MUSIC, LIGHTS, CLOCK.
# The same on HOME and SHOW, so a knob never changes what it does mid-night.
# --------------------------------------------------------------------------
PAGE_HOME, PAGE_SHOW, PAGE_END, PAGE_MIC, PAGE_MUSIC, PAGE_LIGHTS, PAGE_CLOCK = 1, 2, 3, 4, 5, 6, 7
MIC = CHANNEL(1)  # the stage mic. Mics 2-4 are on the MIC page, each on its own knob.


def main_controls():
    def level_knob(source, push):
        fade = dict(duration=0, faderLim=True, **source["strip"])  # never push past 0 dB
        return button("", press=push,
                      turn_right=[action(XAIR, source["fader_action"], ticks="2", **fade)],
                      turn_left=[action(XAIR, source["fader_action"], ticks="-2", **fade)])

    def is_muted(source, text):
        return feedback(XAIR, source["mute_feedback"], muted(text), state="1", **source["feedback_strip"])

    both = ("tables", "bar")
    return {
        (2, 0): button("MIC\\nvolume $(xair:f_ch1_p)\\npush = on/off", press=[go(PAGE_MIC)], bgcolor=0x143A1D,
                       feedbacks=[is_muted(MIC, "MIC IS OFF\\npush knob\\nto turn on")]),
        (3, 0): level_knob(MIC, [action(XAIR, "mute", mute="2", **MIC["mute_strip"])]),
        (2, 1): button("MUSIC\\nvolume $(xair:f_ch3_p)\\npush = play/pause", press=[go(PAGE_MUSIC)], bgcolor=0x16324A,
                       feedbacks=[is_muted(MUSIC, "MUSIC MUTED\\npush knob\\nto turn on")]),
        (3, 1): level_knob(MUSIC, play_pause()),
        (2, 2): button("LIGHTS\\n$(custom:house_tables)%\\npush = on/off", press=[go(PAGE_LIGHTS)], bgcolor=DARK,
                       feedbacks=[when("$(custom:house_tables) > 0", bgcolor=0x6A5A30, color=WHITE)]),
        (3, 2): button("", press=[house(f"toggle?zone={z}") for z in both],
                       turn_right=[house(f"step?zone={z}&delta={DIM_STEP}") for z in both],
                       turn_left=[house(f"step?zone={z}&delta=-{DIM_STEP}") for z in both]),
        (2, 3): clock_tile(),
        (3, 3): clock_knob(),
    }


# Which of the two main screens the deck belongs on right now: SHOW while the show look is on,
# HOME the rest of the time. Used as a step picker (1 = first choice, 2 = second).
SHOW_IS_ON_STEP = "$(custom:room_look) == 'show' ? 2 : 1"


def go_main(first=()):
    """Press choices for a key that returns to the main screen: HOME, or SHOW during a show.
    (Not Companion's own "back": that does nothing after a restart, which would strand the
    deck on an extras page.)"""
    return dict(steps=[[*first, go(PAGE_HOME)], [*[dict(a, id=_next_id("a")) for a in first], go(PAGE_SHOW)]],
                step_expression=SHOW_IS_ON_STEP)


def back_key():
    return button("BACK", bgcolor=BACK_GREY, **go_main())


def god_mic_key():
    """The announcer's mic in the office (channel 5). Green while it is live."""
    god = CHANNEL(5)
    return button("GOD MIC\\nIS LIVE\\ntap = off", bgcolor=0x1F7A35,
                  press=[action(XAIR, "mute", mute="2", **god["mute_strip"])],
                  feedbacks=[feedback(XAIR, "ch", {"bgcolor": GREY, "color": WHITE, "text": "GOD MIC\\ntap to talk"},
                                      state="1", **god["feedback_strip"])])


def look_key(text, look, actions, lit, extra=()):
    """A room-look key: grey until it is the look that is on, then its own colour."""
    return button(text, bgcolor=GREY, press=actions,
                  feedbacks=[when(look_is(look), bgcolor=lit, color=WHITE, text=f"{text}\\non now"), *extra])


def home_page():
    return {
        "name": "HOME",
        "controls": {
            # the night, left to right
            (0, 0): look_key("DAYTIME", "day", look_daytime(), 0xB08A2E),
            (0, 1): look_key("PRE-SHOW", "pre", look_preshow(), 0x8A6400),
            # If the show look is already on (the deck restarted mid-show), a tap only opens
            # the SHOW screen; it does not run the look again.
            (0, 2): button(START_SHOW_TEXT, expression=True, bgcolor=SHOW_COLOR,
                           steps=[look_show() + [go(PAGE_SHOW)], [go(PAGE_SHOW)]], step_expression=SHOW_IS_ON_STEP,
                           feedbacks=[when(look_is("show"), bgcolor=RED, color=WHITE)]),
            (0, 3): look_key("ALL OFF", "off", look_off(), 0x555555, extra=[battery_warning("ALL OFF")]),
            (1, 0): god_mic_key(),
            (1, 1): button("NEXT\\nSONG", bgcolor=GREY, press=[media_key(MEDIA_NEXT)]),
            (1, 2): print_menu_key(),
            (1, 3): menu_refresh_key(),
            **main_controls(),
        },
    }


def show_page():
    """What the deck shows while a show is on. END SHOW is the only way back to HOME, so no
    stray press can bring the house lights up or stop the recording mid-show."""
    return {
        "name": "SHOW",
        "controls": {
            # Orange and saying so if OBS is not recording; a tap then starts it.
            (0, 0): button("SHOW IS ON\\nNOT RECORDING\\ntap = record", bgcolor=0xB06000, press=record(True),
                           feedbacks=[feedback(OBS, "recording",
                                               {"bgcolor": RED, "color": WHITE,
                                                "text": "SHOW IS ON\\nREC\\n$(obs:recording_timecode)"})]),
            (0, 3): button("END\\nSHOW", bgcolor=GREY, press=[go(PAGE_END)], feedbacks=[battery_warning("END SHOW")]),
            (1, 0): god_mic_key(),
            (1, 1): button("START\\nCLOCK", bgcolor=0x1F7A35, press=clock_start(),
                           feedbacks=[when(CLOCK_RUNNING, bgcolor=0x2FA04A, color=WHITE,
                                           text="RESTART\\nCLOCK\\nnext comic")]),
            (1, 2): button("WRAP\\nIT UP", bgcolor=0x8A1C1C, press=clock_wrap(),
                           feedbacks=[when("$(custom:timer_wrap) == 1", bgcolor=0xFF2020, color=WHITE,
                                           text="WRAP IT UP\\nIS ON\\ntap = clear")]),
            (1, 3): button("STOP\\nCLOCK", bgcolor=GREY, press=clock_stop(),
                           feedbacks=[when(CLOCK_RUNNING, bgcolor=0x7A3A00, color=WHITE)]),
            **main_controls(),
        },
    }


def end_show_page():
    """"Are you sure?" NO sits where END SHOW was, so a double tap on END SHOW cancels itself.
    YES brings the pre-show look back (which stops the recording), stops the comic clock and
    returns to HOME."""
    return {
        "name": "END SHOW?",
        "controls": {
            (0, 0): button("END THE\\nSHOW?", bgcolor=BLACK),
            (0, 3): button("NO\\nGO BACK", bgcolor=BACK_GREY, press=[go(PAGE_SHOW)]),
            (1, 1): button("YES\\nEND SHOW\\nlights up", bgcolor=RED,
                           press=look_preshow() + clock_stop() + [go(PAGE_HOME)]),
            **main_controls(),
        },
    }


def mic_page():
    """Tap MIC: each stage mic on its own knob (turn = volume, push or tap = on/off), an
    on/off key for each, the god mic's volume and RESET SOUND."""
    god_fade = dict(duration=0, faderLim=True, type="/ch/", num=5)
    return {
        "name": "MIC",
        "controls": {
            (0, 0): back_key(),
            (0, 1): reset_sound_key(),
            (0, 2): button("GOD MIC\\nQUIETER", bgcolor=GREY, press=[action(XAIR, "fad_a", ticks="-3", **god_fade)]),
            (0, 3): button("GOD MIC\\nLOUDER", bgcolor=GREY, press=[action(XAIR, "fad_a", ticks="3", **god_fade)]),
            **show_mute_keys(SOURCES_4),
            **sound_controls(SOURCES_4),
        },
    }


def music_page():
    return {
        "name": "MUSIC",
        "controls": {
            (0, 0): back_key(),
            (0, 1): button("PLAY /\\nPAUSE", bgcolor=0x16324A, press=play_pause()),
            (0, 2): button("NEXT\\nSONG", bgcolor=0x16324A, press=[media_key(MEDIA_NEXT)]),
            (0, 3): button("LAST\\nSONG", bgcolor=0x16324A, press=[media_key(MEDIA_PREVIOUS)]),
            **main_controls(),
        },
    }


def lights_page():
    """Tap LIGHTS: the stage looks on the keys, the two house dimmers on knobs 1 and 2, and
    the candles on the touch screen (IR can't report back, so ON and OFF are separate taps)."""
    controls = {(0, 0): back_key(), **stage_keys()}
    for col, (zone, name) in enumerate((("tables", "TABLES"), ("bar", "BAR"))):
        controls[(2, col)] = dimmer_strip(zone, name)
        controls[(3, col)] = dimmer_knob(zone)
    controls[(2, 2)] = button("CANDLES\\nON\\ntap", bgcolor=CANDLE_COLOR, press=candles(True))
    controls[(2, 3)] = button("CANDLES\\nOFF\\ntap", bgcolor=DARK, press=candles(False))
    return {"name": "LIGHTS", "controls": controls}


def clock_page():
    """Tap CLOCK: one tap picks a set length and returns to the main screen. It does not start
    the clock."""
    spots = [(0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (1, 3)]
    controls = {(0, 0): back_key(), **main_controls()}
    for spot, minutes in zip(spots, CLOCK_PRESETS):
        controls[spot] = button(f"{minutes} MIN\\nSET", bgcolor=GREY,
                                **go_main([set_number("timer_min", minutes)]),
                                feedbacks=[when(f"{_MIN} == {minutes}", bgcolor=0x1F7A35, color=WHITE)])
    return {"name": "CLOCK", "controls": controls}


# --------------------------------------------------------------------------
# PAGES: edit the page functions above. Keys are (row, column).
# --------------------------------------------------------------------------
PAGES = {
    PAGE_HOME: home_page(),
    PAGE_SHOW: show_page(),
    PAGE_END: end_show_page(),
    PAGE_MIC: mic_page(),
    PAGE_MUSIC: music_page(),
    PAGE_LIGHTS: lights_page(),
    PAGE_CLOCK: clock_page(),
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
        "custom_variables": {
            name: {"description": desc, "defaultValue": default, "persistCurrentValue": False, "sortOrder": i}
            for i, (name, (desc, default)) in enumerate(CUSTOM_VARIABLES.items())
        },
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {OUT}")
