---
name: scalp-timemachine
description: >-
  Máquina del tiempo para scalping de cripto: repite 10.000 veces los minutos
  que dura el scalp (de la entrada a la salida por tiempo) con velas reales de
  1 minuto de las últimas 4 semanas de esa cripto, y vuelve a correr la misma
  regla en cada día pasado. Dice qué tan seguido toca primero el objetivo, el
  stop, o ninguno, y da un veredicto honesto. Usala cuando el usuario diga
  "máquina del tiempo del scalp", "simulá este scalp", "qué probabilidades
  tiene el scalp", o antes de abrir un plan de /scalp-exit.
---

# scalp-timemachine

Adaptación de `crypto-timemachine` (repo skill-cryptos-jeto1337), que viene de
`trader-timemachine` de [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT, ver `LICENSE-day-trader-skill`). Mismo algoritmo, con velas de 1 minuto.

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run                 # trader/plan.json, hasta su flat_by
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --write
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --symbol BTC --date 2026-11-06 --side buy \
    --entry 75783 --stop 75593 --target 76163 --entry-time 14:42 --hold 20
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" chart
```

Otras opciones: `--session wallstreet|europa|utc` (con `--open HH:MM` para la
libre), `--until`, `--hold`, `--confirm`, `--replays`, `--seed` (19), `--window`
(2 minutos), `--offline`, `--now`. Con el plan de `/scalp-exit` no hace falta
ninguna: lee la sesión, la apertura y la hora de salida del plan.
**Precios:** primero Binance (`data-api.binance.vision`, y `api.binance.com` donde no esté bloqueado): son los precios de la exchange misma. Si Binance no tiene la cripto o no responde, Yahoo (`query2.finance.yahoo.com` y `query1`). `--source binance` o `--source yahoo` fuerza una. La salida dice de dónde salieron ("Precios de Binance (BTCUSDT)"). Binance cotiza en USDT y suele quedar un 0,1 % arriba de Yahoo y CoinGecko, que cotizan en dólares: no mezcles fuentes dentro de una misma operación. Los 28 días de velas de 1 minuto se piden a Binance en paralelo (unos 12 segundos); Yahoo da 7 días por consulta y guarda unos 30.

## Cómo funciona

1. **El banco de velas:** unas 4 semanas de velas de 1 minuto, de las **3
   horas** que siguen a la apertura (Wall Street, Londres o la hora de
   `--open`): 2 horas en las que valen las entradas y 1 más para aguantar las
   últimas. Una sesión libre puede cruzar la medianoche UTC. Los días a los
   que les faltan hasta 5 minutos se completan con una vela plana al último
   cierre; los que tienen más huecos se dejan afuera.
2. **10.000 repeticiones** desde el precio de entrada hasta la **salida por
   tiempo** del plan (`flat_by`, entrada + 20 minutos): cada minuto se arma
   con una vela pasada del mismo minuto (±2), escalada al precio. Si una vela
   toca el stop y el objetivo, cuenta el stop.
3. **La historia:** la misma regla (rango de 5 minutos, 2 velas, el mismo stop
   y objetivo, afuera a los 20 minutos) en cada día pasado.
4. **El veredicto:** compara las veces que llegó primero el objetivo con lo que
   hace falta para empatar a ese R: 1 de cada (1 + R).

5. **Después de comisiones.** Cada número sale también neto de las comisiones
   de Binance (entrada y objetivo 0,02 %, stop y salida por tiempo 0,05 %). Con
   stop de 0,25 % y objetivo 2R, ganar vale **+1,84 R** y perder cuesta
   **1,28 R**: el objetivo tiene que llegar primero en el **41 %** de las
   repeticiones que tocan un lado, no en el 33 %.

**El veredicto que vale es el de "after fees"** (después de comisiones).
Mostrale al usuario los dos, pero decidí con ese: un "cerca del empate" sin
comisiones suele ser "se inclina hacia el stop" con comisiones.

## Lo que mostraron los datos

4 semanas de velas de 1 minuto (BTC, ETH, SOL, XRP, DOGE), aperturas de
Londres y Nueva York, de lunes a viernes, 480 configuraciones: **ninguna ganó
después de comisiones en las dos mitades de la muestra** (promedio −0,27 R y
−0,39 R por operación). Sin comisiones quedaban cerca del empate. Este repo es
un simulador para practicar y medir, no una máquina de ganar: decíselo al
usuario cada vez que lo use.

Cerrá siempre con que es una simulación con datos del pasado y no un consejo
de inversión. Siguiente: `/scalp-risk`.
