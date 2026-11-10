---
name: scalp-social-info
description: >-
  Información social y política para cripto: qué hicieron los gobiernos, los
  reguladores, las empresas y las figuras públicas de los países que más pesan
  en cripto (prohibiciones, adopción, reservas, leyes, ETF, elecciones,
  aranceles, colapsos, escándalos) y cómo se movió el precio antes y después.
  Verifica noticias dudosas con 5 fuentes independientes, arma el calendario
  de eventos que vienen y mide los patrones con precios reales. Lee la
  blockchain de Bitcoin y Ethereum: comprueba transacciones de una noticia y
  muestra comisiones, mempool y movimientos grandes. Usala cuando el usuario
  pregunte por una noticia política o social de cripto, "¿esto es verdad?",
  "¿cómo afecta esto al precio?", "¿ya está en el precio?", "qué pasó cuando
  China prohibió", "qué se viene esta semana", "mirá la blockchain", "¿se
  movieron esos bitcoin?", o antes de hacer scalping en un día con noticias.
argument-hint: "[study | patterns | calendar | verify --claim ... | chain | add-event]"
---

# scalp-social-info

Copia de `crypto-social-info` (repo skill-cryptos-jeto1337) para el repo de
scalping: mismas noticias, verificación, blockchain y calendario, con una
regla más para scalping.

## La regla de scalping

**Nada de entradas nuevas desde 15 minutos antes hasta 15 minutos después de
cada evento del calendario** (inflación, la Fed, votaciones, fallos). En esos
minutos el spread se abre, el precio salta y los stops chicos se ejecutan peor.
`calendar` lo recuerda al final. Y una noticia grande verificada y NUEVA de la
última hora manda sobre cualquier ruptura de 1 minuto.


Una sola skill con dos partes, **política** (gobiernos, leyes, reguladores,
elecciones, aranceles) y **social** (adopción de empresas y personas, figuras
públicas, colapsos y escándalos). Cada evento lleva su etiqueta y se puede
filtrar con `--scope politico` o `--scope social`.

`${CLAUDE_SKILL_DIR}` es esta carpeta. El historial (`events.json`) y el
calendario (`calendar.json`) viven acá; las verificaciones quedan en
`trader/verificaciones.json` del proyecto.

```bash
python3 "${CLAUDE_SKILL_DIR}/social.py" study                    # cada evento: antes, día 0, 7 y 30 días
python3 "${CLAUDE_SKILL_DIR}/social.py" study --scope social
python3 "${CLAUDE_SKILL_DIR}/social.py" patterns                 # solo los resúmenes
python3 "${CLAUDE_SKILL_DIR}/social.py" calendar --days 30       # lo que se viene
python3 "${CLAUDE_SKILL_DIR}/social.py" verify --claim "..." --first-seen "2026-11-04 03:00" \
    --source "CNBC|https://...|confirma|2026-11-04 01:10" --source "Reuters|https://...|confirma|2026-11-04" ...
python3 "${CLAUDE_SKILL_DIR}/social.py" verify --claim "..." --onchain "btc|TXID|4259" \
    --source "CNBC|https://...|confirma|2026-11-06 14:00|anonima" --dir - --coin BTC
python3 "${CLAUDE_SKILL_DIR}/social.py" verify --list
python3 "${CLAUDE_SKILL_DIR}/social.py" chain                    # la red de Bitcoin y Ethereum ahora
python3 "${CLAUDE_SKILL_DIR}/social.py" add-event --date 2026-11-04 --country EE.UU. --scope politico \
    --type elecciones --dir - --title "..." --verification 1
```

Necesita `query2.finance.yahoo.com` en la red (precios diarios de la cripto,
de BTC y del Nasdaq). La búsqueda de noticias la hacés vos con tu herramienta
de búsqueda web: los scripts no buscan.

## 1. Verificar una noticia dudosa

Cuando el usuario trae una noticia, o una noticia va a decidir una operación,
**verificala antes de usarla**:

