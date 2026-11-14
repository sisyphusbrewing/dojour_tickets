"""Tests for "music follows the show" on the showroom Stream Deck (Sam, Nov 13 2026:
"the music didn't automatically turn down when I hit start show").

START SHOW has to fade the music out, END SHOW has to bring it back, and nothing may
"remember" the music level while it is already faded out (it would remember silence, and
the music would never come back). These read the deck the generator builds; they don't
need Companion or the mixer."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "deck", Path(__file__).parent / "av/companion/build_companion_config.py")
deck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deck)

MUSIC_CHANNEL = 3


def control(page, row, col):
    return deck.PAGES[page]["controls"][(row, col)]


def presses(ctrl):
    """What each press choice does: a list (one per choice) of (action, options) pairs."""
    out = []
    for i in sorted(ctrl["steps"], key=int):
        out.append([(a["definitionId"], {k: v["value"] for k, v in a["options"].items()})
                    for a in ctrl["steps"][i]["action_sets"]["down"]])
    return out


def names(step):
    return [name for name, _ in step]


def music(step, name):
    """The mixer actions called `name` on the MUSIC channel in one press choice."""
    return [opts for n, opts in step if n == name and opts.get("num") == MUSIC_CHANNEL]


def sets(step, variable):
    return [opts["value"] for n, opts in step if n == "custom_variable_set_value" and opts["name"] == variable]


class StartShow(unittest.TestCase):
    def setUp(self):
        self.key = control(deck.PAGE_HOME, 0, 2)
        self.normal, self.show_already_on, self.music_already_out = presses(self.key)

    def test_picks_the_right_choice(self):
        self.assertEqual(self.key["options"]["stepProgression"], "expression")
        self.assertEqual(self.key["options"]["stepExpression"],
                         "$(custom:room_look) == 'show' ? 2 : ($(custom:music_out) == 1 ? 3 : 1)")

    def test_fades_the_music_out(self):
        step = names(self.normal)
        self.assertEqual(len(music(self.normal, "fad_s")), 1)
        fade = music(self.normal, "fad")
        self.assertEqual(len(fade), 1)
        self.assertEqual(fade[0]["fad"], "0.0")            # all the way down
        self.assertEqual(fade[0]["duration"], 3000)        # over 3 seconds
        # the level is remembered before the fade starts, or it would remember silence
        self.assertLess(step.index("fad_s"), step.index("fad"))
        self.assertEqual(sets(self.normal, "music_out"), ["1"])
        self.assertEqual(sets(self.normal, "room_look"), ["show"])

    def test_show_already_on_only_opens_the_show_screen(self):
        self.assertEqual(names(self.show_already_on), ["set_page"])

    def test_music_already_out_is_not_remembered_again(self):
        self.assertEqual(music(self.music_already_out, "fad_s"), [])
        self.assertEqual(music(self.music_already_out, "fad"), [])
        self.assertEqual(sets(self.music_already_out, "room_look"), ["show"])   # the show still starts


class EndShow(unittest.TestCase):
    def setUp(self):
        self.key = control(deck.PAGE_END, 1, 1)
        self.music_in, self.music_out = presses(self.key)

    def test_brings_the_music_back_when_it_is_out(self):
        self.assertEqual(self.key["options"]["stepExpression"], "$(custom:music_out) == 1 ? 2 : 1")
        back = music(self.music_out, "fad_r")
        self.assertEqual(len(back), 1)
        self.assertTrue(back[0]["faderLim"])               # never louder than 0 dB
        self.assertEqual(sets(self.music_out, "music_out"), ["0"])

    def test_leaves_the_music_alone_when_staff_already_brought_it_back(self):
        self.assertEqual(music(self.music_in, "fad_r"), [])
        self.assertEqual(sets(self.music_in, "music_out"), [])

    def test_both_choices_still_end_the_show(self):
        for step in (self.music_in, self.music_out):
            self.assertEqual(sets(step, "room_look"), ["pre"])
            self.assertEqual(names(step)[-1], "set_page")


class MusicKnob(unittest.TestCase):
    def test_push_brings_music_back_instead_of_pausing_it(self):
        for page in (deck.PAGE_HOME, deck.PAGE_SHOW, deck.PAGE_MUSIC, deck.PAGE_CLOCK):
            knob = control(page, 3, 1)
            play_pause, bring_back = presses(knob)
            self.assertEqual(knob["options"]["stepExpression"], "$(custom:music_out) == 1 ? 2 : 1")
            self.assertIn("exec", names(play_pause))           # the PC's play/pause key
            self.assertNotIn("exec", names(bring_back))        # which would pause the music it just raised
            self.assertEqual(len(music(bring_back, "fad_r")), 1)
            self.assertEqual(sets(bring_back, "music_out"), ["0"])

    def test_turning_works_the_same_either_way(self):
        knob = control(deck.PAGE_SHOW, 3, 1)
        turns = [[a["definitionId"] for a in knob["steps"][i]["action_sets"][side]]
                 for i in knob["steps"] for side in ("rotate_left", "rotate_right")]
        self.assertEqual(turns, [["fad_a"]] * 4)


class WholeDeck(unittest.TestCase):
    def test_level_is_only_remembered_where_music_out_is_checked(self):
        """Any control that remembers the music level must pick its press by music_out,
        and may only remember it in the first choice (music not out)."""
        found = 0
        for page in deck.PAGES.values():
            for ctrl in page["controls"].values():
                for i, step in enumerate(presses(ctrl)):
                    if music(step, "fad_s"):
                        found += 1
                        self.assertEqual(i, 0)
                        self.assertIn("$(custom:music_out) == 1", ctrl["options"]["stepExpression"])
        self.assertEqual(found, 2)   # START SHOW, and the FADE MUSIC OUT key on the MUSIC screen

    def test_music_out_variable_starts_at_zero(self):
        self.assertEqual(deck.CUSTOM_VARIABLES["music_out"][1], 0)


if __name__ == "__main__":
    unittest.main()
