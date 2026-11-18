"""
Sisyphus - push website page text from this repo to Shopify.

Some pages on sisyphusbrewing.com (Online Store > Pages) are kept here as
HTML files so changes are reviewed and saved like everything else. Each file
starts with a comment naming the page, for example:

    <!-- Sisyphus: body of the Shopify page "FAQs" (handle: taproom, Page 144628421). -->

When a pull request that changes one of these files merges to main, the
"Shopify pages" workflow runs this script and the page on the website gets
the file's text (minus that first comment). Pages only, never the theme: the
live theme stays off limits (Sam's rule).

Usage:  python shopify_pages.py [file ...]     (default: every known page file)
Safety: DRY_RUN=1 prints what would change without touching Shopify.

If the repo's Shopify app isn't allowed to read or write pages (it lacks the
read_content / write_content scopes, as it did on Nov 17 2026), the script
says so in a warning and stops without failing. A red run here only emailed
Sam a "failed" notice on every merge (Sam, Nov 17 2026: "Why are we getting
the GitHub failures in my inbox?"), and the fix for it is a setting in
Shopify, not anything in the repo. Until that setting is on, page text gets
pushed with the Shopify connector instead.
"""
import glob
import os
import re
import sys

PAGE_FILES = ["mic/shopify-page.html"] + sorted(glob.glob("pages/*.html"))
HEADER = re.compile(r"\A\s*<!--(?P<c>.*?)-->\s*\n?", re.S)
PAGE_ID = re.compile(r"\bPage (\d+)\b")
DRY_RUN = os.environ.get("DRY_RUN", "").strip().lower() in ("1", "true", "yes")


def split_page_file(text):
    """Return (page id, body) from a page file, or (None, None) if the file
    doesn't start with a comment naming a Shopify page."""
    m = HEADER.match(text)
    if not m:
        return None, None
    pid = PAGE_ID.search(m.group("c"))
    if not pid:
        return None, None
    return pid.group(1), text[m.end():]


UPDATE = """
mutation($id: ID!, $page: PageUpdateInput!) {
  pageUpdate(id: $id, page: $page) { page { id handle } userErrors { field message } }
}"""
READ = "query($id: ID!) { page(id: $id) { handle body } }"

NO_ACCESS_NOTE = ("Shopify won't let this app read or write pages (it needs the "
                  "read_content and write_content access scopes). Nothing was "
                  "changed. Push the page text with the Shopify connector, or "
                  "add those scopes to the app in Shopify.")


def access_denied(err):
    """True when a Shopify error is the app missing a permission (scope)."""
    return "ACCESS_DENIED" in str(err) or "access scope" in str(err)


def main(files):
    jobs = []
    for path in files:
        pid, body = split_page_file(open(path, encoding="utf-8").read())
        if pid is None:
            print(f"skip {path}: no 'Page <id>' header")
            continue
        jobs.append((path, pid, body))
    if not jobs:
        return 0
    from maintain_shows import Shopify
    shop = Shopify()
    failed = 0
    for path, pid, body in jobs:
        gid = f"gid://shopify/Page/{pid}"
        try:
            live = (shop.gql(READ, {"id": gid}).get("page") or {})
        except RuntimeError as err:
            if not access_denied(err):
                raise
            # A GitHub warning shows on the run's page without failing it.
            print(f"::warning title=Shopify pages not pushed::{NO_ACCESS_NOTE}")
            return 0
        if not live:
            print(f"FAIL {path}: page {pid} not found")
            failed += 1
            continue
        if live.get("body", "").strip() == body.strip():
            print(f"same {path} -> /pages/{live['handle']}")
            continue
        if DRY_RUN:
            print(f"would update {path} -> /pages/{live['handle']}")
            continue
        res = shop.gql(UPDATE, {"id": gid, "page": {"body": body}})["pageUpdate"]
        if res["userErrors"]:
            print(f"FAIL {path}: {res['userErrors']}")
            failed += 1
        else:
            print(f"updated {path} -> /pages/{res['page']['handle']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or PAGE_FILES))
