"""
Sisyphus - CSS, the Comic Scoring System: measures comics typed into the CSS
page (css/index.html) and saves their points to Supabase comic_scores.

Run from GitHub: Actions -> "Comic scores" (the page starts it when a name is
added). Scores every row with status 'requested'; with SCORE_ALL=1 it
re-measures everyone. For each comic:
  - Instagram followers: instagram.com/<handle>/embed/ in a real browser (the
    API and profile pages are blocked for servers), biggest matching account.
  - TikTok followers and YouTube subscribers from their public pages.
  - Reddit buzz: votes on the top posts naming them in the past year, plus
    posts in r/Minneapolis and r/TwinCities (Reddit only loads in a browser).
  - Tickets per show here, from show_history (Dojour), recent runs counting most.
The weights come from 105 past headliners (Oct 2026): Reddit buzz predicted
tickets/show best (R2 0.56), Instagram next (0.38), both together 0.64.
House stars, the likeability face and notes are set on the page, which adds
everything up.
"""
import json
import math
import os
import re
import sys
import unicodedata
from datetime import datetime
from urllib.parse import quote

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")
SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SB = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}", "Content-Type": "application/json"}


def L(x):
    return math.log10(1 + (x or 0))


def clamp(x):
    return max(0.0, min(1.0, x))


def simp(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower())


def num(s):
    m = re.search(r"([\d.,]+)\s*([KkMm]?)", s or "")
    if not m:
        return None
    return int(float(m.group(1).replace(",", "")) * {"k": 1e3, "m": 1e6}.get(m.group(2).lower(), 1))


def walk(o, key):
    if isinstance(o, dict):
        if key in o:
            yield o[key]
        for v in o.values():
            yield from walk(v, key)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v, key)


# ---------- followers ----------

def youtube(name):
    try:
        h = requests.get("https://www.youtube.com/results", params={"search_query": f"{name} comedian", "sp": "EgIQAg%3D%3D"},
                         headers={"User-Agent": UA, "Accept-Language": "en-US"}, timeout=20).text
        m = re.search(r"var ytInitialData = (\{.*?\});</script>", h)
        if not m:
            return None
        first, last = simp(name.split()[0]), simp(name.split()[-1])
        for c in walk(json.loads(m.group(1)), "channelRenderer"):
            title = c["title"]["simpleText"]
            t = simp(title)
            if last in t and (first in t or len(name.split()) == 1) and "clips" not in t and "fan" not in t and "topic" not in title.lower():
                texts = [c.get("subscriberCountText", {}).get("simpleText", ""), c.get("videoCountText", {}).get("simpleText", "")]
                subs = next((num(x) for x in texts if "subscriber" in x), None)
                handle = next((x for x in texts if x.startswith("@")), None) or \
                    c["navigationEndpoint"]["browseEndpoint"].get("canonicalBaseUrl", "").lstrip("/")
                return {"handle": handle.lstrip("@"), "subs": subs}
    except Exception as e:
        print(f"  youtube: {e}")
    return None


def tiktok(handle, name):
    try:
        h = requests.get(f"https://www.tiktok.com/@{handle}", headers={"User-Agent": UA}, timeout=20).text
        m = re.search(r'id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>', h)
        u = json.loads(m.group(1))["__DEFAULT_SCOPE__"]["webapp.user-detail"]
        if u.get("statusCode") != 0:
            return None
        nick = u["userInfo"]["user"].get("nickname", "")
        if simp(name.split()[-1]) not in simp(nick) + simp(handle):
            return None
        return {"handle": handle, "followers": u["userInfo"].get("stats", {}).get("followerCount")}
    except Exception:
        return None


def guesses(name, yt):
    base, f, l = simp(name), simp(name.split()[0]), simp(name.split()[-1])
    g = ([yt["handle"]] if yt and yt.get("handle") else []) + \
        [base, base + "comedy", base + "comedian", "the" + base, f + "_" + l, f + "." + l, base + "comic", "its" + base, base + "_"]
    out = []
    for x in g:
        if x and x.lower() not in out:
            out.append(x.lower())
    return out


