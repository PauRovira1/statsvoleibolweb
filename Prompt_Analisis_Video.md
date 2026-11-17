# Prompt reutilizable — Análisis de video: armadas v1

> Copiá todo lo que sigue y pegalo en una sesión abierta dentro de esta carpeta
> (`statsvoleibolweb`), en la rama `analisis-video`. Decile al agente **qué etapa
> hacer** ("hacé la etapa 1"). Es una etapa por sesión: cada una termina en algo
> que se puede probar.

---

Quiero un sistema que mire el **video de un partido** de mi equipo de vóley y me
deje **todas las armadas** encontradas, recortadas y filtrables, para analizarlas
después. Es información extra: **no tiene nada que ver con las estadísticas** que
se cargan tocando. No lee ni escribe los `.txt` de `Datos/`, no toca el motor ni
el informe.

Antes de escribir una línea de código, leé:

- este documento entero, incluidas las etapas que no te toca hacer;
- la cabecera de `servidor_voley.py` (cómo está escrito y comentado este
  proyecto, y por qué la carpeta del proyecto nunca se sirve entera);
- `public/interfaz.css`, el comienzo (los temas claro/oscuro y las variables de
  color: las pantallas nuevas usan las mismas);
- `.vercelignore`, `.gitignore`, `vercel.json` y la lista `MODULOS` de
  `empaquetar_lambda.py` (qué viaja al sitio alojado);
- un test cualquiera, por ejemplo `test_sesion_por_pantalla.py`, para ver cómo se
  prueba acá.

## Lo que ya está decidido (no reabrir)

| Tema | Decisión |
|---|---|
| Para qué | Clips de cada armada + datos del pase, como material de análisis aparte de las stats |
| Vínculo con el partido cargado | **Ninguno.** El video se analiza solo |
| Cuánto hace solo | **Propone y yo corrijo**: nada cuenta como armada hasta que lo acepto |
| Cámara | Fija, atrás de la línea de fondo, en altura, normalmente **en una esquina** (perspectiva oblicua) |
| Dónde corre | En mi PC, después del partido. No en Vercel ni en Lambda |

## Qué es esto y qué no

**Es:** una herramienta local nueva, en su propia carpeta, con sus propias
dependencias y su propio servidor.

**No es:** una pestaña más del sitio alojado (eso queda para una etapa futura),
ni un reemplazo de la carga tocando, ni un sistema que identifique jugadores por
el número de la camiseta. Quién armó se anota a mano en la revisión, y es
opcional.

## Las reglas que no se negocian

**1. La app actual no se entera.** `servidor_voley.py`, `api/`, `lambda_handler.py`
y todo lo que ellos importan no importan nada de `video/`. `requirements.txt` no
cambia. El paquete de Vercel y el zip de Lambda no crecen ni un byte:
`vercel.json` incluye `**`, así que **hay que agregar `video/`, `Videos/` y
`requirements-video.txt` a `.vercelignore`** (el zip de Lambda usa una lista
explícita: ahí alcanza con no agregar nada).

**2. `python -m unittest discover -p "test_*.py"` sigue en verde en una máquina
que solo tiene `requirements.txt`.** Los tests de video que necesitan `numpy`,
`cv2` u `onnxruntime` se saltean solos (`skipUnless`) si no están.

**3. Ni videos ni modelos entran al repo.** Un partido pesa gigas y GitHub corta
en 100 MB. `Videos/` y `video/modelos/*.onnx` van a `.gitignore`. Los modelos se
bajan con un comando que verifica el hash.

**4. Lo que decide una persona no se pisa nunca.** Lo que propone la máquina y lo
que yo corregí viven en archivos distintos. Volver a procesar un video (con otro
modelo, con otros umbrales) regenera las propuestas y **conserva** cada
aceptación, descarte y corrección que ya hice.

**5. Lo lento se hace una sola vez.** Detectar la pelota cuadro por cuadro lleva
más de una hora por partido en esta máquina. Ese resultado se guarda en disco y
todo lo que viene después (trayectorias, eventos, propuestas) se puede volver a
correr en segundos sin tocar el video. El proceso largo se puede cortar y
retomar donde quedó.

