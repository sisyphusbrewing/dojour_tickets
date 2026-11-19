"""
Sisyphus - the website ticket fee, in one place.

Every paid show on the website has a fee built into its price. Since Oct 10
2026 that fee was $3, all of it host and feature pay. Sam approved adding $1
to cover card processing (Nov 18 2026: "let's go ahead with getting that
ready to roll out site wide"), so the fee becomes $4: $3 to the comics, $1 to
Shopify's card charge (2.9% + 30 cents, about $1.11 on a $28 ticket). The $1
is not door money and not comic money.

Each show's Shopify product records its own fee:
  custom.ticket_fee       the whole fee in the price (3.00 before, 4.00 after)
  custom.card_fee         the part that covers card processing (1.00)
  custom.card_fee_since   when that show's price went up

Tickets sold before card_fee_since were sold at the old price and carried
only the $3, so settlements, the pay sheet and swaps treat them that way.

CARD_FEE_ON says whether new shows are built with the $1. It stays False
until Sam OKs the checkout preview; card_fee_rollout.py adds the $1 to the
shows already on sale, and the same change turns this on.
"""
from datetime import datetime

COMICS_FEE = 3.00   # per paid website ticket, 100% host and feature pay
CARD_FEE = 1.00     # per paid website ticket, covers card processing
CARD_FEE_ON = True   # on since Sam OKed the preview, Nov 18 2026


def new_show_fees():
    """(whole fee, card part) for a show built today."""
    card = CARD_FEE if CARD_FEE_ON else 0.0
    return COMICS_FEE + card, card


def _value(field):
    """A metafield as read by GraphQL ({"value": ...}) or a plain value."""
    if isinstance(field, dict):
        field = field.get("value")
    return field


def _when(text):
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None


def card_fee_paid(product, ordered_at):
    """How much of one ticket's price went to card processing.

    `product` carries the metafields as cardFee / cardFeeSince (GraphQL
    aliases). A ticket ordered before the show's price went up paid no card
    fee; neither did anything on a show that never got it."""
    try:
        fee = float(_value((product or {}).get("cardFee")) or 0)
    except (TypeError, ValueError):
        return 0.0
    since, when = _when(_value((product or {}).get("cardFeeSince"))), _when(ordered_at)
    if fee <= 0 or not since or not when:
        return 0.0
    if (since.tzinfo is None) != (when.tzinfo is None):
        return 0.0
    return fee if when >= since else 0.0


# GraphQL fields to add to a product selection so card_fee_paid() can read it.
PRODUCT_FIELDS = ('cardFee: metafield(namespace: "custom", key: "card_fee") { value } '
                  'cardFeeSince: metafield(namespace: "custom", key: "card_fee_since") { value }')


def fee_line(total, card):
    """The sentence at the bottom of a show's description on the website."""
    if card:
        return (f"<p><strong>💵 Price includes a ${total:.0f} ticketing fee:</strong> "
                f"${total - card:.0f} goes to the comics, ${card:.0f} covers card processing.</p>")
    return (f"<p><strong>💵 Price includes a ${total:.0f} ticketing fee</strong> "
            "— 100% of the fee goes to performers.</p>")
