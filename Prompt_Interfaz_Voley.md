# Prompt reutilizable — Interfaz web v2

> Copia todo lo que sigue y pégalo en una sesión abierta dentro de esta carpeta
> (`EstadisticasVoley`). El agente tiene que poder leer los archivos del proyecto.

---

Quiero una versión mejorada de la interfaz web de este proyecto. Antes de escribir
nada, lee `servidor_voley.py`, `sesion_web.py`, `interfaz.html`, la cabecera de
`analisis_voley.py`, `generar_informe_volley.py` y `valores_excel.py`, y mirá un
`.txt` de `Datos/` completo para entender el formato del volcado.

## Qué existe hoy

- `analisis_voley.py` — el motor. Parsea las jugadas, lleva marcador, rotación,
  cambios y calcula todas las estadísticas. Guarda el volcado en
  `Datos/partido_AAAAMMDD_HHMMSS.txt` con `guardar_reporte_txt`.
- `sesion_web.py` — `SesionPartido`. Guarda la lista de líneas tipeadas y en cada
  línea nueva **vuelve a correr el motor entero**. Por eso deshacer sale gratis y la
  web no puede divergir de la consola. `instantanea()` devuelve todo lo que la
  pantalla necesita.
- `servidor_voley.py` — servidor de la biblioteca estándar, escucha en `0.0.0.0`
  para entrar desde el celular. Una sola sesión global protegida por un lock.
  Endpoints actuales: `GET /`, `GET /api/estado`, `GET /api/estadisticas`,
  `POST /api/enviar|deshacer|reiniciar|cargar|guardar|excel`.
- `generar_informe_volley.py` — `parse_volcado(texto)` lee un `.txt` de `Datos/` y
  devuelve el diccionario con todo abierto por equipo; `build_workbook` arma el
  `.xlsx` de `Informes/Informe_<Equipo>_vs_<Rival>_<fecha>.xlsx`.
- `valores_excel.py` — `convertir_a_valores(libro)` evalúa las fórmulas que escribe
  el informe (SUM, SUMIF, SUMIFS, IFERROR, SUMPRODUCT y aritmética entre celdas).
- `interfaz.html` — una sola página, sin dependencias: marcador, turno, campo de
  carga, atajos, últimos puntos, rotación en cancha, ayuda de sintaxis,
  estadísticas en texto, pegar un partido entero y cambios registrados.

Estructura del volcado `.txt` (secciones, en este orden): `=== Jugadas cargadas ===`,
`=== Rotaciones ... ===`, `=== Cambios ===`, `=== Resultado final ===`,
`=== Estadisticas por equipo ===` con un bloque `--- <Equipo> ---` por lado.

## Regla principal

**Lo que ya funciona no se toca.** Cargar un partido en vivo es la pantalla crítica:
se usa con una mano, desde el celular, al costado de la cancha, mientras se juega.
Toda la funcionalidad de carga actual tiene que quedar igual de rápida y con los
mismos atajos. Lo nuevo se agrega alrededor, nunca en el camino de la carga.

## Lo que quiero agregar

Tres pestañas en la misma página: **Cargar**, **Partidos**, **Jugadores**.

- La pestaña activa arranca siempre en **Cargar**.
- La pestaña se refleja en el hash (`#cargar`, `#partidos`, `#jugadores`) para poder
  recargar sin perderla.
- El foco automático del campo de carga y los atajos de teclado solo actúan cuando
  la pestaña **Cargar** está visible.
- Si hay un partido en curso (líneas cargadas), la pestaña **Cargar** lleva un punto
  o contador que lo indique, para que se vea que hay algo sin guardar aunque estés
  mirando otra pestaña.

### Pestaña 1 — Cargar

Es la pantalla actual, reordenada pero con todo su contenido: marcador, turno con el
sacador destacado, campo de carga, mensaje de respuesta del motor, atajos
(`f`, `x`, `w`, cambio, borrar última línea, guardar `.txt`, Excel, reiniciar),
últimos puntos, rotación en cancha, ayuda de sintaxis, estadísticas en texto, pegar
un partido ya escrito y cambios registrados.

