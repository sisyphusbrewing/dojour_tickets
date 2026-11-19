"""Tests for walk-on songs (Sam, Nov 19 2026: "Before a show we should let comics pick a walk
up song and we can integrate that into the deck"): the office PC helper that plays each
comic's song (av/walkon/walkon.py) and the deck keys that drive it. No network, no Spotify."""
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, HERE / path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wo = load("walkon", "av/walkon/walkon.py")
deck = load("deck", "av/companion/build_companion_config.py")

TONIGHT = {"people": [
    {"role": "host", "name": "Aiden McCluskey", "song": {}, "query": ""},
    {"role": "feature", "name": "Tommy Bayer", "song": {"title": "Thunderstruck", "artist": "AC/DC", "start_sec": 12}, "query": ""},
    {"role": "headliner", "name": "Jeffrey Keller", "song": {},
     "query": "Song: Requiem: K. 626: Lacrimosa - Artist: Mozart. START AT: 2:10"},
]}


class ReadTyped(unittest.TestCase):
    def test_older_advance_text_becomes_search_words_and_a_start(self):
        words, start = wo.read_typed("Song: Requiem: K. 626: Lacrimosa - Artist: Wolfgang  Amadeus Mozart, Czech Ssymphony Orchestra. START AT: 2:10")
        self.assertEqual(start, 130)
        self.assertIn("Lacrimosa", words)
        self.assertIn("Mozart", words)
        self.assertNotIn("START", words.upper().split())
        self.assertNotIn(":", words)

    def test_plain_text_starts_at_the_top(self):
        self.assertEqual(wo.read_typed("Thunderstruck by AC/DC"), ("Thunderstruck AC DC", 0))

    def test_nothing(self):
        self.assertEqual(wo.read_typed(""), ("", 0))


class Lineup(unittest.TestCase):
    def setUp(self):
        self.people = wo.lineup(TONIGHT)

    def test_running_order_and_roles(self):
        self.assertEqual([(p["role"], p["name"]) for p in self.people],
                         [("Host", "Aiden McCluskey"), ("Feature", "Tommy Bayer"), ("Headliner", "Jeffrey Keller")])

    def test_a_picked_song_keeps_its_start(self):
        self.assertEqual(self.people[1]["start_sec"], 12)
        self.assertEqual(wo.search_query(self.people[1]), 'track:"Thunderstruck" artist:"AC/DC"')

    def test_no_pick_means_no_song(self):
        self.assertEqual(self.people[0]["title"], "")
        self.assertEqual(wo.search_query(self.people[0]), "")

    def test_typed_advance_answer_is_searched_as_words(self):
        self.assertEqual(self.people[2]["start_sec"], 130)
        self.assertTrue(self.people[2]["title"])            # the key says there is a song
        self.assertFalse(wo.search_query(self.people[2]).startswith("track:"))

    def test_empty_night(self):
        self.assertEqual(wo.lineup({"people": []}), [])
        self.assertEqual(wo.lineup(None), [])


class DeckValues(unittest.TestCase):
    def test_up_next_and_after(self):
        people = wo.lineup(TONIGHT)
        v = wo.deck_values(people, 1, False)
        self.assertEqual((v["walkon_count"], v["walkon_name"], v["walkon_song"], v["walkon_then"], v["walkon_playing"]),
                         (3, "Tommy Bayer", "Thunderstruck", "Jeffrey Keller", 0))

    def test_after_the_last_comes_the_first_again(self):
        v = wo.deck_values(wo.lineup(TONIGHT), 2, True)
        self.assertEqual((v["walkon_then"], v["walkon_playing"]), ("Aiden McCluskey", 1))

    def test_one_person_has_nobody_after(self):
        v = wo.deck_values(wo.lineup({"people": TONIGHT["people"][:1]}), 0, False)
        self.assertEqual(v["walkon_then"], "")

    def test_nobody_tonight_blanks_the_keys(self):
        self.assertEqual(wo.deck_values([], 0, False)["walkon_count"], 0)

    def test_every_value_is_a_deck_variable(self):
        for name in wo.deck_values(wo.lineup(TONIGHT), 0, False):
            self.assertIn(name, deck.CUSTOM_VARIABLES)


