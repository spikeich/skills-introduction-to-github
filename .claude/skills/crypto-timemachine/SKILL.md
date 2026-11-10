---
name: crypto-timemachine
description: >-
  Máquina del tiempo para cripto. Antes de arriesgar un dólar, repite 10.000
  veces el resto de la sesión desde la entrada, armando cada vela con las velas
  reales de 5 minutos de esa misma cripto en los últimos 60 días, y vuelve a
  correr la misma regla en cada día pasado. Dice qué tan seguido toca primero
  el objetivo, el stop, o ninguno, y da un veredicto honesto. Usala cuando el
  usuario diga "máquina del tiempo", "simulá esta operación", "qué
  probabilidades tiene", "backtest", "es tirar una moneda", "monte carlo", o
  antes de abrir una operación planeada con /crypto-scalp.
argument-hint: "[ETH | BTC-USD | SOLUSDT ...]"
---

# crypto-timemachine

Adaptación a cripto de `trader-timemachine` del repo
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(licencia MIT, ver `LICENSE-day-trader-skill` en la raíz del repo). El
algoritmo es el mismo; cambia qué es una "sesión" y cómo se redondean los
precios.

Responde una sola pregunta: **si hoy se comporta como los últimos 60 días de
esta cripto, ¿qué tan seguido este plan toca primero el objetivo, el stop, o
ninguno?** Es una simulación con datos reales del pasado, no una predicción.

`${CLAUDE_SKILL_DIR}` es esta carpeta.

```bash
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run          # el plan de /crypto-exit (trader/plan.json), con su sesión
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --symbol ETH --side sell \
    --entry 2385.25 --stop 2400 --target 2355 --entry-time 14:00 --setup custom
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" chart --symbol ETH --side sell \
    --entry 2385.25 --stop 2400 --target 2355 --entry-time 14:00 --setup custom
python3 "${CLAUDE_SKILL_DIR}/timemachine.py" run --symbol XRP --side sell \
    --entry 1.3008 --stop 1.3076 --target 1.294 --entry-time 14:15 --or-minutes 30
```

Otras opciones: `--date YYYY-MM-DD` (por defecto hoy, UTC), `--session`
(ver abajo), `--until 18:00`, `--replays N`, `--seed N` (por defecto 19),
`--window N` (por defecto 2 velas), `--write`, `--json`, `--offline ARCHIVO`,
`--now "2026-11-05 14:00"`. Con el plan dado por opciones (`--symbol ...`),
`--confirm N` dice cuántas velas seguidas espera la regla de la historia: por
defecto 3 en Wall Street y 1 en lo demás, igual que `/crypto-entry`. Con
`trader/plan.json` lo lee del plan.

Necesita `query2.finance.yahoo.com` (y `query1` de respaldo) en la red del
entorno.

## Qué cambia respecto del original (acciones)

| | Acciones (original) | Cripto (esta) |
| --- | --- | --- |
| Símbolo | TSLA | `ETH`, `ETH-USD` o `ETHUSDT`: todos se leen como `ETH-USD` en Yahoo |
| Sesión | 9:30 a 16:00 de Nueva York, lunes a viernes | una ventana atada al horario de una bolsa, **todos los días** (ver la tabla de sesiones) |
| Horas | Nueva York, AM/PM | **UTC, reloj de 24 horas**. `--entry-time 14:00` es la vela que **cierra** a las 14:00 |
| Redondeo | al centavo | al "tick" de cada cripto, ~1/10.000 del precio (0,0001 en XRP, 0,1 en ETH) |
| Medio día de bolsa | se saltea | no existe; solo se saltean días con datos incompletos |

## Sesiones

Se elige con `--session`. Cripto mueve más volumen cuando abren las bolsas de
Europa y de Wall Street, así que las sesiones siguen esos horarios:

| `--session` | Hora local | En UTC (invierno del norte) | En Argentina |
| --- | --- | --- | --- |
| `europa-wallstreet` (por defecto) | 08:00 Londres a 16:00 Nueva York | 08:00-21:00 | 05:00-18:00 |
| `europa` | 08:00 a 16:30 Londres | 08:00-16:30 | 05:00-13:30 |
| `wallstreet` | 09:30 a 16:00 Nueva York | 14:30-21:00 | 11:30-18:00 |
| `utc` + `--window-utc 00:00-06:00` | la ventana fija que elijas | | |

Londres y Nueva York cambian al horario de verano en fechas distintas
(Europa: último domingo de marzo y de octubre; EE.UU.: segundo domingo de
marzo y primer domingo de noviembre). El script calcula la ventana de **cada
día** con sus propios horarios: en verano todo se corre una hora antes en
UTC. En las semanas en que solo cambió uno de los dos, `europa-wallstreet`
termina una hora antes o después del cierre de Nueva York.

El rango de apertura (`--or-minutes`, por defecto 15) se cuenta desde el
inicio de la sesión: con `europa` o `europa-wallstreet` es la apertura de
Londres, con `wallstreet` la de Nueva York. `--entry-time` va siempre en UTC.

## Cómo funciona

1. **El banco de velas.** Baja 60 días de velas de 5 minutos (una sola
   consulta a Yahoo) y se queda con los días que tienen la ventana completa.
   Cada vela se guarda como proporción de la anterior: apertura, máximo,
   mínimo y cierre sobre el cierre previo.
2. **Una repetición.** Arranca en el precio de entrada. Para cada vela que
   queda de la sesión, elige al azar una vela pasada del mismo horario (más o
   menos 2 velas) y la escala al precio actual. En cada vela revisa primero el
   stop y después el objetivo: si una vela toca los dos, cuenta como stop.
3. **10.000 repeticiones** dan cuatro números: objetivo primero, stop
   primero, ninguno (seguía abierta al final de la ventana) y "verde"
   (objetivo, o en ganancia al final).
4. **La historia.** Con `--setup orb` (el valor por defecto), corre la misma
   regla de ruptura del rango de apertura en cada uno de esos días reales. Eso
   no es simulación: es lo que pasó.
5. **El veredicto.** Mira solo las repeticiones que tocaron un lado. Un
   objetivo más lejano necesita ganar menos seguido para empatar: 1 de cada
   (1 + R). A 1R es el 50 %, a 2R el 33 %. A menos de 5 puntos de ese número:
   "cerca de tirar una moneda" o "cerca del empate".

## Cómo presentarlo

Mostrale al usuario, en castellano:

- las cuatro probabilidades,
- el precio al final de la ventana (mediana y el rango del 90 %),
- la historia real de la regla, si corrió,
- el veredicto en una línea, sin suavizarlo,
- el gráfico de abanico (`chart`) si ayuda a verlo.

Después, el tamaño de la posición sale de `/crypto-scalp` (`size.py`).

Cerrá siempre con que es una simulación con datos del pasado y no un consejo
de inversión: noticias, liquidaciones en cadena o caídas de una exchange
pueden hacer cosas que esos 60 días nunca hicieron.
