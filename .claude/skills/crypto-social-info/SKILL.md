---
name: crypto-social-info
description: >-
  Información social y política para cripto: qué hicieron los gobiernos, los
  reguladores, las empresas y las figuras públicas de los países que más pesan
  en cripto (prohibiciones, adopción, reservas, leyes, ETF, elecciones,
  aranceles, colapsos, escándalos) y cómo se movió el precio antes y después.
  Verifica noticias dudosas con 5 fuentes independientes, arma el calendario
  de eventos que vienen y mide los patrones con precios reales. Usala cuando
  el usuario pregunte por una noticia política o social de cripto, "¿esto es
  verdad?", "¿cómo afecta esto al precio?", "qué pasó cuando China prohibió",
  "qué se viene esta semana", o antes de operar en un día con noticias.
argument-hint: "[study | patterns | calendar | verify --claim ... | add-event]"
---

# crypto-social-info

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
    --source "CNBC|https://...|confirma" --source "Reuters|https://...|confirma" ...
python3 "${CLAUDE_SKILL_DIR}/social.py" verify --list
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
   **desmiente** o **no_dice**.
5. Anotá cuándo apareció la noticia por primera vez (`--first-seen`, UTC).
6. Corré `verify`. El veredicto lo calcula el script, siempre con la misma regla:

| veredicto | cuándo | qué se hace |
| --- | --- | --- |
| **VERIFICADA** | un documento oficial la confirma, o 4 de 5 fuentes confiables confirman los mismos datos, sin desmentido | se puede usar para operar y entra al historial |
| **DUDOSA** | 3 de 5, datos que no coinciden, una fuente confiable la desmiente, o salió hace menos de 1 hora | no se opera por esa noticia; con posiciones abiertas, achicar y volver a revisar en 1 hora |
| **FALSA** | desmentido oficial, o 2 de 5 o menos | se descarta y queda anotada |

En enero de 2024 hackearon la cuenta de la SEC en X, publicaron que aprobaban
los ETF de bitcoin, muchos medios lo repitieron en minutos y el precio saltó y
cayó. Por eso un posteo nunca confirma y una noticia de menos de una hora
nunca queda VERIFICADA.

`fuentes.json` es editable: agregá o sacá medios según tu criterio.

Mostrale al usuario el veredicto, las razones y los links. Nunca inventes
fuentes ni des una noticia por cierta sin pasar por `verify`.

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
stop con `/crypto-risk`.

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
