"""Tests for how voice_notes.py puts a recording's pieces back together.

Since Nov 9 2026 the /voice/ page records each minute as its own complete
file (and restarts when the phone cuts the mic off), while older recordings
were one stream cut into chunks. Both have to come out as one transcript."""
import os
import shutil
import subprocess
import tempfile
import unittest

import voice_notes as vn

MP4_HEAD = b"\x00\x00\x00\x1cftypM4A \x00\x00\x00\x00"
MP4_FRAGMENT = b"\x00\x00\x00\x68moof\x00\x00\x00\x10mfhd"
WEBM_HEAD = b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01"
WEBM_CLUSTER = b"\x1f\x43\xb6\x75\x01\xff\xff\xff"
OGG_HEAD = b"OggS\x00\x02" + b"\x00" * 22 + b"OpusHead\x01\x01"
OGG_PAGE = b"OggS\x00\x00" + b"\x00" * 30


class GroupPieces(unittest.TestCase):
    def test_old_style_one_stream(self):
        self.assertEqual(vn.group_pieces([MP4_HEAD, MP4_FRAGMENT, MP4_FRAGMENT]), [[0, 1, 2]])
        self.assertEqual(vn.group_pieces([WEBM_HEAD, WEBM_CLUSTER]), [[0, 1]])
        self.assertEqual(vn.group_pieces([OGG_HEAD, OGG_PAGE]), [[0, 1]])

    def test_each_minute_its_own_file(self):
        self.assertEqual(vn.group_pieces([MP4_HEAD, MP4_HEAD, MP4_HEAD]), [[0], [1], [2]])

    def test_mixed_after_a_restart(self):
        self.assertEqual(vn.group_pieces([WEBM_HEAD, WEBM_CLUSTER, WEBM_HEAD, WEBM_CLUSTER]), [[0, 1], [2, 3]])

    def test_headerless_first_piece_still_kept(self):
        self.assertEqual(vn.group_pieces([MP4_FRAGMENT, MP4_HEAD]), [[0], [1]])

    def test_nothing(self):
        self.assertEqual(vn.group_pieces([]), [])


@unittest.skipUnless(shutil.which("ffmpeg"), "needs ffmpeg")
class JoinRealAudio(unittest.TestCase):
    """Makes three separate 3-second m4a files plus one broken piece, and
    checks the joined audio is 9 seconds long."""

    def test_separate_files_join_and_bad_piece_is_skipped(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as work:
            paths = []
            for i in range(3):
                p = os.path.join(src, f"part-{i:04d}.m4a")
                subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                                f"sine=frequency={300 + 100 * i}:duration=3", "-c:a", "aac", p], check=True)
                paths.append(p)
            bad = os.path.join(src, "part-0003.m4a")
            with open(bad, "wb") as f:
                f.write(MP4_HEAD + b"\x00" * 500)
            paths.append(bad)

            real_download = vn.download
            vn.download = lambda path, dest: shutil.copyfile(path, dest)
            try:
                wav = vn.to_wav(paths, "m4a", work)
            finally:
                vn.download = real_download
            self.assertAlmostEqual(vn.duration(wav), 9, delta=0.5)


if __name__ == "__main__":
    unittest.main()