class KeepPlace(unittest.TestCase):
    def test_a_re_read_stays_on_the_same_comic(self):
        old = wo.lineup(TONIGHT)
        new = [old[1], old[2]]   # the host came off the board
        self.assertEqual(wo.keep_place(old, new, 1), 0)

    def test_gone_comic_stays_in_range(self):
        old = wo.lineup(TONIGHT)
        self.assertEqual(wo.keep_place(old, old[:1], 2), 0)
        self.assertEqual(wo.keep_place(old, [], 2), 0)


class PickTrack(unittest.TestCase):
    PERSON = {"title": "Thunderstruck", "artist": "AC/DC", "query": "Thunderstruck AC/DC"}

    def track(self, name, artist):
        return {"name": name, "uri": f"spotify:track:{name}-{artist}", "artists": [{"name": artist}]}

    def test_skips_karaoke_and_covers(self):
        items = [self.track("Thunderstruck (Karaoke Version)", "Hit Masters"),
                 self.track("Thunderstruck", "2Cellos"),
                 self.track("Thunderstruck", "AC/DC")]
        self.assertEqual(wo.pick_track(items, self.PERSON)["artists"][0]["name"], "AC/DC")

    def test_falls_back_to_the_first_real_answer(self):
        items = [self.track("Thunderstruck - Live", "Somebody")]
        self.assertEqual(wo.pick_track(items, self.PERSON)["artists"][0]["name"], "Somebody")

    def test_nothing_found(self):
        self.assertIsNone(wo.pick_track([], self.PERSON))


class Device(unittest.TestCase):
    def test_this_pc_by_name(self):
        devices = [{"id": "phone", "type": "Smartphone", "name": "Sam's iPhone", "is_active": True},
                   {"id": "mac", "type": "Computer", "name": "Sams-MacBook", "is_active": False},
                   {"id": "pc", "type": "Computer", "name": "DESKTOP-8QOGQGK", "is_active": False}]
        self.assertEqual(wo.pick_device(devices, "desktop-8qogqgk")["id"], "pc")

    def test_never_a_phone(self):
        self.assertIsNone(wo.pick_device([{"id": "phone", "type": "Smartphone", "name": "x", "is_active": True}], "pc"))


class PutBack(unittest.TestCase):
    def test_playlist_resumes_where_it_was(self):
        saved = {"is_playing": True, "progress_ms": 61000, "item": {"uri": "spotify:track:a"},
                 "context": {"uri": "spotify:playlist:p"}}
        self.assertEqual(wo.restore_body(saved), {"context_uri": "spotify:playlist:p", "offset": {"uri": "spotify:track:a"}, "position_ms": 61000})

    def test_no_playlist_just_the_song(self):
        saved = {"progress_ms": 5, "item": {"uri": "spotify:track:a"}, "context": None}
        self.assertEqual(wo.restore_body(saved), {"uris": ["spotify:track:a"], "position_ms": 5})

    def test_nothing_was_playing(self):
        self.assertIsNone(wo.restore_body(None))


class FakeSpotify:
    ready = True

    def __init__(self):
        self.calls = []

    def find(self, person):
        return {"uri": "spotify:track:" + person["title"], "name": person["title"], "artists": [{"name": "x"}]}

    def device(self):
        return {"id": "pc"}

    def now_playing(self):
        return {"is_playing": True, "progress_ms": 1000, "item": {"uri": "spotify:track:house"}, "context": {"uri": "spotify:playlist:house"}}

    def play(self, device_id, body):
        self.calls.append(("play", body))

    def pause(self, device_id):
        self.calls.append(("pause", None))


