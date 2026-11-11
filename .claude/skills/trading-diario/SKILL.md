---
name: trading-diario
description: Registra operaciones en un diario de trading y genera revisiones periódicas con estadísticas y patrones de comportamiento. Usar cuando el usuario quiera anotar una operación, revisar su semana o mes, calcular su win rate o expectancy, o entender por qué está ganando o perdiendo.
---

# Diario de trading

El diario sirve para separar la calidad de la decisión de la suerte del resultado.
Una operación que siguió el plan y perdió es una buena operación; una que lo rompió
y ganó es una mala. El registro tiene que permitir distinguirlas.

## Dónde se guarda

Un archivo CSV en `diario/operaciones.csv` en la raíz del proyecto, una fila por
operación. Si no existe, crearlo con esta cabecera:

```csv
id,fecha_entrada,fecha_salida,instrumento,direccion,setup,entrada,stop,objetivo,salida,tamano,resultado,resultado_r,siguio_plan,emocion,notas
```

- `direccion`: `largo` o `corto`.
- `setup`: nombre corto y consistente de la estrategia (por ejemplo `ruptura`,
  `retroceso-ma20`). Reutilizar los nombres ya presentes en el archivo.
- `resultado`: ganancia o pérdida en dinero, neta de comisiones.
- `resultado_r`: resultado ÷ riesgo inicial. El riesgo inicial es
  |entrada − stop| × tamaño. Calcularlo, no pedirlo.
- `siguio_plan`: `si` o `no`. Es el campo más importante; preguntarlo siempre.
- `emocion`: una palabra (calma, ansiedad, revancha, euforia, aburrimiento).

Antes de escribir, leer el archivo para continuar la numeración de `id` y no
pisar filas. Agregar al final; no reordenar ni reescribir lo existente.

## Registrar una operación

Tomar lo que el usuario cuente en lenguaje natural y completar la fila. Preguntar
solo por lo que falte y no se pueda calcular; `stop` y `siguio_plan` no se
inventan. Las operaciones abiertas se registran con `salida` y `resultado` vacíos
y se completan al cerrar.

Confirmar con una línea que muestre el resultado en R.

## Revisión periódica

Calcular con código (pandas) sobre el CSV, no a ojo:

- Cantidad de operaciones, win rate, ganancia media y pérdida media en R.
- Expectancy en R y resultado total en R y en dinero.
- Mayor racha de pérdidas y drawdown máximo del período.
- Las mismas métricas **por setup**, por dirección y por `siguio_plan`.
- Resultado por emoción registrada y por día de la semana u hora, si hay datos.

Con menos de unas 20 operaciones por grupo, presentar los números pero aclarar
que la muestra es chica y no alcanza para concluir.

## Qué buscar

- **Costo de romper el plan**: comparar la expectancy de `siguio_plan=si` contra
  `no`. Suele ser el hallazgo más accionable.
- **Setups que no pagan**: los que tienen expectancy negativa con muestra
  suficiente son candidatos a dejar de operarse.
- **Pérdidas mayores a 1R**: indican stops movidos o no respetados.
- **Ganancias cortadas**: ganancia media muy por debajo del objetivo planeado.
- **Operaciones de revancha**: entradas poco después de una pérdida, con más
  tamaño o con emoción negativa.
- **Sobreoperación**: días con muchas más operaciones que el promedio y peor
  resultado.

## Cómo presentar la revisión

Primero dos o tres hallazgos concretos con sus números, después la tabla de
métricas, y al final una o dos acciones para el período siguiente, específicas y
verificables ("no operar `ruptura` en la primera media hora"), no generales
("tener más disciplina"). Describir los patrones sin juzgar al usuario.
