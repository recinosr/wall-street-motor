import json
import unittest
from pathlib import Path

PIT = json.loads(Path('datos/universo_pit/sp500_miembros.json').read_text(encoding='utf8'))
MEMBERS = PIT['miembros_por_fecha']

class Sp500PitTests(unittest.TestCase):
    def test_daily_membership_dates_are_sorted_and_have_index_size(self):
        dates = list(MEMBERS)
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(len(MEMBERS['2025-01-02']), 503)

    def test_known_additions_and_removals(self):
        # Five independently dated Wikipedia changes, including delisted names.
        self.assertIn('PLTR', MEMBERS['2024-09-23']); self.assertNotIn('AAL', MEMBERS['2024-09-23'])
        self.assertIn('HOOD', MEMBERS['2025-09-22']); self.assertNotIn('CZR', MEMBERS['2025-09-22'])
        self.assertIn('SNDK', MEMBERS['2025-11-28']); self.assertNotIn('IPG', MEMBERS['2025-11-28'])
        self.assertIn('AXON', MEMBERS['2023-05-04']); self.assertNotIn('FRC', MEMBERS['2023-05-04'])
        self.assertIn('LITE', MEMBERS['2026-03-23']); self.assertNotIn('MOH', MEMBERS['2026-03-23'])

    def test_weekend_and_non_membership_dates_are_not_fabricated(self):
        self.assertNotIn('2025-01-04', MEMBERS)
        self.assertNotIn('1900-01-01', MEMBERS)

if __name__ == '__main__':
    unittest.main()
