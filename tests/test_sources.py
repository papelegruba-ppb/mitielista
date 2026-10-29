import unittest

from sources import normalize, parse_date, parse_lot, SOURCES


class SourceParsingTests(unittest.TestCase):
    def test_parse_lot_both_orders(self):
        self.assertEqual(parse_lot("2026/178"), (2026, 178))
        self.assertEqual(parse_lot("178/2026"), (2026, 178))

    def test_rejects_number_without_year(self):
        self.assertIsNone(parse_lot("178"))
        self.assertIsNone(parse_lot("lote actual: 178"))

    def test_parse_date_formats(self):
        self.assertEqual(parse_date("20/10/2026"), "2026-10-20")
        self.assertEqual(parse_date("2026-10-20"), "2026-10-20")
        self.assertIsNone(parse_date("32/10/2026"))

    def test_normalize_names(self):
        self.assertEqual(normalize("Comisaría de Málaga"), "comisaria de malaga")

    def test_sources_mark_officiality_and_catalog_only(self):
        by_id = {s["id"]: s for s in SOURCES}
        self.assertTrue(by_id["mpt_melilla"]["official"])
        self.assertFalse(by_id["sclt"]["official"])
        self.assertEqual(by_id["policia_catalogo"]["method"], "csv")


if __name__ == "__main__":
    unittest.main()
