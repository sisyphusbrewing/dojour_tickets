"""Quick checks for exchange_ticket's swap logic with a fake Shopify and Supabase (python -m unittest)."""
import re
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import exchange_ticket as ex

LINE_ID, ORDER_ID = 111, 999
# Show dates are always a couple of weeks out, so the 48-hour swap cutoff
# never trips just because the calendar caught up with a hardcoded date.
def _show(days, time):
    d = datetime.now() + timedelta(days=days)
    return f"{d:%a}, {d:%b} {d.day} • {time}"


OLD_DATE = _show(14, "7:00 PM")
NEW_DATE = _show(15, "9:00 PM")
OLD = f"{OLD_DATE} / General Admission"


def order(qty=2, price="28.0", paid=None, email="Fan@Example.com", new_line=None):
    lines = [{"id": f"gid://shopify/LineItem/{LINE_ID}", "title": "Michael Longfellow", "variantTitle": OLD,
              "currentQuantity": qty, "variant": {"id": "gid://shopify/ProductVariant/1", "product": {"id": "gid://shopify/Product/5"}},
              "originalUnitPriceSet": {"shopMoney": {"amount": price}},
              "discountedUnitPriceAfterAllDiscountsSet": {"shopMoney": {"amount": paid or price}}}]
    if new_line:
        lines.append(new_line)
    return {"orders": {"nodes": [{"id": f"gid://shopify/Order/{ORDER_ID}", "name": "#4417", "email": email,
                                  "cancelledAt": None,
                                  "lineItems": {"nodes": lines}}]}}


def variant(price="28.00", date=NEW_DATE, seats=20, product=5):
    return {"productVariant": {"id": "gid://shopify/ProductVariant/2", "title": f"{date} / General Admission",
                               "price": price, "inventoryQuantity": seats, "inventoryItem": {"tracked": True},
                               "selectedOptions": [{"name": "Date & Time", "value": date},
                                                   {"name": "Ticket Type", "value": "General Admission"}],
                               "product": {"id": f"gid://shopify/Product/{product}", "title": "Michael Longfellow",
                                           "status": "ACTIVE", "handle": "michael-longfellow", "tags": [],
                                           "productType": "Comedy Ticket", "isGiftCard": False}}}


class FakeShop:
    def __init__(self, var, before, after=None):
        self.var, self.orders, self.calls = var, [before, after or before], []

    def gql(self, query, variables=None):
        name = query.split("(")[0].split()[-1] if query.lstrip().startswith("query") else query.split("{", 1)[1].split("(")[0].strip()
        self.calls.append((name, variables))
        if name == "Order":
            return self.orders.pop(0) if len(self.orders) > 1 else self.orders[0]
        if name == "Variant":
            return self.var
        payload = {"userErrors": []}
        if name == "orderEditBegin":
            payload["calculatedOrder"] = {"id": "gid://shopify/CalculatedOrder/7"}
        if name == "orderEditAddVariant":
            payload["calculatedLineItem"] = {"id": "gid://shopify/CalculatedLineItem/222"}
        return {name: payload}

    def names(self):
        return [c[0] for c in self.calls]


REQ = {"order_name": "#4417", "email": "fan@example.com", "from_unique_id": f"shopify_{ORDER_ID}_{LINE_ID}",
       "to_variant_id": 2, "tickets": None}
NEW_LINE = {"id": "gid://shopify/LineItem/333", "title": "Michael Longfellow", "variantTitle": "x", "currentQuantity": 2,
            "variant": {"id": "gid://shopify/ProductVariant/2", "product": {"id": "gid://shopify/Product/5"}},
            "originalUnitPriceSet": {"shopMoney": {"amount": "28"}},
            "discountedUnitPriceAfterAllDiscountsSet": {"shopMoney": {"amount": "28"}}}


