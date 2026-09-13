# Prompt reutilizable — Carga visual v1.1

> Copiá todo lo que sigue y pegalo en una sesión abierta dentro de esta carpeta
> (`statsvoleibolweb`). El agente tiene que poder leer los archivos del proyecto.

---

Quiero una versión 1.1 de **cómo se carga un partido**. Hoy se escribe cada jugada
como un código (`5_1_6_X/3_3/2_4/4_1_P`). Quiero poder cargarla **tocando**: que se
vea la cancha con los jugadores de los dos equipos como círculos con su número, y
que la jugada se arme apretando quién hizo qué. Escribir el código tiene que seguir
funcionando exactamente igual que hoy.

Antes de escribir una línea de código, leé:

- la cabecera de `analisis_voley.py` (el docstring largo): **ahí está la notación
  completa**, que es el contrato de todo esto;
- `sesion_web.py` entero (son 200 líneas y explica por qué el motor se vuelve a
  correr en cada jugada);
- `servidor_voley.py`, al menos `do_POST`, `_despachar` y la lista `RUTAS_CON_CLAVE`;
- `public/interfaz.js`, la sección "2) CARGAR";
- `public/index.html`, la sección "3) CARGAR";
- un `.txt` de `Datos/` completo, para ver cómo termina guardado todo esto.

## Qué es esto y qué no

Es **solo la pantalla de carga**. Las pestañas Partidos y Jugadores no se tocan. El
informe Excel no se toca. El formato del volcado `.txt` no se toca.

## Las tres reglas que no se negocian

**1. El motor es el único que sabe las reglas.** `analisis_voley.py` lleva el
marcador, la rotación, los cambios y decide qué es válido. La pantalla no vuelve a
implementar nada de eso: arma una línea de texto y la manda a `/api/enviar`, igual
que hoy. Si la pantalla empieza a decidir por su cuenta quién ganó el punto, el
trabajo está mal hecho.

**2. Escribir sigue funcionando.** El campo de texto, los atajos de teclado, pegar
un partido entero: todo queda. El modo visual es **otra forma de llenar el mismo
campo**, no un reemplazo. Se tiene que poder alternar en medio de un partido, punto
a punto, sin perder nada. Alguien que ya carga rápido escribiendo no puede terminar
más lento que antes.

**3. La línea que produce el modo visual tiene que ser idéntica, carácter por
carácter, a la que escribiría a mano una persona que sabe la notación.** No una
equivalente: idéntica. De eso depende que el `.txt`, el Excel y las estadísticas
sigan saliendo igual.

## Cómo funciona la carga hoy (el contrato que hay que respetar)

Cada jugada es **una línea de texto** que se manda a `POST /api/enviar` con
`{"linea": "..."}`. El servidor la agrega a la lista de líneas de la sesión, vuelve
a correr el motor entero con todas las líneas, y contesta `{ok, mensaje, estado}`.
Si el motor la rechaza, `ok` es `false`, la línea **no** se guarda y `mensaje` trae
el mismo texto que se vería en la consola.

Un punto puede necesitar **varias líneas**: la primera con el bloque de saque, y una
más por cada intercambio.

El `estado` que vuelve (`sesion_web.instantanea()`) trae, entre otras cosas:

- `nombres`, `marcador`, `set`, `sets_ganados`, `equipo_saca`, `jugador_saca`;
- `rotaciones[letra].jugadores` — **los 6 que están en cancha ahora, en el orden de
  las zonas 1 a 6**. Esto es lo que hay que dibujar;
- `rotaciones[letra].armador` — a quién preseleccionar como armador;
- `etapa` — `nombres` / `rotacion` / `saque_inicial` / `jugadas`;
- `lineas` — todo lo cargado hasta ahora.

## Lo primero que hay que resolver (y no es la pantalla)

Hay un agujero en el estado que hoy no molesta y con la carga visual sí.

Cuando una jugada deja el punto abierto (`..._D`, `..._R_6`, un libre, un toque, un
overpass), el motor pide otra línea. Como no hay más entradas, corta con
`SinMasEntradas` y **descarta el punto a medias**: `ejecutar_partido` devuelve el
estado sin ese punto (ver el final de `ejecutar_partido`, el `except
SinMasEntradas`). El resultado es que el estado **no dice que está esperando una
continuación**, ni de qué lado quedó la pelota.

Hoy da igual porque la persona que escribe se acuerda. Una pantalla que arma la
jugada paso a paso no puede adivinarlo: necesita saber si toca un bloque de saque o
uno de continuación, y **qué equipo tiene la pelota**, que es el que hay que
encender en la cancha.

Resolvelo **en el motor, no en el navegador**. Que `ejecutar_partido` informe el
punto pendiente cuando se queda sin entradas, y que `instantanea()` lo pase para
adelante — algo como:

```
"pendiente": {
  "hay": true,
  "espera": "continuacion",     // o "saque"
  "equipo_con_la_pelota": "B",
  "jugadas": [ ... lo cargado de este punto ... ]
}
```