**6. La lógica no depende del video.** Geometría, trayectorias y eventos trabajan
sobre listas de números y se prueban con datos sintéticos (una parábola
proyectada por una cámara inventada, con ruido, huecos y falsos positivos). Solo
`lectura.py`, `pelota.py` y `clips.py` tocan `cv2` o el modelo.

**7. Estilo de la casa.** Nombres en español y sin acentos en el código,
comentarios que explican *por qué*, JavaScript sin frameworks ni CDNs, `unittest`.

## Con qué se cuenta

**La máquina** (medido el 2026-11-16): Ryzen 5 5500U (6 núcleos / 12 hilos),
**7,4 GB de RAM**, gráfica integrada (sin NVIDIA), 233 GB libres, Windows 11,
Python 3.12. Instalado: `numpy` 2.5 y `opencv` (`cv2`) 5.0. **No** instalado:
`ffmpeg`, `onnxruntime`, `torch`, `av`.

Consecuencias:

- Inferencia en CPU con un modelo chico en ONNX. Nada de PyTorch: pesa gigas y no
  hace falta para inferir.
- Con 7,4 GB el video se procesa **en flujo**, cuadro a cuadro. Nunca se carga un
  tramo largo en memoria.
- Para recortar clips que el navegador pueda reproducir hace falta H.264, y el
  `cv2` de Windows no lo escribe (el `mp4v` que sí escribe no se ve en Chrome).
  Se usa el binario de `imageio-ffmpeg` (trae su propio `ffmpeg`, se instala con
  pip).

**La toma.** Cámara quieta, atrás y en una esquina. Consecuencias:

- La cancha se calibra **una vez por video** marcando puntos conocidos. La
  perspectiva oblicua no es un problema: es exactamente lo que la calibración
  resuelve.
- En la mitad lejana la pelota mide pocos píxeles. Ahí va a fallar más la
  detección; hay que medirlo por separado (cerca / lejos).
- Los equipos **cambian de lado** en cada set (y a los 8 puntos del quinto). "Mi
  equipo" es un lado *por tramo de video*, y lo marco yo.
- La cámara se puede mover por un golpe al trípode. Hay que detectarlo y avisar.
- Las armadas altas pueden **salir del cuadro por arriba**. El seguimiento tiene
  que aguantar que la pelota desaparezca y vuelva a entrar.
- En el gimnasio hay otras pelotas (el banco, la cancha de al lado).

**Modelos de pelota ya entrenados** (visto el 2026-11-16; **verificá licencia,
archivos y formato de entrada en la página antes de usarlos**):

