"""Un activo por proceso CPU; sin selección por resultados ni acceso a la red."""
import pandas as pd
from .boveda_meses import BovedaMes, MotorMes, MODES, jugar, calificar


def activo_job(args):
    sim,frame,dates=args
    vault=BovedaMes(frame,sim.endswith('-USD'));model=None;year=None;missing=0;count=0
    games=[];summaries=[]
    for month in pd.period_range('2006-01','2026-09',freq='M'):
        if month.year!=year:
            year=month.year
            try:model=MotorMes(sim,vault.ver(f'{min(year,2019)}-01-01'),dates)
            except ValueError:model=None
        if model is None:missing+=4;continue
        for mode in MODES:
            try:game=jugar(sim,frame,month,mode,model,dates,vault)
            except ValueError:missing+=1;continue
            stats=calificar(game)
            if stats is None:missing+=1;continue
            count+=1;games.append(game);summaries.append((str(month),mode,stats))
    coverage=dict(sim=sim,desde=str(frame.index.min().date()),meses_modos=count,sin_historia=missing,
                  aviso='sin rellenar antes de creación ni huecos; modelos ausentes vuelven a moneda')
    return sim,games,summaries,coverage
