"""Quick checks for exchange_ticket's swap logic with a fake Shopify and Supabase (python -m unittest)."""
import unittest
from unittest import mock

import exchange_ticket as ex

LINE_ID, ORDER_ID = 111, 999
OLD = "Fri, Nov 6 • 7:00 PM / General Admission"


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


def variant(price="28.00", date="Sat, Nov 7 • 9:00 PM", seats=20, product=5):
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
        self.assertEqual(post["show_date"], "Sat, Nov 7 • 9:00 PM")
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


if __name__ == "__main__":
    unittest.main()