def instagram(page, name, handles):
    last, best = simp(name.split()[-1]), None
    for g in handles:
        try:
            page.goto(f"https://www.instagram.com/{g}/embed/", wait_until="networkidle", timeout=30000)
            text = page.evaluate("() => document.body.innerText")
        except Exception:
            continue
        m = re.search(r"([\d.,]+[KM]?) followers", text, re.I)
        if not m:
            continue
        lines = [s.strip() for s in text.split("\n") if s.strip()]
        display = lines[1] if len(lines) > 1 else ""
        if last not in simp(g) and last not in simp(display):
            continue
        n = num(m.group(1))
        if n and n >= 1000 and (not best or n > best["followers"]):
            best = {"handle": g, "followers": n}
    return best


def reddit_search(page, url, scrolls):
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)
    for _ in range(scrolls):
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(1200)
    rows = page.eval_on_selector_all("[data-testid=search-post-unit]", "es => es.map(e => e.innerText.replace(/\\s+/g, ' '))")
    if not rows and re.search(r"blocked|network security|whoa there", page.evaluate("() => document.body.innerText"), re.I):
        raise RuntimeError("Reddit blocked this server")
    if not rows:
        print(f"  reddit: no posts at {url} ({page.title()})")
    r = {"posts": 0, "votes": 0, "comments": 0}
    for x in rows:
        r["posts"] += 1
        v = re.search(r"([\d.,]+[km]?) votes?", x, re.I)
        c = re.search(r"([\d.,]+[km]?) comments?", x, re.I)
        r["votes"] += num(v.group(1)) or 0 if v else 0
        r["comments"] += num(c.group(1)) or 0 if c else 0
    return r


def reddit(page, name):
    q = quote(f'"{name}"')
    try:
        year = reddit_search(page, f"https://www.reddit.com/search/?q={q}&type=posts&t=year&sort=top", 3)
        local = 0
        for sub in ("Minneapolis", "TwinCities"):
            local += reddit_search(page, f"https://www.reddit.com/r/{sub}/search/?q={q}&type=posts", 0)["posts"]
        return {"votes_year": year["votes"], "posts_year": year["posts"], "local_posts": local}
    except Exception as e:
        print(f"  reddit: {e}")
        return None


# ---------- tickets here ----------

def show_history():
    rows, start = [], 0
    while True:
        r = requests.get(f"{SB_URL}/rest/v1/show_history?select=show_title,event_title,starts_at,tickets,orders&order=starts_at",
                         headers={**SB, "Range": f"{start}-{start + 999}"}, timeout=30)
        r.raise_for_status()
        rows += r.json()
        if len(r.json()) < 1000:
            return rows
        start += 1000


def runs_here(name, history):
    """[(date, tickets, shows)] for runs whose title names the comic. Shows
    within 4 days are one run; venue holds (60+ tickets on 3 or fewer orders)
    and runs under 15 tickets are left out."""
    key, shows = simp(name), []
    for r in history:
        if not r.get("starts_at") or key not in simp(r.get("show_title") or r.get("event_title")):
            continue
        dt = datetime.fromisoformat(r["starts_at"].replace("Z", "+00:00"))
        if dt > datetime.now(dt.tzinfo) or (r["tickets"] >= 60 and r["orders"] <= 3):
            continue
        shows.append((dt, r["tickets"]))
    runs = []
    for dt, t in sorted(shows):
        if runs and (dt - runs[-1]["last"]).days <= 4:
            runs[-1].update(last=dt, tickets=runs[-1]["tickets"] + t, shows=runs[-1]["shows"] + 1)
        else:
            runs.append({"first": dt, "last": dt, "tickets": t, "shows": 1})
    return [(r["first"].date().isoformat(), r["tickets"], r["shows"]) for r in runs if r["tickets"] >= 15]


# ---------- points ----------

def reach_per_show(ig, reddit_votes, twin_cities):
    # Tickets/show from reach, fit on the 91 past headliners with Instagram (R2 0.64);
    # the Reddit-only fit (R2 0.56) when no Instagram account was found.
    if ig:
        p = -15.0 + 11.0 * L(ig) + 7.9 * L(reddit_votes) + 11.6 * bool(twin_cities)
    else:
        p = 32.4 + 10.6 * L(reddit_votes)
    return max(10, min(90, p))


