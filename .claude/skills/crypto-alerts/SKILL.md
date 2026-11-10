---
name: crypto-alerts
description: >-
  Alertas de precio para cripto. Avisa cuando un precio supera o perfora un
  nivel, y sigue un plan de /crypto-exit: cuándo el precio llega a la entrada,
  cuándo toca el stop o el objetivo, cuándo la orden nunca se llenó, y cuándo
  es la hora de salir. Nunca toca órdenes. Usala cuando el usuario diga
  "avisame si BTC pasa 78.000", "poneme una alerta", "vigilá mi operación",
  "avisame si toca el stop", "a cuánto está ETH", o mientras una operación
  está abierta.
argument-hint: "watch [--symbol BTC --above X --below Y] | now --symbol ETH,BTC"
---

# crypto-alerts

Adaptación a cripto de `trader-alerts` del repo
[Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(licencia MIT, ver `LICENSE-day-trader-skill` en la raíz del repo).

`${CLAUDE_SKILL_DIR}` es esta carpeta.

```bash
python3 "${CLAUDE_SKILL_DIR}/alerts.py" now --symbol ETH,BTC,SOL          # precio actual
python3 "${CLAUDE_SKILL_DIR}/alerts.py" watch                             # sigue trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/alerts.py" watch --symbol BTC --above 78000 --below 74000 --plan none
```

**Precios:** primero Binance (`data-api.binance.vision`, y `api.binance.com` donde no esté bloqueado): son los precios de la exchange misma. Si Binance no tiene la cripto o no responde, Yahoo (`query2.finance.yahoo.com` y `query1`). `--source binance` o `--source yahoo` fuerza una. La salida dice de dónde salieron ("Precios de Binance (BTCUSDT)"). Binance cotiza en USDT y suele quedar un 0,1 % arriba de Yahoo y CoinGecko, que cotizan en dólares: no mezcles fuentes dentro de una misma operación.

`now --compare` muestra la misma cripto en las tres fuentes, lado a lado: Binance, Yahoo y CoinGecko, con la
diferencia máxima entre ellas. CoinGecko sirve para el precio de ahora; no tiene velas de 1 ni de 5 minutos.

## Qué avisa

| aviso | cuándo |
| --- | --- |
| **ALERTA** | el precio superó (`--above`) o perforó (`--below`) tu nivel |
| **ENTRADA** | el precio llegó a la entrada del plan: una orden límite ahí se llenó |
| **STOP** | tocó el stop en el minuto de la entrada o después: la operación salió con pérdida |
| **OBJETIVO** | tocó el objetivo en un minuto posterior al de la entrada |
| **PERDIDA** | tocó el stop o el objetivo sin pasar antes por la entrada: la orden no se llenó, cancelala |
| **HORA DE SALIR** | llegó la hora de salida del plan: cerrá, gane o pierda (o cancelá si no entró) |

Mira el máximo y el mínimo de cada minuto, no solo el último precio: una
mecha entre dos consultas también cuenta. Cada minuto cerrado se juzga **una
sola vez y en orden**, y si una consulta falla, la siguiente se pone al día.

Si en el mismo minuto toca la entrada y el stop, **cuenta el stop**: el precio
pasa por la entrada antes de poder llegar al stop. Si en ese minuto toca la
entrada y el objetivo, el objetivo espera al minuto siguiente, porque pudo
haber estado ahí antes de que se llenara la orden.

Si el plan ya venció cuando arranca (su hora de salida pasó), lo dice y no
vigila nada.

## Cómo correrlo

`watch` va bajo `Monitor`: cada línea es un aviso. Imprime una línea al
arrancar, una por alerta, y un "sigue vigilando" cada 30 minutos para que el
silencio nunca parezca un cuelgue. Termina solo cuando la operación terminó o
se cumplieron todas las alertas, o a las 8 horas (`--max-hours`). Si el
monitor vence, relanzalo con los mismos argumentos.

Pasale al usuario cada aviso apenas llega, en una línea, con qué hacer:
"tocó el stop: la operación salió con pérdida; anotala con
`/crypto-risk log`".

Los precios son de Yahoo, gratis y no oficiales: pueden ir uno o dos minutos
atrás de Binance. Para salir en serio, mandan el stop y el take profit que
cargaste en la exchange, no esta alerta.
