import glob
import unittest

from unittest import mock

import shopify_pages
from shopify_pages import PAGE_FILES, split_page_file


class SplitPageFile(unittest.TestCase):
    def test_header_is_removed_and_id_read(self):
        pid, body = split_page_file('<!-- x (handle: a, Page 123).\n  more -->\n<h2>Hi</h2>\n')
        self.assertEqual(pid, "123")
        self.assertEqual(body, "<h2>Hi</h2>\n")

    def test_body_comments_are_kept(self):
        pid, body = split_page_file('<!-- Page 9 -->\n<!-- keep me -->\n<p>x</p>')
        self.assertEqual(body, "<!-- keep me -->\n<p>x</p>")

    def test_files_without_page_header_are_skipped(self):
        self.assertEqual(split_page_file("<p>no header</p>"), (None, None))
        self.assertEqual(split_page_file("<!-- just a note -->\n<p>x</p>"), (None, None))

    def test_repo_page_files_all_name_a_page(self):
        self.assertIn("pages/taproom.html", PAGE_FILES)
        for path in PAGE_FILES:
            pid, body = split_page_file(open(path, encoding="utf-8").read())
            self.assertIsNotNone(pid, path)
            self.assertNotIn("Page " + pid, body[:300], path)

    def test_thursday_showcase_is_8pm_everywhere(self):
        for path in PAGE_FILES:
            text = open(path, encoding="utf-8").read()
            self.assertNotRegex(text, r"Thursday[^.<]*\b7(:00)? ?PM", path)


class MissingScopes(unittest.TestCase):
    """Without page access the run warns and passes, so a merge doesn't
    email Sam a failure (Sam, Nov 17 2026)."""

    def run_with(self, error):
        shop = mock.Mock()
        shop.gql.side_effect = RuntimeError(error)
        with mock.patch("maintain_shows.Shopify", return_value=shop):
            return shopify_pages.main(["mic/shopify-page.html"]), shop

    def test_access_denied_warns_and_passes_without_writing(self):
        code, shop = self.run_with(
            "Shopify error: [{'message': 'Access denied for page field. Required access: "
            "`read_content` access scope', 'extensions': {'code': 'ACCESS_DENIED'}}]")
        self.assertEqual(code, 0)
        self.assertEqual(shop.gql.call_count, 1)  # read only, no pageUpdate

    def test_other_errors_still_fail(self):
        with self.assertRaises(RuntimeError):
            self.run_with("Shopify error: Throttled")


if __name__ == "__main__":
    unittest.main()