Los nombres exactos elegilos vos, pero:

- **No repliques la lógica en JavaScript.** Deducir de quién es la pelota mirando la
  última línea es reimplementar el reglamento en el cliente, que es justo lo que este
  proyecto evitó siempre.
- Que el punto a medias siga sin contar para el marcador ni para las estadísticas,
  como ahora.
- Esto entra con tests propios en `test_analisis_voley.py`.

Mientras estés ahí, fijate si conviene que el estado exponga también la **secuencia
del punto en curso** ya descrita en texto (el proyecto ya tiene
`describir_bloque_saque` y `describir_bloque_defensa`), para poder mostrar arriba
"Saca el 5 → recibe el 3 (calidad 3) → arma el 2 a zona 4" mientras se arma.

## La pantalla que quiero

### Distribución

Arriba el marcador, como ahora. Abajo, **la cancha**: dos mitades, una por equipo,
con los 6 jugadores de cada lado ubicados en su zona (1 a 6) según
`rotaciones[letra].jugadores`. El equipo que tiene la pelota se ve claramente
encendido; el otro, apagado pero visible (hace falta para cargar bloqueos).

Debajo de la cancha, **la línea que se está armando**, siempre a la vista y en el
mismo monoespaciado que usa el proyecto:

```
5_1_6_X/3_3/2_4/4_
                 ^ falta la zona del ataque
```

Y al lado, dos botones que no pueden faltar nunca: **Deshacer el último paso** y
**Cancelar la jugada**.

Esto es para el celular, con una mano, parado al costado de la cancha. Los círculos
tienen que ser cómodos de apretar con el pulgar (44 px mínimo). Nada de menús
desplegables ni diálogos modales en el camino de la carga.

### Los jugadores

Un círculo por jugador con su número adentro. El armador, marcado (el proyecto ya
usa `_S`; usá la misma idea visual). El que va a sacar, destacado.

En cada paso se encienden **solo los círculos que se pueden tocar**. Los demás
quedan apagados y no responden. Eso es lo que hace que no haga falta saber la
notación: en cada momento la pantalla ofrece únicamente lo que el motor aceptaría.

### El paso a paso

Cada toque agrega un pedazo a la línea. Este es el recorrido completo; sale entero
del docstring de `analisis_voley.py`, verificalo ahí antes de codificarlo.

**Bloque de saque** (primera jugada del punto)

| Paso | Qué se toca | Qué se agrega |
|---|---|---|
| Sacador | círculo del equipo que saca, ya preseleccionado con `jugador_saca` | `5` |
| Zona desde | 1, 6 o 5 de su propia cancha | `_1` |
| Zona hacia | 1 a 9 de la cancha rival | `_6` |
| Resultado | **As** / **Error** / **Sigue** | `_A` / `_E` / `_X` |

As y Error cierran el punto: se manda la línea. "Sigue" continúa, y **la pelota pasa
al otro equipo**.

**Bloque de recepción o defensa**

| Paso | Qué se toca | Qué se agrega |
|---|---|---|
| Quién recibe | círculo del equipo que tiene la pelota | `3` |
| Calidad | 3 / 2 / 1 / 0 | `_3` |
| | **Se fue al otro lado** (overpass) | `_-1` → se manda, el punto sigue del otro lado |
| | **Defensa perdida** (solo en continuación) | `_-2` → se manda, punto para el contrario |

**Bloque de armado**

| Paso | Qué se toca | Qué se agrega |
|---|---|---|
| Quién arma | círculo del mismo equipo, preseleccionado el armador | `/2` |
| Zona | 1 a 6 | `_4` |
| | interruptor **no cuenta como armado** | `_4_X` |
| | **se pasó al otro lado** | `_-1` → se manda, el punto sigue |
| | **armada mala** | `_-2` → se manda, punto para el contrario |

**Bloque de ataque**

| Paso | Qué se toca | Qué se agrega |
|---|---|---|
| Quién ataca | círculo del mismo equipo | `/4` |
| Tipo | **Ataque** → zona 1, 6 o 5 | `_1` |
| | **Libre** → zona 1 a 9 | `_F_8` → se manda, el punto sigue |
| | **Toque** → zona 1 a 9 | `_T_8` → se manda, el punto sigue |
| Resultado | **Punto** / **Defendido** / **Afuera** / **Malla** | `_P` / `_D` / `_O` / `_M` |
| | **Bloqueo punto** + círculo del **rival** | `_B_6_P` |
| | **Tocó el bloqueo** + círculo del rival | `_U_6` |
| | **Bloqueo rejugable** + círculo del rival | `_R_6` |

`P`, `O`, `M`, `B_Y_P` y `U_Y` cierran el punto. `D` lo sigue **del lado del que
defendió**. `R_Y` lo sigue **del mismo lado que atacó**.

**Los dos atajos**

