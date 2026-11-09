"""Tests for the office-PC recording splitter's audio fallback (Sam, Nov 9 2026):
when nobody presses the stage timer, sets are found from the host's intros."""
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("split_and_share", Path(__file__).parent / "av/recordings/split_and_share.py")
sas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sas)

KNOWN = ["Joey Hamburger", "Mike Lester", "Ahmed Khalaf", "Kellen Schneider", "Michael Longfellow"]


def talk(start, end, every=20, text="and that's the thing about Minneapolis"):
    """Ordinary set chatter: one short line every `every` seconds."""
    return [{"start": t, "end": t + 8, "text": text} for t in range(start, end, every)]


class AudioSets(unittest.TestCase):
    def show(self):
        segs = talk(0, 600)  # host opener
        segs += [{"start": 600, "end": 605, "text": "Please give it up for Mike Lester, everybody!"}]
        segs += talk(610, 1200)
        segs += [{"start": 1200, "end": 1205, "text": "Make some noise for the very funny Kellyn Schneider, everybody"}]
        segs += talk(1210, 2400)
        segs += [{"start": 2400, "end": 2405, "text": "Welcome to the stage Michael Longfellow, everybody!"}]
        segs += talk(2410, 6000)
        segs += [{"start": 6000, "end": 6004, "text": "One more time for Michael Longfellow! Thanks for coming"}]
        return segs

    def test_splits_at_intros_and_names_each_comic(self):
        sets = sas.audio_sets(self.show(), 6200, KNOWN)
        self.assertEqual([n for _, _, n in sets][1:], ["Mike Lester", "Kellen Schneider", "Michael Longfellow"])
        self.assertEqual([a for a, _, _ in sets][1:], [600, 1200, 2400])
        self.assertAlmostEqual(sets[-1][1], 6009, delta=1)  # ends at the host's sign-off, not the end of the file

    def test_host_opener_is_its_own_set(self):
        a, b, _ = sas.audio_sets(self.show(), 6200, KNOWN)[0]
        self.assertEqual((a, b), (0, 600))

    def test_long_silence_ends_the_show(self):
        segs = self.show()[:-1] + talk(6600, 7200)  # 10 min break, then the next show's crowd
        last = sas.audio_sets(segs, 7300, KNOWN)[-1]
        self.assertLess(last[1], 6100)

    def test_no_intros_in_a_long_file_means_unsorted(self):
        self.assertEqual(sas.audio_sets(talk(0, 6000), 6000, KNOWN), [])

    def test_no_intros_in_a_short_file_is_one_set(self):
        self.assertEqual(len(sas.audio_sets(talk(0, 1800), 1800, KNOWN)), 1)

    def test_fix_name_snaps_whisper_spellings(self):
        self.assertEqual(sas.fix_name("Ahmaq Alaf", KNOWN), "Ahmed Khalaf")
        self.assertEqual(sas.fix_name("Dave Chappelle", KNOWN), "Dave Chappelle")  # not on the list: left alone
        self.assertEqual(sas.fix_name("Kellyn Schneider", KNOWN), "Kellen Schneider")
        self.assertEqual(sas.fix_name("Kellen", KNOWN), "Kellen Schneider")


if __name__ == "__main__":
    unittest.main()