1. Buscá la noticia y juntá **5 fuentes confiables** que no se copien entre
   sí. Confiable quiere decir una de estas tres cosas:
   - un **diario, agencia o medio financiero conocido** de la lista
     `fuentes.json` (Reuters, AP, Bloomberg, Financial Times, WSJ, CNBC, NYT,
     BBC, El País, Clarín, La Nación, Nikkei, SCMP...). Los medios cripto
     (CoinDesk, The Block, Cointelegraph...) y los blogs se pueden citar pero
     **no cuentan**;
   - un **vocero oficial** de un gobierno, regulador o banco central, con
     nombre y cargo (`--vocero "Nombre, cargo|url|confirma"`);
   - un **economista reconocido**, con nombre e institución
     (`--economist "Nombre, institución|url|confirma"`).
   Si un medio solo repite a otro, cargalo con `|copia de OTRO`: no cuenta.
2. Buscá también la **fuente oficial** (sitio del gobierno, del regulador o
   del banco central, el Federal Register, el BOE...) y **buscá desmentidos**
   ("denies", "fake", "hacked", "desmiente").
3. **Rumores de X.** Si la noticia sale de X, cargá el posteo con su tilde
   (`--social "Cuenta|url|confirma|gris"`):
   - **sin tilde o con tilde azul** (se compra): se descarta;
   - **tilde gris** (gobiernos y funcionarios) **o dorado** (organizaciones):
     se anota como el origen, pero **nunca confirma**. Igual hacen falta las 5
     fuentes confiables: en 2024 hackearon la cuenta de la SEC, que tenía
     tilde gris.

   Tu buscador no puede leer algunos sitios grandes (Reuters, AP, NYT, FT,
   WSJ, BBC, The Guardian, El País, Clarín bloquean a los buscadores
   automáticos). Usá los otros de la lista; nunca cuentes como confirmación
   un medio que no pudiste leer.
4. Para cada fuente marcá si **confirma** (coinciden quién, qué, cuándo y
   cuánto), es **parcial** (dice otra cifra, otra fecha u otra persona),
   **desmiente** o **no_dice**, y **la fecha de la nota** en UTC:
   `--source "CNBC|url|confirma|2026-10-30 09:00"` (o solo `2026-10-30`).
5. Anotá cuándo te llegó la noticia (`--first-seen`, UTC): el momento en que
   apareció en X, en el chat o en el buscador.
6. Corré `verify`. El veredicto lo calcula el script, siempre con la misma regla:

| veredicto | cuándo | qué se hace |
| --- | --- | --- |
| **VERIFICADA** | un documento oficial la confirma, o **al menos 4** fuentes confiables confirman los mismos datos **y son el 80 % o más** de las que hablan del tema, con **al menos 2 diarios independientes**, sin desmentido | entra al historial; para operar, mirá además **la fecha** (abajo) |
| **DUDOSA** | le falta poco para eso, datos que no coinciden, una fuente confiable la desmiente, o salió hace menos de 1 hora | no se opera por esa noticia; con posiciones abiertas, achicar y volver a revisar en 1 hora |
| **FALSA** | desmentido oficial, o 2 confirmaciones o menos | se descarta y queda anotada |

Se pueden cargar todas las fuentes que encuentres: la regla mira la
**proporción**, así que 10 fuentes con 4 confirmaciones no alcanzan (40 %).
Dos notas del mismo medio cuentan como una.

### La fecha

Que una noticia sea verdad no quiere decir que sea de hoy. `verify` cuenta la
edad desde la **primera nota confiable**, no desde que la viste, y la muestra
al lado del veredicto:

| fecha | edad | qué se hace |
| --- | --- | --- |
| **NUEVA** | menos de 24 horas | puede mover el precio hoy: se usa para operar |
| **RECIENTE** | de 24 a 72 horas | buena parte ya está en el precio: con cuidado, sin perseguir el movimiento |
| **VIEJA** | más de 72 horas | ya está en el precio: es contexto, nunca una razón para operar hoy |
| **SIN FECHA** | ninguna fuente tiene fecha | antes de operar, buscá cuándo pasó |

