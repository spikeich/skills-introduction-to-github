---
name: crypto-scalp
description: >-
  Analizar el mercado cripto, elegir las criptomonedas que mejor sirven para
  scalping, calcular entrada, stop, take profit y tamaño de posición, y
  simular las operaciones en papel con precios en vivo. Usala cuando el
  usuario diga "analizá el mercado", "elegí criptos para scalping", "¿corto o
  largo?", "cuánto abro", "simulame la operación", o pregunte por bitcoin,
  ETH, SOL u otra cripto para operar en el corto plazo.
---

# crypto-scalp

Tres herramientas en esta carpeta. Las tres corren de verdad: usalas, no
estimes a ojo.

```bash
python3 scan.py                                    # mercado + top 5
python3 size.py --capital 500 --entry 2280 --stop 2345 --target 2230
python3 paper.py --state s.json --trade ethereum:short:1000:10:1.5:2.5
```

Necesitan `api.coingecko.com` en la red del entorno. CoinGecko gratis corta
con 429 si se consulta muy seguido: `paper.py` ya reintenta y consulta cada
90 segundos. No bajes eso de 60.

## Lo que esta skill NO hace

- **No opera.** Nunca manda una orden a una exchange, ni con API key. Los
  números los carga el usuario en su app. Si te pide que operes por él, decí
  que no y ofrecé la simulación.
- **No predice.** Los indicadores describen lo que ya pasó. Cerrá cada
  análisis con una línea que diga que no es consejo de inversión.
- **No inventa precios.** Si CoinGecko no responde, decilo. Nunca rellenes
  con números de memoria.

## 1. Leer el mercado

Corré `scan.py`. Lee las 80 criptos con más volumen, saca stablecoins y
copias envueltas, y descarta:

- volumen < 300 M USD (el spread se come la ganancia),
- rango del día < 5 % (no hay recorrido),
- rango > 14 % (suele ser una noticia, no un rango que se repita),
- volumen mayor a la mitad de la capitalización (especulación pura).

`pos%` es dónde está el precio dentro del rango de 24 h: 0 es el mínimo, 100
el máximo. La línea "Mercado: N de 25 en el mínimo" dice el humor del día. Si
la mayoría está abajo, el sesgo del día es corto en los rebotes y largo solo
en la que muestre fuerza relativa.

Mostrale al usuario la tabla de las 5 elegidas con precio, volumen, rango,
pos% y el sesgo, una línea de por qué cada una, y las descartadas con la
razón.

Para el contexto de una sola cripto (tendencia de días y semanas), bajá
`/coins/{id}/market_chart?vs_currency=usd&days=365&interval=daily` y calculá
SMA 20/50/200, RSI 14, volatilidad de 30 días y el retorno de 7/30/90 días.
Para intradía, `days=1` da precios cada ~5 minutos y `days=2` por hora.

## 2. Corto o largo, y dónde

- **Nunca entrar en el mínimo del día para un corto, ni en el máximo para un
  largo.** Esperar un rebote o una caída del 1-1,5 % y poner la orden límite
  ahí.
- El stop va del otro lado del último nivel donde el precio se frenó.
- El take profit, antes del próximo nivel obvio: el mínimo o máximo del día,
  o un número redondo.
- Relación ganancia/riesgo de al menos 1,3 : 1 después de comisiones.
- Si la caída es larga y sin rebotes, los rebotes van a ser chicos: la
  entrada va cerca del precio, no a 2 % de distancia. Una orden que nunca se
  llena es tiempo perdido.

## 3. Cuánto abrir

Corré `size.py` con el capital del usuario. Por defecto arriesga el 1 % por
operación, con 3x y comisiones de Binance Futuros incluidas. Avisa si la
liquidación cae antes que el stop o si la orden queda debajo del mínimo de
Binance (20 USDT).

Reglas que van siempre con el número:

- margen **aislado**, no cruzado,
- el stop se pone al abrir, no después,
- máximo 3 operaciones perdedoras por día y se corta,
- si nunca hizo scalping, una semana en el modo demo de Binance primero.

Si el usuario pide algo "agresivo" (10x o más, entrada a mercado), simulalo,
pero mostrale en una tabla cuánto pierde en USD y en % del margen si salta el
stop, y a qué distancia está la liquidación.

## 4. Simular

`paper.py` corre bajo `Monitor` (cada línea es un aviso). Una línea al abrir
o llenar cada orden, una al cerrar con el resultado neto de comisiones, y un
resumen cada `--report-min` minutos (20 por defecto). El estado se guarda en
`--state`: si el monitor vence a los 30 minutos, se relanza con el mismo
`--state` y sigue donde quedó.

Ids de CoinGecko que más se usan: `bitcoin`, `ethereum`, `solana`, `ripple`,
`dogecoin`, `binancecoin`, `zcash`, `sui`, `hyperliquid`, `cardano`.

Al terminar, mostrá cada operación con su resultado y el total, y decí qué
enseñó: si la entrada quedó lejos, si el stop estaba muy ajustado, si la
tendencia del día pesó más que el nivel.

## Binance desde esta sesión

`fapi.binance.com` y `api.binance.com` responden "restricted location" desde
los servidores de esta nube. No es un problema de red del entorno: Binance
bloquea el país del servidor. Los precios salen de CoinGecko, que va uno o dos
minutos atrás de la exchange. Para una simulación alcanza; para operar en
vivo, el usuario mira su app.
