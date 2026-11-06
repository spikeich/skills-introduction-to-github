---
name: crypto-scanner
description: >-
  Escáner de gráficos para cripto. Busca, entre las criptos más negociadas,
  cuáles rompen el rango de apertura de Europa o de Wall Street (para arriba o
  para abajo), y qué setups diarios hay: rupturas de 20 días, banderas, media
  de 20, sobreventa y sobrecompra. Usala cuando el usuario diga "qué cripto
  rompe", "escaneá el mercado", "qué rompió la apertura", "rupturas", "qué
  setups hay hoy", "armame la lista para operar", o antes de planear una
  operación con /crypto-timemachine.
argument-hint: "[orb | daily | universe] [--session europa|wallstreet]"
---

# crypto-scanner

Adaptación a cripto de `trader-scanner` del repo
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(licencia MIT, ver `LICENSE-day-trader-skill` en la raíz del repo). Las
reglas son las mismas, pero en **los dos sentidos**: en cripto el corto pesa
tanto como el largo.

`${CLAUDE_SKILL_DIR}` es esta carpeta. Corré los comandos desde la carpeta del
proyecto: los resultados quedan en `trader/`.

```bash
python3 "${CLAUDE_SKILL_DIR}/scan.py" universe                    # las 30 más negociadas -> trader/universe.json
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb                         # rupturas de la apertura de Wall Street, hoy
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --session europa        # rupturas de la apertura de Londres
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --or-minutes 30 --at 15:30
python3 "${CLAUDE_SKILL_DIR}/scan.py" daily                       # setups diarios
python3 "${CLAUDE_SKILL_DIR}/scan.py" orb --symbols BTC,ETH,SOL   # solo esas
```

Necesita `api.coingecko.com` y `query1`/`query2.finance.yahoo.com` en la red.

## Antes de empezar: primero `/crypto-social-info`

Regla fija: **antes de usar esta skill, corré `/crypto-social-info`**
(`calendar` y `news`, y verificá con la regla de 5 fuentes cualquier noticia
grande del día). Lo que encuentres manda sobre lo que diga el gráfico:

- **Noticia mala verificada y NUEVA** (de las últimas 24 horas: prohibición,
  demanda, colapso, aranceles, resultado político en contra): preferí cortos y
  achicá los largos. Si es **VIEJA** (más de 3 días), ya está en el precio: es
  contexto, no una razón para operar hoy.
- **Evento grande en las próximas horas** (dato de inflación, decisión de la
  Fed, votación, fallo): achicá el tamaño o esperá a que pase.
- **Noticia dudosa**: no decide nada hasta que se verifique.

## Los tres comandos

**`universe`.** Toma de CoinGecko las criptos con más volumen en 24 h. Saca
las stablecoins, las copias envueltas o en staking y el oro tokenizado, y las
que mueven menos de 100 M USD. A cada una le busca su par en Yahoo: casi
siempre es `SIM-USD`, pero algunas tienen un número (HYPE es `HYPE32196-USD`,
SUI es `SUI20947-USD`), y el escáner lo resuelve solo. Si `trader/universe.json`
no existe, `orb` y `daily` lo arman.

**`orb` (ruptura del rango de apertura).** El rango es el máximo y el mínimo
de los primeros `--or-minutes` (15) de la sesión. Una ruptura es la primera
vela de 5 minutos que **cierra** por encima del máximo (LARGO) o por debajo
del mínimo (CORTO). Para cada una muestra la hora, el cierre, el nivel, qué
tan afuera del rango cerró, y cómo venía a la hora del corte.

| `--session` | Abre | En UTC (invierno del norte) | En Argentina |
| --- | --- | --- | --- |
| `wallstreet` (por defecto) | 09:30 Nueva York | 14:30 | 11:30 |
| `europa` | 08:00 Londres | 08:00 | 05:00 |

Cada día se calcula con sus propios horarios de verano o de invierno.

Las rupturas de **menos de 0,10 %** afuera del rango (`--min-beyond`) van en
un bloque aparte de "débiles": la mayoría es ruido. Si una cripto rompió para
los dos lados, el escáner lo marca: el rango no tiene dirección.

**`daily`.** Setups con los cierres diarios (velas de 00:00 a 24:00 UTC; la de
hoy no cuenta porque no cerró):

| Setup | Lado | Regla |
| --- | --- | --- |
| ruptura / quiebre de 20 días | largo / corto | cierre por encima / debajo de los 20 anteriores |
| bandera alcista / bajista | largo / corto | +10 % / -10 % en 10 días, después 5 cierres dentro de un 5 % |
| recuperó / perdió la media de 20 | largo / corto | cruzó la media de 20 días |
| sobreventa / sobrecompra | largo / corto | RSI 14 < 30 / > 70 |
| rebote desde sobreventa | largo | RSI < 30 ayer y hoy subió |

Yahoo a veces tarda en cargar el cierre de ayer, sobre todo en las primeras
horas UTC. El escáner lo avisa y muestra la fecha del cierre que usó: en ese
caso los setups pueden estar viejos.

## Cómo presentarlo

- **Mercado entero para un lado** (por ejemplo, 24 de 24 rompiendo para abajo
  en Wall Street): es el humor del día, no 24 oportunidades. Decilo así y
  elegí las 2 o 3 con la ruptura más clara y más volumen.
- Separá las rupturas fuertes de las débiles.
- Una ruptura no es una entrada: el paso siguiente es probar el plan con
  `/crypto-timemachine` (con `--setup orb` y el mismo `--or-minutes`) y
  calcular el tamaño con `/crypto-scalp`.
- Terminá con la nota del escáner: es una lista de gráficos que cumplen una
  regla, no una lista de criptos para comprar o vender.

Los volúmenes por vela de Yahoo para cripto vienen incompletos (muchas velas
en 0), así que el escáner no los usa para confirmar rupturas.