class SwapTest(unittest.TestCase):
    def setUp(self):
        self.sb = mock.patch.object(ex, "sb", side_effect=self.fake_sb).start()
        self.sb_calls = []
        mock.patch.object(ex, "DRY_RUN", False).start()
        self.addCleanup(mock.patch.stopall)
        self.checked_in = 0

    def fake_sb(self, method, path, **kw):
        self.sb_calls.append((method, path, kw.get("json")))
        if method == "GET":
            return [{"unique_id": REQ["from_unique_id"], "guest_name": "Pat Fan", "email": "fan@example.com",
                     "checked_in_count": self.checked_in}]
        return None

    def test_same_price_swap_moves_seats_and_door_list(self):
        shop = FakeShop(variant(), order(), order(new_line=NEW_LINE))
        result = ex.exchange(shop, dict(REQ))
        self.assertEqual(result["diff"], 0)
        self.assertEqual(shop.names(), ["Order", "Variant", "orderEditBegin", "orderEditSetQuantity",
                                        "orderEditAddVariant", "orderEditCommit", "Order"])
        set_qty = next(v for n, v in shop.calls if n == "orderEditSetQuantity")
        self.assertEqual(set_qty["qty"], 0)
        post = next(c for c in self.sb_calls if c[0] == "POST")[2][0]
        self.assertEqual(post["unique_id"], f"shopify_{ORDER_ID}_333")
        self.assertEqual(post["show_date"], NEW_DATE)
        self.assertEqual(post["guest_name"], "Pat Fan")
        self.assertIn(("DELETE", f"tickets?unique_id=eq.{REQ['from_unique_id']}", None), self.sb_calls)

    def test_cheaper_swap_adds_credit_not_refund(self):
        shop = FakeShop(variant(price="23.00"), order(), order(new_line=NEW_LINE))
        result = ex.exchange(shop, dict(REQ))
        self.assertEqual(result["diff"], -10.0)
        credit = next(v for n, v in shop.calls if n == "orderEditAddCustomItem")
        self.assertEqual(credit["price"]["amount"], "10.00")

    def test_pricier_swap_is_refused_before_editing(self):
        shop = FakeShop(variant(price="33.00"), order())
        with self.assertRaises(ex.Refused):
            ex.exchange(shop, dict(REQ))
        self.assertNotIn("orderEditBegin", shop.names())

    def test_promo_percentage_carries_over(self):
        shop = FakeShop(variant(), order(paid="22.40"), order(new_line=NEW_LINE))
        result = ex.exchange(shop, dict(REQ))
        self.assertEqual(result["diff"], 0)
        disc = next(v for n, v in shop.calls if n == "orderEditAddLineItemDiscount")
        self.assertAlmostEqual(disc["discount"]["percentValue"], 20.0)

    def test_partial_swap_keeps_the_rest(self):
        shop = FakeShop(variant(), order(qty=4), order(qty=3, new_line=dict(NEW_LINE, currentQuantity=1)))
        ex.exchange(shop, dict(REQ, tickets=1))
        set_qty = next(v for n, v in shop.calls if n == "orderEditSetQuantity")
        self.assertEqual(set_qty["qty"], 3)
        self.assertIn(("PATCH", f"tickets?unique_id=eq.{REQ['from_unique_id']}", {"tickets": 3}), self.sb_calls)

    def _card_fee_case(self, ordered_hours_ago, paid="26.0"):
        since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        var = variant(price="27.00")
        var["productVariant"]["product"].update({"cardFee": {"value": "1.0"}, "cardFeeSince": {"value": since}})
        before = order(price=paid)
        before["orders"]["nodes"][0]["createdAt"] = (datetime.now(timezone.utc) - timedelta(hours=ordered_hours_ago)).isoformat()
        return FakeShop(var, before, order(new_line=NEW_LINE))

    def test_ticket_bought_before_the_card_fee_swaps_at_its_old_price(self):
        # Bought at $26 ($23 + $3); the new night is now $27 ($23 + $4). Same seats, no charge.
        shop = self._card_fee_case(ordered_hours_ago=72)
        result = ex.exchange(shop, dict(REQ))
        self.assertEqual(result["diff"], 0)
        disc = next(v for n, v in shop.calls if n == "orderEditAddLineItemDiscount")
        self.assertEqual(disc["discount"]["description"], "Original price")
        self.assertAlmostEqual(27 * (1 - disc["discount"]["percentValue"] / 100), 26.0, places=1)

    def test_ticket_bought_after_the_card_fee_swaps_at_the_same_price(self):
        shop = self._card_fee_case(ordered_hours_ago=2, paid="27.0")
        result = ex.exchange(shop, dict(REQ))
        self.assertEqual(result["diff"], 0)
        self.assertNotIn("orderEditAddLineItemDiscount", shop.names())

    def test_refusals(self):
        cases = [
            (dict(REQ, email="someone@else.com"), variant(), "email"),
            (dict(REQ), variant(seats=1), "seats"),
            (dict(REQ), variant(product=6), "same show"),
        ]
        for req, var, word in cases:
            with self.assertRaises(ex.Refused) as ctx:
                ex.exchange(FakeShop(var, order()), req)
            self.assertIn(word, str(ctx.exception))
        self.checked_in = 1
        with self.assertRaises(ex.Refused):
            ex.exchange(FakeShop(variant(), order()), dict(REQ))


