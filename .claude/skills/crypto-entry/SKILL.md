---
name: crypto-entry
description: >-
  Temporizador de entrada para cripto. Vigila un setup vela por vela y dice el
  momento exacto de entrar, en largo o en corto: la primera vela de 5 minutos
  que cierra afuera del rango de apertura de Europa o de Wall Street, o que
  cierra a través de un nivel. Nunca manda órdenes. Usala cuando el usuario
  diga "avisame cuándo entrar", "¿ya rompió?", "vigilá ETH", "¿entro ahora?",
  "esperá la ruptura", o después de /crypto-scanner y antes de /crypto-exit.
argument-hint: "SÍMBOLO [--session europa|wallstreet] [--side long|short]"
---

# crypto-entry

Adaptación a cripto de `trader-entry` del repo
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(licencia MIT, ver `LICENSE-day-trader-skill` en la raíz del repo). Mismas
reglas, pero **en los dos sentidos** y con las sesiones de Europa y Wall
Street, todos los días.

`${CLAUDE_SKILL_DIR}` es esta carpeta. Corré los comandos desde la carpeta del
proyecto: el resultado queda en `trader/entry.json`.

```bash
python3 "${CLAUDE_SKILL_DIR}/entry.py" check ETH                       # apertura de Wall Street, cualquier lado
python3 "${CLAUDE_SKILL_DIR}/entry.py" check ETH --session europa --side short
python3 "${CLAUDE_SKILL_DIR}/entry.py" check SOL --setup level --level 92.5 --side long
python3 "${CLAUDE_SKILL_DIR}/entry.py" check ETH --write               # guarda trader/entry.json
python3 "${CLAUDE_SKILL_DIR}/entry.py" watch ETH --side short          # vela por vela hasta que dispare
```

Necesita `query2.finance.yahoo.com` (y `query1`) en la red del entorno.

## Las reglas

- **`orb` (por defecto).** El rango es el máximo y el mínimo de los primeros
  `--or-minutes` (15) de la sesión. Dispara con la **primera vela cerrada**
  después del rango que **cierra** por encima del máximo (largo) o por debajo
  del mínimo (corto). Una mecha que pasa el nivel y vuelve no cuenta.
- **`level`.** La primera vela de la sesión que cierra por encima (`--side
  long`) o por debajo (`--side short`) de `--level`, por ejemplo un máximo de
  20 días que marcó `/crypto-scanner daily`.
- La hora del disparo es la del **cierre** de la vela (la vela de las 14:50
  cierra a las 14:55) y el precio es ese cierre.
- **Vence** a las `--expire-hours` (6) de la apertura: más tarde, la ruptura
  de la apertura ya es vieja.

| `--session` | Abre | UTC (invierno del norte) | Argentina |
| --- | --- | --- | --- |
| `wallstreet` (por defecto) | 09:30 Nueva York | 14:30 | 11:30 |
| `europa` | 08:00 Londres | 08:00 | 05:00 |

Estados: **DISPARÓ** (con lado, hora y precio), **ESPERANDO** (no abrió, el
rango se está formando, o todavía no cerró afuera), **VENCIDO**, **SIN DATOS**.

## Vigilar en vivo

`watch` imprime una línea por cada vela cerrada y termina cuando dispara
(escribe `trader/entry.json`) o cuando vence. Corrélo bajo `Monitor`, así cada
vela llega como aviso:

```
Monitor: python3 "${CLAUDE_SKILL_DIR}/entry.py" watch ETH --side short
```

Avisale al usuario solo lo que importa: cuando el rango quedó armado (con el
máximo y el mínimo), cuando dispara y cuando vence. No repitas cada vela.

## Después

Un disparo no es una orden. El paso siguiente es `/crypto-exit` (stop,
objetivo y hora de salida), después `/crypto-timemachine` (¿tiene ventaja?) y
`/crypto-scalp size.py` (cuánto abrir). El usuario carga la orden en su app:
esta skill nunca opera.
