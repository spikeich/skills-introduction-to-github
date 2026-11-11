---
name: trading-analisis-tecnico
description: Analiza un gráfico o una serie de precios (OHLCV) de forma estructurada, con tendencia, niveles, momentum, volumen y escenarios con invalidación. Usar cuando el usuario comparta un gráfico, datos de precios o un ticker y pida un análisis técnico, niveles de soporte y resistencia, lectura de indicadores o un plan de operación.
---

# Análisis técnico

Un análisis útil termina en escenarios condicionales ("si pasa X, entonces Y, y
queda invalidado en Z"), no en una predicción. El orden de abajo va de lo más
general a lo más específico; no saltar a los indicadores antes de tener el contexto.

## Trabajar solo con datos reales

Analizar únicamente lo que el usuario dio: una imagen del gráfico, un CSV, o datos
obtenidos con una herramienta en esta sesión. Si no hay datos, pedirlos. No citar
precios, niveles ni valores de indicadores de memoria: están desactualizados y
parecen exactos.

Con un CSV, calcular los indicadores con código (pandas) en lugar de estimarlos.
Con una imagen, decir qué se lee con claridad y qué es aproximado.

## Orden del análisis

1. **Contexto**: instrumento, temporalidad y qué quiere hacer el usuario
   (intradía, swing, posición). Mirar siempre una temporalidad superior a la de
   operación para ubicar la tendencia mayor.
2. **Estructura**: secuencia de máximos y mínimos. Ascendentes es tendencia
   alcista, descendentes es bajista, mezclados es rango. Marcar el último quiebre
   de estructura.
3. **Niveles**: soportes y resistencias con más de un toque, máximos y mínimos
   previos relevantes, huecos sin cerrar. Pocos niveles claros valen más que
   muchos; dar zonas, no precios al centavo.
4. **Medias móviles**: posición del precio frente a las de 20, 50 y 200, y su
   pendiente. Sirven para confirmar la tendencia, no para dar la señal.
5. **Momentum**: RSI o MACD. Lo que importa son las divergencias con el precio y
   el comportamiento en la zona media, no el "sobrecomprado" aislado: en tendencia
   fuerte el RSI se queda alto mucho tiempo.
6. **Volatilidad**: ATR para dimensionar stops y objetivos realistas. Compresión
   de rango suele anteceder a expansión.
7. **Volumen**: confirma quiebres (volumen alto) o los pone en duda (volumen
   bajo). En forex spot el volumen es de tick y pesa menos.

## Formato de salida

- **Sesgo**: alcista, bajista o neutral, con la temporalidad a la que aplica.
- **Niveles clave**: lista corta de zonas con una línea de por qué importan.
- **Escenario principal y alternativo**: disparador, objetivo e invalidación de
  cada uno.
- **Qué no se sabe**: eventos próximos (resultados, datos macro), datos faltantes,
  señales contradictorias entre temporalidades.

## Criterio

- Cuando las señales se contradicen, decirlo y dar sesgo neutral. Forzar una
  conclusión es peor que no tener ninguna.
- Los patrones (hombro-cabeza-hombro, banderas, triángulos) solo cuentan una vez
  confirmados por el quiebre; antes son una hipótesis.
- Más indicadores no dan más certeza: la mayoría deriva del mismo precio y repite
  la misma información.
- El análisis describe probabilidades, no certezas. No presentarlo como consejo de
  inversión. Si el usuario quiere operar el escenario, pasar a
  `trading-gestion-riesgo` para dimensionar la posición.