- **Pasada de segunda**: en el paso del armado, un botón "la manda de segunda".
  Reemplaza armado y ataque juntos: se toca el jugador, la zona (1 a 9) y el
  resultado (`D` / `P` / `O`) → `/10_S_6_D`.
- **Ataque de primera**: solo cuando toca una continuación, un botón "ataca de
  primera" en el paso de la defensa. Reemplaza todo el bloque: jugador, zona (1, 6 o
  5) y resultado (`P` / `D`) → `9_A_1_P`.

### Lo que no es una jugada

Estos ya existen y tienen que seguir a un toque de distancia, sin pasar por el
armador de jugadas:

- **`f`** — error en juego (dobles, cuatro toques, rotación). Punto directo para el
  rival. Disponible en cualquier momento, también en medio de un punto.
- **`x`** — deshacer. Ojo: `x` es del motor y deshace **un punto o una jugada**;
  "Deshacer el último paso" es de la pantalla y saca un pedazo de la línea que se
  está armando. Son dos cosas distintas y tienen que verse distintas.
- **`w`** — cerrar el set.
- **Cambios** — `C_7_28`, o `C_7_S_28` si el que entra pasa a ser armador. Esto sí
  merece pantalla visual: se toca al que sale (un círculo de la cancha), se elige al
  que entra (teclado numérico) y un interruptor "queda como armador". Solo entre
  puntos, que es cuando el motor los acepta.

### Antes del primer saque

La preparación (`etapa` = `nombres` / `rotacion` / `saque_inicial`) también merece
pantalla, porque hoy son cinco líneas escritas a ciegas:

- nombres de los dos equipos;
- la rotación de cada uno: los 6 números en las zonas 1 a 6, cargados sobre un
  dibujo de la cancha, marcando cuál es el armador;
- qué equipo saca primero.

Que se pueda dejar la rotación vacía, como ahora.

### Equipos sin rotación

Esto pasa de verdad: mirá los `.txt` de `Datos/`, donde solo un equipo tiene
rotación cargada. Sin rotación no hay 6 círculos que dibujar.

En ese caso, para ese equipo, en vez de la cancha va un **teclado numérico** para
escribir el dorsal. El resto del recorrido es igual. La pantalla no puede romperse
ni esconder los pasos porque falte la rotación de un lado.

## Cómo sé que está bien

Esto es lo que voy a mirar, en este orden.

**1. El test de equivalencia.** Un test nuevo que agarre un `.txt` de `Datos/`
completo, y para cada una de sus líneas reproduzca la secuencia de toques que la
generaría, y compare la línea resultante con la original. Tienen que salir las 200 y
pico idénticas. Si el armador de jugadas es JavaScript puro, sacalo a un módulo que
se pueda correr sin navegador para poder testearlo así.

**2. Los casos raros cargados de punta a punta**, con una prueba cada uno: as, error
de saque, overpass en la recepción, overpass en el armado, armada mala, armado que
no cuenta (`_X`), libre, toque, pasada de segunda después del saque y en
continuación, ataque de primera, bloqueo punto, toque de bloqueo, bloqueo
rejugable, malla, `f` en medio de un punto, y un punto con cinco intercambios.

**3. Los 304 tests que ya existen siguen pasando.** `python -m unittest
test_archivo_partidos test_analisis_voley`. Si alguno hay que cambiarlo, quiero
saber por qué antes de que lo cambies.

**4. Un partido cargado entero tocando** produce un `.txt` que
`generar_informe_volley.parse_volcado` lee sin quejarse y del que sale el Excel de
siempre.

## Restricciones técnicas

- **Sin dependencias nuevas.** Nada de npm, frameworks ni CDNs. El proyecto usa la
  biblioteca estándar de Python y JavaScript a mano, y así se queda.
- **Sin cambios en el formato del volcado** ni en `parse_volcado`.
- `/api/enviar` sigue siendo el único camino de escritura de una jugada. Si agregás
  endpoints nuevos, que sean de lectura.
- Anda alojado en Vercel: leé `DESPLIEGUE.md`. Cada pedido puede caer en una
  instancia distinta, así que **nada de estado nuevo en variables de módulo del
  servidor**.
- Los comentarios del proyecto explican *por qué*, no *qué*. Seguí ese tono.

## Lo que no quiero

- Que la pantalla decida quién ganó el punto, o valide la notación por su cuenta.
- Que el modo visual sea obligatorio, o que apague el campo de texto.
- Una animación de la pelota moviéndose por la cancha. Esto se usa mientras se
  juega: cada milisegundo de animación es un punto que te perdés.
- Confirmaciones en el medio de la carga. El error se arregla con deshacer, no
  preguntando antes de cada toque.
- Rehacer las pestañas Partidos y Jugadores.

---

Arrancá contándome cómo pensás resolver el punto pendiente en el motor y cómo queda
la máquina de estados del armador de jugadas. Cuando estemos de acuerdo en eso,
seguí con la pantalla.
