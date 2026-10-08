import random
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from lab.escuela import Sesion, dias_particion
from lab.escuela_bots import BOTS, jugar
from lab import escuela_cli


def velas(precios):
    idx = pd.date_range("2026-09-01 14:30", periods=len(precios), freq="min", tz="UTC")
    return pd.DataFrame({"open": precios, "high": precios, "low": precios,
                         "close": precios, "volume": [1] * len(precios)}, index=idx)


class EscuelaTest(unittest.TestCase):
    def test_particiones_fijas_no_cambian_al_agregar_dias(self):
        dias = ['2025-03-31', '2025-04-01', '2025-12-31', '2026-01-01']
        self.assertEqual(dias_particion(dias, 'entrenamiento'), dias[:1])
        self.assertEqual(dias_particion(dias, 'validacion'), dias[1:3])
        self.assertEqual(dias_particion(dias, 'prueba'), dias[3:])
        self.assertEqual(dias_particion(dias + ['2026-10-03'], 'entrenamiento'), dias[:1])
    def test_monte_carlo_vectorizado_conserva_20_semillas(self):
        rng_precios = random.Random(951)
        precios = [100.0]
        for _ in range(80):
            precios.append(precios[-1] * (1 + rng_precios.gauss(0, 0.003)))
        frame = velas(precios)
        for seed in range(20):
            with self.subTest(semilla=seed):
                s = Sesion(seed, activo="BTC", duracion=80, velas=frame, guardar=False)
                s.paso("esperar", k=seed + 1)
                s.paso("comprar", tamaño=0.5, prob_sube=0.5, razon="referencia")
                s.paso("esperar", k=10)
                s.paso("cerrar", prob_sube=0.5, razon="referencia")
                previo = random.Random()
                previo.setstate(s.rng.getstate())
                muestras = []
                for _ in range(1000):
                    valor = 1.0
                    for ini, fin in ((seed + 1, seed + 12),):
                        plazo = fin - ini
                        j = previo.randrange(0, 80 - plazo + 1)
                        ratio = precios[j + plazo] / precios[j]
                        f = s.operaciones[0]["fraccion"]
                        valor *= 1 + f * ((ratio - 1) - s.costo * (1 + ratio))
                    muestras.append(valor - 1)
                r = s.terminar()
                neto = s.cash / 10000 - 1
                esperado = 100 * (sum(x < neto - 1e-10 for x in muestras) +
                                  0.5 * sum(abs(x - neto) <= 1e-10 for x in muestras)) / 1000
                self.assertEqual(r["percentil_azar"], round(esperado, 2))

    def test_bot_resumido_conserva_20_resultados(self):
        rng = random.Random(42)
        precios = [100.0]
        for _ in range(80):
            precios.append(precios[-1] * (1 + rng.gauss(0, 0.003)))
        frame = velas(precios)
        for seed in range(20):
            bot = BOTS[seed % len(BOTS)]
            viejo = Sesion(seed, activo="BTC", duracion=60, velas=frame, guardar=False)
            nuevo = Sesion(seed, activo="BTC", duracion=60, velas=frame, guardar=False, resumido=True)
            self.assertEqual(jugar(viejo, bot, seed + 7), jugar(nuevo, bot, seed + 7))

    def test_observacion_no_filtra_futuro_ni_fecha_en_anonimo(self):
        s = Sesion(1, activo="BTC", duracion=3, velas=velas([100, 200, 300, 400]), guardar=False)
        obs = s.observacion()
        self.assertEqual(len(obs["velas"]), 1)
        self.assertNotIn("activo", obs)
        self.assertNotIn("instante", obs)
        self.assertEqual(obs["velas"][-1]["close"], 100)
        s.paso("esperar")
        self.assertEqual(len(s.observacion()["velas"]), 2)

    def test_cobra_ambos_lados(self):
        s = Sesion(1, activo="BTC", duracion=3, velas=velas([100] * 4), guardar=False)
        s.paso("comprar", tamaño=0.5, prob_sube=0.5, razon="prueba")
        s.paso("cerrar", prob_sube=0.5, razon="prueba")
        r = s.terminar()
        self.assertAlmostEqual(r["neto"], -0.001, places=5)
        self.assertEqual(r["operaciones"], 2)
        self.assertAlmostEqual(r["percentil_azar"], 50, places=1)

    def test_azar_queda_cerca_de_percentil_cincuenta(self):
        rng = random.Random(55)
        percentiles = []
        for seed in range(20):
            precios = [100.0]
            for _ in range(80):
                precios.append(precios[-1] * (1 + rng.gauss(0, 0.003)))
            s = Sesion(seed, activo="BTC", duracion=80, velas=velas(precios), guardar=False, costo=0)
            s.paso("esperar", k=rng.randrange(1, 50))
            s.paso("comprar", tamaño=0.5, prob_sube=0.5, razon="azar")
            s.paso("esperar", k=10)
            s.paso("cerrar", prob_sube=0.5, razon="azar")
            percentiles.append(s.terminar()["percentil_azar"])
        self.assertTrue(30 < sum(percentiles) / len(percentiles) < 70)

    def test_prueba_sellada_requiere_evaluacion(self):
        with self.assertRaises(PermissionError):
            Sesion(1, particion="prueba", velas=velas([100] * 4), duracion=3, guardar=False)

    def test_sesion_archivada_conserva_historia_previa_sin_mostrar_futuro(self):
        frame = velas([98, 99, 100, 101, 102, 103])
        start = frame.index[2]
        with patch('lab.escuela._dias_disponibles', return_value=['2026-09-01']), \
             patch('lab.escuela.archivo.leer', return_value=frame), \
             patch('lab.escuela.contexto_previo', return_value={'cierre_previo': 99}):
            sesion = Sesion(1, activo='BTC', inicio=start, duracion=3, guardar=False)
        observacion = sesion.observacion()
        self.assertEqual([x['close'] for x in observacion['velas']], [98, 99, 100])
        self.assertEqual(observacion['contexto']['cierre_previo'], 99)

    def test_cli_avanzar_solo_muestra_velas_hasta_instante_actual(self):
        frame = velas([100, 111, 222, 333])
        def fabrica(semilla, **kw):
            return Sesion(semilla, activo='BTC', duracion=3, velas=frame,
                          guardar=False, anonimo=kw['anonimo'], modo='cfd_x1')
        with tempfile.TemporaryDirectory() as td, \
             patch.object(escuela_cli, 'ESTADO', Path(td) / 'activa.json'), \
             patch.object(escuela_cli, 'LISTA', ['BTC']), \
             patch.object(escuela_cli, 'Sesion', side_effect=fabrica):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                escuela_cli.ejecutar(['nueva', '--anonimo', '--duracion', '3'])
            self.assertNotIn('222.0000', out.getvalue())
            self.assertNotIn('333.0000', out.getvalue())
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                escuela_cli.ejecutar(['avanzar', '1'])
            self.assertNotIn('222.0000', out.getvalue())
            self.assertNotIn('333.0000', out.getvalue())
            estado = json.loads(escuela_cli.ESTADO.read_text())
            self.assertNotIn('velas', estado)
            self.assertEqual(estado['pasos'], [{'accion': 'esperar', 'argumentos': {'k': 1}}])
