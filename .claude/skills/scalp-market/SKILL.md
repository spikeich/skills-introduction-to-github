---
name: scalp-market
description: >-
  Scalping de cripto: elegir qué criptos sirven para scalpear (las más
  líquidas), calcular el tamaño de la posición con apalancamiento y simular
  en papel un scalp con velas reales de 1 minuto y comisiones de Binance.
  Usala cuando el usuario diga "scalping", "scalpear", "simulame el scalp",
  "cuánto abro para el scalp", "qué cripto scalpeo", o después de
  /scalp-risk para practicar sin plata real.
---

# scalp-market

Tres herramientas. Corren de verdad: usalas, no estimes a ojo.

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py"                                  # mercado (CoinGecko) y candidatas
python3 "${CLAUDE_SKILL_DIR}/size.py" --capital 3000 --entry 75783 --stop 75593 --target 76163
python3 "${CLAUDE_SKILL_DIR}/paper.py" --capital 3000                  # simula trader/plan.json en vivo
python3 "${CLAUDE_SKILL_DIR}/paper.py" --capital 3000 --offline BTC-1m.json   # sobre velas guardadas
```

`scan.py` lee CoinGecko (`api.coingecko.com`). `paper.py` lee las velas de 1 minuto. **Precios:** primero Binance (`data-api.binance.vision`, y `api.binance.com` donde no esté bloqueado): son los precios de la exchange misma. Si Binance no tiene la cripto o no responde, Yahoo (`query2.finance.yahoo.com` y `query1`). `--source binance` o `--source yahoo` fuerza una. La salida dice de dónde salieron ("Precios de Binance (BTCUSDT)"). Binance cotiza en USDT y suele quedar un 0,1 % arriba de Yahoo y CoinGecko, que cotizan en dólares: no mezcles fuentes dentro de una misma operación.

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

## Lo que esta skill NO hace

- **No opera.** Nunca manda una orden. El usuario carga los números en su app.
  Si te pide que operes por él, decí que no y ofrecé la simulación.
- **No predice** ni inventa precios. Si Yahoo o CoinGecko no responden, decilo.

## 1. Qué criptos scalpear

Solo las más líquidas, donde el spread es mínimo: **BTC y ETH**, y como mucho
SOL y XRP. `scan.py` lee el mercado de CoinGecko y marca como candidatas las
que negocian **más de 1.000 M USD por día** (el mismo piso que
`/scalp-scanner universe`) y se movieron entre 1,5 % y 14 % en el día.

Al lado de cada candidata muestra un **sesgo a ojo** (corto en rebotes, largo
en caídas) según dónde está el precio dentro de su día. **Nunca se midió con
datos**: es contexto, no una señal. Decíselo al usuario cuando lo muestres.

## 2. El tamaño (`size.py`)

El tamaño sale del **riesgo**, no del apalancamiento: la cantidad que pierde
`--risk` % del capital (0,5 % por defecto) si salta el stop, con comisiones.
El apalancamiento (10x por defecto, margen aislado) solo cambia cuánto margen
queda trabado y dónde está la liquidación. Con 3.000 USD, 0,5 % de riesgo y un
stop de 0,25 %, la posición es de unos 6.000 USD y si salta el stop perdés
15 USD, a 5x, 10x o 20x.

## 3. La simulación (`paper.py`)

Juega el plan de `/scalp-exit` (`trader/plan.json`) vela por vela, con el
máximo y el mínimo de cada minuto:

| paso | regla |
| --- | --- |
| entrada | orden límite en la entrada del plan, desde la vela siguiente a la señal. Una compra se llena cuando el precio está **en la entrada o por debajo**; una venta, en la entrada o por encima. Si no llega en 3 minutos, se cancela |
| stop | tocado desde la vela de la entrada: sale al stop (comisión taker 0,05 %). En la vela de la entrada cuenta, porque el precio pasa por la entrada antes de llegar al stop |
| objetivo | tocado después de la vela de la entrada: sale al objetivo (maker 0,02 %). Si una vela toca los dos, cuenta el stop |
| tiempo | a la hora de salida del plan (entrada + 20 min, aunque cruce la medianoche UTC): sale al cierre, gane o pierda |

**Una orden límite no te protege de un movimiento en contra.** Si el precio
ya está del otro lado del límite cuando entra la orden, se llena en el acto:
solo evita perseguir el precio cuando se escapa a favor. La orden queda
"cancelada" únicamente cuando el precio se va a favor sin volver.

Imprime una línea por evento (corré en vivo bajo `Monitor`), el resultado en
USD con comisiones y la línea para anotarlo con `/scalp-risk log`.

## Lo que mostraron los datos

4 semanas de velas de 1 minuto (BTC, ETH, SOL, XRP, DOGE), aperturas de
Londres y Nueva York, de lunes a viernes, 480 configuraciones: **ninguna ganó
después de comisiones en las dos mitades de la muestra** (promedio −0,27 R y
−0,39 R por operación). Sin comisiones quedaban cerca del empate. Este repo es
un simulador para practicar y medir, no una máquina de ganar: decíselo al
usuario cada vez que lo use.

Cerrá siempre con que es una simulación y no un consejo de inversión.