- Una confirmación con fecha **más de 7 días anterior** a las demás habla de
  **otro hecho** y no cuenta (por ejemplo, una nota de 2022 sobre otro hackeo
  a Binance no confirma uno de 2026).
- Si te llegó (`--first-seen`) **más de 24 horas después** de la primera
  nota, es una noticia vieja que volvió a circular: **RECICLADA**. Es un
  truco común en X para mover el precio con algo que ya pasó.
- `news --for-verify` ya trae la fecha de cada nota.

Ejemplo: el 6 de noviembre apareció el hackeo de 6.300 millones a Binance.
Era verdad (Bloomberg, CNBC, NPR, NBC), pero había pasado el 29 de octubre:
VERIFICADA, VIEJA, RECICLADA. No servía para operar ese día.

**Noticias de alto impacto** (`--high-impact`): las que pueden mover mucho el
precio o cambiar lo que vas a operar (aprobación de un ETF, una prohibición, un
gobierno que compra o vende bitcoin). Piden **6 confirmaciones, 85 %**, de **2
regiones o más** (América, Europa, Asia y Oceanía, Medio Oriente, África) y con
**una agencia internacional** (Reuters, AP, AFP, Bloomberg, dpa, Kyodo,
Yonhap...) o un documento oficial entre ellas.

### Fuentes anónimas

Si una nota se basa solo en "fuentes cercanas", "people familiar with the
matter" o "según personas al tanto", agregale `|anonima`:
`--source "Bloomberg|url|confirma|2026-11-06 12:00|anonima"`. **Todas las
notas anónimas juntas cuentan como una sola confirmación**: cinco diarios que
citan a "una persona al tanto" pueden estar citando a la misma persona.

### La prueba en la blockchain (`--onchain`)

Los hackeos, los movimientos de ballenas, las ventas de un gobierno y los
pagos se ven en la cadena. Si la noticia trae el número de transacción (o lo
encontrás en el explorador), cargalo:

```bash
--onchain "btc|TXID|4259"              # Bitcoin, por mempool.space
--onchain "eth|0xHASH|12.5"            # Ethereum (ETH), por eth.blockscout.com
--onchain "eth|0xHASH|503.9 USDT"      # un token de Ethereum
```

El script lee la transacción y compara el monto (con 1 % de tolerancia, sin
separador de miles):

| la cadena muestra | qué pasa |
| --- | --- |
| la transacción con ese monto | se movió la plata; con **2 diarios independientes** que digan de quién es, queda **VERIFICADA** (no hacen falta 4) |
| la transacción, pero otro monto o sin confirmar | **DUDOSA**: la noticia tiene datos mal |
| no existe, o falló | **FALSA** |
| la transacción, sin diarios | **DUDOSA**: la cadena prueba que se movió la plata, **nunca de quién es** |

La hora del bloque cuenta como la fecha del hecho. Necesita `mempool.space` y
`eth.blockscout.com` en la red del entorno. Solo Bitcoin y Ethereum.

### ¿Ya está en el precio? (`--dir`)

Aunque sea NUEVA, el precio puede haberse movido en los primeros minutos.
`--dir -` (noticia mala para la cripto) o `--dir +` (buena), con `--coin`
(BTC por defecto), mide cuánto se movió desde la primera nota contra lo normal
para esas horas (velas de Yahoo de 5 minutos, o de 1 hora si pasaron más de 2
días):

| se movió | veredicto | qué se hace |
| --- | --- | --- |
| 2 veces lo normal o más, a favor de la noticia | **YA ESTÁ EN EL PRECIO** | no persigas el movimiento |
| entre 1 y 2 veces, a favor | **EN PARTE** | con cuidado |
| menos de 1 vez | **TODAVÍA NO SE MOVIÓ** | si es NUEVA, puede faltar la reacción |
| 1 vez o más, en contra | **AL REVÉS** | el mercado no le cree o ya la tenía descontada: no operes a favor de la noticia |

