"""
Recurring events: keeps repeating shows stocked with upcoming dates.

Tag a show in Shopify with its schedule and the daily maintenance run adds
the next dates for it, so it never runs out and is never archived:

    recurring: 1st Wed 7:00 PM      (first Wednesday of every month)
    recurring: 2nd Tue 7 PM         (second Tuesday)
    recurring: last Fri 8:00 PM     (last Friday)
    recurring: every Thu 8:00 PM    (weekly)

To skip one date (a holiday, or another show in the room), also tag it
"skip: Oct 22"; that date is never added.

Monthly events keep the next MONTHLY_AHEAD dates listed, weekly events the
next WEEKLY_AHEAD. New dates copy the price of the show's existing dates and
the largest capacity among them (default 100). Only shows with a single
"Date & Time" option are handled; anything else is reported and left alone.
"""
import re
from datetime import date, datetime, timedelta

from show_dates import parse_show_datetime, CENTRAL_TZ

MONTHLY_AHEAD = 6
WEEKLY_AHEAD = 8
DEFAULT_CAPACITY = 100

WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
ORDINALS = {"1st": 1, "first": 1, "2nd": 2, "second": 2, "3rd": 3, "third": 3,
            "4th": 4, "fourth": 4, "last": -1, "every": 0}

_RULE = re.compile(
    r"^\s*recurring\s*:\s*(1st|2nd|3rd|4th|first|second|third|fourth|last|every)\s+"
    r"(mon|tue|wed|thu|fri|sat|sun)[a-z]*\.?\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*$",
    re.IGNORECASE)


def parse_rule(tags):
    """(nth, weekday, hour, minute) from a "recurring: ..." tag, or None.

    nth is 1-4 for "Nth weekday of the month", -1 for last, 0 for weekly.
    """
    for tag in tags or []:
        m = _RULE.match(tag)
        if m:
            hour = int(m.group(3)) % 12 + (12 if m.group(5).lower() == "pm" else 0)
            return (ORDINALS[m.group(1).lower()], WEEKDAYS[m.group(2).lower()[:3]],
                    hour, int(m.group(4) or 0))
    return None


def skip_days(tags, now):
    """Dates from "skip: Oct 22" tags."""
    days = set()
    for tag in tags or []:
        if tag.strip().lower().startswith("skip:"):
            d = parse_show_datetime(tag.split(":", 1)[1], now=now)
            if d:
                days.add(d.date())
    return days


def has_recurring_tag(tags):
    return any(t.strip().lower().startswith("recurring") for t in tags or [])


def _nth_weekday(year, month, nth, weekday):
    if nth == -1:
        nxt = date(year + (month == 12), month % 12 + 1, 1)
        d = nxt - timedelta(days=1)
        return d - timedelta(days=(d.weekday() - weekday) % 7)
    first = date(year, month, 1)
    d = first + timedelta(days=(weekday - first.weekday()) % 7 + 7 * (nth - 1))
    return d if d.month == month else None


def upcoming_dates(rule, now):
    """The next dates this rule should have listed, as Central datetimes."""
    nth, weekday, hour, minute = rule
    at = lambda d: datetime(d.year, d.month, d.day, hour, minute, tzinfo=CENTRAL_TZ)
    out = []
    if nth == 0:
        d = now.date() + timedelta(days=(weekday - now.weekday()) % 7)
        while len(out) < WEEKLY_AHEAD:
            if at(d) > now:
                out.append(at(d))
            d += timedelta(days=7)
        return out
    year, month = now.year, now.month
    while len(out) < MONTHLY_AHEAD:
        d = _nth_weekday(year, month, nth, weekday)
        if d and at(d) > now:
            out.append(at(d))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def variant_name(dt):
    """Same style as the Create Show button: "Wed Nov 4 • 7:00 PM"."""
    return f"{dt:%a %b} {dt.day} • {dt.hour % 12 or 12}:{dt:%M %p}"


