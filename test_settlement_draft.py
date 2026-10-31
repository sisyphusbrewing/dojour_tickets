"""Checks the settlement draft's money math with Shopify and Dojour stubbed out.

    python -m pytest test_settlement_draft.py   (or just: python test_settlement_draft.py)
"""
import settlement_draft as sd


def test_door_and_pool():
    sd.shopify_sales = lambda t: ([], {
        (t, "Fri Nov 6 • 7:00 PM"): {"tickets": 50, "orders": 30, "gross": 48 * 28.0, "refunded_tickets": 0, "comps": 2},
    })
    sd.dojour_sales = lambda t: {(t, "Sat, Nov 7 2026 • 7:00 PM"): {"tickets": 10, "orders": 5, "vip": 0, "revenue": 250.0}}
    body = sd.draft("Test Comic")
    # web: 48 paid x $25 door = 1200; dojour 250 - 30 = 220
    assert "Tickets: 60" in body
    assert "Door to the headliner: $1,420.00" in body
    # pool: (48 + 10) x $3 = 174, host 58, feature 116
    assert "Host/feature pool: $174.00 (host $58.00, feature $116.00)" in body
    assert "2 free" in body


def test_dojour_down_still_drafts():
    sd.shopify_sales = lambda t: ([], {})
    def boom(t):
        raise RuntimeError("login expired")
    sd.dojour_sales = boom
    body = sd.draft("Test Comic")
    assert "Dojour couldn't be read" in body and "Tickets: 0" in body


if __name__ == "__main__":
    test_door_and_pool()
    test_dojour_down_still_drafts()
    print("ok")