### Fuentes por país

`fuentes.json` tiene los medios confiables de 26 países, con su región. Para
los países donde más se compra cripto (EE.UU., Rusia, Reino Unido, Alemania,
Ucrania, Francia, Pakistán, Vietnam, Brasil, Nigeria, Indonesia, Corea del
Sur, Japón, e India) buscá también en sus diarios: la noticia de un gobierno
sale primero en la prensa local. `verify` muestra las fuentes **agrupadas por
país** y cuántos países y regiones confirman.

Los **medios estatales** (TASS y RIA Novosti en Rusia, Xinhua en China, VNA en
Vietnam, APP en Pakistán, Antara en Indonesia, NAN en Nigeria, Agência Brasil...)
cuentan como la **voz oficial de ese gobierno**, igual que un vocero: sirven
para saber qué dice, pero una noticia nunca queda verificada solo con voces
oficiales. Hacen falta al menos 2 diarios independientes.

Para Vietnam, Indonesia, Corea del Sur y Japón buscá las ediciones en inglés
(VnExpress International, The Jakarta Post, Korea Herald, Yonhap, Nikkei
Asia): tu buscador las encuentra mejor.

En enero de 2024 hackearon la cuenta de la SEC en X, publicaron que aprobaban
los ETF de bitcoin, muchos medios lo repitieron en minutos y el precio saltó y
cayó. Por eso un posteo nunca confirma y una noticia de menos de una hora
nunca queda VERIFICADA.

`fuentes.json` es editable: agregá o sacá medios según tu criterio.

Mostrale al usuario el veredicto, las razones y los links. Nunca inventes
fuentes ni des una noticia por cierta sin pasar por `verify`.

## La red ahora (`chain`)

`chain` muestra el estado de Bitcoin (mempool.space) y Ethereum
(eth.blockscout.com). Va en la revisión del mercado, junto con `calendar` y
`news`:

- **Comisiones** de Bitcoin ahora contra la mediana de los últimos 15
  bloques: **normales**, **altas** (1,5 veces) o **muy altas** (3 veces). Por debajo de 5 sat/vB siempre son
  normales: con bloques casi vacíos (mediana de 0,1) la proporción engaña. Muy
  altas quiere decir mucha gente apurada por mover BTC, como en las caídas
  fuertes (depósitos para vender) o en las subidas con euforia: esperá más
  volatilidad y achicá el tamaño.
- **Transacciones esperando** en el mempool y el ritmo de los bloques.
- **Movimientos de 1.000 BTC o más** en los últimos 6 bloques (`--min-btc`,
  `--blocks`), con su link y la línea `--onchain` lista para `verify`.
- **Ethereum:** gas y uso de la red.

Es contexto, no una señal. **Un movimiento grande no es una venta**: muchas
veces es un exchange ordenando sus billeteras. La blockchain no dice de quién es
una dirección.

## Noticias de The Guardian, New York Times y BBC

`news` lee los **feeds RSS** de The Guardian (sección cripto, economía y
política de EE.UU.), The New York Times (economía, tecnología, política) y la
BBC (economía, tecnología, mundo). Es el formato que publican para que lo lean
programas: no hace falta clave. Solo traen los últimos días.

```bash
python3 "${CLAUDE_SKILL_DIR}/social.py" news                        # cripto y macro/política, 3 días
python3 "${CLAUDE_SKILL_DIR}/social.py" news --query "tariff,china" --days 2
python3 "${CLAUDE_SKILL_DIR}/social.py" news --query "stablecoin" --for-verify
```

Necesita `www.theguardian.com`, `rss.nytimes.com` y `feeds.bbci.co.uk` en la
red del entorno; si no responden, el comando lo dice.

Usalo de dos maneras:
- **Antes de operar:** ¿hay alguna noticia cripto o política de hoy? Si la
  hay y es importante, verificala y miralá en el historial.
