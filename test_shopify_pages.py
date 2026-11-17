import glob
import unittest

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


if __name__ == "__main__":
    unittest.main()
