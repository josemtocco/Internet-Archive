import unittest
from gerar_m3u import allowed_license, is_portuguese, merge_items, render_m3u, video_files


class PlaylistTests(unittest.TestCase):
    def test_license_filter_allows_cc_by(self):
        self.assertTrue(allowed_license({"licenseurl": "https://creativecommons.org/licenses/by/4.0/"}))

    def test_portuguese_language_metadata_is_accepted(self):
        self.assertTrue(is_portuguese({"language": "por"}))
        self.assertTrue(is_portuguese({"language": "Portuguese"}))
        self.assertTrue(is_portuguese({"description": "Audio in Portuguese"}))
        self.assertTrue(is_portuguese({"description": "Dublagem brasileira"}))
        self.assertTrue(is_portuguese({"subject": ["cinema brasileiro"]}))

    def test_english_only_metadata_is_rejected(self):
        self.assertFalse(is_portuguese({"language": "eng", "title": "Classic western"}))

    def test_license_filter_rejects_unknown(self):
        self.assertFalse(allowed_license({"licenseurl": "https://example.com/all-rights-reserved"}))
        self.assertFalse(allowed_license({}))

    def test_video_files_prefers_mp4_and_ignores_tiny(self):
        item = {"files": [
            {"name": "preview.mp4", "size": "500"},
            {"name": "film.webm", "size": "5000000"},
            {"name": "film.mp4", "size": "9000000"},
        ]}
        self.assertEqual(video_files(item)[0]["name"], "film.mp4")

    def test_m3u_deduplicates_urls(self):
        items = [
            {"title": "Filme A", "url": "https://example.org/a.mp4", "group": "Filmes"},
            {"title": "Outro título", "url": "https://example.org/a.mp4", "group": "Filmes"},
        ]
        result = render_m3u(items)
        self.assertEqual(result.count("https://example.org/a.mp4"), 1)
        self.assertIn("#EXTM3U", result)
        self.assertIn("#EXTINF:", result)

    def test_existing_unknown_link_is_preserved(self):
        old = [{"title": "Antigo", "url": "https://example.org/old.mp4", "misses": 0}]
        merged = merge_items(old, [], dead_checker=lambda url: None)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["last_status"], "unknown_preserved")

    def test_dead_link_removed_only_after_two_checks(self):
        old = [{"title": "Antigo", "url": "https://example.org/old.mp4", "misses": 0}]
        first = merge_items(old, [], dead_checker=lambda url: True)
        self.assertEqual(len(first), 1)
        self.assertEqual(first[0]["misses"], 1)
        second = merge_items(first, [], dead_checker=lambda url: True)
        self.assertEqual(len(second), 0)


if __name__ == "__main__":
    unittest.main()