def plan_additions(products, now):
    """For each recurring product, the dates it is missing. Pure - easy to test.

    Returns (additions, problems): additions is a list of
    (product, option_name, price, capacity, [datetimes]); problems is a list
    of (product, reason) for tagged shows that couldn't be handled.
    """
    additions, problems = [], []
    for p in products:
        tags = p.get("tags") or []
        if not has_recurring_tag(tags):
            continue
        rule = parse_rule(tags)
        if not rule:
            problems.append((p, "couldn't read the recurring tag "
                                f"{[t for t in tags if t.lower().startswith('recurring')]}"))
            continue
        options = p.get("options") or []
        if len(options) != 1:
            problems.append((p, "has more than one option (e.g. ticket types); add dates by hand"))
            continue

        variants = p["variants"]["nodes"]
        have = {parse_show_datetime(v["title"], now=now, require_time=True) for v in variants}
        skipped = skip_days(tags, now)
        missing = [d for d in upcoming_dates(rule, now) if d not in have and d.date() not in skipped]
        if not missing:
            continue
        prices = [v.get("price") for v in variants if v.get("price") is not None]
        price = prices[-1] if prices else "0.00"
        capacity = max([v.get("inventoryQuantity") or 0 for v in variants] + [0]) or DEFAULT_CAPACITY
        additions.append((p, options[0]["name"], price, capacity, missing))
    return additions, problems


def add_dates(shop, location_id, product, option_name, price, capacity, dates):
    variants = [{
        "optionValues": [{"optionName": option_name, "name": variant_name(d)}],
        "price": price,
        "inventoryPolicy": "DENY",
        "inventoryItem": {"tracked": True, "requiresShipping": True},  # pickup = Minneapolis tax
        "inventoryQuantities": [{"availableQuantity": capacity, "locationId": location_id}],
        "metafields": [{"namespace": "custom", "key": "show_start",
                        "type": "single_line_text_field", "value": d.isoformat()}],
    } for d in dates]
    res = shop.gql("""
      mutation AddDates($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
        productVariantsBulkCreate(productId: $productId, variants: $variants) {
          productVariants { id } userErrors { field message }
        }
      }""", {"productId": product["id"], "variants": variants})["productVariantsBulkCreate"]
    if res["userErrors"]:
        raise RuntimeError(res["userErrors"])


# The taproom (712 Ontario Ave W); used if the app can't list locations.
FALLBACK_LOCATION_ID = "gid://shopify/Location/13316229"


def first_location_id(shop):
    try:
        return shop.gql("{ locations(first: 1) { nodes { id } } }")["locations"]["nodes"][0]["id"]
    except Exception:
        return FALLBACK_LOCATION_ID


# ---------------------------------------------------------------------------
# Card label: the site's show cards would list every date ("★ 6 SHOW DATES,
# Nov 4 - April 7"). For recurring shows we keep a "date:Wed Nov 4 • 7:00 PM"
# tag up to date instead, so the card's date box shows just the next date.
# (Shopify tags can't contain commas, so the date has none.)
# ---------------------------------------------------------------------------
def label_tags(product, now):
    """The date: tag a recurring show should carry, as a set, or None."""
    rule = parse_rule(product.get("tags"))
    if not rule:
        return None
    dates = sorted(d for d in (parse_show_datetime(v["title"], now=now, require_time=True)
                               for v in product["variants"]["nodes"]) if d and d >= now)
    if not dates:
        return None
    return {"date:" + variant_name(dates[0])}


def plan_label_updates(products, now):
    """[(product, tags_to_add, tags_to_remove)] for recurring shows. Pure - easy to test."""
    updates = []
    for p in products:
        want = label_tags(p, now)
        if want is None:
            continue
        have = {t for t in p.get("tags") or [] if t.startswith("date:")}
        add, remove = sorted(want - have), sorted(have - want)
        if add or remove:
            updates.append((p, add, remove))
    return updates


def apply_label_update(shop, product, add, remove):
    for mutation, tags in (("tagsRemove", remove), ("tagsAdd", add)):
        if not tags:
            continue
        res = shop.gql("""
          mutation Tags($id: ID!, $tags: [String!]!) {
            %s(id: $id, tags: $tags) { userErrors { field message } }
          }""" % mutation, {"id": product["id"], "tags": tags})[mutation]
        if res["userErrors"]:
            raise RuntimeError(res["userErrors"])
