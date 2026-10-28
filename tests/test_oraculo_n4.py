import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lab import oraculo_n4 as o
from lab import oraculo_n4_datos as datos


@pytest.fixture(scope="module")
def prereg():
    return datos.verificar_prereg()[0]


def _caso(prereg, seed=7):
    spy_raw, diario = o._sintetico(prereg, seed=seed)
    return o.preparar_spy(spy_raw), diario, o.noticias_de(prereg)


def test_ejecucion_sintetica_completa(prereg, tmp_path):
    spy_raw, diario = o._sintetico(prereg)
    salida = tmp_path / "n4.json"
    res = o.ejecutar(prereg, "x" * 64, spy_raw, diario, None, salida, sintetico=True)
    en_disco = json.loads(salida.read_text(encoding="utf-8"))
    assert en_disco["estado"] == res["estado"]
    assert res["estado"] in {"aprobado", "no_aprobado", "sin_evaluacion", "interrumpido"}
    assert res["prueba_abierta"] is True
    assert set(res["pruebas"]) == {"direccion_h1", "direccion_h5", "tamano_h1", "tamano_h5"}
    for p in res["pruebas"].values():
        assert 0 < p["prueba"]["p"] <= 1
        assert 0 <= p["prueba"]["q_BH"] <= 1
    assert res["particion"]["usada"] in {"fechas", "cronologica_60_15_25"}


def test_sin_lookahead_noticias_ni_precios(prereg):
    spy, diario, noticias = _caso(prereg)
    c0 = o.construir(spy, diario, noticias)
    # Cambios en noticias de la fecha de T en adelante y en precios desde el cierre de T.
    for i in [120, 500, 1500, 2400]:
        t = spy["date"].iloc[i]
        d2 = diario.copy()
        d2.index = pd.DatetimeIndex(pd.to_datetime(d2.index))
        d2.loc[d2.index >= t] = d2.loc[d2.index >= t] + 50.0
        s2 = spy.copy()
        s2.loc[s2.index >= i, ["open", "close"]] *= 1.3
        c1 = o.construir(s2, d2, noticias)
        assert np.array_equal(c0["Z"][i], c1["Z"][i])
        assert np.array_equal(c0["RV"][i], c1["RV"][i])
        assert c0["valida"][i] == c1["valida"][i]
        # Control: el cambio sí debe afectar a la fila siguiente.
        assert not np.allclose(c0["A"][i + 1], c1["A"][i + 1], equal_nan=True)


def test_zscore_solo_usa_pasado():
    rng = np.random.default_rng(3)
    A = rng.normal(size=(200, 10))
    A[::7, 3] = np.nan
    Z, v = o.zscore_pasado(A)
    i = 150
    A2 = A.copy()
    A2[i + 1:] = rng.normal(size=(200 - i - 1, 10)) * 100
    Z2, v2 = o.zscore_pasado(A2)
    assert np.array_equal(Z[:i + 1], Z2[:i + 1])
    assert np.array_equal(v[:i + 1], v2[:i + 1])
    # Valor manual: media y desviación de las 60 filas anteriores.
    H = A[i - 60:i, 0]
    esperado = np.clip((A[i, 0] - H.mean()) / H.std(), -5, 5)
    assert np.isclose(Z[i, 0], esperado)


def test_zscore_exige_20_observaciones_pasadas():
    A = np.random.default_rng(0).normal(size=(100, 10))
    A[:60, 1] = np.nan  # variable 1: en la fila 80 la historia (filas 20..79) tiene 20 valores válidos
    _, v = o.zscore_pasado(A)
    assert not v[79]  # historia 19..78 tiene solo 19 valores
    assert v[80]


def test_embargo_descarta_bordes_del_tramo():
    c = {"valida": np.ones(100, bool), "tg": {1: {"abs": np.ones(100)}, 5: {"abs": np.ones(100)}}}
    h1 = o.conjunto(c, 10, 30, 1)
    h5 = o.conjunto(c, 10, 30, 5)
    assert h1.tolist() == list(range(10, 31))
    assert h5.tolist() == list(range(10, 27))  # T+4 debe caer dentro de 10..30
    assert 27 not in h5 and 30 not in h5


def test_guarda_rechaza_prueba_abierta(tmp_path, monkeypatch):
    ruta = tmp_path / "oraculo_n4.json"
    ruta.write_text(json.dumps({"prueba_abierta": True}), encoding="utf-8")
    monkeypatch.setattr(o, "SALIDA", ruta)
    assert o.main([]) == 1


def test_sintetico_ignora_guarda(tmp_path, monkeypatch):
    ruta = tmp_path / "oraculo_n4.json"
    ruta.write_text(json.dumps({"prueba_abierta": True}), encoding="utf-8")
    monkeypatch.setattr(o, "SALIDA", ruta)
    assert o.main(["--sintetico"]) == 0
    assert json.loads(ruta.read_text(encoding="utf-8"))["prueba_abierta"] is True


def test_cargar_diario_agrega_por_dia_y_corta(prereg, tmp_path):
    for tema in prereg["fuente_noticias"]["temas"]:
        for modo in datos.MODOS:
            for anio in datos.ANIOS:
                puntos = [{"date": f"{anio}0101T000000Z", "value": 1.0},
                          {"date": f"{anio}0101T120000Z", "value": 3.0}]
                if anio == 2026:
                    puntos.append({"date": "20261028T000000Z", "value": 9.0})
                cuerpo = {"timeline": [{"series": "x", "data": puntos}]}
                (tmp_path / f"{tema}_{modo}_{anio}.json").write_text(json.dumps(cuerpo), encoding="utf-8")
    df = datos.cargar_diario(tmp_path, verificar=False)
    assert df.loc[pd.Timestamp("2017-01-01").date(), "mercado_vol"] == 2.0
    assert pd.Timestamp("2026-10-28").date() not in set(df.index)
    assert f"mercado_tono" in df.columns
