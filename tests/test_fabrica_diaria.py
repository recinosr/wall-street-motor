import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from lab import fabrica_diaria as daily


def frame(days=160, start="2024-01-01"):
    idx = pd.date_range(start, periods=days, freq="D", tz="UTC")
    prices = [100+i for i in range(days)]
    return pd.DataFrame({"open": prices, "high": [p+2 for p in prices],
                         "low": [p-2 for p in prices], "close": [p+1 for p in prices],
                         "volume": [1]*days}, index=idx)


class DailyFactoryTests(unittest.TestCase):
    def test_universe_and_exact_candle_definitions(self):
        plan = list(daily.rules())
        self.assertEqual(len(plan), 102)
        self.assertEqual(sum(r["family"] == "velas_japonesas" for r in plan), 54)
        df = frame(20)
        self.assertTrue(daily.patterns(df)["tres_soldados_blancos"].iloc[2])
        self.assertFalse(daily.patterns(df)["tres_cuervos_negros"].iloc[2])

    def test_future_open_and_both_costs(self):
        df = frame(30)
        rule = {"family": "velas_japonesas", "asset": "BTC", "pattern": "tres_soldados_blancos", "horizon": 1}
        events = daily._schedule(rule, df, daily.signal(rule, df))
        self.assertEqual(events[0], (3, 3))
        returns = daily._event_returns(df, [events[0]])
        self.assertAlmostEqual(returns[3], df.close.iloc[3]/df.open.iloc[3]*.999**2-1)
        self.assertEqual(returns[2], 0)

    def test_weekday_is_day_traded_not_day_of_signal(self):
        df = frame(30, "2024-01-01")
        rule = {"family": "dia_semana", "asset": "BTC", "weekday": 1}
        self.assertTrue(daily.signal(rule, df).iloc[0])  # lunes decide martes
        self.assertFalse(daily.signal(rule, df).iloc[1])

    def test_missing_day_is_not_filled(self):
        df = frame(30).drop(pd.Timestamp("2024-01-04", tz="UTC"))
        rule = {"family": "velas_japonesas", "asset": "BTC", "pattern": "tres_soldados_blancos", "horizon": 1}
        events = daily._schedule(rule, df, daily.signal(rule, df))
        self.assertNotIn((3, 3), events)

    def test_reserved_not_fetched_without_full_bh(self):
        calls = []
        def fetcher(asset, start, end):
            calls.append((asset, start, end))
            return frame(30)
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(daily, "score", return_value={"months": [], "operations": 0, "reason": "insufficient_data"}):
            root = Path(folder)
            (root/"ideas").mkdir()
            for name in ("tendencia_diaria.json", "momentum_diario.json", "velas_diarias.json", "estacionalidad_diaria.json"):
                source = daily.ROOT/"ideas"/name
                (root/"ideas"/name).write_bytes(source.read_bytes())
            report = daily.run(fetcher, root, date(2026, 10, 8))
            self.assertEqual(report["tested"], 102)
            self.assertEqual(report["bh_passed"], 0)
            self.assertEqual(len(calls), 2)
            self.assertEqual({c[1:] for c in calls}, {(daily.START, daily.RESERVE_START)})
            saved = json.loads((root/"resultados/fabrica_diaria.json").read_text())
            self.assertNotIn("prices", saved)


if __name__ == "__main__":
    unittest.main()
