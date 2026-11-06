---
name: crypto-exit
description: >-
  Planificador de salida para cripto. Antes de entrar, fija el stop, el
  objetivo y la hora de salida, en largo o en corto: stop en la mitad o en el
  otro extremo del rango de apertura, por porcentaje, por ATR o en un precio;
  objetivo en múltiplos de R. Muestra el R neto de las comisiones de Binance y
  revisa que la liquidación no llegue antes que el stop. Usala cuando el
  usuario diga "dónde pongo el stop", "dónde salgo", "armame el plan",
  "take profit", "stop loss", o después de /crypto-entry y antes de
  /crypto-timemachine.
argument-hint: "[--stop or-mid|or-far|pct:X|atr:K|price:X] [--target 2R] [--lev N]"
---

# crypto-exit

Adaptación a cripto de `trader-exit` del repo
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(licencia MIT, ver `LICENSE-day-trader-skill` en la raíz del repo). Decide
cómo termina la operación **antes** de que empiece: el stop es donde el setup
falló, el objetivo es donde te llevás lo que viniste a buscar. Las dos cosas
quedan escritas, para no decidir nada en el medio de un movimiento rápido.

`${CLAUDE_SKILL_DIR}` es esta carpeta. Lee `trader/entry.json` (de
`/crypto-entry`) y escribe `trader/plan.json`, que es lo que lee
`/crypto-timemachine`.

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan                          # mitad del rango, objetivo 2R
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop or-far --target 1.5R --write
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:1.5           # 1,5 veces el ATR de 14 velas
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --lev 10 --write         # revisa la liquidación
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol ETH --side sell --entry 2349.1 \
    --or-high 2386.86 --or-low 2357.67 --entry-time 14:55 --date 2026-11-05 --session wallstreet
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

## Stops

Se redondean al "tick" de cada cripto, **alejándose** de la entrada.

| `--stop` | Dónde |
| --- | --- |
| `or-mid` (por defecto con `orb`) | la mitad del rango de apertura |
| `or-far` | el otro extremo del rango: el mínimo en un largo, el máximo en un corto |
| `pct:X` | X % desde la entrada |
| `atr:K` | K veces el ATR de 14 velas de 5 minutos de la sesión, hasta la vela de entrada |
| `price:X` | tu precio |

Con `setup level` no hay rango: dale un stop.

## Objetivo y hora de salida

`--target 2R` (por defecto), `1R`, `1.5R`... o `price:X`. La hora de salida
(`flat_by`) es 5 minutos antes del cierre de la sesión: 16:00 de Nueva York
para `wallstreet` (20:55 UTC en invierno), 16:30 de Londres para `europa`.

## Lo que rechaza, y por qué

- un stop o un objetivo del lado equivocado de la entrada;
- un riesgo menor a `--min-risk-pct` (0,15 % del precio): la ida y vuelta de
  comisiones de Binance (~0,07 %) se comería la mitad;
- con `--lev`, un apalancamiento cuya **liquidación llega antes que el stop**;
- un `entry.json` que no disparó, salvo que le pases `--entry` y `--side` para
  planear por adelantado.

## Cómo presentarlo

Mostrá entrada, stop (y por qué ahí), objetivo, el **R neto de comisiones**,
la hora de salida y, si hay apalancamiento, la liquidación. Si el R neto da
menos de 1, decilo claro: ganás menos de lo que arriesgás.

Después: `/crypto-timemachine run` (lee `trader/plan.json` con su sesión) y
`/crypto-scalp size.py` para el tamaño. Un stop es un plan, no una garantía:
una cascada de liquidaciones puede ejecutarlo peor.
