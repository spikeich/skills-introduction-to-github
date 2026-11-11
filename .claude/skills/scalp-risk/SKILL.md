---
name: scalp-risk
description: >-
  Gestor de riesgo para scalping de cripto: antes de cargar la orden revisa el
  plan contra límites de scalping (0,5 % de riesgo, hasta 10x aislado, R neto
  de comisiones, liquidación, 3 pérdidas y se termina el día, una posición a
  la vez, señal de menos de 3 minutos), calcula la cantidad y arma la orden
  para cargar a mano en Binance. Lleva el registro del día. Usala cuando el
  usuario diga "¿puedo entrar al scalp?", "cuánto abro", "armame la orden",
  "anotá el scalp", "cómo voy hoy", o después de /scalp-timemachine.
---

# scalp-risk

Adaptación de `crypto-risk` (repo skill-cryptos-jeto1337), que viene de
`trader-risk` de [Jakeschincariol/day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill)
(MIT, ver `LICENSE-day-trader-skill`).

```bash
python3 "${CLAUDE_SKILL_DIR}/risk.py" check --capital 3000              # trader/plan.json
python3 "${CLAUDE_SKILL_DIR}/risk.py" check --capital 3000 --lev 10 --risk 0.5 --record
python3 "${CLAUDE_SKILL_DIR}/risk.py" log --symbol BTC --result -15
python3 "${CLAUDE_SKILL_DIR}/risk.py" today
python3 "${CLAUDE_SKILL_DIR}/risk.py" config
```

## Los límites (`trader/config.json`, clave `risk`)

| límite | por defecto | por qué |
| --- | --- | --- |
| `max_risk_pct` | 0,5 % | en scalping hay muchas operaciones: cada una arriesga poco |
| `max_leverage` | 10x | más cerca, la liquidación compite con el stop |
| `min_net_r` | 1,2 | el objetivo tiene que pagar las comisiones |
| `max_trades_per_day` | 20 | |
| `max_losses_per_day` | 3 | la tercera pérdida termina el día |
| `max_daily_loss_pct` | 2 % | |
| `max_open` | 1 | un scalp a la vez |
| `liq_buffer` | 2 | la liquidación, al menos al doble de distancia que el stop |
| `min_notional` | 20 USDT | el mínimo habitual de Binance |
| `max_signal_age_min` | 3 | una señal de hace más de 3 minutos ya es vieja |

**El apalancamiento no cambia la pérdida**: la marca el stop. El tamaño sale
del riesgo; el apalancamiento solo decide cuánto margen queda trabado. Con
`check` en **PASA** imprime la orden para cargar a mano en Binance Futuros
(margen aislado, orden límite, TP/SL, hora de salida). Nunca la manda.

## Lo que mostraron los datos

4 semanas de velas de 1 minuto (BTC, ETH, SOL, XRP, DOGE), aperturas de
Londres y Nueva York, de lunes a viernes, 480 configuraciones: **ninguna ganó
después de comisiones en las dos mitades de la muestra** (promedio −0,27 R y
−0,39 R por operación). Sin comisiones quedaban cerca del empate. Este repo es
un simulador para practicar y medir, no una máquina de ganar: decíselo al
usuario cada vez que lo use.

Esto revisa límites; no es un consejo de inversión. El usuario carga la orden.
