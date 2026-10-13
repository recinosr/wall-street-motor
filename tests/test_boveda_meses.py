import unittest
import numpy as np
import pandas as pd
from lab.boveda_meses import (ASSETS, ETF, METHODS, BovedaMes, MotorMes,
                            jugar, calendario, start_index, calificar)


def fixture():
    from exchange_calendars import get_calendar
    index=get_calendar('XNYS',start='2003-01-01',end='2012-12-31').sessions
    rng=np.random.default_rng(22);c=100*np.exp(np.cumsum(rng.normal(.0002,.01,len(index))))
    return pd.DataFrame(dict(close=c,open=c*.999,high=c*1.01,low=c*.99,volume=1000),index=index)


class DiarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d=fixture();cls.model=MotorMes('SPY',cls.d.loc[:'2009-12-31'])

    def test_universo(self):
        self.assertEqual(len(ETF),100);self.assertEqual(len(set(ETF)),100)
        self.assertEqual(len(ASSETS),102);self.assertEqual(len(METHODS),9)

    def test_futuro_envenenado_mes_completo(self):
        d=self.d.copy();mask=d.index>='2010-03-01';d.loc[mask,['open','high','low','close']]*=np.linspace(10,1000,mask.sum())[:,None]
        a=jugar('SPY',self.d,'2010-03','A_primero',self.model,vault=BovedaMes(self.d))
        b=jugar('SPY',d,'2010-03','A_primero',self.model,vault=BovedaMes(d))
        for key in ('probabilidades','rango','contexto','ajuste_hasta','etiquetas_hasta'):
            self.assertEqual(a[key],b[key])
        self.assertNotEqual(a['retorno_mes'],b['retorno_mes'])

    def test_futuro_envenenado_dia_a_dia(self):
        d=self.d.copy();d.loc[d.index>='2010-03-10','close']*=100
        a=jugar('SPY',self.d,'2010-03','B_primero',self.model,vault=BovedaMes(self.d))
        b=jugar('SPY',d,'2010-03','B_primero',self.model,vault=BovedaMes(d))
        n=sum(t<='2010-03-10' for t in a['fechas'])
        self.assertEqual(a['probabilidades'][:n],b['probabilidades'][:n])
        self.assertNotEqual(a['probabilidades'][n:],b['probabilidades'][n:])

    def test_cache_igual_prefijo_y_copia(self):
        a=BovedaMes(self.d).ver('2010-03-10');b=BovedaMes(self.d.loc[:'2010-03-09']).ver('2010-03-10')
        pd.testing.assert_frame_equal(a.rasgos,b.rasgos);pd.testing.assert_series_equal(a.bases,b.bases)
        a.iloc[-1,0]=0;self.assertNotEqual(BovedaMes(self.d).ver('2010-03-10').iloc[-1,0],0)

    def test_etiquetas_maduras_y_techo(self):
        m=MotorMes('SPY',self.d)
        self.assertLessEqual(m.etiquetas_hasta,'2018-12-31')
        self.assertLessEqual(self.model.etiquetas_hasta,'2009-12-31')

    def test_azar_independiente_outcomes(self):
        targets=pd.bdate_range('2010-03-01','2010-03-31')
        self.assertEqual(start_index('SPY','2010-03',targets),start_index('SPY','2010-03',targets))
        a=jugar('SPY',self.d,'2010-03','A_azar',self.model)
        self.assertEqual(a['contexto']['hasta']<a['inicio'],True)
        self.assertEqual(a['fechas'][-1],'2010-03-31')

    def test_calendario_no_depende_de_cierres(self):
        f=calendario(pd.to_datetime(['2010-03-01','2010-03-19','2010-03-24','2010-04-01']))
        self.assertEqual(f.iloc[0].primer_dia,1);self.assertEqual(f.iloc[1].tercer_viernes,1)
        self.assertEqual(f.iloc[2].cuarto_miercoles,1);self.assertEqual(f.iloc[3].pre_feriado,1)
        self.assertEqual(calendario(pd.to_datetime(['2010-03-16']),['2010-03-16']).iloc[0].fomc,1)

    def test_huecos_no_se_inventan(self):
        d=self.d.copy();d.loc['2010-03-10','close']=np.nan
        g=jugar('SPY',d,'2010-03','A_primero',self.model)
        self.assertIsNone(g['y'][g['fechas'].index('2010-03-10')])
        self.assertIsNone(g['y'][g['fechas'].index('2010-03-11')])
        self.assertEqual(calificar(g)['moneda']['n'],len(g['fechas'])-2)

    def test_brier_acierto_manual(self):
        g=jugar('SPY',self.d,'2010-03','A_primero',self.model)
        p=np.array(g['probabilidades'])[:,0];y=np.array(g['y'])
        self.assertAlmostEqual(calificar(g)['moneda']['brier'],np.mean((p-y)**2))
        self.assertAlmostEqual(calificar(g)['moneda']['acierto'],np.mean((p>=.5)==y))

    def test_b_vectorizado_igual_mañanas(self):
        g=jugar('SPY',self.d,'2010-03','B_primero',self.model)
        for i,t in enumerate(g['fechas']):
            one=self.model.pronosticar(self.d.loc[self.d.index<t], [pd.Timestamp(t)], 'B_primero')[0].tolist()
            self.assertEqual(one,g['probabilidades'][i])

    def test_rango_fijado_en_t(self):
        a=jugar('SPY',self.d,'2010-03','A_primero',self.model)
        b=jugar('SPY',self.d,'2010-03','B_primero',self.model)
        # Azar distinto por modo, otros rangos son idénticos al inicio.
        for m in METHODS:
            if m!='azar':self.assertEqual(a['rango'][m],b['rango'][m])


if __name__=='__main__':unittest.main()
