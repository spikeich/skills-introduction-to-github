---
name: crypto-risk
description: >-
  Gestor de riesgo para cripto. Antes de cargar una orden, revisa el plan
  contra tus límites (riesgo por operación, apalancamiento máximo, R neto de
  comisiones, distancia a la liquidación, pérdidas y operaciones del día,
  posiciones abiertas, hora límite), calcula la cantidad y arma la orden para
  cargar a mano en Binance. Lleva el registro del día. Usala cuando el usuario
  diga "¿puedo entrar?", "revisá el riesgo", "cuánto abro", "armame la orden",
  "anotá que perdí / gané", "cómo voy hoy", o después de /crypto-exit y
  /crypto-timemachine, antes de operar.
argument-hint: "check --capital USDT [--lev N] [--risk %]"
---

# crypto-risk

Adaptación a cripto de `trader-risk` del repo
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(licencia MIT, ver `LICENSE-day-trader-skill` en la raíz del repo). En lugar
de las reglas de un broker de acciones, cuida lo que en cripto te saca del
juego: el apalancamiento, la liquidación y las comisiones.

`${CLAUDE_SKILL_DIR}` es esta carpeta. Lee `trader/plan.json` (de
`/crypto-exit`), `trader/config.json` (tus límites) y `trader/journal.json`
(el registro del día).

```bash
python3 "${CLAUDE_SKILL_DIR}/risk.py" check --capital 500              # PASA o BLOQUEADA, y la orden
python3 "${CLAUDE_SKILL_DIR}/risk.py" check --capital 500 --lev 5 --risk 1 --record
python3 "${CLAUDE_SKILL_DIR}/risk.py" log --symbol ETH --result -5.2   # al cerrar: resultado en USD
python3 "${CLAUDE_SKILL_DIR}/risk.py" today
python3 "${CLAUDE_SKILL_DIR}/risk.py" config
```

## Los límites

Se cambian en `trader/config.json`, bajo la clave `"risk"`:

```json
{"risk": {"max_leverage": 3, "max_risk_pct": 0.5}}
```

| límite | por defecto | qué bloquea |
| --- | --- | --- |
| `max_risk_pct` | 1 | arriesgar más de ese % del capital si salta el stop |
| `max_leverage` | 5 | más apalancamiento que eso |
| `min_net_r` | 1,2 | ganar menos de 1,2 veces lo que arriesgás, después de comisiones |
| `liq_buffer` | 2 | una liquidación a menos del doble de la distancia del stop |
| `max_trades_per_day` | 5 | la sexta operación del día |
| `max_losses_per_day` | 3 | seguir después de la tercera pérdida |
| `max_daily_loss_pct` | 3 | seguir si el día ya perdió ese % (o si este stop lo haría pasar) |
| `max_open` | 3 | más posiciones abiertas a la vez |
| `min_notional` | 20 | órdenes de menos de 20 USDT (el mínimo habitual de Binance) |
| `no_new_after_min` | 60 | entrar en la última hora antes de la hora de salida del plan |

Además avisa (sin bloquear) si ya tenés una posición en la misma cripto, o si
sumás otra posición en un mercado donde todo se mueve junto.

## La orden

Con **PASA**, imprime la orden para cargar a mano en Binance Futuros: par,
margen aislado y apalancamiento, orden límite en la entrada, cantidad, TP/SL y
cuánto perdés si salta el stop. Con `--record` la anota como abierta en el
registro. Cuando la cerrás, `log --symbol ETH --result USD` anota el
resultado, y eso cuenta para los límites del día.

## Cómo presentarlo

Si está **BLOQUEADA**, mostrá todas las razones y no busques la vuelta para
que pase: los límites están para los días en que uno quiere saltearlos. Si
**PASA**, mostrá la orden tal cual. En los dos casos: es una revisión de tus
límites, no un consejo de inversión, y la orden la cargás vos.
