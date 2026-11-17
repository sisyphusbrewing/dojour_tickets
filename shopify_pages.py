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
        live = (shop.gql(READ, {"id": gid}).get("page") or {})
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