- **Para verificar:** `--for-verify` imprime cada nota como una línea
  `--source` lista para `verify`. **Leé cada nota antes de usarla** y cambiá
  `confirma` por `parcial`, `desmiente` o `no_dice` según lo que dice: que un
  título coincida con las palabras buscadas no quiere decir que confirme.
  Son tres de las 5 fuentes; las otras dos salen de tu búsqueda web.

## 2. El historial y los patrones

`study` mide cada evento contra los precios reales: la semana anterior (¿el
mercado se adelantó?), el día del anuncio, 7 y 30 días después, cuántas veces
un día normal se movió (z), y el Nasdaq en esos mismos 7 días (¿era todo el
mercado?). Lo compara con una semana cualquiera de bitcoin desde 2017.

`patterns` muestra los resúmenes por tipo, por lo que se esperaba (buena o
mala noticia), social contra político, y una prueba de si se repite (eventos
hasta 2022 contra 2023 en adelante).

Lo que mostraban los datos al armar la skill (36 eventos, 2017-2026), para
contar con cuidado:

- **Las malas noticias pesan más que las buenas.** Después de una mala,
  bitcoin bajó en 10 de 12 semanas (y 5 de 5 desde 2023); después de una
  buena, subió en solo 10 de 21, menos que una semana cualquiera.
- **"Se compra el rumor, se vende la noticia".** Lo que se esperaba hacía
  meses (ETF, decretos, salidas a bolsa) sube antes y baja después.
- **Las sorpresas positivas sí empujan** (Xi Jinping 2019, Tesla 2021, la
  elección de Trump 2024).
- **Las prohibiciones dan caídas que en un mes se recuperan.**
- **Los colapsos** (Terra, FTX) son las caídas más largas.
- **Los aranceles** mueven todo el mercado, no solo cripto.
- **Si la noticia nombra una cripto**, esa se mueve mucho más que bitcoin
  (XRP +73 % el día del fallo contra la SEC).

Volvé a correr `patterns` antes de citar números: cambian cuando se agregan
eventos. Siempre aclarale al usuario que son pocos casos, elegidos por
personas, y que pasar al mismo tiempo no prueba que una cosa cause la otra.

## 3. El calendario

`calendar` lista lo que se viene (datos de inflación, decisiones de la Fed,
votaciones, fallos, elecciones, cambios de gobierno) y, si hay casos parecidos
en el historial, cuánto se movió el precio en ellos. Mantené `calendar.json`
al día: buscá las fechas en las fuentes oficiales (bls.gov,
federalreserve.gov, el congreso o el regulador de cada país) y cargá la
fuente. Antes de un evento grande, sugerí achicar el tamaño o ensanchar el
stop con `/scalp-risk`.

## 4. Agregar eventos

`add-event` suma un evento al historial. Pide su fuente: `--verification ID`
de una verificación VERIFICADA, o `--src`. Una verificación DUDOSA o FALSA no
entra. La fecha es la del **primer anuncio público creíble** (UTC), no la de
la firma ni la de la entrada en vigencia: si hubo varias, cargá cada una como
un evento.

Tipos que ya usa el historial: `prohibicion`, `regulacion_favorable`,
`regulacion_hostil`, `adopcion_estado`, `apoyo_gobierno`, `marcha_atras`,
`fallo_judicial`, `elecciones`, `promesa_campana`, `aranceles`,
`adopcion_empresas`, `figura_publica`, `uso_cotidiano`, `colapso_escandalo`.

## Países que más pesan

Por peso en cripto, no por poder político: EE.UU. (Casa Blanca, SEC, CFTC,
Fed, Tesoro, Congreso), China y Hong Kong, Unión Europea, Reino Unido, Japón,
Corea del Sur (mucho volumen minorista), Singapur, Emiratos, Rusia, India, y
por adopción Argentina, Turquía, Nigeria y El Salvador.

Esto es información para decidir con más contexto, no un consejo de inversión.
