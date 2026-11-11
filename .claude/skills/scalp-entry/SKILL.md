---
name: scalp-entry
description: >-
  Temporizador de entrada para scalping de cripto: vigila velas de 1 minuto y
  dice el momento exacto de entrar, en largo o en corto, cuando 2 velas
  seguidas cierran afuera del rango de los primeros 5 minutos de Londres o de
  Wall Street, o a través de un nivel. Nunca manda órdenes. Usala cuando el
  usuario diga "¿ya rompió?" en scalping, "avisame cuándo entrar al scalp",
  "vigilá BTC en 1 minuto", o después de /scalp-scanner y antes de /scalp-exit.
argument-hint: "SÍMBOLO [--session europa|wallstreet] [--side long|short]"
---

# scalp-entry

Adaptación de `crypto-entry` (repo skill-cryptos-jeto1337), que viene de
`trader-entry` de [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT, ver `LICENSE-day-trader-skill`).

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check BTC                     # Wall Street, rango 5 min, 2 velas
python3 "${CLAUDE_SKILL_DIR}/entry.py" check ETH --session europa --side short
python3 "${CLAUDE_SKILL_DIR}/entry.py" check SOL --setup level --level 92.5 --side long
python3 "${CLAUDE_SKILL_DIR}/entry.py" check BTC --write              # guarda trader/entry.json
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch BTC                      # vela por vela hasta que dispare
```

**Precios:** primero Binance (`data-api.binance.vision`, y `api.binance.com` donde no esté bloqueado): son los precios de la exchange misma. Si Binance no tiene la cripto o no responde, Yahoo (`query2.finance.yahoo.com` y `query1`). `--source binance` o `--source yahoo` fuerza una. La salida dice de dónde salieron ("Precios de Binance (BTCUSDT)"). Binance cotiza en USDT y suele quedar un 0,1 % arriba de Yahoo y CoinGecko, que cotizan en dólares: no mezcles fuentes dentro de una misma operación.

## Antes de empezar: primero `/scalp-social-info`

Regla fija: **antes de usar esta skill, corré `/scalp-social-info`**
(`calendar`, `news` y `chain`). En scalping las noticias pegan en segundos:

- **Evento del calendario** (inflación, la Fed, una votación): **nada de
  entradas nuevas desde 15 minutos antes hasta 15 minutos después**. El spread
  se abre y el precio salta los stops.
- **Noticia grande verificada y NUEVA** (de la última hora): no hagas scalping
  en contra. Si `verify --dir` dice **YA ESTÁ EN EL PRECIO**, tampoco a favor.
- **Comisiones de Bitcoin muy altas** (`chain`): más volatilidad, achicá el
  tamaño o esperá.
- **Noticia dudosa**: no decide nada hasta que se verifique.

## Las reglas

- **`orb` (por defecto):** el rango es el máximo y el mínimo de los primeros
  `--or-minutes` (5) de la sesión. Dispara cuando **`--confirm` (2) velas de
  1 minuto seguidas** cierran por encima del máximo (largo) o por debajo del
  mínimo (corto). Una mecha que pasa y vuelve no cuenta.
- **`level`:** lo mismo contra `--level`, con `--side long` o `--side short`.
- La hora del disparo es la del **cierre** de la vela (la vela de las 14:41
  cierra a las 14:42) y el precio es ese cierre.
- **Vence** a las `--expire-hours` (2) de la apertura: el scalping solo tiene
  sentido mientras hay volumen.
- **En scalping la señal envejece rápido:** `/scalp-risk` la bloquea si pasaron
  más de 3 minutos desde el cierre de la vela.

| `--session` | Abre | UTC (invierno del norte) | Argentina |
| --- | --- | --- | --- |
| `wallstreet` (por defecto) | 09:30 Nueva York | 14:30 | 11:30 |
| `europa` | 08:00 Londres | 08:00 | 05:00 |
| `utc` + `--open HH:MM` | cuando quieras (UTC) | | |

La sesión libre (`--session utc --open 03:00`) sirve para practicar a
cualquier hora: la cripto opera siempre. Pero lejos de las aperturas se mueve
menos (el fin de semana, unas 3 veces menos en BTC) y en las pruebas ningún
horario ganó después de comisiones.

Una sesión libre puede **cruzar la medianoche UTC** (las 21:00 de Argentina):
pasada la medianoche, el mismo `--open 23:45` sigue siendo la sesión que
abrió la noche anterior, hasta que vence. `trader/entry.json` guarda las
horas completas (`open_at`, `entry_at`) y `date` es el día en que abrió.

Estados: **DISPARÓ**, **ESPERANDO** (el rango se forma o todavía no hay 2
cierres afuera), **VENCIDO**, **SIN DATOS**.

## Vigilar en vivo

`watch` imprime una línea por vela cerrada y termina cuando dispara (escribe
`trader/entry.json`) o vence. Corrélo bajo `Monitor` y avisale al usuario solo
cuando el rango quedó armado, cuando dispara y cuando vence.

## Lo que mostraron los datos

4 semanas de velas de 1 minuto (BTC, ETH, SOL, XRP, DOGE), aperturas de
Londres y Nueva York, de lunes a viernes, 480 configuraciones: **ninguna ganó
después de comisiones en las dos mitades de la muestra** (promedio −0,27 R y
−0,39 R por operación). Sin comisiones quedaban cerca del empate. Este repo es
un simulador para practicar y medir, no una máquina de ganar: decíselo al
usuario cada vez que lo use.

Siguiente: `/scalp-exit` (stop, objetivo y salida por tiempo), después
`/scalp-timemachine` y `/scalp-risk`. Un disparo no es una orden.
