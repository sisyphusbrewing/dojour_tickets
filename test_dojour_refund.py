"""Checks the Dojour partial-refund body: tickets stay, only the flat amount goes back."""
import unittest

from dojour_refund import build_refund_body, to_cents

RES = {
    "encrypted_pk": "abc", "is_cancelled": False,
    "invoice": {"charge_amount": 8127},
    "option_set": [{"id": 1, "title": "Reserved Seating", "count": 2,
                    "invoice_item": {"unit_count": 2, "unit_price": 3500, "due": 8213}}],
    "upgrade_set": [],
}


class RefundBody(unittest.TestCase):
    def test_vip_difference_two_tickets(self):
        # 2 tickets x $10 VIP difference + $1.94 of the tax paid on it
        b = build_refund_body(RES, to_cents("21.94"))
        self.assertEqual(b["comp_amount"], 2194)
        self.assertEqual(b["refund_amount"], 2194)
        self.assertFalse(b["refund_as_credit"])
        opt = b["full_option_set"][0]
        self.assertEqual(opt["reserve_count"], 2)          # nobody loses a seat
        self.assertEqual(opt["invoice_count"], opt["invoice_count_max"])
        self.assertEqual(opt["invoice_price"], opt["invoice_price_max"])

    def test_refuses_more_than_paid_or_cap(self):
        with self.assertRaises(ValueError):
            build_refund_body(RES, 9000, max_cents=100000)   # more than the $81.27 paid
        with self.assertRaises(ValueError):
            build_refund_body(RES, 2000, refunded_cents=7000)  # only $11.27 left
        with self.assertRaises(ValueError):
            build_refund_body(RES, 6000, max_cents=5000)
        with self.assertRaises(ValueError):
            build_refund_body(RES, 0)

    def test_cancelled_reservation(self):
        with self.assertRaises(ValueError):
            build_refund_body(dict(RES, is_cancelled=True), 100)

    def test_to_cents(self):
        self.assertEqual(to_cents("$21.94"), 2194)
        self.assertEqual(to_cents("10"), 1000)


if __name__ == "__main__":
    unittest.main()
