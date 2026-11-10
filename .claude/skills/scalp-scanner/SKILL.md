---
name: scalp-scanner
description: >-
  Escáner de scalping para cripto: busca, entre las criptos más líquidas,
  cuáles rompieron el rango de los primeros 5 minutos de la apertura de
  Londres o de Wall Street con 2 velas de 1 minuto seguidas afuera. Usala
  cuando el usuario diga "qué cripto rompe para scalpear", "escaneá para
  scalping", "rupturas de 1 minuto", "armame la lista de scalping", o antes
  de /scalp-entry.
argument-hint: "[universe | orb | daily] [--session europa|wallstreet]"
---

# scalp-scanner

Adaptación de `crypto-scanner` (repo skill-cryptos-jeto1337), que viene de
`trader-scanner` de [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT, ver `LICENSE-day-trader-skill`).

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                 # las más líquidas -> trader/universe.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                      # apertura de Wall Street, 1 minuto
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --session europa     # apertura de Londres
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --at 14:50 --write   # cortar el reloj, guardar trader/orb.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                    # contexto diario (tendencia, RSI)
```

Necesita `api.coingecko.com` y `query2.finance.yahoo.com`.

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

## Qué hace

- **`universe`:** las criptos con más de **1.000 M USD** de volumen en 24 horas
  (`--min-volume`), como mucho 8 (`--limit`), dentro de las 100 de mayor
  capitalización (`--max-rank`). Sin stablecoins ni copias. En scalping el
  spread lo es todo: solo las más líquidas. A cada una le busca su par en
  Yahoo y **compara el precio con el de CoinGecko**: los símbolos se repiten, y
  si el precio no coincide es otra moneda. La lista se guarda en
  `trader/universe.json` la primera vez; si tiene más de un día, avisa. Si
  CoinGecko no responde y no hay lista guardada, usa una lista fija de las 12
  más grandes y lo dice.
- **`orb`:** el rango son los primeros **5 minutos** de la sesión
  (`--or-minutes`); una ruptura son **2 velas de 1 minuto seguidas** cerrando
  afuera (`--confirm`). Marca como débiles las que quedan a menos de 0,05 %
  del rango. Una cripto cuenta si tiene el rango completo y el 90 % de los
  minutos (Yahoo saltea algún minuto quieto).
- **`daily`:** los setups diarios del repo de day trading, como contexto de
  tendencia. No son señales de scalping.

| `--session` | Abre | UTC (invierno del norte) | Argentina |
| --- | --- | --- | --- |
| `wallstreet` (por defecto) | 09:30 Nueva York | 14:30 | 11:30 |
| `europa` | 08:00 Londres | 08:00 | 05:00 |

Con `--session utc --open HH:MM` escanea una sesión libre, que puede cruzar
la medianoche UTC. `orb --offline CARPETA` lee gráficos guardados
(`<PAR>.json`) en vez de la red: lo usan los tests.

Una lista de rupturas no es una lista de compras. Lo que rompe para los dos
lados es un rango sin dirección: mejor no tocarlo.

## Lo que mostraron los datos

4 semanas de velas de 1 minuto (BTC, ETH, SOL, XRP, DOGE), aperturas de
Londres y Nueva York, de lunes a viernes, 480 configuraciones: **ninguna ganó
después de comisiones en las dos mitades de la muestra** (promedio −0,27 R y
−0,39 R por operación). Sin comisiones quedaban cerca del empate. Este repo es
un simulador para practicar y medir, no una máquina de ganar: decíselo al
usuario cada vez que lo use.

Siguiente: `/scalp-entry` confirma el momento exacto.
