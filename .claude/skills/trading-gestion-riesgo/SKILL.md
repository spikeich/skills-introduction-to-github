---
name: trading-gestion-riesgo
description: Calcula tamaño de posición, stop-loss, relación riesgo/beneficio y límites de drawdown para una operación o una cartera. Usar cuando el usuario pregunte cuánto comprar o vender, dónde poner el stop, cuánto arriesgar por operación, o si una operación "vale la pena" por su riesgo/beneficio.
---

# Gestión de riesgo

El objetivo es que ninguna operación individual, ni una racha de pérdidas, pueda
sacar al usuario del mercado. Primero se define cuánto se puede perder; el tamaño
de la posición sale de ahí, nunca al revés.

## Datos que hay que tener antes de calcular

- Capital de la cuenta y moneda.
- Riesgo máximo por operación (si no lo da, proponer 1 % y decirlo).
- Precio de entrada y precio de stop. Sin stop no hay cálculo: pedirlo.
- Objetivo de salida, si quiere relación riesgo/beneficio.
- Instrumento: acciones, futuros (valor del punto), forex (valor del pip) o cripto.
  El multiplicador cambia el resultado, así que no asumirlo.

Si falta alguno, preguntar solo por ese dato.

## Cálculo

Usar el script en vez de hacer la cuenta a mano:

```bash
python3 .claude/skills/trading-gestion-riesgo/scripts/position_size.py \
  --capital 10000 --riesgo-pct 1 --entrada 50 --stop 48 --objetivo 56
```

Opciones útiles: `--multiplicador` (valor por punto en futuros o por pip en forex),
`--comision` (por unidad, ida y vuelta), `--lote` (tamaño mínimo negociable),
`--json` para salida estructurada.

Las fórmulas que aplica:

- Riesgo en dinero = capital × riesgo % / 100
- Riesgo por unidad = |entrada − stop| × multiplicador + comisión
- Tamaño = riesgo en dinero ÷ riesgo por unidad, redondeado **hacia abajo** al lote
- R/B = |objetivo − entrada| ÷ |entrada − stop|
- Win rate de equilibrio = 1 ÷ (1 + R/B)

## Qué revisar además del número

- **Exposición total**: si la posición resultante supera el capital, hay
  apalancamiento. Decirlo explícitamente con el múltiplo.
- **Riesgo agregado**: sumar el riesgo abierto de todas las posiciones. Posiciones
  correlacionadas (mismo sector, mismo par base) cuentan como una sola apuesta.
- **Stop con sentido**: el stop va donde la idea queda invalidada (debajo de un
  soporte, más allá de un ATR), no donde "da" el tamaño que el usuario quería.
  Si mueve el stop para agrandar la posición, señalarlo.
- **Gaps y deslizamiento**: el stop no garantiza el precio de salida. En
  instrumentos que abren con gap, la pérdida real puede superar el riesgo calculado.
- **Límites de racha**: sugerir un tope diario y uno mensual (por ejemplo 3R y 10R)
  después del cual se deja de operar.

## Cómo responder

Dar el tamaño, el riesgo en dinero, la exposición y la R/B en pocas líneas, y
después las advertencias que apliquen a ese caso. No dar recomendaciones de compra
o venta: la skill dimensiona una operación que el usuario ya decidió, no la valida.
