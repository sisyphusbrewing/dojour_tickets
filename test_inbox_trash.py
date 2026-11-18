"""Checks for inbox_trash.py: which conversations it may move to Trash."""
import unittest
from unittest import mock

import inbox_trash as t


class FakeBox:
    """Stands in for Gmail: two conversations, one we wrote in."""
    def __init__(self):
        self.stored = []

    def uid(self, cmd, *args):
        if cmd == "SEARCH":
            thr = args[-1]
            return "OK", [{"111": b"1 2", "222": b"3", "333": b""}[thr]]
        if cmd == "FETCH":
            uids = args[0].split(",")
            fr = {"1": b"From: Spammer <x@spam.example>\r\n", "2": b"From: x@spam.example\r\n",
                  "3": b"From: Sisyphus Brewing <events@sisyphusbrewing.com>\r\n"}
            return "OK", [(b"%s (UID %s BODY[...])" % (u.encode(), u.encode()), fr[u]) for u in uids]
        if cmd == "STORE":
            self.stored.append(args[0])
            return "OK", []
        raise AssertionError(cmd)


class TrashTests(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(t.parse_keys("gm:12, 34 gm:12"), ["12", "34"])
        self.assertEqual(t.parse_keys("1a1f057ca4d87b59"), [str(int("1a1f057ca4d87b59", 16))])
        with self.assertRaises(ValueError):
            t.parse_keys("gm:12; drop")

    def test_from_us(self):
        self.assertTrue(t.from_us(b"From: Sisyphus <booking@sisyphusbrewing.com>\r\n"))
        self.assertFalse(t.from_us(b"From: Someone <a@b.com>\r\n"))

    def test_only_junk_moves(self):
        box = FakeBox()
        with mock.patch.object(t.mail, "THREADS_PER_ASK", 1):
            trashed, refused, missing, done = t.trash(box, ["111", "222", "333"], dry_run=False)
        self.assertEqual((trashed, refused, missing), (1, 1, 1))
        self.assertEqual(done, ["111"])
        self.assertEqual(box.stored, ["1,2"])

    def test_dry_run_changes_nothing(self):
        box = FakeBox()
        with mock.patch.object(t.mail, "THREADS_PER_ASK", 1):
            trashed, _, _, _ = t.trash(box, ["111"], dry_run=True)
        self.assertEqual(trashed, 1)
        self.assertEqual(box.stored, [])


if __name__ == "__main__":
    unittest.main()
