import unittest

from lab.oraculo_n6 import bh, cargar_prereg


class OraculoN6(unittest.TestCase):
    def test_prereg_sellado(self):
        pre, sha = cargar_prereg()
        self.assertEqual(pre["version"], "oraculo-nivel6")
        self.assertEqual(len(sha), 64)

    def test_bh_monotono(self):
        q = bh([0.01, 0.04, 0.5])
        self.assertAlmostEqual(q[0], 0.03)
        self.assertTrue(all(0 <= x <= 1 for x in q))


if __name__ == "__main__":
    unittest.main()
