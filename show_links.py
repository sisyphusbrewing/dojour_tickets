"""
Short show links: sisyphusbrewing.com/shows/<handle> -> /products/<handle>.

Shopify won't let a store rename /products/, so every show gets a URL redirect
instead. Posters, ads and emails use the /shows/ link; Shopify forwards it to
the real page. Used by the show builder (new show) and daily maintenance
(every active show, so nothing is ever missed).
"""
SITE = "https://www.sisyphusbrewing.com"

REDIRECTS_QUERY = """
query ShowRedirects($cursor: String) {
  urlRedirects(first: 250, after: $cursor, query: "path:/shows/*") {
    nodes { path }
    pageInfo { hasNextPage endCursor }
  }
}"""

CREATE_MUTATION = """
mutation ShowLink($r: UrlRedirectInput!) {
  urlRedirectCreate(urlRedirect: $r) { userErrors { field message } }
}"""


def path(handle):
    return f"/shows/{handle}"


def url(handle, site=SITE):
    return f"{site.rstrip('/')}{path(handle)}"


def existing_paths(gql):
    paths, cursor = set(), None
    while True:
        page = gql(REDIRECTS_QUERY, {"cursor": cursor})["urlRedirects"]
        paths.update(n["path"] for n in page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            return paths
        cursor = page["pageInfo"]["endCursor"]


def ensure(gql, handles, dry_run=False):
    """Create any missing /shows/ redirects. Returns (created, errors)."""
    have = existing_paths(gql)
    created, errors = [], []
    for handle in handles:
        if path(handle) in have:
            continue
        if not dry_run:
            res = gql(CREATE_MUTATION, {"r": {"path": path(handle), "target": f"/products/{handle}"}})
            problems = res["urlRedirectCreate"]["userErrors"]
            if problems:
                errors.append((handle, "; ".join(p["message"] for p in problems)))
                continue
        created.append(handle)
    return created, errors