class Helper(unittest.TestCase):
    def setUp(self):
        self.sp = FakeSpotify()
        self.w = wo.Walkon(self.sp)
        self.w.tell_deck = lambda: None
        self.w.people = wo.lineup(TONIGHT)
        wo.FADE_WAIT = 0

    def test_play_starts_their_song_where_they_asked(self):
        self.w.pos = 1
        self.assertEqual(self.w.play(), "playing")
        self.assertEqual(self.sp.calls[0], ("play", {"uris": ["spotify:track:Thunderstruck"], "position_ms": 12000}))
        self.assertTrue(self.w.playing)

    def test_stop_moves_on_and_puts_the_playlist_back(self):
        self.w.pos = 1
        self.w.play()
        self.assertEqual(self.w.stop(), "stopped")
        self.assertEqual(self.w.pos, 2)
        import time
        for _ in range(50):
            if len(self.sp.calls) > 1:
                break
            time.sleep(0.02)
        self.assertEqual(self.sp.calls[1], ("play", {"context_uri": "spotify:playlist:house", "offset": {"uri": "spotify:track:house"}, "position_ms": 1000}))

    def test_no_song_plays_nothing_but_still_counts(self):
        self.w.pos = 0
        self.assertIn("house music", self.w.play())
        self.assertEqual(self.sp.calls, [])
        self.w.stop()
        self.assertEqual(self.w.pos, 1)

    def test_a_second_play_does_nothing(self):
        self.w.pos = 1
        self.w.play()
        self.assertEqual(self.w.play(), "already playing")
        self.assertEqual(len(self.sp.calls), 1)

    def test_skip_wraps_and_never_while_playing(self):
        self.w.pos = 2
        self.w.skip()
        self.assertEqual(self.w.pos, 0)
        self.w.pos = 1
        self.w.play()
        self.w.skip()
        self.assertEqual(self.w.pos, 1)


class DeckKeys(unittest.TestCase):
    def setUp(self):
        self.key = deck.PAGES[deck.PAGE_SHOW]["controls"][(0, 1)]
        self.steps = [[(a["definitionId"], {k: v["value"] for k, v in a["options"].items()}) for a in self.key["steps"][i]["action_sets"]["down"]]
                      for i in sorted(self.key["steps"], key=int)]

    def urls(self, step):
        return [o["url"] for n, o in step if n == "get"]

    def test_five_choices(self):
        nothing, play_out, play_up, fade, stop = self.steps
        self.assertEqual(nothing, [])
        self.assertEqual(self.urls(play_out), [deck.WALKON_URL + "/play"])
        self.assertTrue(any(n == "fad_r" for n, _ in play_out))        # fader back up for the song
        self.assertFalse(any(n.startswith("fad") for n, _ in play_up))  # music already up: leave it
        self.assertEqual(self.urls(fade), [deck.WALKON_URL + "/stop"])
        self.assertTrue(any(n == "fad" for n, _ in fade))
        self.assertEqual(self.urls(stop), [deck.WALKON_URL + "/stop"])
        self.assertFalse(any(n.startswith("fad") for n, _ in stop))

    def test_open_mic_nights_keep_the_lineup(self):
        self.assertTrue(self.key["options"]["stepExpression"].startswith(f"{deck.LINEUP_ON} || !({deck.WALKON_ON}) ? 1"))

    def test_the_helper_presses_this_key(self):
        self.assertEqual(wo.WALKON_KEY, f"/api/location/{deck.PAGE_SHOW}/0/1/press")

    def test_start_show_loads_tonight(self):
        start = deck.PAGES[deck.PAGE_HOME]["controls"][(0, 2)]
        for i in start["steps"]:
            urls = [a["options"]["url"]["value"] for a in start["steps"][i]["action_sets"]["down"] if a["definitionId"] == "get"]
            self.assertIn(deck.WALKON_URL + "/load", urls)


if __name__ == "__main__":
    unittest.main()
