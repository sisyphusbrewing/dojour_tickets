"""Quick checks for sync_inventory's matching and planning (python -m unittest)."""
import unittest

from sync_inventory import build_external_counts, plan_changes


def variant(vid, date, kind, qty, recorded=None):
    return {"id": vid, "title": f"{date} / {kind}", "inventoryQuantity": qty,
            "selectedOptions": [{"name": "Date & Time", "value": date},
                                {"name": "Ticket Type", "value": kind}],
            "inventoryItem": {"id": f"inv-{vid}"},
            "metafield": None if recorded is None else {"value": str(recorded)}}


def product(title, variants, handle="x"):
    return {"id": "p", "title": title, "handle": handle, "productType": "Comedy Ticket",
            "tags": [], "isGiftCard": False, "variants": {"nodes": variants}}


ROWS = [
    {"show_title": "Sam Jay", "show_date": "Fri, Oct 16 • 7:00 PM", "tickets": 19, "source": "Dojour",
     "guest_name": "A B", "email": "a@b.c"},
    {"show_title": "Sam Jay", "show_date": "Fri, Oct 16 • 7:00 PM", "tickets": 2, "source": "Comp",
     "guest_name": "C D", "email": ""},
    {"show_title": "Sam Jay", "show_date": "Fri, Oct 16 • 9:00 PM", "tickets": 90, "source": "Dojour",
     "guest_name": "Hold Hold", "email": ""},
    {"show_title": "Sam Jay", "show_date": "Fri, Oct 16 • 9:00 PM", "tickets": 2, "source": "Dojour",
     "guest_name": "E F", "email": "e@f.g"},
    {"show_title": "Henry Sir", "show_date": "Fri, Jan 15, 2027 • 7:00 PM", "tickets": 4, "source": "Dojour",
     "guest_name": "G H", "email": "g@h.i"},
]


class CountsTest(unittest.TestCase):
    def test_counts_skip_holds_and_merge_sources(self):
        counts = build_external_counts(ROWS)
        self.assertEqual(counts[("sam jay", "2026-10-16T19:00:00-05:00")], 21)
        self.assertEqual(counts[("sam jay", "2026-10-16T21:00:00-05:00")], 2)
        self.assertEqual(counts[("henry sir", "2027-01-15T19:00:00-06:00")], 4)


class PlanTest(unittest.TestCase):
    def test_first_sight_is_a_baseline_not_a_cut(self):
        products = [product("Sam Jay", [variant("ga", "Fri, Oct 16 • 7:00 PM", "General Admission", 37),
                                        variant("vip", "Fri, Oct 16 • 7:00 PM", "VIP / Reserved Seating", 10)])]
        changes, baselines, unmatched = plan_changes(products, build_external_counts(ROWS))
        self.assertEqual(changes, [])
        self.assertEqual(len(baselines), 1)
        self.assertEqual(baselines[0]["variant"]["id"], "ga")
        self.assertEqual(baselines[0]["external"], 21)
        self.assertEqual(baselines[0]["after"], 37)

    def test_later_sales_come_off_general_admission_only(self):
        products = [product("Sam Jay", [variant("ga", "Fri, Oct 16 • 7:00 PM", "General Admission", 37, recorded=15),
                                        variant("vip", "Fri, Oct 16 • 7:00 PM", "VIP / Reserved Seating", 10, recorded=0)])]
        changes, baselines, _ = plan_changes(products, build_external_counts(ROWS))
        self.assertEqual(baselines, [])
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["variant"]["id"], "ga")
        self.assertEqual(changes[0]["after"], 31)   # 37 - (21 - 15)

    def test_refund_gives_seats_back_and_floor_is_zero(self):
        products = [product("Sam Jay", [variant("ga", "Fri, Oct 16 • 7:00 PM", "General Admission", 3, recorded=25)]),
                    product("Henry Sir", [variant("hs", "Fri, Jan 15, 2027 • 7:00 PM", "General Admission", 1, recorded=0)])]
        changes, _, _ = plan_changes(products, build_external_counts(ROWS))
        by_id = {c["variant"]["id"]: c["after"] for c in changes}
        self.assertEqual(by_id["ga"], 7)    # 3 + (25 - 21)
        self.assertEqual(by_id["hs"], 0)    # 1 - 4, floored

    def test_unchanged_and_unmatched(self):
        products = [product("Sam Jay", [variant("ga", "Fri, Oct 16 • 7:00 PM", "General Admission", 37, recorded=21)])]
        changes, baselines, unmatched = plan_changes(products, build_external_counts(ROWS))
        self.assertEqual((changes, baselines), ([], []))
        self.assertEqual([k[0] for k in unmatched], ["henry sir", "sam jay"])

    def test_fee_products_are_ignored(self):
        products = [product("Ticket Fee", [variant("fee", "Fri, Oct 16 • 7:00 PM", "Fee", 999)], handle="ticket-fee")]
        changes, baselines, _ = plan_changes(products, build_external_counts(ROWS))
        self.assertEqual((changes, baselines), ([], []))


if __name__ == "__main__":
    unittest.main()