Mejoras admitidas acá, y solo estas:

- Que el bloque de ayuda de sintaxis se pueda abrir sin perder lo escrito en el campo.
- Que el botón de Excel deje elegir el equipo con un selector de A / B en vez de un
  `prompt()` donde hay que escribir el nombre a mano.
- Que después de generar el Excel aparezca un enlace directo para abrirlo o
  descargarlo, en vez de solo la ruta en texto.

### Pestaña 2 — Partidos (buscar y abrir)

Lista todos los partidos del proyecto, cruzando dos fuentes:

- los volcados de `Datos/*.txt`,
- los informes de `Informes/*.xlsx`.

Un partido es una fila con: **fecha**, **equipo**, **rival**, **sets** (2-0, 3-1…),
**parciales**, **puntos cargados**, y dos indicadores de qué archivos tiene (volcado
`.txt` sí/no, informe `.xlsx` sí/no). Ordenada por fecha, la más nueva arriba.

**Buscador**: un campo de texto que filtra por nombre de equipo, rival o fecha
mientras se escribe (sin apretar Enter, filtrado en el cliente sobre la lista ya
traída). Además, filtros rápidos: por equipo (desplegable armado con los equipos que
aparecen), por rango de fechas y un interruptor "solo los que tienen informe". Si no
hay resultados, un mensaje que diga qué se buscó, no una tabla vacía.

**Al abrir un partido** (clic en la fila) se ve, dentro de la misma pestaña:

- Cabecera con equipos, fecha, sets y parciales por set.
- Resultado final y total de puntos cargados.
- Rotaciones por set y cambios registrados.
- Las estadísticas del volcado renderizadas como **tablas**, no como el texto plano
  que devuelve `formatear_estadisticas`: puntos por fase (K1, K2, K3, Saque, Sin
  fase) con hechos y recibidos, puntos por causa, armado por zona, recepción por
  jugador y ataque por jugador. Un selector para ver el bloque de mi equipo o el del
  rival.
- Botones: **Abrir el Excel**, **Descargar el .txt**, **Cargar en la pestaña Cargar**
  (que pega el volcado en la sesión usando el `/api/cargar` que ya existe, pidiendo
  confirmación si hay un partido en curso).

**Abrir el Excel ya resumido**: si el partido tiene informe, se muestra el contenido
del `.xlsx` dentro de la web — un selector de hoja (`Partido`, `Fases y armador`,
`Recepción`, `Armado`, `Ataque jugador`, `Zona y dirección`, `Datos_Base`) y la hoja
elegida como tabla HTML, con los porcentajes ya formateados y las filas TOTAL
resaltadas. Además un botón para **descargar** el archivo y otro para **abrirlo en
Excel** en la máquina donde corre el servidor (que no aparezca, o aparezca
deshabilitado, cuando se está entrando desde el celular).

### Pestaña 3 — Jugadores (mock-up)

Esta pestaña **queda maquetada, no conectada**. Quiero ver cómo va a ser y poder
decidir sobre el diseño antes de que se calcule nada de verdad.

- Un aviso arriba, visible pero discreto: los números son de ejemplo.
- Selector de jugador (los dorsales), y arriba del todo una ficha con el dorsal, si
  es armador, partidos y sets jugados.
- Fila de indicadores grandes: recepciones, % positiva (calidad 2+3), % perfecta
  (calidad 3), ataques, % punto, bloqueos punto.
- Tabla de **recepción**: total, reparto por calidad 3/2/1/0 y pase al otro lado, con
  porcentajes, y la misma tabla abierta por set.
- Tabla de **ataque**: totales, punto, defendido, fuera con porcentajes; abierta por
  zona de origen; y una matriz zona de origen × dirección (1, 5, 6).
- Si el jugador es armador: armados totales, reparto por zona y la matriz calidad de
  recepción × zona armada.