- [asigatchov/fast-volleyball-tracking-inference](https://github.com/asigatchov/fast-volleyball-tracking-inference):
  modelos ONNX específicos de vóley (familia VballNet, derivados de TrackNet),
  entrada de 9 cuadros en gris, salida en mapa de calor. El README dice licencia
  MIT también para los pesos y ~100 FPS de punta a punta en una CPU de
  escritorio; trae además lógica de rallies y de toques que conviene leer.
  Sus números de precisión (F1 0,80–0,90) son sobre vóley de playa: **no dicen
  nada de mis videos**.
- [asigatchov/vball-net](https://github.com/asigatchov/vball-net): el
  entrenamiento de esos modelos y su herramienta de etiquetado, por si hay que
  afinar con mis videos.
- [nttcom/WASB-SBDT](https://github.com/nttcom/WASB-SBDT): línea de base
  académica con vóley entre sus deportes. Alternativa si lo anterior no rinde.
- Evitá `ultralytics` (YOLO) salvo que yo lo apruebe: es AGPL y este repo es
  público.

## Qué quiero poder hacer

1. Tirar un video en una carpeta y correr un comando.
2. Abrir una pantalla, marcar la cancha una vez y decir de qué lado está mi
   equipo en cada set.
3. Dejarlo procesando (de noche si hace falta).
4. Revisar las armadas propuestas: cada una se reproduce sola en bucle, con la
   trayectoria dibujada encima; acepto, descarto o corrijo con una tecla. Si se
   le escapó una, la marco yo sobre el video.
5. Abrir una galería con las aceptadas, filtrar (zona de destino, rápida/alta,
   armador, set, etiqueta) y verlas una atrás de otra.
6. Exportar los clips filtrados a archivos `.mp4` para compartir.

## Cómo se organiza

```
video/                      el paquete; nada de afuera lo importa
  __main__.py               la consola:  python -m video <orden>
  proyecto.py               carpeta de trabajo de cada video, esquemas, versionado
  lectura.py                metadatos y proxy (ffmpeg); cuadros con su tiempo (cv2, etapa 2)
  calibracion.py            de puntos marcados a camara                     (puro)
  geometria.py              proyectar, rayos, planos, ajuste balistico      (puro)
  pelota.py                 detector de pelota: interfaz + implementaciones (cv2/onnx)
  trayectorias.py           de candidatos sueltos a arcos                   (puro)
  eventos.py                toques, rallies, posesiones, armadas            (puro)
  fusion.py                 propuestas + decisiones mias = armadas          (puro)
  decisiones.py             operaciones de las pantallas -> revision.json   (puro)
  clips.py                  recorte a mp4                                   (ffmpeg)
  servidor_video.py         servidor local de las pantallas (y el deshacer)
  web/                      inicio, revision y galeria (.html + .js), comun.js, video.css
  modelos/                  pesos .onnx (ignorados) + LEEME con origen y hash
requirements-video.txt
test_video_*.py             en la raiz, como el resto de los tests
Videos/                     ignorada por git
  <nombre>/                 minusculas y guiones; el titulo con acentos va en fuente.json
    fuente.json             ruta del original, duracion, fps, hash parcial
    proxy.mp4               copia liviana para el navegador (ver "Lectura")
    calibracion.json        puntos marcados y camara por tramo     (etapa 3)
    pelota.csv              la deteccion cruda, cuadro por cuadro  (lo lento)
    propuestas.json         lo que propone la maquina              (se regenera)
    revision.json           lo que decidi yo: armadas y sets       (nunca se pisa)
    revision.anterior.json  la revision de antes del ultimo guardado
    clips/                  mp4 exportados
```

Los sets (desde cuándo y de qué lado de la red está mi equipo) quedaron en
`revision.json` y no en `calibracion.json`: los marca la persona igual que las
armadas, desde la etapa 1, y se deshacen con el mismo `Z`. La etapa 3 los lee
de ahí.

Órdenes de la consola: `nuevo <video>`, `procesar <nombre>` (detecta lo que falte
y regenera propuestas), `proponer <nombre>` (solo regenera propuestas desde
`pelota.csv`), `servir`, `exportar <nombre>`, `modelos` (baja y verifica),
`medir <nombre>` (compara propuestas contra lo revisado: ver "Cómo se mide").

### Los datos

Todos los tiempos son **segundos del video original**, con decimales. Nunca
números de cuadro: los celulares graban a ritmo variable y `cuadro / fps` se
corre varios segundos a lo largo de un partido.

`pelota.csv` — una fila por candidato, varias por cuadro si hay duda:
`t, x, y, puntaje, detector`. `x`, `y` en fracción del ancho y del alto (0 a 1),
así no dependen de a qué resolución se procesó.

`propuestas.json` — lo que sale de `eventos.py`:

```
{
  "version": 1,
  "generado": {"detector": "...", "parametros": {...}, "fecha": "..."},
  "rallies": [{"id": "r012", "t_inicio": 1820.4, "t_fin": 1839.9}],
  "armadas": [{
    "id": "p0042",
    "rally": "r012",
    "t_armado": 1834.27,          // el toque del armador
    "t_ataque": 1835.31,          // el toque siguiente; null si no se vio
    "t_toque_previo": 1832.90,    // recepcion o defensa; null si no se vio
    "lado": "cerca",              // "cerca" | "lejos" respecto de la camara
    "tipo": "armada",             // "armada" | "segunda" (paso la red en el 2do toque)
    "zona_destino": 4,            // 1 a 6, como en la carga; null si no se pudo
    "tiempo_vuelo": 1.04,         // t_ataque - t_armado
    "trayectoria": [[t, x, y], ...],
    "medidas": null,              // etapa 7
    "confianza": 0.83,
    "motivos": ["arco limpio", "lado dudoso"]
  }]
}
```

`revision.json` — lo que decidí yo. Cada entrada apunta a una propuesta **por
tiempo, no por id** (los ids cambian al regenerar): se considera la misma armada
si el armado difiere en menos de 0,5 s del tiempo que tenía al decidirla **o**
del corregido, y no están de lados distintos de la red (un lado desconocido no
descarta). Las parejas son de a una, empezando por las más cercanas.

```
{
  "version": 1,
  "edicion": 12,                  // sube con cada guardado: una pestaña vieja no pisa
  "sets": [{"desde": 0.0, "set": 1, "lado": "cerca"}],   // de ahí en adelante, mi equipo
  "decisiones": [{
    "id": "d7",
    "t_armado": 1834.27,          // el tiempo que tenía al decidirla (no cambia)
    "lado": "cerca",              // null en una marca a mano: es el de mi equipo en ese set
    "estado": "aceptada",         // "aceptada" | "descartada"
    "origen": "auto",             // "auto" | "manual" (la marqué yo, no había propuesta)
    "propuesta": {"t_armado": 1834.27, "t_ataque": 1835.31, "zona_destino": 4, ...},
                                  // lo que propuso la máquina y vi al decidir; null si es manual
    "cambios": {"zona_destino": 3, "t_inicio": 1831.0},   // solo lo que corregí
    "armador": 3, "etiquetas": ["pipe"], "nota": ""
  }]
}
```

`fusion.py` junta las dos cosas y es lo que leen la revisión, la galería y la
exportación. Una propuesta sin decisión queda "pendiente". Una decisión manual
sin propuesta sigue existiendo. Cuando se juntan, manda la persona: lo que
acepté (la copia en `propuesta`) y lo que corregí tapan a la propuesta nueva,
que solo completa lo que yo no dije (la trayectoria, una zona que no marqué).
Una decisión cuya propuesta desapareció al regenerar **se conserva igual** con
los datos de esa copia.

Las pantallas no escriben decisiones: mandan operaciones (`marcar`, `aceptar`,
`descartar`, `cambiar`, `set`, `quitar_set`, `deshacer`) y `decisiones.py` las
arma y valida. Deshacer es una pila en memoria del servidor: cerrar el servidor
la vacía, lo guardado queda.

El recorte de cada clip va, por defecto, desde 1 s antes del toque previo hasta
2 s después del ataque (así se ve de qué recepción salió y cómo terminó), y se
puede ajustar a mano.

## Cómo funciona cada pieza (y dónde se rompe)

### Lectura

- El tiempo de cada cuadro sale del propio video (`CAP_PROP_POS_MSEC`), nunca de
  contar cuadros.
- Los videos de celular traen la rotación como metadato: comprobá que el cuadro
  sale derecho.
- Probá una ruta con espacios y acentos (`Videos/Palestino vs Español/…`): en
  Windows `cv2` ha fallado con rutas que no son ASCII.
- **Proxy.** Al dar de alta un video se genera una copia H.264 720p con un cuadro
  clave por segundo. Es lo que reproducen las pantallas: el original puede venir
  en HEVC (no todos los navegadores lo abren) y saltar dentro de un archivo de
  4 GB con pocos cuadros clave es lento. La detección corre sobre el **original**.
- La revisión y la galería **no necesitan clips recortados**: reproducen el proxy
  entre `t_inicio` y `t_fin`. Los `.mp4` sueltos son solo para exportar.

### Calibración

Sistema de coordenadas de la cancha, en metros: origen en el piso, debajo del
centro de la red; `x` a lo largo de la red (−4,5 a 4,5), `y` a lo largo de la
cancha (−9 a 9; negativo = mitad cercana a la cámara), `z` hacia arriba.

En la pantalla se marcan sobre un cuadro quieto los puntos que se vean de esta
lista (mínimo 6, con al menos 2 que no estén en el piso):

- las 4 esquinas de la cancha y los 2 cruces de la línea central con los
  laterales (`z = 0`);
- los 4 extremos de las líneas de ataque (`y = ±3`, `z = 0`);
- el borde superior de la red en cada antena (`z` = altura de la red,
  configurable: **2,43 m** varones, 2,24 m mujeres) y la punta de cada antena
  (80 cm más arriba).

De ahí sale la matriz de proyección de la cámara. Se puede hacer con `numpy`
solo (DLT normalizado y un refinamiento); no agregues `scipy` para esto.

"Propone y corrijo" también vale acá: después de marcar, la pantalla **dibuja la
cancha, la red y las antenas encima del cuadro** con la cámara calculada. Si el
dibujo calza con la imagen, está bien; si no, se arrastra un punto y se
recalcula. Mostrá además el error de reproyección en píxeles y rechazá cámaras
absurdas (adentro de la cancha, bajo el piso).

**Cámara movida:** guardá un recorte chico alrededor de cada punto marcado y
comparalo cada tantos segundos de video. Si se corrió, el procesamiento lo anota
con el tiempo y la revisión pide recalibrar desde ahí (la calibración es una
lista de tramos `{desde, hasta, camara}`, como los sets de `revision.json`).

### Detección de la pelota

Una interfaz, varias implementaciones, todas devuelven candidatos `(t, x, y,
puntaje)`:

1. **Modelo ONNX de vóley** con `onnxruntime` en CPU. Es la apuesta principal.
2. **Movimiento**: con cámara fija, restar el fondo y quedarse con manchas del
   tamaño y la forma de una pelota es barato y funciona justo donde más importa
   (la pelota en el aire, contra la pared). Sirve de respaldo y de segunda
   opinión.

Cuál se usa, a qué resolución y con qué umbral **lo decide la etapa 2 midiendo
sobre mis videos**, no este documento.

Para no quemar una hora de más: los tramos sin movimiento en la cancha (tiempos
muertos, entretiempos) se saltean con una prueba barata antes de pasar el
modelo. Guardá los candidatos con puntaje bajo también: el filtro de después
decide mejor que un umbral fijo.

### Trayectorias

- **Sacar lo que no se mueve.** Un candidato que aparece en el mismo lugar durante
  segundos es una lámpara, un logo o una cabeza.
- **Arcos.** Entre toque y toque la pelota está en caída libre. En la imagen, un
  tramo corto se ajusta bien con `x(t)` lineal e `y(t)` cuadrática. Se buscan
  arcos con RANSAC sobre los candidatos y se elige el conjunto de arcos que mejor
  explica el tramo sin superponerse.
- **Gravedad plausible.** La calibración dice cuántos píxeles/s² puede valer la
  gravedad en el punto más lejano y en el más cercano de la cancha. Un "arco" que
  cae más despacio o más rápido que eso no es la pelota del partido. Este filtro
  es lo que saca a la pelota de la cancha de al lado.
- **Huecos.** Un arco puede tener cuadros sin detección (tapada por un jugador,
  fuera del cuadro por arriba). Se extiende mientras los candidatos que
  reaparecen caigan sobre la misma curva.

### Eventos

- **Toque:** el punto donde un arco termina y empieza otro. El instante se afina
  cruzando los dos ajustes, no se redondea al cuadro.
- **Rally:** una cadena de arcos sin pausas largas. Arranca con el saque (un arco
  largo que nace detrás de una línea de fondo) y termina cuando la pelota deja de
  volar.
- **De qué lado fue cada toque.** Con una sola cámara, un píxel es un rayo: no
  dice si la pelota está alta y cerca o baja y lejos. Se resuelve con dos cosas:
  (a) el rayo cortado entre 0,3 y 3,5 m de altura da un segmento sobre la cancha;
  si queda entero de un lado de la red, listo; (b) si no, manda la secuencia: a
  lo sumo 3 toques seguidos por lado (el bloqueo no cuenta), y los arcos que
  cruzan la red son largos. Programación dinámica sobre la cadena de toques.
- **Armada:** el segundo toque de una posesión que tiene tercero. Si el segundo
  toque cruzó la red, se propone como `"segunda"` con confianza baja.
- **Zona de destino, sin 3D completo:** el ataque de primera línea pasa cerca de
  la red. Cortando el rayo del toque de ataque con un plano vertical paralelo a
  la red, a ~0,7 m de ella del lado que corresponde, sale la posición a lo largo
  de la red: tercios → zona 4, 3 o 2 (ojo: se espeja según el lado). Las de
  zaguero salen mal con este truco; se corrigen a mano hasta la etapa 7.
- **Confianza:** qué fracción del arco tiene detección, qué tan bien ajusta, qué
  tan seguro es el lado, si la posesión está completa. Guardá los `motivos` en
  texto: en la revisión quiero ver *por qué* duda.
- **Posesiones sin armada:** si en una posesión de mi equipo no se encontró el
  segundo toque, proponé igual una armada "a ciegas" en el tiempo estimado, con
  confianza mínima. Prefiero descartar de más a que se pierda una.

### Pantalla de revisión

Es donde paso el tiempo, así que **cada cosa es una tecla o un toque**:

- El clip de la propuesta se reproduce solo, en bucle, con la trayectoria y los
  toques dibujados encima (un `<canvas>` sobre el `<video>`).
- `Enter` acepta y pasa a la siguiente; `Supr` descarta; `4` `3` `2` `1` `6` `5`
  corrigen la zona; `←` `→` mueven cuadro a cuadro; `[` `]` ajustan inicio y fin;
  `Espacio` pausa; `M` marca una armada que no estaba propuesta en el instante
  actual; `Z` deshace.
- Hecho en la etapa 1, además: `M` frena el video y deja la marca elegida; con
  una elegida y el video quieto, `M` la mueve al cuadro actual (para corregir
  una marca que quedó tarde). `Espacio` la suelta y sigue. `A` marca el remate
  (da el vuelo y el tempo), `S` empieza un set, `I` `F` sirven igual que `[` `]`
  (en teclados en español esos salen con AltGr), `↑` `↓` pasan de armada, `Esc`
  suelta, `N` `E` escriben armador y etiquetas, `−` `+` cambian la velocidad.
  Lo que se toca enseguida de una `M` va a esa marca aunque el servidor todavía
  no haya contestado.
- El armador es **pegajoso**: el número que puse en una armada queda para las
  siguientes hasta que lo cambie.
- Una línea de tiempo del partido con los rallies y las armadas, coloreadas por
  estado, para saltar a cualquier lado.
- "Aceptar todas las de confianza mayor a X" en un botón, con el número de
  cuántas son a la vista antes de apretar.
- Cada cambio se guarda al instante en `revision.json`. Cerrar la pestaña no
  pierde nada.
- Funciona con el dedo en una tablet además de con teclado.

### Galería

- Filtros combinables: zona de destino, tiempo de vuelo (rápida / media / alta,
  con cortes configurables), armador, set, lado, etiqueta, texto de la nota.
- "Reproducir todas": pasa las filtradas una atrás de otra.
- Exportar las filtradas: un `.mp4` por armada y, opcional, uno solo con todas.

### Servidor local

`python -m video servir` levanta un servidor de biblioteca estándar en
`127.0.0.1:8001` (solo esta máquina: por eso no pide contraseña, a diferencia de
la carga; abrirlo a la red para una tablet pediría una). Dos cosas que no pueden
faltar:

- **Pedidos por rango** (`Range` → `206 Partial Content`). Sin eso el navegador
  no puede saltar dentro del video y la revisión no sirve.
- **Lista blanca**, como en `servidor_voley.py`: se sirven las páginas de
  `video/web/` y los archivos de `Videos/<nombre>/` por nombre, nunca una ruta
  que venga del pedido.

## Las etapas

Cada etapa termina con sus tests en verde, lo que **no** se pudo probar dicho con
todas las letras, y sin commitear salvo que yo lo pida.

**Etapa 1 — Marcar a mano, ver y filtrar.** Sin detección ni modelos.
`proyecto.py`, `lectura.py` (alta de video + proxy), `fusion.py`,
`servidor_video.py`, revisión (solo marcado manual con `M`, ajuste de recorte,
zona, armador, etiquetas) y galería con filtros. Sirve por sí sola desde el
primer día y deja **armadas marcadas por mí**, que son la verdad contra la que
se mide todo lo que sigue.
*Listo cuando:* marco 20 armadas de un video real, cierro, vuelvo a abrir y
están; las filtro por zona en la galería; los tests de `fusion.py` cubren
regenerar propuestas sin perder decisiones.
*Estado (2026-11-16):* hecha. 84 tests (`test_video_*.py`) y un recorrido en
Chrome sobre un video sintético de 1 minuto: 23 marcas con teclado, recargar,
filtrar por zona, bucle, todas seguidas, propuestas pendientes y ancho de
celular. Falta la prueba con un partido real. Lo que la pantalla de revisión
todavía no tiene y queda para la etapa 5: el dibujo de la trayectoria encima
del video, los rallies en la línea de tiempo y "aceptar todas las de confianza
mayor a X".

**Etapa 2 — ¿Se ve la pelota en mis videos?** Es una prueba, no producto.
`pelota.py` con el modelo ONNX y con el detector de movimiento; `modelos`.
Correr los candidatos sobre 5 minutos de un video mío y entregar: un video con
las detecciones dibujadas, y una tabla por detector con *cuadros con pelota
detectada durante el vuelo de las armadas que marqué en la etapa 1* (separado
cerca / lejos) y velocidad en cuadros por segundo en esta máquina.
*Listo cuando:* está la tabla y una recomendación. **Pará acá y mostrame el
resultado**: si ningún detector pasa de ~70 % en el vuelo de las armadas, el
paso siguiente es afinar un modelo con mis videos, no seguir construyendo.

**Etapa 3 — Calibración.** `calibracion.py`, `geometria.py` y la pantalla para
marcar puntos, con el dibujo de la cancha encima. De qué lado está mi equipo en
cada set ya se marca desde la etapa 1 (tecla `S`, en `revision.json`).
*Listo cuando:* con una cámara sintética, los puntos marcados con 2 px de ruido
recuperan la cámara con menos de 10 cm de error en puntos de la red; en un video
real el dibujo calza a ojo.

**Etapa 4 — Procesar un partido entero.** `procesar` con caché en `pelota.csv`,
salteo de tiempos muertos, corte y reanudación, aviso de cámara movida.
*Listo cuando:* un partido completo termina sin pasar de 3 GB de memoria, en no
más de 1,5 veces su duración; cortarlo a la mitad y relanzarlo no repite lo
hecho.

**Etapa 5 — Proponer armadas.** `trayectorias.py`, `eventos.py`, `proponer`,
`medir`, y la revisión mostrando propuestas con trayectoria, confianza y motivos.
*Listo cuando:* con datos sintéticos (arcos con ruido, 30 % de cuadros
faltantes, una segunda pelota) se recuperan los toques a menos de 0,1 s; contra
lo que marqué a mano en un partido real, `medir` da los números de "Cómo se
mide".

**Etapa 6 — Exportar.** `clips.py`, exportación desde la galería.

**Etapa 7 (opcional) — Medidas del pase.** Altura máxima, desde dónde armó y
dónde llegó, en metros. Primero con la aproximación del plano vertical paralelo
a la red; después, ajuste balístico en 3D (posición y velocidad inicial que
mejor explican los píxeles, con la gravedad conocida). Antes de mostrar un solo
número, **medí el error con trayectorias sintéticas vistas desde mi cámara
real**: la profundidad es la dirección débil de una sola cámara. Cada medida
sale con su error estimado y, si es grande, no se muestra.

**Más adelante, no ahora:** silbato del árbitro por audio para delimitar
rallies; afinar el modelo con mis correcciones; publicar las aceptadas en el
sitio alojado (S3); que el video proponga la carga del partido.

## Cómo se mide

`python -m video medir <nombre>` compara las propuestas contra las armadas que
están aceptadas o marcadas a mano en `revision.json` (misma regla de 0,5 s):

| Qué | Meta para la etapa 5 |
|---|---|
| Armadas de mi equipo que el sistema propuso | ≥ 85 % |
| Propuestas que tuve que descartar | ≤ 1 de cada 3 |
| Error en el instante del toque | ≤ 0,2 s en el 90 % |
| Zona de destino correcta (primera línea) | ≥ 80 % |
| Tiempo de revisión de un partido | ≤ 15 minutos |

Si no se llega, el informe de `medir` tiene que decir **dónde se pierden**: sin
detección de pelota, arco no armado, lado equivocado, o posesión mal contada.
Sin ese desglose no se sabe qué arreglar.

## Lo que necesito tener antes de empezar

- Un partido completo grabado como siempre, copiado a `Videos/`. Mejor dos, de
  gimnasios distintos.
- Para grabar de acá en adelante: cámara quieta y lo más alta posible; **que se
  vea toda la cancha y bastante aire arriba de la red** (las armadas altas se
  van del cuadro); horizontal, sin zoom; 1080p y, si el celular lo permite,
  60 cuadros por segundo (la pelota sale menos borrosa y cada arco tiene el doble
  de puntos); foco y exposición bloqueados.
