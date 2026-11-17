"""Checks for the reorder emails in supply_notify.py (the Reorder buttons on
the Supplies page). Run: python -m unittest test_supply_orders"""
import unittest
from unittest import mock

import supply_notify as sn

ORDER = {"id": "o1", "to_email": "andy@example.com", "subject": "Sisyphus order",
         "body": "Hey Andy,\n\nWe need:\n6 cases Root Beer\n\nThanks much!\nSam",
         "supply_reorders": {"label": "Sodas & Liquid Death"}}


class OrderMessage(unittest.TestCase):
    def test_copies_sam_and_booking_and_replies_to_sam(self):
        with mock.patch.object(sn, "FROM_EMAIL", "events@sisyphusbrewing.com"):
            msg = sn.order_message(ORDER)
        self.assertEqual(msg["To"], "andy@example.com")
        self.assertEqual(msg["Cc"], "sam@sisyphusbrewing.com, booking@sisyphusbrewing.com")
        self.assertEqual(msg["Reply-To"], "sam@sisyphusbrewing.com")
        self.assertEqual(msg["Subject"], "Sisyphus order")
        self.assertIn("6 cases Root Beer", msg.get_content())

    def test_no_copy_to_the_sending_address(self):
        with mock.patch.object(sn, "FROM_EMAIL", "booking@sisyphusbrewing.com"):
            msg = sn.order_message(ORDER)
        self.assertEqual(msg["Cc"], "sam@sisyphusbrewing.com")


class SendOrders(unittest.TestCase):
    def run_send(self, smtp_side_effect=None):
        marks = []
        with mock.patch.object(sn, "fetch_orders", return_value=[ORDER]), \
             mock.patch.object(sn, "mark", side_effect=lambda i, s, e=None: marks.append((i, s, e))), \
             mock.patch.object(sn, "DRY_RUN", False), \
             mock.patch.object(sn, "FROM_EMAIL", "events@sisyphusbrewing.com"), \
             mock.patch.object(sn.smtplib, "SMTP_SSL") as smtp, \
             mock.patch("builtins.print") as out:
            if smtp_side_effect:
                smtp.side_effect = smtp_side_effect
            sn.send_orders()
        return marks, smtp, out

    def test_sent_order_is_marked_sent(self):
        marks, smtp, _ = self.run_send()
        self.assertEqual(marks, [("o1", "sent", None)])
        smtp.return_value.__enter__.return_value.send_message.assert_called_once()

    def test_failure_is_marked_failed_with_reason(self):
        marks, _, _ = self.run_send(OSError("connection refused"))
        self.assertEqual(marks[0][:2], ("o1", "failed"))
        self.assertIn("connection refused", marks[0][2])

    def test_log_never_shows_the_address(self):
        _, _, out = self.run_send()
        printed = " ".join(str(c) for c in out.call_args_list)
        self.assertNotIn("andy@example.com", printed)
        self.assertIn("Sodas & Liquid Death", printed)

    def test_dry_run_sends_and_marks_nothing(self):
        with mock.patch.object(sn, "fetch_orders", return_value=[ORDER]), \
             mock.patch.object(sn, "mark") as mark, \
             mock.patch.object(sn, "DRY_RUN", True), \
             mock.patch.object(sn.smtplib, "SMTP_SSL") as smtp, \
             mock.patch("builtins.print"):
            sn.send_orders()
        mark.assert_not_called()
        smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
