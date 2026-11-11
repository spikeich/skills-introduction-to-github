---
name: scalp-alerts
description: >-
  Alertas para scalping de cripto: sigue el plan de /scalp-exit minuto a
  minuto y avisa cuando el precio llega a la entrada, toca el stop o el
  objetivo, la orden nunca se llenó, o se cumple la salida por tiempo. También
  alertas de precio sueltas. Nunca toca órdenes. Usala cuando el usuario diga
  "vigilá el scalp", "avisame si toca el stop del scalp", "a cuánto está BTC",
  o mientras un scalp está abierto.
---

# scalp-alerts

Adaptación de `crypto-alerts` (repo skill-cryptos-jeto1337), que viene de
`trader-alerts` de [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT, ver `LICENSE-day-trader-skill`).

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" watch                       # trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" watch --symbol BTC --above 76000 --below 75000 --plan none
python3 "${CLAUDE_SKILL_DIR}/alerts.py" now --symbol BTC,ETH
```

Mira cada 20 segundos (`--every`) las velas de 1 minuto cerradas, con su
máximo y su mínimo: cada minuto se juzga **una sola vez y en orden**, así una
mecha entre dos miradas igual cuenta, y si una mirada falla la siguiente se
pone al día. Imprime una
línea cuando arranca, una por alerta y un "sigue vigilando" cada 5 minutos
(`--heartbeat`). Termina cuando el scalp terminó (stop, objetivo, orden que no
se llenó o salida por tiempo) o a la hora (`--max-hours`). Corrélo bajo
`Monitor` y avisale al usuario solo lo que importa.

| evento | qué quiere decir |
| --- | --- |
| ENTRADA | el precio llegó a la entrada: una orden límite ahí se llenaba |
| STOP | tocado en el minuto de la entrada o después: el scalp terminó con pérdida (el precio pasa por la entrada antes de llegar al stop) |
| OBJETIVO | tocado en un minuto posterior al de la entrada: el scalp terminó en ganancia |
| PERDIDA | llegó al stop o al objetivo sin pasar por la entrada: la orden no se llenó, cancelala |
| HORA DE SALIR | la salida por tiempo del plan (aunque cruce la medianoche UTC): afuera, gane o pierda |

Si el plan ya venció cuando arranca (su hora de salida pasó), lo dice y no
vigila nada: hay que armar un plan nuevo.

**Precios:** primero Binance (`data-api.binance.vision`, y `api.binance.com` donde no esté bloqueado): son los precios de la exchange misma. Si Binance no tiene la cripto o no responde, Yahoo (`query2.finance.yahoo.com` y `query1`). `--source binance` o `--source yahoo` fuerza una. La salida dice de dónde salieron ("Precios de Binance (BTCUSDT)"). Binance cotiza en USDT y suele quedar un 0,1 % arriba de Yahoo y CoinGecko, que cotizan en dólares: no mezcles fuentes dentro de una misma operación.

`now --compare` muestra la misma cripto en Binance, Yahoo y CoinGecko, lado a lado.

Yahoo puede ir uno o dos minutos atrás de Binance: en scalping eso es mucho.
Para operar de verdad, mirá el precio en la app de la exchange.
