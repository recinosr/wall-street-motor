# Oráculo nivel 7: reglas de aporte contra el plan 80/20
Pre-registro `lab/oraculo_n7_prereg.json`, sha256 `39b79b7dcea62caf9f788a945f8ecf74b322a22c5f82f6c05fc30cd9a7ca85be`, verificado al arrancar. Ejecutado 2026-10-18T15:24:45+00:00 UTC.
Ventanas de 60 aportes de 100 USD: validación 768 (_GSPC), prueba 147 (VT 80 / SPY 20). Plan R0, múltiplo medio: validación 1,334, prueba 1,298.

| Tramo | Regla | Múltiplo medio | Mejora media vs R0 | p | q BH | Peor caída mediana | Aprobada |
|---|---|---|---|---|---|---|---|
| validación | R1 | 1,298 | -0,0355 | 1,0000 | - | -16,2 % | - |
| validación | R2 | 1,328 | -0,0057 | 0,9240 | - | -14,0 % | - |
| validación | R3 | 1,294 | -0,0394 | 1,0000 | - | -15,2 % | - |
| prueba | R1 | 1,272 | -0,0265 | 1,0000 | 1,0000 | -14,6 % | no |
| prueba | R2 | 1,284 | -0,0143 | 1,0000 | 1,0000 | -14,6 % | no |
| prueba | R3 | 1,273 | -0,0250 | 1,0000 | 1,0000 | -14,0 % | no |
| prueba | R4 | 1,298 | 0,0000 | 1,0000 | 1,0000 | -15,0 % | no |

**Veredicto:** nivel 7 no aprobado: ninguna regla de prueba cumple q BH < 0,05 con mejora media positiva en prueba y, cuando aplica, en validación. El plan 80/20 no cambia por este resultado; una regla aprobada solo entra a la bóveda y espera 90 días.