- Un gráfico simple de evolución por set (por ejemplo % positiva de recepción y %
  punto de ataque), dibujado **a mano en SVG**, sin librerías.
- Una comparación del jugador contra el promedio del equipo en las mismas métricas.

Requisitos del mock-up:

- Los datos de ejemplo van en **una sola constante** de JavaScript
  (`JUGADORES_DEMO`), arriba y bien señalada, con **exactamente la forma** que
  tendría la respuesta de un futuro `GET /api/jugador?dorsal=13`. Conectarlo después
  tiene que ser cambiar la constante por un `fetch`, sin tocar el renderizado.
- Marcá en el propio mock-up, con una nota al pie, qué métricas **ya se pueden
  calcular** con lo que hay en el volcado (recepción por jugador y por set, ataque
  por jugador con zona y dirección, bloqueos punto, armado por armador y por calidad
  de recepción) y cuáles **todavía no existen** y harían falta cambios en el motor:
  saque por jugador (ases y errores propios), ataque abierto por set, y el acumulado
  entre varios partidos. No inventes que están.

## Endpoints nuevos

Agregalos a `servidor_voley.py`, todos de **solo lectura** y sin tocar la sesión en
curso:

- `GET /api/partidos` → lista de partidos. Para armarla **no** parsees el volcado
  entero: alcanza con la cabecera y la sección `=== Resultado final ===`. Cacheá por
  `(ruta, mtime)` para no releer el disco en cada tecla del buscador.
- `GET /api/partido?archivo=<nombre>` → el partido completo, ya parseado con
  `generar_informe_volley.parse_volcado`, en JSON.
- `GET /api/informe?archivo=<nombre>` → el `.xlsx` como JSON: una entrada por hoja,
  con filas, valores ya calculados y una marca de qué filas son TOTAL o encabezado.
- `GET /api/descargar?archivo=<nombre>&tipo=txt|xlsx` → devuelve el archivo con su
  `Content-Type` y `Content-Disposition` para descargarlo.
- `POST /api/abrir` → abre el archivo con la aplicación del sistema (`os.startfile`
  en Windows) en la máquina del servidor. Solo para `Informes/` y `Datos/`.

## Detalles que se pasan por alto

Estos son los que más veces se hacen mal; resolvelos explícitamente:

1. **El informe está lleno de fórmulas y openpyxl no guarda el resultado.** Si abrís
   el `.xlsx` con `data_only=True` y nunca lo abrió Excel, las celdas vienen en
   `None` y la tabla se ve vacía. Ese problema ya está resuelto en
   `valores_excel.py`: intentá primero con `data_only=True` y, si los valores son
   `None`, abrí el libro normal y pasalo por `convertir_a_valores`. **No
   reimplementes un evaluador nuevo.** Si aun así queda una fórmula sin evaluar,
   mostrá la fórmula, no un cero inventado.
2. **Recorrido de rutas.** El servidor escucha en toda la red. Todo endpoint que
   reciba un nombre de archivo tiene que resolverlo con `Path(...).resolve()` y
   verificar que quede **dentro** de `CARPETA_DATOS` o `CARPETA_INFORMES`; cualquier
   otra cosa se responde 400 sin abrir nada. Nada de concatenar rutas a mano.
3. **Archivos temporales de Excel.** Los `~$Informe_*.xlsx` que deja Excel abierto no
   son informes: filtralos del listado.
4. **El `.xlsx` abierto en Excel.** Leerlo o abrirlo puede tirar `PermissionError`;
   respondé con el mismo mensaje claro que ya usa `/api/excel`.
5. **`openpyxl` es opcional.** Listar partidos y ver un volcado `.txt` tienen que
   funcionar sin tenerlo instalado; solo la vista del `.xlsx` puede pedirlo, con el
   mensaje "falta openpyxl: pip install openpyxl" y sin romper la página.
