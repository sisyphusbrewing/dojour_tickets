"""Tests for the open mic lineup on the showroom Stream Deck (Sam, Nov 17 2026: "Can we have
the comedy line up run through the Stream Deck for the tuesday night shows?").

START SHOW loads tonight's lineup, START NEXT COMIC moves it on, UP NEXT skips a comic who
isn't there, END SHOW forgets it. On a night with no lineup the deck has to work exactly as
before. These read the deck the generator builds; they don't need Companion. The database
side is checked by supabase/tests/mic_deck/."""
import importlib.util
import json
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "deck", Path(__file__).parent / "av/companion/build_companion_config.py")
deck = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deck)


def control(page, row, col):
    return deck.PAGES[page]["controls"][(row, col)]


def presses(ctrl):
    out = []
    for i in sorted(ctrl["steps"], key=int):
        out.append([(a["definitionId"], {k: v["value"] for k, v in a["options"].items()})
                    for a in ctrl["steps"][i]["action_sets"]["down"]])
    return out


def lineup_moves(step):
    """The mic_deck moves one press choice sends, in order."""
    return [json.loads(o["body"])["move"] for n, o in step
            if n == "post" and o["url"].endswith("/rpc/mic_deck")]


def sets(step, variable):
    return [o["value"] for n, o in step if n == "custom_variable_set_value" and o["name"] == variable]


class Calls(unittest.TestCase):
    def test_answer_is_kept_in_the_mic_variable(self):
        act = deck.lineup_call("next")
        opts = {k: v["value"] for k, v in act["options"].items()}
        self.assertEqual(opts["url"], f"{deck.SUPABASE}/rest/v1/rpc/mic_deck")
        self.assertEqual(json.loads(opts["body"]), {"move": "next"})
        self.assertEqual(opts["jsonResultDataVariable"], "mic")
        self.assertTrue(opts["result_stringify"])

    def test_mic_variable_starts_off(self):
        self.assertEqual(json.loads(deck.CUSTOM_VARIABLES["mic"][1]), {"on": False})
        self.assertEqual(deck.LINEUP_OFF, deck.CUSTOM_VARIABLES["mic"][1])

    def test_other_calls_keep_nothing(self):
        opts = deck.supabase_call("timer_stop")["options"]
        self.assertEqual(opts["jsonResultDataVariable"]["value"], "")


class StartShow(unittest.TestCase):
    def test_every_choice_loads_the_lineup(self):
        for step in presses(control(deck.PAGE_HOME, 0, 2)):
            self.assertEqual(lineup_moves(step), ["load"])


class NextComic(unittest.TestCase):
    def setUp(self):
        self.key = control(deck.PAGE_SHOW, 1, 1)
        self.no_lineup, self.next_on, self.last_done, self.double_tap = presses(self.key)

    def test_no_lineup_is_the_old_start_clock(self):
        names = [n for n, _ in self.no_lineup]
        self.assertIn("post", names)
        self.assertTrue(any(o["url"].endswith("/rpc/timer_start") for n, o in self.no_lineup if n == "post"))
        self.assertEqual(sets(self.no_lineup, "timer_t0"), ["$(internal:time_unix)"])
        self.assertEqual(lineup_moves(self.no_lineup), ["load"])

    def test_next_comic_moves_on_and_starts_at_their_length(self):
        self.assertEqual(lineup_moves(self.next_on), ["next"])
        self.assertEqual(sets(self.next_on, "timer_min"), [deck.mic("next_min")])
        self.assertEqual(sets(self.next_on, "timer_t0"), ["$(internal:time_unix)"])
        # the length is read before the answer arrives, so it must be set before the call
        order = [n if n != "custom_variable_set_value" else o["name"] for n, o in self.next_on]
        self.assertLess(order.index("timer_min"), order.index("post"))
        # the database starts the comic's clock itself; the deck must not start it twice
        self.assertFalse(any(o["url"].endswith("/rpc/timer_start") for n, o in self.next_on if n == "post"))

    def test_last_comic_done_stops_the_clock(self):
        self.assertEqual(lineup_moves(self.last_done), ["next"])
        self.assertTrue(any(o["url"].endswith("/rpc/timer_stop") for n, o in self.last_done if n == "post"))

    def test_double_tap_does_nothing(self):
        self.assertEqual(self.double_tap, [])
        self.assertIn(f"< {deck.NEXT_COMIC_GUARD_S}) ? 4", self.key["options"]["stepExpression"])

    def test_no_lineup_comes_first(self):
        self.assertTrue(self.key["options"]["stepExpression"].startswith(f"!({deck.LINEUP_ON}) ? 1"))


class UpNext(unittest.TestCase):
    def test_tap_skips_only_when_someone_is_next(self):
        key = control(deck.PAGE_SHOW, 0, 2)
        nothing, skip = presses(key)
        self.assertEqual(nothing, [])
        self.assertEqual(lineup_moves(skip), ["skip"])
        self.assertEqual(key["options"]["stepExpression"], f"({deck.LINEUP_ON}) && {deck.mic('next')} != '' ? 2 : 1")


class EndShow(unittest.TestCase):
    def test_yes_forgets_the_lineup(self):
        for step in presses(control(deck.PAGE_END, 1, 1)):
            self.assertEqual(sets(step, "mic"), [deck.LINEUP_OFF])


class Blank(unittest.TestCase):
    def test_no_lineup_keys_are_blank(self):
        for text in (deck.ON_NOW_TEXT, deck.UP_NEXT_TEXT):
            self.assertTrue(text.startswith(f"!({deck.LINEUP_ON}) ? '' : "))


if __name__ == "__main__":
    unittest.main()
