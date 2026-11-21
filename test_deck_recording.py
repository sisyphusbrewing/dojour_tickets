"""Tests for "a show can't record silent" on the showroom Stream Deck (Nov 20 2026).

Only one OBS scene has the room's sound on it. A recording started while OBS sits on any
other scene has a picture and no sound, so every key that starts the recording has to put
OBS on that scene first. These read the deck the generator builds; they don't need
Companion or OBS."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "deck", Path(__file__).parent / "av/companion/build_companion_config.py")
deck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deck)


def control(page, row, col):
    return deck.PAGES[page]["controls"][(row, col)]


def presses(ctrl):
    """What each press choice does: a list (one per choice) of (connection, action, options)."""
    out = []
    for i in sorted(ctrl["steps"], key=int):
        out.append([(a["connectionId"], a["definitionId"], {k: v["value"] for k, v in a["options"].items()})
                    for a in ctrl["steps"][i]["action_sets"]["down"]])
    return out


def obs(step):
    """The OBS actions in one press choice, in the order the deck sends them."""
    return [(name, opts) for conn, name, opts in step if conn == deck.OBS]


def every_press():
    """Every press choice of every key, knob and touch tile on the deck."""
    for page in deck.PAGES.values():
        for ctrl in page["controls"].values():
            for step in presses(ctrl):
                yield step


class StartingTheRecording(unittest.TestCase):
    def test_start_show_goes_to_the_show_scene_then_records(self):
        normal, show_already_on, music_already_out = presses(control(deck.PAGE_HOME, 0, 2))
        for step in (normal, music_already_out):
            self.assertEqual(obs(step), [("set_scene", {"scene": deck.OBS_SHOW_SCENE}),
                                         ("recording", {"action": "start"})])
        # The deck restarted mid-show: the key only opens the SHOW screen and must not
        # touch OBS (a scene change would show up in the recording).
        self.assertEqual(obs(show_already_on), [])

    def test_the_tap_to_record_key_does_the_same(self):
        (step,) = presses(control(deck.PAGE_SHOW, 0, 0))
        self.assertEqual(obs(step), [("set_scene", {"scene": deck.OBS_SHOW_SCENE}),
                                     ("recording", {"action": "start"})])

    def test_nothing_starts_a_recording_without_the_scene_first(self):
        starts = 0
        for step in every_press():
            actions = obs(step)
            for i, (name, opts) in enumerate(actions):
                if name == "recording" and opts.get("action") in ("start", "toggle"):
                    starts += 1
                    self.assertIn(("set_scene", {"scene": deck.OBS_SHOW_SCENE}), actions[:i])
        self.assertGreaterEqual(starts, 3)   # START SHOW (two of its three choices) and tap = record

    def test_the_scene_is_only_changed_when_a_recording_starts(self):
        # Stopping, the other looks and every other key leave OBS's scene alone.
        for step in every_press():
            names = [name for name, _ in obs(step)]
            if "set_scene" in names:
                self.assertIn("recording", names)

    def test_the_other_looks_only_stop_the_recording(self):
        for col in (0, 1, 3):   # DAYTIME, PRE-SHOW, ALL OFF
            for step in presses(control(deck.PAGE_HOME, 0, col)):
                self.assertEqual(obs(step), [("recording", {"action": "stop"})])

if __name__ == "__main__":
    unittest.main()
