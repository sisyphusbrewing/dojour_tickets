"""
Daily ticket counts for RealCount (ticketcounts@realcount.pro).

Agencies (UTA, WME, CAA, Gersh...) track counts through RealCount, which asks the
venue for updated numbers unless an automatic daily report arrives. This sends
one email a day listing every upcoming show booked through an agency, with
website + Dojour tickets combined, as a plain table in the body and a CSV
attachment so it can be read either way.

A show counts as agency-booked when its show_agents contact is on a company
domain (not gmail.com etc. and not our own). Set REALCOUNT_SHOWS to a comma
list of show titles to send only those instead.

Env: same Supabase/Shopify/SMTP secrets as the weekly agent report.
  REALCOUNT_TO  override the recipient (testing). Default ticketcounts@realcount.pro
  DRY_RUN=1     print instead of sending
"""
import csv
import html
import io
import os
import smtplib
import ssl
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from send_weekly_agent_reports import (
    CENTRAL_TZ, DRY_RUN, FROM_EMAIL, REPLY_TO, SMTP_HOST, SMTP_PASS, SMTP_USER,
    collect_shows, fetch_supabase,
)

TO = (os.environ.get("REALCOUNT_TO") or "ticketcounts@realcount.pro").strip()
ONLY = [t.strip() for t in (os.environ.get("REALCOUNT_SHOWS") or "").split(",") if t.strip()]

# The name agencies list us under in RealCount.
VENUE = "Sisyphus Brewing & Comedy"
CITY = "Minneapolis, MN"
DEFAULT_CAPACITY = 90   # the showroom; used only when Shopify can't be read

PERSONAL_DOMAINS = {"gmail.com", "googlemail.com", "yahoo.com", "icloud.com", "me.com", "mac.com",
                    "hotmail.com", "outlook.com", "live.com", "aol.com", "msn.com", "proton.me",
                    "protonmail.com", "sisyphusbrewing.com"}


def is_agency(agent_email):
    domains = {a.strip().lower().rpartition("@")[2] for a in agent_email.replace(";", ",").split(",") if "@" in a}
    return any(d and d not in PERSONAL_DOMAINS for d in domains)


def agency_titles():
    rows = fetch_supabase("show_agents?select=show_title,agent_email")
    if ONLY:
        wanted = {t.lower() for t in ONLY}
        return [r["show_title"].strip() for r in rows if r["show_title"].strip().lower() in wanted]
    return [r["show_title"].strip() for r in rows if is_agency(r.get("agent_email") or "")]


def seats_left(titles):
    """{(title, show_date): seats still for sale on the website}. The inventory
    mirror takes Dojour sales out of these, so sold + comps + this = capacity,
    which follows a show into the bigger room. Empty if Shopify is unreachable."""
    try:
        from maintain_shows import Shopify, fetch_active_products, date_text, skip_reason
        from fetch_tickets import clean_show_title, format_show_date
        from show_dates import parse_show_datetime
        products = fetch_active_products(Shopify())
    except (Exception, SystemExit) as e:
        print(f"Notice: could not read Shopify inventory ({e}); capacity falls back to {DEFAULT_CAPACITY}.")
        return {}
    wanted = {t.lower(): t for t in titles}
    left = {}
    for p in products:
        title = wanted.get(clean_show_title(p["title"]).lower())
        if not title or skip_reason(p):
            continue
        for v in p["variants"]["nodes"]:
            date_str = format_show_date(parse_show_datetime(date_text(v), require_time=True))
            if date_str:
                key = (title, date_str)
                left[key] = left.get(key, 0) + max(int(v.get("inventoryQuantity") or 0), 0)
    return left


