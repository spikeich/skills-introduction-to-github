---
name: scalp-exit
description: >-
  Planificador de salida para scalping de cripto: antes de entrar fija el stop
  (0,25 % por defecto), el objetivo (2R) y la salida por tiempo (20 minutos),
  en largo o en corto, con el R neto de las comisiones de Binance y la
  liquidación con apalancamiento. Usala cuando el usuario diga "dónde pongo el
  stop del scalp", "armame el plan de scalping", "take profit del scalp", o
  después de /scalp-entry y antes de /scalp-timemachine.
---

# scalp-exit

Adaptación de `crypto-exit` (repo skill-cryptos-jeto1337), que viene de
`trader-exit` de [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT, ver `LICENSE-day-trader-skill`).

```bash
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --lev 10 --write             # de trader/entry.json
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop pct:0.35 --target 3R --hold 30
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --stop atr:1.5               # 1,5 ATR de las velas de 1 minuto
python3 "${CLAUDE_SKILL_DIR}/exit.py" plan --symbol BTC --side buy --entry 75783 --entry-time 14:42
python3 "${CLAUDE_SKILL_DIR}/exit.py" show
```

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

| | por defecto | opciones |
| --- | --- | --- |
| stop | `pct:0.25` (0,25 % de la entrada) | `pct:X`, `or-mid`, `or-far`, `price:X`, `atr:K` |
| objetivo | `2R` | `1.5R`, `3R`, `price:X` |
| salida por tiempo | `--hold 20` minutos desde la entrada | `--flat-by HH:MM` para fijar la hora |

- **Se rechaza** un stop de menos de **0,15 %**: las comisiones de ida y vuelta
  (~0,07 %) se comerían la mitad.
- **Las comisiones son casi todo:** el plan muestra el R neto (entrada límite
  maker 0,02 %, stop taker 0,05 %, objetivo maker 0,02 %). Con stop de 0,25 % y
  objetivo 2R queda en ~1,44R neto; con 1,5R, menos de 1.
- Con `--lev` calcula la liquidación en margen aislado y rechaza el plan si
  llega antes que el stop. Con stops de 0,25 %, a 10x queda a ~9,5 %.

El plan guarda las horas completas (`entry_at`, `flat_at`), así que un scalp
puede cruzar la medianoche UTC (las 21:00 de Argentina) sin confundir el día.

Un stop es un plan, no una garantía: un mercado rápido lo puede ejecutar peor.

## Lo que mostraron los datos

4 semanas de velas de 1 minuto (BTC, ETH, SOL, XRP, DOGE), aperturas de
Londres y Nueva York, de lunes a viernes, 480 configuraciones: **ninguna ganó
después de comisiones en las dos mitades de la muestra** (promedio −0,27 R y
−0,39 R por operación). Sin comisiones quedaban cerca del empate. Este repo es
un simulador para practicar y medir, no una máquina de ganar: decíselo al
usuario cada vez que lo use.

Siguiente: `/scalp-timemachine` (¿tiene ventaja?) y `/scalp-risk` (¿entra en
tus límites? cuánto abrir).
