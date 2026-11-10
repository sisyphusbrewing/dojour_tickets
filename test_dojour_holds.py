import unittest

from dojour_holds import notice_text


class NoticeText(unittest.TestCase):
    def test_lists_each_showing_and_total(self):
        text = notice_text([("Liz Miele", "Fri, Feb 26, 2027 • 7:00 PM", 18, "18 Liz Miele /// Comedy"),
                            ("Tyler Horvath", "Fri, Mar 19, 2027 • 7:00 PM", 2, "2 Tyler Horvath /// Comedy")])
        self.assertIn("20 more seats blocked", text)
        self.assertIn("on 2 showings", text)
        self.assertIn("- Liz Miele, Fri, Feb 26, 2027 • 7:00 PM: 18 (18 Liz Miele /// Comedy)", text)
        self.assertIn("top up Dojour", text)

    def test_singular(self):
        text = notice_text([("Keller", "Fri, Nov 20 • 10:00 PM", 1, "1 Jeffrey Keller")])
        self.assertIn("1 more seat blocked", text)
        self.assertIn("on 1 showing:", text)


if __name__ == "__main__":
    unittest.main()