class RefreshShowtimes(unittest.TestCase):
    """The list of showtimes is also the staff site's show calendar: tonight's
    show must stay on it while the show is on (Sam, Nov 17 2026: "There is a
    show tonight - the free mic")."""

    def setUp(self):
        self.now = datetime.now(timezone.utc)
        # The website right now: one show still to come, and tonight's free
        # mic, which started an hour ago (Shopify still lists it).
        self.site = {11: self.now + timedelta(days=3), 12: self.now - timedelta(hours=1)}
        # What the list held before this run.
        self.table = {11: self.now + timedelta(days=3),        # still on sale
                      12: self.now - timedelta(hours=1),       # tonight's show, an hour in
                      13: self.now - timedelta(hours=7),       # last night's show
                      14: self.now + timedelta(days=9)}        # taken off the website
        def products(shop):
            return [{"id": "gid://shopify/Product/5", "title": "Tuesday Open Mic",
                     "variants": {"nodes": [{"id": f"gid://shopify/ProductVariant/{v}", "price": "0.00",
                                             "inventoryQuantity": 40} for v in self.site]}}]
        self.calls = []
        for name, value in (("fetch_active_products", products), ("is_show", lambda p: True),
                            ("skip_reason", lambda p: None), ("date_text", lambda v: v["id"]),
                            ("parse_show_datetime", lambda text, require_time=True: self.site[int(text.rsplit("/", 1)[-1])]),
                            ("sb", lambda method, path, **kw: self.calls.append((method, path, kw.get("json")))),
                            ("DRY_RUN", False)):
            mock.patch.object(ex, name, value).start()
        self.addCleanup(mock.patch.stopall)

    def left_after(self):
        """Runs the refresh, then does to self.table what its DELETE asks for."""
        ex.refresh_showtimes(shop=None)
        deletes = [path for method, path, _ in self.calls if method == "DELETE"]
        self.assertEqual(len(deletes), 1)
        got = re.fullmatch(r"exchange_showtimes\?variant_id=not\.in\.\(([\d,]+)\)"
                           r"&or=\(starts_at\.gt\.([^,)]+),starts_at\.lt\.([^,)]+)\)", deletes[0])
        self.assertTrue(got, deletes[0])
        keep = {int(v) for v in got.group(1).split(",")}
        after, before = (datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) for t in got.group(2, 3))
        return sorted(v for v, starts in self.table.items() if v in keep or not (starts > after or starts < before))

    def test_a_show_that_has_started_stays_until_its_night_is_over(self):
        self.assertEqual(self.left_after(), [11, 12])

    def test_a_started_show_is_not_saved_again_or_offered(self):
        ex.refresh_showtimes(shop=None)
        saved = [row["variant_id"] for method, _, rows in self.calls if method == "POST" for row in rows]
        self.assertEqual(saved, [11])

    def test_nothing_on_the_website_still_keeps_tonight(self):
        self.site = {12: self.now - timedelta(hours=1)}
        self.table.pop(14)
        self.assertEqual(self.left_after(), [12])
        self.assertFalse([c for c in self.calls if c[0] == "POST"])

    def test_the_filter_has_no_plus_sign_to_be_read_as_a_space(self):
        ex.refresh_showtimes(shop=None)
        self.assertNotIn("+", [path for method, path, _ in self.calls if method == "DELETE"][0])


if __name__ == "__main__":
    unittest.main()