def report_rows(titles):
    rows = []
    left = seats_left(titles)
    for (title, date_str), s in collect_shows(titles).items():
        if title not in titles or not s["timestamp"]:
            continue
        dt = datetime.fromtimestamp(s["timestamp"], CENTRAL_TZ)
        used = s["total"] + s["comp_tickets"]
        remaining = left.get((title, date_str))
        if remaining is None:
            remaining = max(DEFAULT_CAPACITY - used, 0)
        # Seats the venue blocked in Dojour leave the website at 0 without being
        # sold, so never report a room smaller than the showroom.
        capacity = max(used + remaining, DEFAULT_CAPACITY)
        remaining = capacity - used
        rows.append({
            "Event": f"{title} @ {VENUE}",
            "Artist": title,
            "Venue": VENUE,
            "City": CITY,
            "Date": dt.strftime("%Y-%m-%d"),
            "Day": dt.strftime("%a %d %b %Y"),
            "Time": dt.strftime("%-I:%M %p"),
            "Capacity": capacity,
            "Sold": s["total"],
            "Comps": s["comp_tickets"],
            "Remaining": remaining,
            "_ts": s["timestamp"],
        })
    rows.sort(key=lambda r: (r["_ts"], r["Artist"]))
    return rows


COLUMNS = ["Event", "Artist", "Venue", "City", "Date", "Time", "Capacity", "Sold", "Comps", "Remaining"]


def build_csv(rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=COLUMNS, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def build_text(rows, as_of):
    lines = [f"Daily ticket counts from {VENUE}, {CITY}", f"As of {as_of} (Central)", ""]
    for r in rows:
        lines.append(f"[{r['Day']}] {r['Event']} - {r['Time']}: {r['Sold']} sold, {r['Comps']} comps, "
                     f"capacity {r['Capacity']}")
    lines += ["", "Sold = paid tickets from all outlets (website + Dojour). Comps are not included in Sold.",
              "Same data attached as CSV.", "", "Sisyphus Box Office", "712 Ontario Ave W, Minneapolis, MN"]
    return "\n".join(lines)


def build_html(rows, as_of):
    th = 'style="text-align:left;padding:6px 10px;border:1px solid #ccc;background:#f2f2f2;"'
    td = 'style="padding:6px 10px;border:1px solid #ccc;"'
    head = "".join(f"<th {th}>{c}</th>" for c in COLUMNS)
    body = "".join("<tr>" + "".join(f"<td {td}>{html.escape(str(r[c]))}</td>" for c in COLUMNS) + "</tr>"
                   for r in rows)
    return (f'<html><body style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;">'
            f"<p>Daily ticket counts from <strong>{VENUE}</strong>, {CITY}.<br>As of {html.escape(as_of)} (Central).</p>"
            f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
            f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
            f"<p>Sold = paid tickets from all outlets (website + Dojour). Comps are not included in Sold. "
            f"Same data attached as CSV.</p>"
            f"<p>Sisyphus Box Office<br>712 Ontario Ave W, Minneapolis, MN</p></body></html>")


def main():
    titles = agency_titles()
    print(f"Agency-booked shows: {', '.join(titles) or 'none'}")
    rows = report_rows(titles)
    if not rows:
        print("No upcoming agency showtimes; nothing to send.")
        return

    now = datetime.now(CENTRAL_TZ)
    as_of = now.strftime("%Y-%m-%d %-I:%M %p")
    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"Daily Ticket Counts - {VENUE} - {now.strftime('%d %b %Y')}"
    msg["From"] = f"Sisyphus Box Office <{FROM_EMAIL}>"
    msg["To"] = TO
    if REPLY_TO:
        msg["Reply-To"] = REPLY_TO
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(build_text(rows, as_of), "plain"))
    alt.attach(MIMEText(build_html(rows, as_of), "html"))
    msg.attach(alt)
    att = MIMEApplication(build_csv(rows).encode("utf-8"), _subtype="csv")
    att.add_header("Content-Disposition", "attachment", filename=f"sisyphus-ticket-counts-{now.strftime('%Y-%m-%d')}.csv")
    msg.attach(att)

    print(build_text(rows, as_of))
    if DRY_RUN:
        print(f"[DRY RUN] Would send to {TO}")
        return
    if not SMTP_USER or not SMTP_PASS:
        raise SystemExit("SMTP credentials missing (SMTP_USER / SMTP_PASS).")
    with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=30) as server:
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(FROM_EMAIL, [TO], msg.as_string())
    print(f"Sent {len(rows)} showtimes to {TO}")


if __name__ == "__main__":
    main()
