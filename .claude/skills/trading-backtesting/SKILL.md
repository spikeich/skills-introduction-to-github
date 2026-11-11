---
name: trading-backtesting
description: Diseña, programa y evalúa backtests de estrategias de trading con datos históricos, evitando los sesgos que inflan los resultados. Usar cuando el usuario quiera probar una estrategia, escribir o revisar código de backtesting, interpretar métricas como Sharpe, drawdown o expectancy, u optimizar parámetros.
---

# Backtesting

Un backtest es fácil de hacer mal de una forma que da buenos resultados. La mayor
parte del trabajo consiste en descartar que la ganancia venga de un error, no en
conseguir una curva linda. Un resultado demasiado bueno es, ante todo, un bug a
buscar.

## Antes de escribir código

Dejar por escrito las reglas completas, sin ambigüedad:

- Universo e instrumento, temporalidad y período de prueba.
- Condición de entrada, de salida, stop y objetivo.
- Tamaño de posición y cuántas posiciones simultáneas.
- Costos: comisión, spread, deslizamiento y, si aplica, financiación o swap.

Si una regla necesita "criterio" para aplicarse, no se puede testear todavía.

## Errores que invalidan el resultado

Revisar cada uno explícitamente en cualquier backtest propio o ajeno:

- **Mirar el futuro (look-ahead)**: la señal se calcula con el cierre de la vela y
  se ejecuta a ese mismo cierre. La señal de la vela *t* se opera en la apertura de
  *t+1*. En pandas, hacer `shift(1)` de la señal antes de multiplicar por los
  retornos.
- **Sesgo de supervivencia**: usar solo los activos que existen hoy excluye a los
  que quebraron o fueron deslistados.
- **Sobreajuste**: muchos parámetros optimizados sobre un solo período. Cuantas
  más combinaciones se prueban, más probable es que la mejor sea azar.
- **Sin costos**: las estrategias de alta frecuencia de operaciones suelen pasar
  de ganadoras a perdedoras al agregar comisiones y spread.
- **Ejecución irreal**: asumir llenado al precio exacto del stop o del límite, o
  volumen ilimitado en activos poco líquidos.
- **Datos sin ajustar**: splits y dividendos sin ajustar generan saltos falsos.
- **Stop y objetivo en la misma vela**: sin datos intravela no se sabe cuál se
  tocó primero. Asumir el peor caso (el stop).

## Validación

- Separar los datos en un tramo para desarrollar y otro **fuera de muestra** que
  no se toca hasta el final. Si se ajusta la estrategia después de mirarlo, deja de
  ser fuera de muestra.
- Para parámetros optimizados, usar walk-forward: optimizar en una ventana, probar
  en la siguiente, avanzar y repetir.
- Probar la sensibilidad: una estrategia sólida sigue funcionando con parámetros
  vecinos. Un pico aislado de rendimiento es sobreajuste.
- Comparar siempre contra un punto de referencia: comprar y mantener el mismo
  activo en el mismo período.

## Métricas a reportar

| Métrica | Qué mirar |
| --- | --- |
| Número de operaciones | Menos de ~30 no permite concluir nada |
| Retorno total y anualizado (CAGR) | Frente al de comprar y mantener |
| Drawdown máximo y su duración | Si el usuario lo podría soportar en real |
| Sharpe / Sortino | Anualizados; aclarar la tasa libre de riesgo usada |
| Win rate y ganancia/pérdida media | Juntos; por separado no dicen nada |
| Expectancy | win% × ganancia media − loss% × pérdida media, en R |
| Profit factor | Ganancias brutas ÷ pérdidas brutas |
| Tiempo en el mercado | Para comparar retorno por exposición |

Mostrar la curva de capital y la de drawdown. Indicar si los resultados dependen
de pocas operaciones grandes.

## Implementación

- Empezar con pandas vectorizado para estrategias simples sobre un activo. Para
  órdenes complejas o carteras, usar una librería (`backtesting.py`, `vectorbt`,
  `backtrader`) y verificar en su documentación cómo modela la ejecución.
- Hacer que el código sea reproducible: datos versionados, semilla fija,
  parámetros en un solo lugar.
- Verificar a mano dos o tres operaciones del registro contra el gráfico.

## Cómo presentar resultados

Dar las métricas, las suposiciones (costos, ejecución, período) y las limitaciones
juntas. Decir con claridad que el rendimiento pasado no garantiza el futuro y que
el paso siguiente a un backtest que sobrevive es operar en simulado o con tamaño
mínimo, no con el tamaño completo.
