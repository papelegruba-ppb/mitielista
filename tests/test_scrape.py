import datetime as dt
import pathlib
import unittest

import scrape


ROOT = pathlib.Path(__file__).parent
FIXTURES = ROOT / "fixtures"


class OfficialParserTests(unittest.TestCase):
    def test_parse_official_rx(self):
        html = (FIXTURES / "official_rx.html").read_text(encoding="utf-8")
        parser = scrape._TextExtractor()
        parser.feed(html)
        self.assertEqual(scrape.parse_official_lot(parser.text), (2026, 184))


class FallbackParserTests(unittest.TestCase):
    def test_explicit_year_and_publication_date(self):
        html = (FIXTURES / "fallback_portal.html").read_text(encoding="utf-8")
        records = scrape.parse_portal_html(
            html, "Albacete", "https://portalextranjeria.com/lotes-nie-albacete/",
            checked="2026-10-31",
        )
        self.assertEqual(len(records), 1)
        self.assertEqual((records[0]["y"], records[0]["n"]), (2026, 73))
        self.assertEqual(records[0]["published"], "2026-10-20")
        self.assertEqual(records[0]["checked"], "2026-10-31")

    def test_missing_lot_year_is_discarded(self):
        html = (FIXTURES / "fallback_no_year.html").read_text(encoding="utf-8")
        records = scrape.parse_portal_html(
            html, "Albacete", "https://portalextranjeria.com/lotes-nie-albacete/",
            checked="2026-10-31",
        )
        self.assertEqual(records, [])

    def test_merge_drops_stale_or_undated_retained_offices(self):
        today = dt.date(2026, 10, 31).isoformat()
        previous = {"offices": [
            {"id": "fresh", "prov": "Albacete", "name": "Fresh", "y": 2026, "n": 10,
             "checked": "2026-10-20", "published": "2026-10-19"},
            {"id": "stale-published", "prov": "Albacete", "name": "Stale published",
             "y": 2026, "n": 20, "checked": "2026-10-20", "published": "2026-09-01"},
            {"id": "stale-checked", "prov": "Albacete", "name": "Stale checked",
             "y": 2026, "n": 30, "checked": "2026-09-01", "published": "2026-10-20"},
            {"id": "undated", "prov": "Albacete", "name": "Undated", "y": 2026, "n": 40},
        ]}
        merged = scrape.merge(previous, [], today)
        self.assertEqual([item["id"] for item in merged], ["fresh"])


if __name__ == "__main__":
    unittest.main()