def points(c):
    runs = sorted(c["runs"])
    if runs:
        w = [0.5 ** i for i in range(len(runs))][::-1]   # latest run counts 1, the one before 1/2, ...
        per = sum(wi * t / n for wi, (d, t, n) in zip(w, runs)) / sum(w)
    else:
        per = reach_per_show(c["ig"], c["reddit_votes"], c["twin_cities"])
    momentum = 2.5
    if len(runs) >= 2:
        ratio = (runs[-1][1] / runs[-1][2]) / max(1, runs[-2][1] / runs[-2][2])
        momentum = 2.5 + 2.5 * max(-1, min(1, (ratio - 1) / 0.5))
    pts = {
        "draw_here": 30 * clamp(per / 90),
        "reddit": 15 * clamp((L(c["reddit_votes"]) - 1) / 4),
        "instagram": 9 * clamp((L(c["ig"]) - 3) / 3.3),
        "tiktok": 3 * clamp((L(c["tiktok"]) - 3) / 3.3),
        "youtube": 3 * clamp((L(c["youtube"]) - 3) / 3),
        "local": 10.0 if c["twin_cities"] else float(min(5, c["reddit_local_posts"] or 0)),
        "momentum": momentum,
    }
    return {k: round(v, 1) for k, v in pts.items()}, round(per), not runs


# ---------- main ----------

def measure(page, row, history):
    name = row["comedian"]
    old = row.get("inputs") or {}
    yt = youtube(name)
    handles = guesses(name, yt)
    if old.get("instagram_handle") and old["instagram_handle"] not in handles:
        handles.insert(0, old["instagram_handle"])
    tt = max((r for r in (tiktok(g, name) for g in handles) if r), key=lambda r: r["followers"] or 0, default=None)
    ig = instagram(page, name, handles)
    # Reddit blocks some servers (GitHub's included). Then keep what we had,
    # and reddit_checked says the buzz wasn't re-measured this time.
    rd = reddit(page, name)
    if rd is None:
        rd = {"votes_year": old.get("reddit_votes"), "posts_year": old.get("reddit_posts"), "local_posts": old.get("reddit_local_posts")}
    c = {"ig": (ig or {}).get("followers"), "instagram_handle": (ig or {}).get("handle"),
         "tiktok": (tt or {}).get("followers"), "tiktok_handle": (tt or {}).get("handle"),
         "youtube": (yt or {}).get("subs"), "youtube_handle": (yt or {}).get("handle"),
         "reddit_votes": rd.get("votes_year"), "reddit_posts": rd.get("posts_year"), "reddit_local_posts": rd.get("local_posts"),
         "twin_cities": bool(row.get("twin_cities")), "runs": runs_here(name, history),
         "reddit_checked": rd.get("votes_year") is not None}
    pts, per, estimated = points(c)
    found = any(c[k] for k in ("ig", "tiktok", "youtube", "reddit_votes")) or c["runs"]
    print(f"{name}: IG {c['ig']} TT {c['tiktok']} YT {c['youtube']} Reddit {c['reddit_votes']} runs {len(c['runs'])} -> "
          f"{sum(pts.values()):.0f} + house", flush=True)
    return {"status": "scored" if found else "not_found", "points": pts, "inputs": c, "per_show": per,
            "draw_estimated": estimated, "scored_at": datetime.utcnow().isoformat() + "Z"}


def main():
    if not SB_URL or not SB_KEY:
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are needed.")
    filt = "" if os.environ.get("SCORE_ALL") == "1" else "&status=eq.requested"
    rows = requests.get(f"{SB_URL}/rest/v1/comic_scores?select=*{filt}", headers=SB, timeout=30).json()
    print(f"{len(rows)} comic(s) to score.")
    if not rows:
        return
    history = show_history()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=UA)
        for row in rows:
            try:
                patch = measure(page, row, history)
            except Exception as e:
                print(f"{row['comedian']}: failed ({e})")
                continue
            r = requests.patch(f"{SB_URL}/rest/v1/comic_scores?comedian=eq.{quote(row['comedian'])}",
                               headers=SB, json=patch, timeout=30)
            if r.status_code >= 300:
                print(f"  save failed: {r.status_code} {r.text[:200]}")
        browser.close()


if __name__ == "__main__":
    main()
