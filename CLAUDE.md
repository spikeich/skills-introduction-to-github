# CLAUDE.md

Contexto para Claude al empezar cada sesión en este repo. Editalo cuando cambie algo.

## Sobre mí
- Seba, Argentina. Estudio Analista de Sistemas (primer año) y me oriento a Data Engineering.
- Hablame en castellano rioplatense, tono informal. Respuestas cortas, con tablas cuando ayuden.
- Uso Claude Code casi siempre desde el celular (app Android), a veces desde la app de escritorio.
- Horarios: decime la hora de Argentina además de la de Nueva York o UTC.

## Mi trading
- **Todo es simulado (paper trading).** No hay broker conectado ni dinero real.
- Estilo: scalping intradía, sobre todo en corto. También cripto.
- Reglas actuales en `trader/config.json`: capital $5.000 (usar hasta $4.500), riesgo hasta $100 por
  operación, objetivo 3R, hasta 10 operaciones por día, pérdida diaria máxima $250, parar al ganar $250,
  entradas 9:45–15:30 y todo cerrado a las 15:55 (hora de Nueva York). Cortos permitidos; margen, opciones
  y cripto en las reglas de acciones, no.
- Antes de entrar, mostrame precio, stop, objetivo, cantidad y cuánto gano o pierdo. Esperá mi "dale".
- Mientras hay posiciones abiertas, avisame al tocar stop u objetivo, y un resumen cada 20 minutos si lo pido.

## Lo que aprendimos (5/11/2026)
- La primera tanda, a favor de la caída y temprano, ganó (6 de 7). El scalping en corto de la tarde perdió.
- En días de pánico, después de las 14:00 los rebotes sacan los cortos: no abrir scalping en corto tarde.
- Parar el día si devuelvo la mitad de lo ganado.
- No estirar el objetivo para llegar a un número del día.
- Respetar el stop: nunca alejarlo para "darle aire".

## Dónde está todo
- Operaciones simuladas: `trader/sim_trades.json`. Reglas: `trader/config.json`.
- Scripts propios: `trader/tools/` (scans de cortos, scalping y rebote; vigilantes de posiciones).
- Skills de acciones: `trader-*` (de Jakeschincariol/day-trader-skill).
- Skills de cripto: `crypto-*` (de spikeich/skill-cryptos-jeto1337). Hay otro repo mío: scalp-trading-crypto-jeto1337.
- Otras skills: `headroom` (compresión de contexto), `task-observer` (mejora de skills; no activado).
- Skills de Instagram (`ig-*`): en la rama `claude/instagram-agent-skill-xucx30` de este repo.
- Rama de trabajo de trading: `claude/trading-session-2wg1is`.

## Al instalar algo nuevo
- Revisá el código antes de instalar y confirmá que sea el repo oficial (cuidado con forks y copias).
- Lo que solo sirve en una compu (proxies, servicios en segundo plano) no se instala en la nube: explicámelo.
