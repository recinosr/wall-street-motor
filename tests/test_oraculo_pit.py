import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import json
from unittest.mock import Mock

from lab import oraculo_pit, oraculo_niveles


class PointInTimeTests(unittest.TestCase):
    def test_visibility_uses_availability_instant(self):
        rows = [
            {"available_at": "2020-01-02T14:30:00Z", "x": 1},
            {"available_at": "2020-01-02T21:00:00Z", "x": 2},
        ]
        self.assertEqual([r["x"] for r in oraculo_pit.visibles(rows, "2020-01-02T16:00:00Z")], [1])

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            oraculo_pit.visibles([{"available_at": "2020-01-02T14:30:00Z"}], "2020-01-02 16:00")

    @patch("lab.oraculo_pit._get")
    def test_cpi_uses_bls_release_date_and_time_not_reference_month(self, get):
        get.return_value = {"body": '<a href="/news.release/archives/cpi_03122024.pdf">January 2024 CPI</a>', "fetched_at": "2026-10-16T00:00:00Z"}
        result = oraculo_pit.serie_cpi_bls("2024-01-01", "2024-04-01")
        self.assertEqual(result["events"][0]["date"], "2024-03-12")
        self.assertEqual(result["events"][0]["available_at"], "2024-03-12T12:30:00+00:00")

    @patch("lab.oraculo_pit._get")
    def test_fomc_uses_statement_publication_timestamp(self, get):
        get.return_value = {"body": '<a href="/newsevents/pressreleases/monetary20240131a.htm">Statement</a>', "fetched_at": "2026-10-16T00:00:00Z"}
        result = oraculo_pit.fomc("2024-01-01", "2024-03-01")
        self.assertEqual(result["events"][0]["date"], "2024-01-31")
        self.assertEqual(result["events"][0]["available_at"], "2024-01-31T19:00:00+00:00")

    def test_edgar_invalid_cik_rejected_before_network(self):
        with self.assertRaises(ValueError):
            oraculo_pit.edgar_presentaciones("abc")

    def test_opened_sealed_window_cannot_be_run_again_in_same_version(self):
        output = Mock()
        output.exists.return_value = True
        output.read_text.return_value = json.dumps({"version": "oraculo-pit-v1",
                                                    "aperturas_prueba_sellada": {"nivel1": 2}})
        with patch.object(oraculo_niveles, "OUTPUT", output):
            with self.assertRaisesRegex(RuntimeError, "ya se abrió"):
                oraculo_niveles.ejecutar()


if __name__ == "__main__":
    unittest.main()