6. **La sesión es una sola y global.** Navegar por Partidos o Jugadores no puede
   modificar `sesion` ni quedarse con el lock: son lecturas de disco, no toques el
   candado más de lo necesario.
7. **Nombres con caracteres raros.** Hay informes como
   `Informe_Palestino_vs_O'sommer_2026-09-08.xlsx`: cuidá el escapado en las URL y en
   el HTML que se genera desde JavaScript.
8. **Puede no haber internet en la cancha.** Cero CDN, cero fuentes remotas, cero
   librerías de gráficos: todo dibujado a mano.

## Restricciones técnicas

- Python: **solo biblioteca estándar**, más `openpyxl` donde ya se usa hoy.
- Front: **una sola página, sin build, sin dependencias, JavaScript a secas**. Si el
  archivo se vuelve inmanejable, se puede partir en `interfaz.html` + `interfaz.css`
  + `interfaz.js` servidos por el mismo servidor, pero con una lista blanca explícita
  de archivos servibles, nunca sirviendo la carpeta entera.
- Se mantienen la paleta oscura y las variables CSS que ya están; las pestañas nuevas
  tienen que parecer parte de la misma aplicación, no un injerto.
- Tiene que verse bien en celular en vertical: es donde más se usa. Las tablas anchas
  se desplazan solas en horizontal, la página nunca.
- Textos de la interfaz **sin tildes**, como está hoy (`Estadisticas`, `Rotacion`,
  `Ultimos puntos`).
- Comentarios en el código con el estilo del proyecto: en castellano, explicando **por
  qué** algo está hecho así, no qué hace la línea de al lado.
- Los endpoints nuevos que tengan lógica de verdad (armar el listado, leer el `.xlsx`)
  van en funciones puras y probables, no dentro del `Manejador`.

## Entregables

1. `interfaz.html` (o el trío html/css/js) con las tres pestañas.
2. `servidor_voley.py` con los endpoints nuevos.
3. El módulo nuevo que haga falta para listar y leer archivos —por ejemplo
   `archivo_partidos.py`—, con su docstring explicando de qué se ocupa.
4. Tests para las funciones nuevas, en el estilo de `test_analisis_voley.py`
   (`python -m unittest`, sin librerías extra): listado de partidos desde una carpeta
   de prueba, filtrado de temporales, rechazo de rutas fuera de la carpeta y lectura
   de un `.xlsx` con fórmulas sin valores cacheados.

## Criterios de aceptación

- Cargar un partido entero desde el celular funciona exactamente como antes.
- El buscador filtra mientras se escribe sobre los volcados e informes que ya hay en
  la carpeta, sin recargar la página.
- Abrir `Informes/Informe_Palestino_vs_UVC_2026-09-08.xlsx` desde la web muestra las
  seis hojas **con números**, no celdas vacías ni fórmulas en crudo, aunque ese
  archivo nunca se haya abierto en Excel.
- Pedir `/api/descargar?archivo=../../algo` responde 400 y no lee nada.
- La pestaña Jugadores se ve completa y navegable con los datos de ejemplo, y queda
  claro en la propia pantalla que son de ejemplo.
- Con `openpyxl` desinstalado, la aplicación arranca y las pestañas Cargar y Partidos
  siguen funcionando.
- `python -m unittest` pasa entero.

## Qué NO hacer

- No reescribir `analisis_voley.py` ni `sesion_web.py`: la interfaz es una vista.
- No agregar frameworks, bundlers, TypeScript ni npm.
- No guardar estado del partido en `localStorage`: la fuente de verdad es el servidor.
- No inventar métricas ni juicios de valor (ni semáforos, ni "rendimiento bajo", ni
  recomendaciones). Como en el informe de Excel: solo datos, totales y porcentajes.
- No conectar la pestaña Jugadores a datos reales en esta entrega: quiero decidir el
  diseño primero.

Cuando termines, decime qué quedó implementado de verdad, qué quedó como mock-up y
qué haría falta agregarle al motor para conectar la pestaña Jugadores.
