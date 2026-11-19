"""Checks for the $1 card-processing part of the ticket fee (python -m unittest test_ticket_fee).

The comics' $3 a ticket must not change, the $1 must stay out of the door,
and tickets sold before a show's price went up keep their old price."""
import unittest
from datetime import datetime, timedelta, timezone

import card_fee_rollout as rollout
import settlement_draft as sd
import ticket_fee as tf


def stamp(hours):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


SINCE = stamp(-24)
PRODUCT = {"cardFee": {"value": "1.0"}, "cardFeeSince": {"value": SINCE}}


class CardFeeTest(unittest.TestCase):
    def test_only_tickets_sold_after_the_price_went_up_carry_it(self):
        self.assertEqual(tf.card_fee_paid(PRODUCT, stamp(-1)), 1.0)
        self.assertEqual(tf.card_fee_paid(PRODUCT, stamp(-48)), 0.0)

    def test_shows_without_it_never_carry_it(self):
        self.assertEqual(tf.card_fee_paid({"cardFee": None, "cardFeeSince": None}, stamp(-1)), 0.0)
        self.assertEqual(tf.card_fee_paid({}, stamp(-1)), 0.0)
        self.assertEqual(tf.card_fee_paid(PRODUCT, None), 0.0)

    def test_new_shows_stay_at_three_until_sam_approves(self):
        # Flipped in the same change that runs the rollout.
        total, card = tf.new_show_fees()
        self.assertEqual(total, 3.0 + card)
        self.assertEqual(tf.COMICS_FEE, 3.0)

    def test_fee_sentence_says_where_the_money_goes(self):
        line = tf.fee_line(4, 1)
        self.assertIn("$4 ticketing fee", line)
        self.assertIn("$3 goes to the comics", line)
        self.assertIn("$1 covers card processing", line)
        self.assertNotIn("100% of the fee", line)


class SettlementTest(unittest.TestCase):
    def test_card_fee_is_neither_door_nor_pool(self):
        # 20 tickets at the old $26 ($23 + $3) and 30 at the new $27 ($23 + $4), 2 free.
        gross = 20 * 26.0 + 28 * 27.0
        sd.shopify_sales = lambda t: ([], {
            (t, "Fri Nov 6 • 7:00 PM"): {"tickets": 50, "orders": 30, "gross": gross, "refunded_tickets": 0,
                                         "comps": 2, "card_fees": 28 * 1.0},
        })
        sd.dojour_sales = lambda t: {}
        body = sd.draft("Test Comic")
        # door: 48 paid x $23, the same as if every ticket were sold at the old price
        self.assertIn("Door to the headliner: $1,104.00", body)
        # pool: still $3 a paid ticket, 48 x 3
        self.assertIn("Host/feature pool: $144.00 (host $48.00, feature $96.00)", body)


class RolloutTest(unittest.TestCase):
    def product(self, fee="3.0", card=None, prices=("28.00", "28.00"), body=None):
        return {"id": "gid://shopify/Product/1", "handle": "a-comic", "title": "A Comic",
                "descriptionHtml": body if body is not None else
                "<p>Bio.</p><p><strong>💵 Price includes a $3 ticketing fee</strong> — 100% of the fee goes to performers.</p>",
                "fee": {"value": fee} if fee else None, "card": {"value": card} if card else None,
                "variants": {"nodes": [{"id": f"v{i}", "price": p, "compareAtPrice": None} for i, p in enumerate(prices)]}}

    def test_raises_each_showtime_by_one_dollar_and_rewrites_the_sentence(self):
        [t] = rollout.plan([self.product()])
        self.assertEqual([v["price"] for v in t["variants"]], ["29.00", "29.00"])
        self.assertIn("$3 goes to the comics, $1 covers card processing", t["body"])
        self.assertNotIn("100% of the fee", t["body"])
        self.assertTrue(t["body"].startswith("<p>Bio.</p>"))

    def test_leaves_free_shows_classes_and_done_shows_alone(self):
        self.assertEqual(rollout.plan([self.product(fee=None)]), [])          # free night / class
        self.assertEqual(rollout.plan([self.product(card="1.0", fee="4.0")]), [])  # already done
        self.assertEqual(rollout.plan([self.product(prices=("0.00",))]), [])

    def test_keeps_text_it_does_not_recognise(self):
        [t] = rollout.plan([self.product(body="<p>Custom words.</p>")])
        self.assertIsNone(t["body"])


if __name__ == "__main__":
    unittest.main()
