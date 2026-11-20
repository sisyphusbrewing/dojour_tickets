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

    def test_intro_without_everybody_counts_for_a_known_comic(self):
        # Sat Nov 14 6 PM: "Please give it up for Gabby Bryan." and no "everybody" after it.
        segs = talk(0, 600) + [{"start": 600, "end": 604, "text": "Please give it up for Gabby Bryan."}] + talk(610, 4000)
        sets = sas.audio_sets(segs, 4100, KNOWN + ["Gabby Bryan"])
        self.assertEqual([(a, n) for a, _, n in sets][-1], (600, "Gabby Bryan"))

    def test_give_it_up_for_a_stranger_is_not_an_intro(self):
        segs = talk(0, 600) + [{"start": 600, "end": 604, "text": "Give it up for Pete Behind The Bar."}] + talk(610, 1800)
        self.assertEqual(len(sas.audio_sets(segs, 1800, KNOWN)), 1)

    def test_same_comic_introduced_twice_is_one_set(self):
        # Sat Nov 14 8 PM: Whisper heard "Lahiru" then "Lehiro" and made two clips of one set.
        segs = talk(0, 300)
        segs += [{"start": 300, "end": 304, "text": "Make some noise for Lahiru Perera, everybody"}] + talk(310, 700)
        segs += [{"start": 700, "end": 704, "text": "Keep it going, welcome Lehiro Perera, everybody"}] + talk(710, 1100)
        segs += [{"start": 1100, "end": 1104, "text": "Please give it up for Mike Lester, everybody"}] + talk(1110, 1800)
        sets = sas.audio_sets(segs, 1800, KNOWN)
        self.assertEqual([(a, b) for a, b, _ in sets][1:], [(300, 1100), (1100, 1800)])

    def test_fix_name_snaps_whisper_spellings(self):
        self.assertEqual(sas.fix_name("Ahmaq Alaf", KNOWN), "Ahmed Khalaf")
        self.assertEqual(sas.fix_name("Dave Chappelle", KNOWN), "Dave Chappelle")  # not on the list: left alone
        self.assertEqual(sas.fix_name("Kellyn Schneider", KNOWN), "Kellen Schneider")
        self.assertEqual(sas.fix_name("Kellen", KNOWN), "Kellen Schneider")


class Cleanup(unittest.TestCase):
    """Old clip folders go even when they hold a "transcripts" folder (the
    Nov 18 2026 run stopped with Access denied on one)."""
    def test_old_folder_with_subfolder_is_removed(self):
        import os, tempfile, time
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "clips"
            old = out / "2026-01-01 show"
            (old / "transcripts").mkdir(parents=True)
            (old / "transcripts" / "a.json").write_text("{}")
            (old / "full show.mp4").write_text("x")
            new = out / "today show"
            new.mkdir()
            past = time.time() - 30 * 86400
            os.utime(old, (past, past))
            with mock.patch.object(sas, "OUT_DIR", out), mock.patch.object(sas, "DRY", False), \
                 mock.patch.object(sas.subprocess, "run"), mock.patch.dict(os.environ, {"OBS_DIR": tmp}):
                sas.cleanup({})
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())


if __name__ == "__main__":
    unittest.main()


class TimerCoverage(unittest.TestCase):
    """Nov 13 2026: one stage-timer press for the first comic only, and the cutter called that set the
    headliner. Presses that don't cover the show mean: find the sets from the audio instead."""

    def setUp(self):
        from datetime import datetime, timedelta, timezone
        self.t0 = datetime(2030, 1, 1, 2, 0, tzinfo=timezone.utc)
        self.m = lambda minutes: self.t0 + timedelta(minutes=minutes)

    def test_one_short_press_is_not_trusted(self):
        sets = [(self.m(5), self.m(32), None)]
        self.assertFalse(sas.timer_covers_show(sets, self.t0, self.m(100)))

    def test_presses_for_every_comic_are_trusted(self):
        sets = [(self.m(5), self.m(20), None), (self.m(20), self.m(35), None), (self.m(35), self.m(95), None)]
        self.assertTrue(sas.timer_covers_show(sets, self.t0, self.m(100)))

    def test_two_short_presses_in_a_long_show_are_not_trusted(self):
        sets = [(self.m(5), self.m(15), None), (self.m(15), self.m(25), None)]
        self.assertFalse(sas.timer_covers_show(sets, self.t0, self.m(100)))


class NightlyTaskCommand(unittest.TestCase):
    """Nov 20 2026: the 4 AM task was one hidden PowerShell line that downloaded this script from GitHub and
    ran it. Microsoft Defender judged that line to be malware and stopped the task, so no recording was cut
    or sent that night. The task must only ever run a plain local file."""

    def setUp(self):
        folder = Path(__file__).parent / "av/recordings"
        self.setup = (folder / "setup.ps1").read_text()
        self.runner = folder / "run-recordings.ps1"

    def test_the_task_runs_a_local_file_not_a_one_liner(self):
        actions = [line for line in self.setup.splitlines() if "New-ScheduledTaskAction" in line]
        self.assertEqual(len(actions), 1)
        self.assertIn("-File", actions[0])
        self.assertIn("run-recordings.ps1", actions[0])
        self.assertNotIn("-Command", actions[0])
        self.assertNotIn("Invoke-WebRequest", actions[0])
        self.assertNotIn("http", actions[0])

    def test_setup_puts_the_runner_on_the_pc(self):
        self.assertTrue(self.runner.exists())
        self.assertIn("'run-recordings.ps1'", self.setup)

    def test_the_runner_keeps_the_working_script_when_the_download_is_bad(self):
        text = self.runner.read_text()
        # downloads to a side file, checks it is Python, and only then replaces the real one
        self.assertIn("split_and_share.new.py", text)
        self.assertIn("py_compile", text)
        self.assertLess(text.index("py_compile"), text.index("Move-Item -Force $new $script"))
        self.assertIn("py -3 $script @args", text)

    def test_the_runner_writes_the_log_in_one_encoding(self):
        # Windows PowerShell's ">>" writes UTF-16; mixing that with UTF-8 made recordings.log unreadable
        # on Nov 20 2026. Everything goes through Log (UTF-8) instead.
        code = [line for line in self.runner.read_text().splitlines() if not line.lstrip().startswith("#")]
        self.assertFalse([line for line in code if ">>" in line])
        self.assertTrue(any("Add-Content" in line and "-Encoding UTF8" in line for line in code))
