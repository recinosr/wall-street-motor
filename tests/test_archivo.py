import tempfile
import unittest

import pandas as pd

from lab.archivar import guardar
from lab.archivo import leer


class ArchivoTest(unittest.TestCase):
    def test_merge_idempotente_y_lectura_utc(self):
        with tempfile.TemporaryDirectory() as tmp:
            idx = pd.date_range("2026-09-30 23:59", periods=3, freq="min", tz="UTC")
            velas = pd.DataFrame({"open": [1., 2., 3.], "high": [1., 2., 3.],
                                  "low": [1., 2., 3.], "close": [1., 2., 3.],
                                  "volume": [10., 20., 30.]}, index=idx)
            guardar(velas, "BTC", tmp)
            guardar(velas, "BTC", tmp)
            out = leer("BTC", idx[0], idx[-1] + pd.Timedelta(minutes=1), raiz=tmp)
            self.assertEqual(len(out), 3)
            self.assertEqual(list(out.close), [1., 2., 3.])
            self.assertEqual(str(out.index.tz), "UTC")

    def test_rechaza_rutas_no_seguras(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                leer("../BTC", "2026-09-01", "2026-10-01", raiz=tmp)
