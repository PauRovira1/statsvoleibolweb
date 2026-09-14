"""
Analisis de partidos de voley.

Antes de arrancar se pregunta el nombre de cada equipo (si se deja vacio se
usa "A"/"B"), la rotacion de cada uno y despues que equipo saca primero.

La rotacion son los 6 jugadores en el orden de las zonas 1 a 6 de la cancha,
con uno marcado con _S como armador del equipo. Ejemplo:

    28_S 5 13 88 3 40

Con la rotacion cargada el programa sabe a quien le toca sacar y lo muestra
en el prompt ("[Saca Palestino, saca el 28]"). El equipo que recupera el
saque rota antes de sacar, asi que el primer sacador del equipo que recibe
es el que empieza en la zona 2. Eso hace que el numero del sacador en el
comando sea opcional: si le toca al 28, tanto "28_1_5_X/..." como
"1_5_X/..." significan lo mismo, y poner otro numero da error. Dejar la
rotacion vacia desactiva todo esto y el numero vuelve a ser obligatorio.

Los cambios se escriben "C_entra_sale" (ej. C_7_28: entra el 7, sale el 28)
en el prompt del saque, que es cuando el balon esta muerto. El que entra
ocupa la misma zona del que sale, asi que el orden de saque no se altera. El
equipo se deduce de la rotacion en la que este el jugador que sale.

El que entra puede llevar la marca _S ("C_7_S_28") para indicar cambio de
armador: pasa a ser el armador del equipo aunque el que sale no lo fuera, y
el armador anterior deja de serlo. Sin la marca solo hereda el rol si esta
reemplazando al armador, para que el equipo nunca se quede sin uno.

Deshacer con "x" deshace puntos, no cambios: para revertir un cambio se hace
el inverso.

Al terminar, el volcado .txt del partido va a la carpeta Datos/ y el informe
Excel a Informes/, las dos al lado de este archivo. Se crean solas la primera
vez y no dependen del directorio desde el que se ejecute el programa.

A partir de ahi el programa
va llevando el marcador y el saque solo: gana el punto -> saca ese equipo
en el punto siguiente (regla de rally point). Los nombres elegidos se usan
solo para mostrar en pantalla y en el reporte final; internamente los
equipos se siguen identificando como A y B.

En cualquier momento en que se pide la primera jugada de un punto (el
prompt "[Saca ...]"), escribir solo "w" cierra el set actual: guarda su
marcador, suma un set ganado para quien iba arriba, reinicia el marcador a
0-0 y vuelve a preguntar que equipo saca primero (para el set siguiente).
Las estadisticas de jugadores siguen siendo del partido completo.

Escribir solo "x" deshace la ultima jugada cargada:
  - Si se escribe en un prompt "[Juega ...]" (dentro de un punto que ya
    tiene alguna jugada de continuacion) borra esa ultima jugada y vuelve a
    pedir la misma.
  - Si se escribe ahi mismo pero el punto no tiene ninguna continuacion
    todavia, se cancela el punto completo (incluido el saque) y se vuelve a
    pedir desde el saque.
  - Si se escribe en el prompt "[Saca ...]" (sin haber cargado nada de este
    punto), se deshace el ultimo punto ya cerrado: se le resta al marcador,
    se borran sus jugadas y se vuelve a preguntar el saque de ese punto. No
    se puede deshacer un punto de un set ya cerrado con "w".

Escribir solo "f" en cualquier prompt de jugada (tanto "[Saca ...]" como
"[Juega ...]") registra un error en juego (falta cualquiera: dobles, cuatro
toques, rotacion, etc.) del equipo que tenia que jugar en ese momento, y le
da el punto directo al equipo contrario. No hace falta cargar jugador ni
zona.

Al salir del programa se guarda un .txt con todos los inputs cargados y las
estadisticas finales, y despues se ofrece generar tambien el informe Excel
(usando generar_informe_volley.py, que necesita openpyxl instalado).

Cada PUNTO se carga con una o mas jugadas en consola:

1) Primera jugada del punto (bloque de saque), formato:

    X_Z1_Z2_R1[/Y_C/W_Z3/A_Z4_R2]

    X  = numero del jugador que saca
    Z1 = zona desde donde saca      (1, 6 o 5)
    Z2 = zona hacia donde saca      (1 a 9)
    R1 = resultado del saque:
           X -> sigue la jugada (no fue punto directo)
           A -> as (punto directo para el equipo que saca)
           E -> error de saque (punto para el rival)

    Si R1 es "A" o "E" el punto termina ahi. Si R1 es "X", la jugada
    continua con:

    Y  = numero del jugador que recibe
    C  = calidad del pase de recepcion (0, 1, 2 o 3; o -1 si el pase se va
         directo al otro lado sin querer, un "overpass". En ese caso la
         jugada termina en la recepcion: no hay armado ni ataque, el punto
         sigue y el otro equipo recibe esa pelota)
    W  = numero del jugador que arma (colocador)
    Z3 = zona hacia donde arma      (1 a 6)
    W_Z3 puede llevar un "_X" opcional al final (W_Z3_X): significa que en
    realidad NO hubo armado (ej. un segundo toque que no fue una asistencia
    real), y esa jugada no se cuenta en las estadisticas de armado.
    En vez de "W_Z3" tambien puede ser:
      W_-1  -> la armada se pasa directo al otro lado (overpass). El punto
               sigue, no hace falta cargar el ataque. Formato:
               X_Z1_Z2_X/Y_C/W_-1
      W_-2  -> la armada fue mala y el punto termina ahi mismo, directo
               para el equipo contrario (no hace falta cargar el ataque).
               Formato: X_Z1_Z2_X/Y_C/W_-2
    A  = numero del jugador que ataca
    Z4 = zona hacia donde ataca     (1, 6 o 5)
    R2 = resultado del ataque:
           P       -> punto directo (kill)
           D       -> el rival defiende, el punto sigue
           O       -> el ataque se va afuera, punto para el equipo que defiende
           M       -> el ataque va a la malla (red), punto para el equipo que
                      defiende (es lo mismo que "O" pero para diferenciar en
                      las estadisticas si fue afuera o a la red)
           B_Y_P   -> bloqueo del jugador Y, punto para el equipo que bloquea
           U_Y     -> toque de bloqueo del jugador Y ("usado"), punto para
                      el equipo que ataco
           R_Y     -> bloqueo rejugable del jugador Y: la pelota vuelve al
                      lado del equipo que ataco, que recupera el control

    En vez de "A_Z4_R2" (ataque normal), el bloque de ataque tambien puede
    ser:

    A_F_Z       = LIBRE: el jugador A no ataca, hace un libre hacia la zona
                  Z (1 a 9). El punto siempre sigue: el otro equipo recibe
                  ese libre. No cuenta como ataque en las estadisticas.

    A_T_Z       = TOQUE: el jugador A toca la pelota hacia la zona Z (1 a
                  9), sin atacar. El punto siempre sigue. No cuenta como
                  ataque en las estadisticas (igual que el libre, pero se
                  guarda como un caso distinto).

    IMPORTANTE: la pasada de segunda (ver mas abajo) NO va en este lugar,
    porque ella misma reemplaza el armado + ataque juntos (es el segundo
    toque, no el tercero).

2) Si el punto sigue (R2 fue D, R_Y o hubo un libre/toque), se pide una
   jugada mas, esta vez SIN el bloque de saque, formato:

    Y_C/W_Z3/A_Z4_R2   (o  Y_C/W_Z3/A_F_Z  si es libre, o  Y_C/W_Z3/A_T_Z
    si es toque)

    Y = numero del jugador que recibe/defiende la pelota
    C = calidad de esa recepcion/defensa (0, 1, 2 o 3; es solo informativo,
        no termina el punto por si sola). Tambien puede ser:
          -1 -> overpass: se va directo al otro lado. La jugada termina en
               "Y_-1", sin armado ni ataque, y el punto sigue del lado del
               otro equipo.
          -2 -> la defensa se pierde por completo. La jugada termina en
               "Y_-2" y el punto es directo para el equipo contrario (el
               que ataco).
    W  = numero del jugador que arma (colocador)
    Z3 = zona hacia donde arma      (1 a 6)
    W_Z3 tambien admite el "_X" opcional (W_Z3_X) para marcar que no hubo
    armado real. Y tambien puede ser "W_-1" (se pasa directo al otro lado,
    el punto sigue) o "W_-2" (la armada fue mala, el punto termina ahi
    mismo, directo para el equipo contrario).
    A  = numero del jugador que ataca (o hace el libre, o el toque)
    Z4 = zona hacia donde ataca     (1, 6 o 5; 1 a 9 si es libre o toque)
    R2 = resultado del ataque (mismos codigos que arriba: P / D / O / M /
         B_Y_P / U_Y / R_Y)

   Esto se puede repetir tantas veces como intercambios tenga el punto,
   hasta que alguien haga punto (R2 = P, O, M, B_Y_P o U_Y).

   Atajo: en vez del bloque de defensa completo, si el jugador ataca de
   primera (sin armado, de una) se puede cargar directo:

    X_A_Z_(P/D)

    X = numero del jugador que ataca de primera
    A = literal, indica que es un ataque de primera (sin armado)
    Z = zona hacia donde ataca     (1, 6 o 5)
    P/D = punto directo o el rival lo defiende

   PASADA DE SEGUNDA: el jugador que recibe/defiende manda el mismo la
   pelota en el segundo toque (en vez de armar para que otro ataque). Como
   ES el segundo toque, no lleva armado por separado: si llevara armado
   antes, seria un tercer toque, no una segunda. Reemplaza el "W_Z3/A_Z4_R2"
   (armado + ataque) por directamente "A_S_Z_R2":

    Despues del saque:  X_Z1_Z2_X/Y_C/A_S_Z_R2
    En una continuacion:  Y_C/A_S_Z_R2

    Y  = numero del jugador que recibe/defiende (el primer toque)
    C  = calidad de ese primer toque (0 a 3; o -1/-2 si es una continuacion)
    A  = numero del jugador que hace la pasada de segunda (el segundo toque)
    S  = literal, indica que es una pasada de segunda
    Z  = zona hacia donde la manda  (1 a 9)
    R2 = resultado: D (se defiende, sigue el punto), P (punto directo) u
         O (se va afuera, punto para el equipo contrario)

Ejemplos:
    5_1_6_A                        -> as
    5_1_6_E                        -> error de saque
    5_1_6_X/3_3/2_4/4_1_P          -> punto en el primer ataque
    5_1_6_X/3_3/2_4/4_1_D          -> defendido, sigue el punto...
    7_0/1_5/9_5_D                  -> ...se defiende con calidad 0 y sigue...
    7_2/1_5/9_5_O                  -> ...hasta que el ataque se va afuera, punto para la defensa
    7_2/1_5/9_5_B_6_P              -> ...o el jugador 6 bloquea y hace punto
    7_2/1_5/9_5_U_6                -> ...o toca el bloqueo y sale, punto igual para el ataque
    7_2/1_5/9_5_R_6                -> ...o el bloqueo es rejugable y el mismo equipo sigue atacando
    7_2/1_5/9_F_8                  -> ...o el jugador 9 no puede atacar y hace un libre a zona 8
    7_2/1_5/9_T_8                  -> ...o el jugador 9 toca hacia zona 8 (no cuenta como ataque)
    7_2/1_5_X/9_5_P                -> ...o hay punto pero el armado no cuenta en las estadisticas
    5_1_6_X/3_-1                   -> la recepcion se va directo al otro lado (overpass)
    9_A_1_P                        -> el jugador 9 ataca de primera hacia zona 1 y hace punto
    7_-1                           -> la defensa tambien se va directo al otro lado (overpass)
    7_-2                           -> la defensa se pierde, punto directo para el equipo contrario
    7_2/1_-2                       -> la armada del jugador 1 fue mala, punto directo para el contrario
    7_2/1_-1                       -> la armada del jugador 1 se pasa al otro lado, sigue el punto
    7_2/1_5/9_5_M                  -> el ataque va a la malla, punto para la defensa
    5_1_6_X/3_3/10_S_6_D           -> el jugador 10 hace la pasada de segunda a zona 6 (recien recibio el 3), y se defiende
    2_2/10_S_6_D                   -> lo mismo pero como continuacion: jugador 2 defiende, jugador 10 hace la segunda
    f                               -> error en juego (en cualquier prompt): punto directo para el rival
"""

import getpass
import os
import re
import secrets
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import almacenamiento as alm

# Donde se guardan los archivos lo decide almacenamiento.py, no este modulo.
# En la notebook es al lado del .py, como siempre; alojado en Vercel la carpeta
# del proyecto es de solo lectura y hay que escribir en otro lado. Aca solo se
# pregunta cual es la que toca.
CARPETA_PROYECTO = Path(__file__).resolve().parent
CARPETA_DATOS = alm.carpeta_de_escritura(alm.DATOS)        # volcados .txt
CARPETA_INFORMES = alm.carpeta_de_escritura(alm.INFORMES)  # informes .xlsx

# Clave para cargar un partido, por consola o por la web. En la maquina de
# casa y en la WiFi del club lo unico que evita es que alguien que entre desde
# el celular arruine una carga en curso, y con una clave escrita aca alcanzaba.
#
# Publicada en internet ya no: el sitio lo puede abrir cualquiera, y la clave
# esta a la vista de cualquiera que mire el repositorio. Por eso ahora manda
# VOLEY_CLAVE, que en Vercel se carga como variable de entorno y no viaja en el
# codigo. La de aca abajo queda como la de siempre para correr en casa.
CONTRASENA_CARGA = os.environ.get("VOLEY_CLAVE") or "Pau2250224"
INTENTOS_CONTRASENA = 3


def carpeta_lista(carpeta: Path) -> Path:
    """Devuelve la carpeta, creandola la primera vez que hace falta."""
    return alm.carpeta_lista(carpeta)

# Prefijo comun de todos los saques. El numero del sacador es opcional: si hay
# rotacion cargada se completa solo con el jugador al que le toca sacar. No hay
# ambiguedad con la forma larga porque las zonas son de un solo digito, asi que
# la cantidad de campos distingue "28_1_5_X" de "1_5_X".
SAQUE_PREFIJO = (
    r"^(?:(?P<sacador>\d+)_)?(?P<zona_saque>[165])"
    r"_(?P<zona_destino_saque>[1-9])"
)

PATRON_SAQUE_TERMINAL = re.compile(
    SAQUE_PREFIJO +
    r"_(?P<resultado_saque>[AE])$"
)

RESULTADO_ATAQUE = r"(?:P|D|O|M|B_\d+_P|U_\d+|R_\d+)"

# El bloque de ataque puede ser un ataque normal (atacante_zona_resultado), un
# libre (atacante_F_zona, el jugador no pudo atacar y solo la pasa), o un
# toque (atacante_T_zona: el jugador toca hacia esa zona, tampoco cuenta
# como ataque).
ATAQUE_O_LIBRE = (
    rf"(?:(?P<atacante>\d+)_(?P<zona_ataque>[165])_(?P<resultado>{RESULTADO_ATAQUE})"
    r"|(?P<atacante_libre>\d+)_F_(?P<zona_libre>[1-9])"
    r"|(?P<atacante_toca>\d+)_T_(?P<zona_toca>[1-9]))"
)

# Despues de colocador_zona puede venir un "_X" opcional: indica que en
# realidad no hubo armado (no se cuenta en las estadisticas de armado).
ARMADO = r"(?P<colocador>\d+)_(?P<zona_colocacion>[1-6])(?:_(?P<sin_armado>X))?"

PATRON_SAQUE_COMPLETO = re.compile(
    SAQUE_PREFIJO +
    r"_X"
    r"/(?P<receptor>\d+)_(?P<calidad_recepcion>[0-3])"
    r"/" + ARMADO +
    r"/" + ATAQUE_O_LIBRE + r"$"
)

# El armado tambien puede ser -1: se pasa directo al otro lado (overpass).
# El punto sigue, no hace falta cargar el ataque.
PATRON_SAQUE_ARMADO_OVERPASS = re.compile(
    SAQUE_PREFIJO +
    r"_X"
    r"/(?P<receptor>\d+)_(?P<calidad_recepcion>[0-3])"
    r"/(?P<colocador>\d+)_-1$"
)

# O -2: la armada fue mala y termina el punto ahi mismo, directo para el
# equipo contrario (no hace falta cargar el ataque).
PATRON_SAQUE_ARMADO_MALO = re.compile(
    SAQUE_PREFIJO +
    r"_X"
    r"/(?P<receptor>\d+)_(?P<calidad_recepcion>[0-3])"
    r"/(?P<colocador>\d+)_-2$"
)

# Pasada de segunda directa: es el segundo toque en si mismo (el jugador que
# recibe/defiende la manda el mismo hacia la zona), asi que NO lleva armado
# antes (si llevara armado, seria un tercer toque, no una "segunda").
PATRON_SAQUE_SEGUNDA = re.compile(
    SAQUE_PREFIJO +
    r"_X"
    r"/(?P<receptor>\d+)_(?P<calidad_recepcion>[0-3])"
    r"/(?P<atacante>\d+)_S_(?P<zona_ataque>[1-9])_(?P<resultado>[DPO])$"
)

# La recepcion tambien puede ser -1: el pase se va directo al otro lado
# (overpass). Ahi la jugada termina en la recepcion, no hay armado ni ataque.
PATRON_SAQUE_OVERPASS = re.compile(
    SAQUE_PREFIJO +
    r"_X"
    r"/(?P<receptor>\d+)_-1$"
)

PATRON_DEFENSA = re.compile(
    r"^(?P<defensor>\d+)_(?P<calidad_defensa>[0-3])"
    r"/" + ARMADO +
    r"/" + ATAQUE_O_LIBRE + r"$"
)

# Idem, pasada de segunda directa desde una continuacion (sin armado previo).
PATRON_DEFENSA_SEGUNDA = re.compile(
    r"^(?P<defensor>\d+)_(?P<calidad_defensa>[0-3])"
    r"/(?P<atacante>\d+)_S_(?P<zona_ataque>[1-9])_(?P<resultado>[DPO])$"
)

# Idem, armado -1 desde una continuacion: se pasa directo al otro lado.
PATRON_DEFENSA_ARMADO_OVERPASS = re.compile(
    r"^(?P<defensor>\d+)_(?P<calidad_defensa>[0-3])"
    r"/(?P<colocador>\d+)_-1$"
)

# Idem, armado -2 desde una continuacion: la armada fue mala, punto directo
# para el equipo contrario.
PATRON_DEFENSA_ARMADO_MALO = re.compile(
    r"^(?P<defensor>\d+)_(?P<calidad_defensa>[0-3])"
    r"/(?P<colocador>\d+)_-2$"
)

# La defensa tambien puede ser -1: se va directo al otro lado (overpass).
# Ahi la jugada termina en la defensa, no hay armado ni ataque.
PATRON_DEFENSA_OVERPASS = re.compile(
    r"^(?P<defensor>\d+)_-1$"
)

# O -2: la defensa se pierde por completo, punto directo para el equipo
# contrario (el que ataco).
PATRON_DEFENSA_PERDIDA = re.compile(
    r"^(?P<defensor>\d+)_-2$"
)

# Atajo: el jugador ataca de primera (sin armado) directo desde la defensa.
PATRON_DEFENSA_PRIMERA = re.compile(
    r"^(?P<atacante>\d+)_A_(?P<zona_ataque>[165])_(?P<resultado>[PD])$"
)

# Cambio de jugador: C_entra_sale, con un _S opcional sobre el que entra
# (C_7_S_28) para decir que entra como armador. Se escribe en el prompt del
# saque, que es cuando el balon esta muerto. No choca con ningun saque porque
# todos empiezan con un numero.
PATRON_CAMBIO = re.compile(
    r"^C_(?P<entra>\d+)(?P<marca_armador>_S)?_(?P<sale>\d+)$", re.IGNORECASE
)

CAMPOS_NUMERICOS = ("sacador", "receptor", "colocador", "atacante", "defensor")
COMANDOS_SALIDA = {"salir", "fin", "exit", "q"}
COMANDO_CAMBIO_SET = "w"
COMANDO_DESHACER = "x"
COMANDO_ERROR_JUEGO = "f"
EQUIPOS = {"A", "B"}

# Rotacion: los 6 jugadores en el orden de las zonas 1 a 6, y uno marcado con
# _S como armador del equipo.
CANTIDAD_ROTACION = 6
MARCA_ARMADOR = "_S"

GRUPOS_ZONA_ARMADO = ("1", "2", "6-5", "3", "4")
ZONA_A_GRUPO = {
    "1": "1",
    "2": "2",
    "6": "6-5", "5": "6-5",
    "3": "3",
    "4": "4",
}


def _a_enteros(datos: dict) -> dict:
    for campo in CAMPOS_NUMERICOS:
        if datos.get(campo) is not None:
            datos[campo] = int(datos[campo])
    return datos


def _procesar_resultado(datos: dict) -> dict:
    """Descompone el resultado del ataque (P/D/B_Y_P/U_Y/R_Y) en tipo + jugador de bloqueo."""
    crudo = datos["resultado"]

    if crudo in ("P", "D", "O", "M"):
        datos["jugador_bloqueo"] = None
        return datos

    tipo, jugador = crudo.split("_", 1)
    if tipo == "B":
        jugador = jugador[:-2]  # saca el "_P" final
    datos["resultado"] = tipo
    datos["jugador_bloqueo"] = int(jugador)
    return datos


def _normalizar_armado(datos: dict) -> dict:
    """True si hubo un armado real; False si vino marcado con el "_X" opcional."""
    datos["armado_valido"] = datos.pop("sin_armado") is None
    return datos


def _normalizar_ataque(datos: dict) -> dict:
    """Unifica el ataque normal, el libre (atacante_F_zona) y el toque
    (atacante_T_zona) en las mismas claves."""
    claves_alternativas = ("atacante_libre", "zona_libre", "atacante_toca", "zona_toca")

    if datos.get("atacante_libre") is not None:
        datos["atacante"] = datos.pop("atacante_libre")
        datos["zona_ataque"] = datos.pop("zona_libre")
        datos["resultado"] = "F"
        datos["jugador_bloqueo"] = None
        datos["es_segunda"] = False
    elif datos.get("atacante_toca") is not None:
        datos["atacante"] = datos.pop("atacante_toca")
        datos["zona_ataque"] = datos.pop("zona_toca")
        datos["resultado"] = "T"
        datos["jugador_bloqueo"] = None
        datos["es_segunda"] = False
    else:
        datos["es_segunda"] = False

    for clave in claves_alternativas:
        datos.pop(clave, None)

    return datos


def parsear_bloque_saque(texto: str) -> dict | None:
    """Parsea la primera jugada de un punto (incluye el saque)."""
    texto = texto.strip()

    match = PATRON_SAQUE_TERMINAL.match(texto)
    if match:
        datos = match.groupdict()
        for campo in ("receptor", "calidad_recepcion", "colocador", "zona_colocacion",
                      "atacante", "zona_ataque", "resultado", "jugador_bloqueo"):
            datos[campo] = None
        datos["armado_valido"] = None
        return _a_enteros(datos)

    match = PATRON_SAQUE_OVERPASS.match(texto)
    if match:
        datos = match.groupdict()
        datos["resultado_saque"] = "X"
        datos["calidad_recepcion"] = -1
        for campo in ("colocador", "zona_colocacion", "armado_valido",
                      "atacante", "zona_ataque", "jugador_bloqueo"):
            datos[campo] = None
        datos["resultado"] = "V"
        return _a_enteros(datos)

    match = PATRON_SAQUE_SEGUNDA.match(texto)
    if match:
        datos = match.groupdict()
        datos["resultado_saque"] = "X"
        datos["calidad_recepcion"] = int(datos["calidad_recepcion"])
        for campo in ("colocador", "zona_colocacion", "armado_valido", "jugador_bloqueo"):
            datos[campo] = None
        datos["es_segunda"] = True
        return _a_enteros(datos)

    match = PATRON_SAQUE_ARMADO_OVERPASS.match(texto)
    if match:
        datos = match.groupdict()
        datos["resultado_saque"] = "X"
        datos["calidad_recepcion"] = int(datos["calidad_recepcion"])
        for campo in ("zona_colocacion", "armado_valido", "atacante", "zona_ataque", "jugador_bloqueo"):
            datos[campo] = None
        datos["es_segunda"] = False
        datos["resultado"] = "K"
        return _a_enteros(datos)

    match = PATRON_SAQUE_ARMADO_MALO.match(texto)
    if match:
        datos = match.groupdict()
        datos["resultado_saque"] = "X"
        datos["calidad_recepcion"] = int(datos["calidad_recepcion"])
        for campo in ("zona_colocacion", "armado_valido", "atacante", "zona_ataque", "jugador_bloqueo"):
            datos[campo] = None
        datos["es_segunda"] = False
        datos["resultado"] = "N"
        return _a_enteros(datos)

    match = PATRON_SAQUE_COMPLETO.match(texto)
    if match:
        datos = match.groupdict()
        datos["resultado_saque"] = "X"
        datos["calidad_recepcion"] = int(datos["calidad_recepcion"])
        datos = _normalizar_armado(datos)
        datos = _normalizar_ataque(datos)
        if datos["resultado"] not in ("F", "T"):
            datos = _procesar_resultado(datos)
        return _a_enteros(datos)

    return None


def parsear_bloque_defensa(texto: str) -> dict | None:
    """Parsea una jugada de continuacion (defensa) dentro del mismo punto."""
    texto = texto.strip()

    match = PATRON_DEFENSA_PRIMERA.match(texto)
    if match:
        datos = match.groupdict()
        for campo in ("defensor", "calidad_defensa", "colocador", "zona_colocacion",
                      "armado_valido", "jugador_bloqueo"):
            datos[campo] = None
        return _a_enteros(datos)

    match = PATRON_DEFENSA_SEGUNDA.match(texto)
    if match:
        datos = match.groupdict()
        datos["calidad_defensa"] = int(datos["calidad_defensa"])
        for campo in ("colocador", "zona_colocacion", "armado_valido", "jugador_bloqueo"):
            datos[campo] = None
        datos["es_segunda"] = True
        return _a_enteros(datos)

    match = PATRON_DEFENSA_ARMADO_OVERPASS.match(texto)
    if match:
        datos = match.groupdict()
        datos["calidad_defensa"] = int(datos["calidad_defensa"])
        for campo in ("zona_colocacion", "armado_valido", "atacante", "zona_ataque", "jugador_bloqueo"):
            datos[campo] = None
        datos["es_segunda"] = False
        datos["resultado"] = "K"
        return _a_enteros(datos)

    match = PATRON_DEFENSA_ARMADO_MALO.match(texto)
    if match:
        datos = match.groupdict()
        datos["calidad_defensa"] = int(datos["calidad_defensa"])
        for campo in ("zona_colocacion", "armado_valido", "atacante", "zona_ataque", "jugador_bloqueo"):
            datos[campo] = None
        datos["es_segunda"] = False
        datos["resultado"] = "N"
        return _a_enteros(datos)

    match = PATRON_DEFENSA_OVERPASS.match(texto)
    if match:
        datos = match.groupdict()
        datos["calidad_defensa"] = -1
        for campo in ("colocador", "zona_colocacion", "armado_valido",
                      "atacante", "zona_ataque", "jugador_bloqueo"):
            datos[campo] = None
        datos["resultado"] = "V"
        return _a_enteros(datos)

    match = PATRON_DEFENSA_PERDIDA.match(texto)
    if match:
        datos = match.groupdict()
        datos["calidad_defensa"] = -2
        for campo in ("colocador", "zona_colocacion", "armado_valido",
                      "atacante", "zona_ataque", "jugador_bloqueo"):
            datos[campo] = None
        datos["resultado"] = "L"
        return _a_enteros(datos)

    match = PATRON_DEFENSA.match(texto)
    if not match:
        return None

    datos = match.groupdict()
    datos["calidad_defensa"] = int(datos["calidad_defensa"])
    datos = _normalizar_armado(datos)
    datos = _normalizar_ataque(datos)
    if datos["resultado"] not in ("F", "T"):
        datos = _procesar_resultado(datos)
    return _a_enteros(datos)


def _describir_resultado_ataque(bloque: dict) -> str:
    tipo = bloque["resultado"]
    if tipo == "P":
        return "PUNTO"
    if tipo == "D":
        return "defendido"
    if tipo == "O":
        return "FUERA (error de ataque, punto para la defensa)"
    if tipo == "M":
        return "A LA MALLA (error de ataque, punto para la defensa)"
    if tipo == "B":
        return f"BLOQUEADO por jugador {bloque['jugador_bloqueo']} (punto para el bloqueo)"
    if tipo == "U":
        return f"toque de bloqueo (jugador {bloque['jugador_bloqueo']}), punto para el ataque"
    return f"bloqueo rejugable (jugador {bloque['jugador_bloqueo']} bloquea), sigue atacando el mismo equipo"


def _describir_ataque(bloque: dict) -> str:
    if bloque["resultado"] == "F":
        return (
            f"Libre: jugador {bloque['atacante']} no ataca, "
            f"la manda a zona {bloque['zona_ataque']} (sigue el punto)"
        )
    if bloque["resultado"] == "T":
        return (
            f"Toque: jugador {bloque['atacante']} toca "
            f"hacia zona {bloque['zona_ataque']} (sigue el punto)"
        )
    if bloque.get("es_segunda"):
        return (
            f"Segunda: jugador {bloque['atacante']} (zona {bloque['zona_ataque']}) "
            f"-> {_describir_resultado_ataque(bloque)}"
        )
    return (
        f"Ataque: jugador {bloque['atacante']} (zona {bloque['zona_ataque']}) "
        f"-> {_describir_resultado_ataque(bloque)}"
    )


def _describir_armado(bloque: dict) -> str:
    base = f"Armado: jugador {bloque['colocador']} (zona {bloque['zona_colocacion']})"
    if bloque.get("armado_valido") is False:
        return base + " (no hubo armado, no cuenta en estadisticas)"
    return base


def describir_bloque_saque(bloque: dict) -> str:
    base = (
        f"Saque: jugador {bloque['sacador']} "
        f"(zona {bloque['zona_saque']} -> zona {bloque['zona_destino_saque']})"
    )
    if bloque["resultado_saque"] == "A":
        return base + " -> AS"
    if bloque["resultado_saque"] == "E":
        return base + " -> ERROR DE SAQUE"
    if bloque["resultado"] == "V":
        return (
            base + " (sigue) | "
            f"Recepcion: jugador {bloque['receptor']} (calidad -1) "
            "-> PASE AL OTRO LADO (sigue el punto)"
        )

    if bloque.get("es_segunda") and bloque.get("colocador") is None:
        # pasada de segunda directa: no hubo armado previo (seria un tercer toque)
        return (
            base + " (sigue) | "
            f"Recepcion: jugador {bloque['receptor']} (calidad {bloque['calidad_recepcion']}) | "
            f"{_describir_ataque(bloque)}"
        )

    if bloque["resultado"] == "N":
        return (
            base + " (sigue) | "
            f"Recepcion: jugador {bloque['receptor']} (calidad {bloque['calidad_recepcion']}) | "
            f"Armado: jugador {bloque['colocador']} "
            "-> ARMADO MALO (punto para el equipo contrario)"
        )

    if bloque["resultado"] == "K":
        return (
            base + " (sigue) | "
            f"Recepcion: jugador {bloque['receptor']} (calidad {bloque['calidad_recepcion']}) | "
            f"Armado: jugador {bloque['colocador']} "
            "-> PASE AL OTRO LADO (sigue el punto)"
        )

    return (
        base + " (sigue) | "
        f"Recepcion: jugador {bloque['receptor']} (calidad {bloque['calidad_recepcion']}) | "
        f"{_describir_armado(bloque)} | "
        f"{_describir_ataque(bloque)}"
    )


def describir_bloque_defensa(bloque: dict) -> str:
    if bloque.get("defensor") is None:
        resultado = "PUNTO" if bloque["resultado"] == "P" else "defendido"
        return (
            f"Ataque de primera: jugador {bloque['atacante']} "
            f"(zona {bloque['zona_ataque']}) -> {resultado}"
        )

    if bloque["resultado"] == "V":
        return (
            f"Defensa: jugador {bloque['defensor']} (calidad -1) "
            "-> PASE AL OTRO LADO (sigue el punto)"
        )

    if bloque["resultado"] == "L":
        return (
            f"Defensa: jugador {bloque['defensor']} (calidad -2) "
            "-> DEFENSA PERDIDA (punto para el equipo contrario)"
        )

    base = f"Defensa: jugador {bloque['defensor']} (calidad {bloque['calidad_defensa']})"

    if bloque.get("es_segunda") and bloque.get("colocador") is None:
        # pasada de segunda directa: no hubo armado previo (seria un tercer toque)
        return base + " | " + _describir_ataque(bloque)

    if bloque["resultado"] == "N":
        return (
            base + " | "
            f"Armado: jugador {bloque['colocador']} "
            "-> ARMADO MALO (punto para el equipo contrario)"
        )

    if bloque["resultado"] == "K":
        return (
            base + " | "
            f"Armado: jugador {bloque['colocador']} "
            "-> PASE AL OTRO LADO (sigue el punto)"
        )

    return (
        base + " | "
        f"{_describir_armado(bloque)} | "
        f"{_describir_ataque(bloque)}"
    )


class SinMasEntradas(Exception):
    """Se agotaron las lineas cargadas. La consola nunca la levanta (input()
    siempre espera); la interfaz web si, para cortar el loop donde va la
    partida y quedarse con el estado."""


@contextmanager
def _esperando(descripcion: dict):
    """Le pega a SinMasEntradas la pregunta que el motor estaba haciendo.

    El corte de la web es mudo: se levanta desde adentro de un input(), el
    frame se destruye y el estado vuelve sin decir en que prompt quedo parado.
    Al que tipea le da igual porque se acuerda, pero una pantalla que arma la
    jugada tocando no puede adivinarlo, y deducirlo mirando la ultima linea
    seria reimplementar el reglamento afuera del motor.

    La descripcion se puede seguir mutando despues de entrar: jugar_punto la
    usa para ir contando de quien es la pelota mientras avanza el punto."""
    try:
        yield descripcion
    except SinMasEntradas as corte:
        # gana la descripcion mas adentro, que es la mas precisa
        if getattr(corte, "esperando", None) is None:
            corte.esperando = descripcion
        raise


def preguntar_nombres_equipos() -> tuple[dict, list[str]]:
    """Pregunta el nombre de cada equipo (vacio = usar la letra A/B).
    Devuelve (nombres, entradas_crudas): entradas_crudas guarda lo tipeado tal
    cual (aunque este vacio) para poder reproducir la carga pegando el .txt."""
    print("Nombre de los equipos (dejar vacio para usar 'A' / 'B'):")
    nombres = {}
    entradas_crudas = []
    for letra in sorted(EQUIPOS):
        with _esperando({"que": "nombre_equipo", "equipo": letra}):
            respuesta = input(f"  Nombre del equipo {letra}: ").strip()
        nombres[letra] = respuesta if respuesta else letra
        entradas_crudas.append(respuesta)
    return nombres, entradas_crudas


def parsear_rotacion(entrada: str) -> tuple[list[int], int]:
    """Convierte "28_S 5 13 88 3 40" en ([28, 5, 13, 88, 3, 40], 28).

    Los jugadores van en el orden de las zonas 1 a 6 de la cancha, y exactamente
    uno lleva la marca _S para indicar que es el armador. Si algo no cuadra
    levanta ValueError con el motivo, para que el que pregunta lo muestre."""
    partes = entrada.replace(",", " ").replace("/", " ").split()
    if len(partes) != CANTIDAD_ROTACION:
        raise ValueError(
            f"Tienen que ser {CANTIDAD_ROTACION} jugadores (zonas 1 a 6), vinieron {len(partes)}."
        )

    jugadores: list[int] = []
    armadores: list[int] = []
    for parte in partes:
        numero_texto = parte
        es_armador = parte.upper().endswith(MARCA_ARMADOR)
        if es_armador:
            numero_texto = parte[: -len(MARCA_ARMADOR)]
        if not numero_texto.isdigit():
            raise ValueError(f"'{parte}' no es un numero de jugador valido.")
        numero = int(numero_texto)
        if numero in jugadores:
            raise ValueError(f"El jugador {numero} esta repetido en la rotacion.")
        jugadores.append(numero)
        if es_armador:
            armadores.append(numero)

    if len(armadores) != 1:
        raise ValueError(
            f"Marca exactamente un armador con {MARCA_ARMADOR} "
            f"(se marcaron {len(armadores)})."
        )
    return jugadores, armadores[0]


def preguntar_rotacion(nombre_equipo: str) -> tuple[dict | None, str]:
    """Pide la rotacion de un equipo. Devuelve (rotacion, entrada_cruda), con
    rotacion en None si se dejo vacio."""
    print(f"  Rotacion de {nombre_equipo}: {CANTIDAD_ROTACION} jugadores en las zonas 1 a 6.")
    print(f"    La zona 1 es la que saca primero. Marca al armador con {MARCA_ARMADOR}.")
    print("    Ejemplo: 28_S 5 13 88 3 40   (vacio = sin rotacion)")
    while True:
        entrada = input(f"  [Rotacion {nombre_equipo}]: ").strip()
        if not entrada:
            # sin rotacion: se sigue como antes, con el numero del sacador obligatorio
            return None, entrada
        try:
            jugadores, armador = parsear_rotacion(entrada)
        except ValueError as error:
            print(f"    {error}")
            continue
        return {"jugadores": jugadores, "armador": armador}, entrada


def preguntar_rotaciones(nombres: dict) -> tuple[dict, list[str]]:
    """Rotacion de los dos equipos. Devuelve (rotaciones, entradas_crudas)."""
    print("\nRotacion inicial de cada equipo:")
    rotaciones = {}
    entradas_crudas = []
    for letra in sorted(EQUIPOS):
        with _esperando({"que": "rotacion", "equipo": letra}):
            rotacion, entrada = preguntar_rotacion(nombres[letra])
        if rotacion is not None:
            rotaciones[letra] = rotacion
        entradas_crudas.append(entrada)
    return rotaciones, entradas_crudas


def copiar_rotaciones(rotaciones: dict) -> dict:
    """Copia independiente, para guardar la formacion inicial de un set sin que
    los cambios posteriores la modifiquen."""
    return {
        letra: {"jugadores": list(rotacion["jugadores"]), "armador": rotacion["armador"]}
        for letra, rotacion in rotaciones.items()
    }


def aplicar_cambio(
    rotaciones: dict, entrada: str, nombres: dict | None = None,
    puntos: list[dict] | None = None, numero_set: int = 1,
) -> dict | None:
    """Aplica un cambio "C_entra_sale" sobre la rotacion del equipo al que
    pertenece el jugador que sale: el que entra ocupa su misma zona.

    Con un _S sobre el que entra ("C_7_S_28") el cambio es de armador: el que
    entra pasa a ser el armador del equipo aunque el que sale no lo fuera, y el
    armador anterior deja de serlo. Sin la marca, el que entra hereda el rol
    solo si esta reemplazando justamente al armador, para que el equipo nunca
    se quede sin uno.

    Devuelve el registro del cambio, o None si no se pudo aplicar (en ese caso
    ya se explico el motivo por pantalla)."""
    nombres = nombres or {"A": "A", "B": "B"}
    coincidencia = PATRON_CAMBIO.match(entrada)
    if coincidencia is None:
        return None

    entra = int(coincidencia.group("entra"))
    sale = int(coincidencia.group("sale"))
    if entra == sale:
        print(f"  El jugador {entra} no puede entrar y salir a la vez.")
        return None
    if not rotaciones:
        print("  No hay rotacion cargada, asi que no se pueden registrar cambios.")
        return None

    equipos = [letra for letra, rotacion in rotaciones.items() if sale in rotacion["jugadores"]]
    if not equipos:
        print(f"  El jugador {sale} no esta en cancha en ninguno de los dos equipos.")
        return None
    if len(equipos) > 1:
        # el mismo numero en los dos equipos: hay que desempatar
        equipo = preguntar_equipo(
            f"  Los dos equipos tienen al jugador {sale}. De cual sale? "
            f"A) {nombres['A']}  B) {nombres['B']}: ",
            nombres,
        )
    else:
        equipo = equipos[0]

    rotacion = rotaciones[equipo]
    if entra in rotacion["jugadores"]:
        print(f"  El jugador {entra} ya esta en cancha en {nombres[equipo]}.")
        return None

    # El que entra toma el lugar del que sale en el orden de rotacion, asi que
    # el turno de saque no se altera. La zona que se informa es donde esta
    # parado ahora, que no es la inicial si el equipo ya roto.
    posicion = rotacion["jugadores"].index(sale)
    rotacion["jugadores"][posicion] = entra
    giros = veces_que_roto(puntos or [], numero_set, equipo)
    zona = (posicion - giros) % len(rotacion["jugadores"]) + 1

    armador_previo = rotacion["armador"]
    # marcado con _S, o reemplazando al armador (para no quedarse sin uno)
    entra_de_armador = coincidencia.group("marca_armador") is not None or armador_previo == sale
    if entra_de_armador:
        rotacion["armador"] = entra
    # solo se avisa del armador desplazado si sigue en cancha; si era el que
    # salio, ya se entiende del propio cambio
    armador_desplazado = armador_previo if entra_de_armador and armador_previo != sale else None

    detalle = ""
    if entra_de_armador:
        detalle = " y pasa a ser el armador"
        if armador_desplazado is not None:
            detalle += f" (deja de serlo el {armador_desplazado})"
    print(f"  Cambio en {nombres[equipo]}: entra el {entra} por el {sale} (zona {zona}){detalle}.")
    return {
        "equipo": equipo, "entra": entra, "sale": sale, "zona": zona,
        "armador": entra_de_armador, "armador_desplazado": armador_desplazado,
    }


def veces_que_roto(puntos: list[dict], numero_set: int, equipo: str) -> int:
    """Cuantas veces roto el equipo en el set: una por cada saque que recupero.

    Se cuenta sobre los puntos en vez de llevarlo en una variable para que
    deshacer un punto devuelva la rotacion sola, igual que el marcador."""
    return sum(
        1 for punto in puntos
        if punto.get("set", 1) == numero_set
        and punto["equipo_gana"] == equipo
        and punto["equipo_saca"] != equipo
    )


def rotar(jugadores: list[int], veces: int = 1) -> list[int]:
    """Gira la formacion: el de zona 2 pasa a la 1, el de la 3 a la 2, y asi
    hasta que el de la 1 pasa a la 6. La lista va siempre en orden de zonas."""
    if not jugadores:
        return []
    veces %= len(jugadores)
    return jugadores[veces:] + jugadores[:veces]


def rotacion_en_cancha(
    rotaciones: dict, puntos: list[dict], numero_set: int, equipo: str
) -> list[int] | None:
    """Como esta parado el equipo ahora mismo, en orden de zonas 1 a 6.

    La rotacion que se cargo al empezar es la formacion inicial; a partir de
    ahi el equipo gira una posicion cada vez que recupera el saque."""
    rotacion = (rotaciones or {}).get(equipo)
    if not rotacion:
        return None
    return rotar(rotacion["jugadores"], veces_que_roto(puntos, numero_set, equipo))


def jugador_que_saca(rotaciones: dict, puntos: list[dict], numero_set: int, equipo: str) -> int | None:
    """Numero del jugador al que le toca sacar: el que quedo en la zona 1."""
    en_cancha = rotacion_en_cancha(rotaciones, puntos, numero_set, equipo)
    return en_cancha[0] if en_cancha else None


def zona_del_armador(rotaciones: dict, puntos: list[dict], numero_set: int, equipo: str) -> int | None:
    """En que zona esta parado el armador (el del flag _S) en este momento.

    Es la forma habitual de nombrar las rotaciones: no importa quien saca sino
    donde esta el armador, porque de eso depende si arma de adelante o de
    atras y con cuantos atacantes cuenta."""
    en_cancha = rotacion_en_cancha(rotaciones, puntos, numero_set, equipo)
    rotacion = (rotaciones or {}).get(equipo)
    if not en_cancha or not rotacion:
        return None
    armador = rotacion["armador"]
    return en_cancha.index(armador) + 1 if armador in en_cancha else None


def preguntar_equipo(mensaje: str, nombres: dict | None = None) -> str:
    """Pide una letra de equipo (A/B). Tambien acepta el nombre elegido para ese equipo."""
    nombres = nombres or {}
    alias = {nombre.lower(): letra for letra, nombre in nombres.items()}
    while True:
        respuesta = input(mensaje).strip()
        letra = respuesta.upper()
        if letra in EQUIPOS:
            return letra
        letra = alias.get(respuesta.lower())
        if letra:
            return letra
        print(f"  Respuesta invalida, ingresa {' o '.join(sorted(EQUIPOS))}.")


def otro_equipo(equipo: str) -> str:
    return "B" if equipo == "A" else "A"


def _recalcular_estado_punto(equipo_saca: str, secuencia: list[dict]) -> tuple:
    """Recalcula (equipo_atacante, equipo_defensor, tipo_resultado) repasando los
    bloques ya cargados de un punto. Se usa para deshacer la ultima jugada sin
    tener que llevar un historial de estados aparte."""
    equipo_recibe = otro_equipo(equipo_saca)
    equipo_atacante = equipo_recibe
    equipo_defensor = equipo_saca
    tipo_resultado = secuencia[0]["resultado"]

    for bloque in secuencia[1:]:
        if tipo_resultado in ("D", "F", "V", "T", "K"):
            equipo_atacante, equipo_defensor = equipo_defensor, equipo_atacante
        tipo_resultado = bloque["resultado"]

    return equipo_atacante, equipo_defensor, tipo_resultado


def jugar_punto(
    equipo_saca: str, nombres: dict | None = None, jugador_saca: int | None = None
) -> tuple | None:
    """Pide por consola las jugadas de un punto completo.

    "jugador_saca" es el numero que la rotacion dice que tiene que sacar. Si se
    pasa, el numero en el comando de saque queda opcional (se completa solo) y
    si viene uno distinto se rechaza la jugada.
    Devuelve:
      - (equipo_ganador, secuencia_de_bloques, entradas_crudas) si se completo el punto
        (incluye el caso "f": error en juego, punto directo para el adversario
        de quien tenia que jugar en ese momento)
      - ("CAMBIO_SET", entrada) si se pidio cambiar de set (escribiendo "w")
      - ("DESHACER", entrada) si se pidio deshacer sin nada cargado todavia de
        este punto (escribiendo "x"): hay que deshacer el punto anterior
      - None si se pidio salir"""
    nombres = nombres or {"A": "A", "B": "B"}
    equipo_recibe = otro_equipo(equipo_saca)

    while True:  # permite reiniciar el punto si se deshace hasta el saque
        secuencia = []
        entradas_crudas = []
        # De quien es la pelota vive solo aca adentro: es el resultado de ir
        # repasando los bloques ya cargados, no un dato guardado. Si la carga
        # se corta este dict es lo unico que sobrevive (ver _esperando), y sin
        # el la pantalla no sabria si pedir un saque o una continuacion.
        espera = {
            "que": "saque", "equipo": equipo_saca, "jugador": jugador_saca,
            "equipo_con_la_pelota": equipo_saca,
            "jugadas": secuencia, "entradas": entradas_crudas,
        }

        etiqueta_saque = nombres[equipo_saca]
        if jugador_saca is not None:
            etiqueta_saque += f", saca el {jugador_saca}"

        while True:
            with _esperando(espera):
                entrada = input(f"\n[Saca {etiqueta_saque}] Jugada: ").strip()
            if entrada.lower() in COMANDOS_SALIDA:
                return None
            if entrada.lower() == COMANDO_CAMBIO_SET:
                return "CAMBIO_SET", entrada
            if entrada.lower() == COMANDO_DESHACER:
                return "DESHACER", entrada
            if entrada.lower() == COMANDO_ERROR_JUEGO:
                # falta del equipo que tenia que sacar: punto directo para el otro
                return equipo_recibe, [], [entrada]
            if PATRON_CAMBIO.match(entrada):
                return "CAMBIO", entrada
            bloque = parsear_bloque_saque(entrada)
            if bloque is None:
                print("  Formato invalido. Ejemplos: 5_1_6_A | 5_1_6_E | 5_1_6_X/3_3/2_4/4_1_P")
                continue
            if jugador_saca is None:
                if bloque["sacador"] is None:
                    print("  Falta el numero del sacador (sin rotacion cargada no se puede completar solo).")
                    continue
            elif bloque["sacador"] is None:
                bloque["sacador"] = jugador_saca  # se completa con la rotacion
            elif bloque["sacador"] != jugador_saca:
                print(
                    f"  Saca el jugador {jugador_saca}, no el {bloque['sacador']}. "
                    f"Corregi el numero o escribilo sin el (ej. {bloque['zona_saque']}_{bloque['zona_destino_saque']}_...)."
                )
                continue
            break

        entradas_crudas.append(entrada)
        bloque["equipo_receptor"] = equipo_recibe if bloque.get("receptor") is not None else None
        bloque["equipo_set"] = equipo_recibe if bloque.get("zona_colocacion") is not None else None
        bloque["equipo_atacante"] = equipo_recibe if bloque.get("atacante") is not None else None
        # el bloqueo lo hace el equipo que NO esta atacando: aca ataca el que recibe
        bloque["equipo_bloqueo"] = equipo_saca if bloque.get("jugador_bloqueo") is not None else None
        secuencia.append(bloque)
        print(f"  OK: {describir_bloque_saque(bloque)}")

        if bloque["resultado_saque"] == "A":
            return equipo_saca, secuencia, entradas_crudas
        if bloque["resultado_saque"] == "E":
            return equipo_recibe, secuencia, entradas_crudas

        equipo_atacante = equipo_recibe
        equipo_defensor = equipo_saca
        tipo_resultado = bloque["resultado"]
        reiniciar_punto = False

        while tipo_resultado in ("D", "R", "F", "V", "T", "K"):
            if tipo_resultado in ("D", "F", "V", "T", "K"):
                # el equipo que defendio (o que recibe el libre/overpass/toque) pasa a atacar
                equipo_atacante, equipo_defensor = equipo_defensor, equipo_atacante
            # si es "R" (bloqueo rejugable) el equipo atacante no cambia: recupera
            # el control y tiene que volver a recibir/armar/atacar
            espera.update(que="continuacion", equipo=equipo_atacante, jugador=None,
                          equipo_con_la_pelota=equipo_atacante)

            while True:
                with _esperando(espera):
                    entrada = input(f"[Juega {nombres[equipo_atacante]}] Jugada: ").strip()
                if entrada.lower() in COMANDOS_SALIDA:
                    return None
                if entrada.lower() == COMANDO_ERROR_JUEGO:
                    # falta del equipo que tenia el control: punto directo para el otro
                    entradas_crudas.append(entrada)
                    return equipo_defensor, secuencia, entradas_crudas
                if entrada.lower() == COMANDO_DESHACER:
                    break
                if PATRON_CAMBIO.match(entrada):
                    print("  Los cambios se hacen entre puntos, en el prompt [Saca ...].")
                    continue
                bloque_defensa = parsear_bloque_defensa(entrada)
                if bloque_defensa is None:
                    print("  Formato invalido. Ejemplo: 7_2/1_5/9_5_D")
                    continue
                break

            if entrada.lower() == COMANDO_DESHACER:
                if len(secuencia) > 1:
                    secuencia.pop()
                    entradas_crudas.pop()
                    equipo_atacante, equipo_defensor, tipo_resultado = _recalcular_estado_punto(
                        equipo_saca, secuencia
                    )
                    print("  Deshecho: se elimino la ultima jugada del punto.")
                    continue
                # no hay ninguna continuacion cargada: se cancela el punto entero
                # (incluido el saque) y se vuelve a pedir desde cero
                print("  Deshecho: se cancela el punto, volvemos a pedir el saque.")
                reiniciar_punto = True
                break

            entradas_crudas.append(entrada)
            bloque_defensa["equipo_set"] = (
                equipo_atacante if bloque_defensa.get("zona_colocacion") is not None else None
            )
            bloque_defensa["equipo_atacante"] = (
                equipo_atacante if bloque_defensa.get("atacante") is not None else None
            )
            bloque_defensa["equipo_bloqueo"] = (
                equipo_defensor if bloque_defensa.get("jugador_bloqueo") is not None else None
            )
            secuencia.append(bloque_defensa)
            print(f"  OK: {describir_bloque_defensa(bloque_defensa)}")

            tipo_resultado = bloque_defensa["resultado"]

        if reiniciar_punto:
            continue

        equipo_ganador = equipo_defensor if tipo_resultado in ("B", "O", "M", "L", "N") else equipo_atacante
        return equipo_ganador, secuencia, entradas_crudas


def calcular_estadisticas_armado(puntos: list[dict]) -> dict:
    """% de armadas de cada equipo hacia cada grupo de zona (1-2 / 6-5 / 3 / 4)."""
    conteo = {equipo: {grupo: 0 for grupo in GRUPOS_ZONA_ARMADO} for equipo in EQUIPOS}
    total = {equipo: 0 for equipo in EQUIPOS}

    for punto in puntos:
        for bloque in punto["jugadas"]:
            equipo_set = bloque.get("equipo_set")
            zona = bloque.get("zona_colocacion")
            if equipo_set is None or zona is None:
                continue
            if not bloque.get("armado_valido", True):
                continue
            grupo = ZONA_A_GRUPO[zona]
            conteo[equipo_set][grupo] += 1
            total[equipo_set] += 1

    estadisticas = {}
    for equipo in EQUIPOS:
        estadisticas[equipo] = {}
        for grupo in GRUPOS_ZONA_ARMADO:
            cantidad = conteo[equipo][grupo]
            porcentaje = (cantidad / total[equipo] * 100) if total[equipo] else 0.0
            estadisticas[equipo][grupo] = (cantidad, porcentaje)
    return estadisticas


# Fases del rally. K1/K2/K3 son las que pidio el club; las otras dos existen
# para que los totales cierren con el marcador en vez de meter a la fuerza en
# K1 los puntos que nunca llegaron a una recepcion.
FASES_RALLY = ("K1", "K2", "K3", "Saque", "Sin fase")

# Codigos con los que el rally sigue: si el ultimo bloque cargado termina en
# uno de estos, el punto se definio despues, por un error en juego ("f").
RESULTADOS_QUE_SIGUEN = ("D", "R", "F", "V", "T", "K")


def _bloque_cierra_el_punto(bloque: dict) -> bool:
    if bloque.get("resultado_saque") in ("A", "E"):
        return True
    return bloque.get("resultado") not in RESULTADOS_QUE_SIGUEN


def fase_del_punto(punto: dict) -> str:
    """En que fase del rally se definio el punto.

    K1 es el primer bloque: recepcion, armado y ataque del que recibe.
    K2 es el segundo: la primera defensa del rally, su armado y su ataque.
    K3 es de ahi en adelante. Un as o un error de saque no llegan a tener
    recepcion, asi que van aparte en "Saque"; un error en juego sin ninguna
    jugada cargada queda en "Sin fase"."""
    jugadas = punto["jugadas"]
    if not jugadas:
        return "Sin fase"

    if _bloque_cierra_el_punto(jugadas[-1]):
        indice = len(jugadas) - 1
    else:
        # el ultimo bloque dejaba la pelota en juego: el punto lo definio un
        # error en juego, ya dentro de la fase siguiente
        indice = len(jugadas)

    if indice == 0:
        return "Saque" if jugadas[0].get("resultado_saque") in ("A", "E") else "K1"
    return "K2" if indice == 1 else "K3"


# Como se cerro el rally. Se separan los puntos que gano alguien haciendo algo
# de los que llegaron porque el otro se equivoco: no es lo mismo un ataque
# punto que un ataque del rival que se fue afuera.
CAUSAS_GANADAS = {
    "P": "Ataque punto",
    "U": "Ataque usando el bloqueo",
    "B": "Bloqueo punto",
    "A": "As de saque",
}
CAUSAS_ERROR = {
    "O": "Ataque afuera",
    "M": "Ataque a la malla",
    "E": "Error de saque",
    "N": "Armado malo",
    "L": "Defensa perdida",
    "EJ": "Error en juego",
}
CAUSAS_PUNTO = {**CAUSAS_GANADAS, **CAUSAS_ERROR}


def causa_del_punto(punto: dict) -> str:
    """Con que accion se cerro el rally. "EJ" es el error en juego ("f"), que
    no deja bloque cargado."""
    jugadas = punto["jugadas"]
    if not jugadas:
        return "EJ"

    ultimo = jugadas[-1]
    if ultimo.get("resultado_saque") in ("A", "E"):
        return ultimo["resultado_saque"]

    resultado = ultimo.get("resultado")
    if resultado is None or resultado in RESULTADOS_QUE_SIGUEN:
        # el ultimo bloque dejaba la pelota en juego: lo corto un error
        return "EJ"
    return resultado


def calcular_puntos_por_fase(puntos: list[dict]) -> dict:
    """Puntos que hizo y que recibio cada equipo, por fase del rally, separando
    los que se ganaron de los que llegaron por error del que perdio.

    Devuelve {equipo: {"hechos"|"recibidos": {fase: {total, ganados, error}}}}.
    Los "recibidos" de un equipo son los "hechos" del otro en la misma fase, y
    cada total cierra con el marcador."""
    datos = {
        equipo: {
            clase: {fase: {"total": 0, "ganados": 0, "error": 0} for fase in FASES_RALLY}
            for clase in ("hechos", "recibidos")
        }
        for equipo in EQUIPOS
    }

    for punto in puntos:
        fase = fase_del_punto(punto)
        clave = "error" if causa_del_punto(punto) in CAUSAS_ERROR else "ganados"
        gana = punto["equipo_gana"]
        for equipo, clase in ((gana, "hechos"), (otro_equipo(gana), "recibidos")):
            datos[equipo][clase][fase]["total"] += 1
            datos[equipo][clase][fase][clave] += 1

    return datos


ZONAS_ARMADOR = (1, 2, 3, 4, 5, 6)

# En este desglose el saque va partido en dos, porque un as y un error de saque
# del rival no son la misma situacion: en el as sacabamos nosotros y en el
# error sacaban ellos. Juntarlos hacia leer 5 aces donde habia 1.
COLUMNAS_ZONA_ARMADOR = ("K1", "K2", "K3", "As", "Error de saque", "Sin fase")


def _columna_zona_armador(punto: dict) -> str:
    fase = fase_del_punto(punto)
    if fase != "Saque":
        return fase
    return "As" if causa_del_punto(punto) == "A" else "Error de saque"


def calcular_puntos_por_zona_armador(puntos: list[dict]) -> dict:
    """Puntos hechos y recibidos segun en que zona estaba el armador propio,
    abiertos por fase del rally.

    Las columnas no son exactamente las fases: el saque va separado en "As" y
    "Error de saque" (ver COLUMNAS_ZONA_ARMADOR). Los puntos cargados sin
    rotacion no tienen zona y quedan afuera."""
    datos = {
        equipo: {
            zona: {clase: {col: 0 for col in COLUMNAS_ZONA_ARMADOR}
                   for clase in ("hechos", "recibidos")}
            for zona in ZONAS_ARMADOR
        }
        for equipo in EQUIPOS
    }

    for punto in puntos:
        fase = _columna_zona_armador(punto)
        gana = punto["equipo_gana"]
        zonas = punto.get("zona_armador") or {}
        for equipo in EQUIPOS:
            zona = zonas.get(equipo)
            if zona is None:
                continue
            clase = "hechos" if equipo == gana else "recibidos"
            datos[equipo][zona][clase][fase] += 1

    return datos


def calcular_puntos_por_causa(puntos: list[dict]) -> dict:
    """El detalle de la clasificacion anterior: con que accion concreta se
    cerro cada punto. {equipo: {"hechos"|"recibidos": {causa: cantidad}}}."""
    datos = {
        equipo: {clase: {causa: 0 for causa in CAUSAS_PUNTO} for clase in ("hechos", "recibidos")}
        for equipo in EQUIPOS
    }

    for punto in puntos:
        causa = causa_del_punto(punto)
        gana = punto["equipo_gana"]
        datos[gana]["hechos"][causa] += 1
        datos[otro_equipo(gana)]["recibidos"][causa] += 1

    return datos


def calcular_estadisticas_armado_por_set(puntos: list[dict]) -> dict:
    """El mismo desglose que calcular_estadisticas_armado pero separado por set.
    Devuelve {numero_de_set: {equipo: {grupo_de_zona: (cantidad, porcentaje)}}}."""
    numeros = sorted({punto.get("set", 1) for punto in puntos})
    return {
        numero: calcular_estadisticas_armado(
            [punto for punto in puntos if punto.get("set", 1) == numero]
        )
        for numero in numeros
    }


def calcular_armado_por_armador(puntos: list[dict]) -> dict:
    """Armados por jugador y zona, separado por equipo.

    Devuelve {equipo: {jugador: {"total": n, "zonas": {grupo: (cantidad, %)}}}}.
    Incluye a todos los que armaron; filtrar por los marcados con _S es cosa de
    quien lo muestra, porque el armador de turno tambien puede ser cubierto por
    cualquier otro jugador cuando el armador defiende la pelota."""
    conteo = {equipo: {} for equipo in EQUIPOS}

    for punto in puntos:
        for bloque in punto["jugadas"]:
            equipo_set = bloque.get("equipo_set")
            zona = bloque.get("zona_colocacion")
            colocador = bloque.get("colocador")
            if equipo_set is None or zona is None or colocador is None:
                continue
            if not bloque.get("armado_valido", True):
                continue
            zonas = conteo[equipo_set].setdefault(
                colocador, {grupo: 0 for grupo in GRUPOS_ZONA_ARMADO}
            )
            zonas[ZONA_A_GRUPO[zona]] += 1

    estadisticas = {}
    for equipo in EQUIPOS:
        estadisticas[equipo] = {}
        for colocador, zonas in conteo[equipo].items():
            total = sum(zonas.values())
            estadisticas[equipo][colocador] = {
                "total": total,
                "zonas": {
                    grupo: (zonas[grupo], (zonas[grupo] / total * 100) if total else 0.0)
                    for grupo in GRUPOS_ZONA_ARMADO
                },
            }
    return estadisticas


def calcular_armado_por_armador_por_set(puntos: list[dict]) -> dict:
    """calcular_armado_por_armador separado por set."""
    numeros = sorted({punto.get("set", 1) for punto in puntos})
    return {
        numero: calcular_armado_por_armador(
            [punto for punto in puntos if punto.get("set", 1) == numero]
        )
        for numero in numeros
    }


def calcular_estadisticas_recepcion(puntos: list[dict]) -> dict:
    """Cantidad de recepciones y % de calidad (-1 a 3) por jugador, separado por equipo."""
    conteo = {equipo: {} for equipo in EQUIPOS}
    for punto in puntos:
        for bloque in punto["jugadas"]:
            receptor = bloque.get("receptor")
            calidad = bloque.get("calidad_recepcion")
            equipo = bloque.get("equipo_receptor")
            if receptor is None or calidad is None or equipo is None:
                continue
            conteo[equipo].setdefault(receptor, {-1: 0, 0: 0, 1: 0, 2: 0, 3: 0})
            conteo[equipo][receptor][calidad] += 1

    estadisticas = {equipo: {} for equipo in EQUIPOS}
    for equipo, jugadores in conteo.items():
        for jugador, cantidades in jugadores.items():
            total = sum(cantidades.values())
            estadisticas[equipo][jugador] = {
                "total": total,
                "calidades": {
                    calidad: (cantidad, (cantidad / total * 100) if total else 0.0)
                    for calidad, cantidad in cantidades.items()
                },
            }
    return estadisticas


def calcular_estadisticas_recepcion_por_set(puntos: list[dict]) -> dict:
    """El mismo desglose que calcular_estadisticas_recepcion pero separado por
    set. Devuelve {numero_de_set: {equipo: {jugador: {...}}}}."""
    numeros = sorted({punto.get("set", 1) for punto in puntos})
    return {
        numero: calcular_estadisticas_recepcion(
            [punto for punto in puntos if punto.get("set", 1) == numero]
        )
        for numero in numeros
    }


def calcular_armado_por_calidad_recepcion(puntos: list[dict]) -> dict:
    """Estadistica GLOBAL de equipo (no por jugador): para cada calidad de
    recepcion (-1 a 3), a que zona fue el armado resultante."""
    conteo = {equipo: {calidad: {} for calidad in (-1, 0, 1, 2, 3)} for equipo in EQUIPOS}

    for punto in puntos:
        for bloque in punto["jugadas"]:
            calidad = bloque.get("calidad_recepcion")
            equipo = bloque.get("equipo_receptor")
            zona_colocacion = bloque.get("zona_colocacion")
            if calidad is None or equipo is None:
                continue
            if zona_colocacion is None or not bloque.get("armado_valido", True):
                continue
            grupo = ZONA_A_GRUPO[zona_colocacion]
            zonas = conteo[equipo][calidad]
            zonas[grupo] = zonas.get(grupo, 0) + 1

    return conteo


def calcular_armado_por_calidad_recepcion_por_armador(puntos: list[dict]) -> dict:
    """La misma matriz calidad de recepcion x zona armada, pero abierta por el
    jugador que armo. Devuelve {equipo: {colocador: {calidad: {zona: cant}}}}."""
    conteo = {equipo: {} for equipo in EQUIPOS}

    for punto in puntos:
        for bloque in punto["jugadas"]:
            calidad = bloque.get("calidad_recepcion")
            equipo = bloque.get("equipo_receptor")
            zona_colocacion = bloque.get("zona_colocacion")
            colocador = bloque.get("colocador")
            if calidad is None or equipo is None or colocador is None:
                continue
            if zona_colocacion is None or not bloque.get("armado_valido", True):
                continue
            calidades = conteo[equipo].setdefault(
                colocador, {c: {} for c in (-1, 0, 1, 2, 3)}
            )
            grupo = ZONA_A_GRUPO[zona_colocacion]
            calidades[calidad][grupo] = calidades[calidad].get(grupo, 0) + 1

    return conteo


TIPOS_SAQUE = ("paralelo", "cruzado")

# Clasificacion de saque segun zona de origen (1/6/5) y zona de destino.
# Ojo: las zonas se numeran desde cada lado, asi que la zona 1 de un lado
# queda enfrentada a la zona 5 del otro (y la 6 enfrentada a la 6):
#   paralelo -> el saque va derecho, a la zona que tiene enfrente
#               (1 a 5, 5 a 1, 6 a 6)
#   cruzado  -> el saque va en diagonal (1 a 1, 5 a 5, 6 a 1, 6 a 5)
# Los saques hacia el resto de las zonas (2, 3, 4, 7, 8, 9) no entran en
# ninguna de las dos categorias y no se cuentan en esta estadistica.
PARES_POR_TIPO_SAQUE = {
    "paralelo": (("1", "5"), ("5", "1"), ("6", "6")),
    "cruzado": (("1", "1"), ("5", "5"), ("6", "1"), ("6", "5")),
}

PAR_A_TIPO_SAQUE = {
    par: tipo for tipo, pares in PARES_POR_TIPO_SAQUE.items() for par in pares
}


def _tipo_saque(zona_saque, zona_destino_saque) -> str | None:
    return PAR_A_TIPO_SAQUE.get((zona_saque, zona_destino_saque))


def _etiqueta_par_saque(zona_saque, zona_destino_saque) -> str:
    return f"{zona_saque} a {zona_destino_saque}"


def calcular_recepcion_por_tipo_saque(puntos: list[dict]) -> dict:
    """Estadistica GLOBAL de equipo (no por jugador): calidad de recepcion
    (-1 a 3) del equipo que RECIBE, desglosada por tipo de saque (paralelo /
    cruzado) y, dentro de cada tipo, por el par concreto de zonas
    (ej. "1 a 1", "6 a 5")."""
    conteo = {
        equipo: {
            tipo: {
                _etiqueta_par_saque(*par): {-1: 0, 0: 0, 1: 0, 2: 0, 3: 0}
                for par in pares
            }
            for tipo, pares in PARES_POR_TIPO_SAQUE.items()
        }
        for equipo in EQUIPOS
    }

    for punto in puntos:
        for bloque in punto["jugadas"]:
            calidad = bloque.get("calidad_recepcion")
            equipo = bloque.get("equipo_receptor")
            if calidad is None or equipo is None:
                continue
            zona_saque = bloque.get("zona_saque")
            zona_destino = bloque.get("zona_destino_saque")
            tipo = _tipo_saque(zona_saque, zona_destino)
            if tipo is None:
                continue
            etiqueta = _etiqueta_par_saque(zona_saque, zona_destino)
            conteo[equipo][tipo][etiqueta][calidad] += 1

    return conteo


ZONAS_DESTINO_ATAQUE = (1, 5, 6)

# Como se clasifica cada resultado de ataque a efectos de estas estadisticas:
#   efectivo  -> P (punto directo) y U (toque de bloqueo, punto igual para el ataque)
#   defendido -> D (defendido) y R (bloqueo rejugable, sigue el mismo equipo)
#   fuera     -> O (se va afuera), M (a la malla) y B (bloqueado, punto para el bloqueo)
#   (F, el libre, no cuenta como ataque; las pasadas de segunda tampoco, se
#   filtran aparte por el flag "es_segunda")
_CLASE_POR_RESULTADO = {
    "P": "efectivo", "U": "efectivo",
    "D": "defendido", "R": "defendido",
    "O": "fuera", "M": "fuera", "B": "fuera",
}


def calcular_estadisticas_ataque(puntos: list[dict]) -> dict:
    """Ataques por jugador (efectivos/defendidos/fuera), desglosados por zona de
    armado de origen y zona de destino del ataque, separado por equipo."""
    datos = {equipo: {} for equipo in EQUIPOS}

    def _registro_jugador(equipo, jugador):
        return datos[equipo].setdefault(jugador, {
            "efectivo": 0, "defendido": 0, "fuera": 0,
            "zonas": {
                grupo: {
                    "efectivo": 0, "defendido": 0, "fuera": 0,
                    "destinos": {
                        zona: {"efectivo": 0, "defendido": 0, "fuera": 0}
                        for zona in ZONAS_DESTINO_ATAQUE
                    },
                }
                for grupo in GRUPOS_ZONA_ARMADO
            },
        })

    for punto in puntos:
        for bloque in punto["jugadas"]:
            atacante = bloque.get("atacante")
            equipo = bloque.get("equipo_atacante")
            if atacante is None or equipo is None:
                continue
            if bloque.get("es_segunda"):
                continue  # toque de segunda (tip): no es un ataque real
            clase = _CLASE_POR_RESULTADO.get(bloque.get("resultado"))
            if clase is None:
                continue  # libre (F) u otro caso que no cuenta como ataque

            registro = _registro_jugador(equipo, atacante)
            registro[clase] += 1

            zona_colocacion = bloque.get("zona_colocacion")
            zona_ataque = bloque.get("zona_ataque")
            if zona_colocacion is None or zona_ataque is None:
                continue  # ej. ataque de primera: no hay zona de armado de origen

            zona_ataque_int = int(zona_ataque)
            datos_zona = registro["zonas"][ZONA_A_GRUPO[zona_colocacion]]
            datos_zona[clase] += 1
            datos_zona["destinos"][zona_ataque_int][clase] += 1

    return datos


def calcular_estadisticas_bloqueo(puntos: list[dict]) -> dict:
    """Bloqueos que son punto por jugador, separado por equipo.

    Solo cuenta el resultado "B" (bloqueo directo, punto para el que bloquea).
    Los otros dos toques de bloqueo no entran porque no son punto de quien
    bloquea: "U" es punto del atacante y "R" deja la pelota en juego."""
    datos = {equipo: {} for equipo in EQUIPOS}

    for punto in puntos:
        for bloque in punto["jugadas"]:
            if bloque.get("resultado") != "B":
                continue
            jugador = bloque.get("jugador_bloqueo")
            equipo = bloque.get("equipo_bloqueo")
            if jugador is None or equipo is None:
                continue
            datos[equipo][jugador] = datos[equipo].get(jugador, 0) + 1

    return datos


def _formatear_bloqueos(bloqueo: dict) -> list[str]:
    if not bloqueo:
        return ["    (sin bloqueos punto)"]

    total = sum(bloqueo.values())
    lineas = []
    for jugador in sorted(bloqueo):
        cantidad = bloqueo[jugador]
        porcentaje = (cantidad / total * 100) if total else 0.0
        lineas.append(f"  Jugador {jugador}: {cantidad} bloqueos punto ({porcentaje:.1f}%)")
    lineas.append(f"  Total: {total} bloqueos punto")
    return lineas


def _formatear_ataques_jugador(jugador: int, registro: dict) -> list[str]:
    total = registro["efectivo"] + registro["defendido"] + registro["fuera"]
    lineas = [f"  Jugador {jugador}:", f"    Ataques totales: {total}"]

    for etiqueta, clave in (("Efectivos/Punto Directo", "efectivo"), ("Defendidos", "defendido"), ("Fuera", "fuera")):
        cantidad = registro[clave]
        porcentaje = (cantidad / total * 100) if total else 0.0
        lineas.append(f"    {etiqueta}: {cantidad} ({porcentaje:.1f}%)")


    for grupo in GRUPOS_ZONA_ARMADO:
        datos_zona = registro["zonas"][grupo]
        total_zona = datos_zona["efectivo"] + datos_zona["defendido"] + datos_zona["fuera"]
        lineas.append(f"    Por zona {grupo}:")
        if total_zona == 0:
            continue
        porcentaje_zona = (total_zona / total * 100) if total else 0.0
        lineas.append(
            f"      {total_zona} ataques "
            f"({datos_zona['efectivo']}-{datos_zona['defendido']}-{datos_zona['fuera']}) "
            f"({porcentaje_zona:.1f}%)"
        )
        for zona_destino in ZONAS_DESTINO_ATAQUE:
            destino = datos_zona["destinos"][zona_destino]
            lineas.append(
                f"      Hacia zona {zona_destino}: "
                f"{destino['efectivo']}-{destino['defendido']}-{destino['fuera']}"
            )

    return lineas


def _formatear_recepciones(recepcion: dict) -> list[str]:
    """Lineas de la tabla de recepciones por jugador (se usa para el total del
    partido y para cada set)."""
    if not recepcion:
        return ["    (sin recepciones)"]

    lineas = []
    for jugador in sorted(recepcion):
        datos = recepcion[jugador]
        lineas.append(f"  Jugador {jugador}: {datos['total']} recepciones")
        for calidad in (-1, 0, 1, 2, 3):
            cantidad, porcentaje = datos["calidades"][calidad]
            etiqueta = "Pase al otro lado" if calidad == -1 else f"Calidad {calidad}"
            lineas.append(f"      {etiqueta}: {cantidad} ({porcentaje:.1f}%)")
    return lineas


def _formatear_armado_zonas(armado: dict) -> list[str]:
    return [
        f"    Zona {grupo}: {armado[grupo][0]} ({armado[grupo][1]:.1f}%)"
        for grupo in GRUPOS_ZONA_ARMADO
    ]


def _armadores_a_mostrar(datos_por_armador: dict, armadores: set | None) -> list:
    """Que jugadores listar en los desgloses por armador: los marcados con _S
    cuando se sabe quienes son, y si no (sin rotacion cargada) todos los que
    armaron."""
    if not armadores:
        return sorted(datos_por_armador)
    return [jugador for jugador in sorted(datos_por_armador) if jugador in armadores]


def _formatear_matriz_calidad_zona(calidades: dict) -> list[str]:
    if not any(calidades[calidad] for calidad in calidades):
        return ["    (sin datos)"]

    lineas = []
    for calidad in (-1, 0, 1, 2, 3):
        zonas = calidades[calidad]
        if not zonas:
            continue
        etiqueta = "Pase al otro lado" if calidad == -1 else f"Calidad {calidad}"
        lineas.append(f"  {etiqueta}:")
        for grupo in GRUPOS_ZONA_ARMADO:
            cantidad_zona = zonas.get(grupo, 0)
            if cantidad_zona:
                lineas.append(f"      Hacia zona {grupo}: {cantidad_zona}")
    return lineas


def _formatear_armadores(por_armador: dict, armadores: set | None) -> list[str]:
    """Armados por jugador, mostrando solo a los marcados con _S cuando se sabe
    quienes son. La fila "Otros jugadores" cierra la diferencia con el total del
    equipo, que incluye los armados de emergencia de cualquiera."""
    if not por_armador:
        return ["    (sin armados)"]

    total_equipo = sum(datos["total"] for datos in por_armador.values())
    elegidos = _armadores_a_mostrar(por_armador, armadores)

    lineas = []
    for jugador in elegidos:
        datos = por_armador[jugador]
        lineas.append(f"  Jugador {jugador}: {datos['total']} armados")
        for grupo in GRUPOS_ZONA_ARMADO:
            cantidad, porcentaje = datos["zonas"][grupo]
            lineas.append(f"      Zona {grupo}: {cantidad} ({porcentaje:.1f}%)")

    otros = total_equipo - sum(por_armador[jugador]["total"] for jugador in elegidos)
    if otros:
        lineas.append(f"  Otros jugadores: {otros} armados")
    if not elegidos:
        lineas.insert(0, "    (ningun armador marcado con _S armo en este tramo)")
    return lineas


def _formatear_estadisticas_equipo(
    nombre: str, armado: dict, recepcion: dict, ataque: dict, armado_calidad: dict,
    recepcion_tipo_saque: dict, recepcion_por_set: dict, bloqueo: dict,
    armado_por_set: dict, por_armador: dict, por_armador_por_set: dict,
    armadores: set | None, armado_calidad_armador: dict, fases: dict, causas: dict,
    zona_armador: dict,
) -> str:
    lineas = [f"--- {nombre} ---"]

    # Los mismos numeros se leen distinto de cada lado: lo que para el que
    # gano el punto es "error del rival", para el que lo recibio es propio.
    lineas.append("Puntos por fase del rally:")
    for clase, etiqueta in (("hechos", "Hechos"), ("recibidos", "Recibidos")):
        total = sum(datos["total"] for datos in fases[clase].values())
        lineas.append(f"  {etiqueta}: {total}")
        for fase in FASES_RALLY:
            datos = fases[clase][fase]
            porcentaje = (datos["total"] / total * 100) if total else 0.0
            lineas.append(
                f"      {fase}: {datos['total']} ({porcentaje:.1f}%)"
                f" - ganados {datos['ganados']}, por error {datos['error']}"
            )

    # La rotacion se nombra por donde esta el armador: de eso depende si arma
    # de adelante o de atras y con cuantos atacantes cuenta.
    lineas.append("Puntos con el armador en cada zona:")
    if not any(sum(d[c][col] for c in ("hechos", "recibidos") for col in COLUMNAS_ZONA_ARMADOR)
               for d in zona_armador.values()):
        lineas.append("    (sin rotacion cargada)")
    else:
        for zona in ZONAS_ARMADOR:
            lineas.append(f"  Zona {zona}:")
            for clase, etiqueta in (("hechos", "Hechos"), ("recibidos", "Recibidos")):
                por_fase = zona_armador[zona][clase]
                detalle = ", ".join(f"{col} {por_fase[col]}" for col in COLUMNAS_ZONA_ARMADOR)
                lineas.append(f"      {etiqueta}: {sum(por_fase.values())} - {detalle}")

    lineas.append("Puntos por causa:")
    for clase, etiqueta in (("hechos", "Hechos"), ("recibidos", "Recibidos")):
        total = sum(causas[clase].values())
        lineas.append(f"  {etiqueta}: {total}")
        for grupo, titulo in ((CAUSAS_GANADAS, "Ganados"), (CAUSAS_ERROR, "Por error")):
            subtotal = sum(causas[clase][causa] for causa in grupo)
            porcentaje = (subtotal / total * 100) if total else 0.0
            lineas.append(f"    {titulo}: {subtotal} ({porcentaje:.1f}%)")
            for causa, nombre_causa in grupo.items():
                lineas.append(f"        {nombre_causa}: {causas[clase][causa]}")

    lineas.append("Armado por zona:")
    lineas.extend(_formatear_armado_zonas(armado))

    if len(armado_por_set) > 1:
        for numero in sorted(armado_por_set):
            lineas.append(f"Armado por zona (set {numero}):")
            lineas.extend(_formatear_armado_zonas(armado_por_set[numero]))

    lineas.append("Armado por armador:")
    lineas.extend(_formatear_armadores(por_armador, armadores))

    if len(por_armador_por_set) > 1:
        for numero in sorted(por_armador_por_set):
            lineas.append(f"Armado por armador (set {numero}):")
            lineas.extend(_formatear_armadores(por_armador_por_set[numero], armadores))

    lineas.append("Recepciones por jugador:")
    lineas.extend(_formatear_recepciones(recepcion))

    # ademas del total del partido, el mismo desglose set por set
    if len(recepcion_por_set) > 1:
        for numero in sorted(recepcion_por_set):
            lineas.append(f"Recepciones por jugador (set {numero}):")
            lineas.extend(_formatear_recepciones(recepcion_por_set[numero]))

    lineas.append("Recepcion segun tipo de saque (global del equipo):")
    total_por_tipo_saque = {
        tipo: sum(sum(cantidades.values()) for cantidades in recepcion_tipo_saque[tipo].values())
        for tipo in TIPOS_SAQUE
    }
    if not any(total_por_tipo_saque.values()):
        lineas.append("    (sin datos)")
    else:
        for tipo in TIPOS_SAQUE:
            total_tipo = total_por_tipo_saque[tipo]
            lineas.append(f"  {tipo.capitalize()}: {total_tipo} recibidos")
            for etiqueta_par, cantidades in recepcion_tipo_saque[tipo].items():
                total_par = sum(cantidades.values())
                if not total_par:
                    continue
                lineas.append(f"    De {etiqueta_par}: {total_par} recibidos")
                for calidad in (-1, 0, 1, 2, 3):
                    cantidad = cantidades[calidad]
                    porcentaje = (cantidad / total_par * 100) if total_par else 0.0
                    etiqueta = "Pase al otro lado" if calidad == -1 else f"Calidad {calidad}"
                    lineas.append(f"        {etiqueta}: {cantidad} ({porcentaje:.1f}%)")

    lineas.append("Armado segun calidad de recepcion (global del equipo):")
    lineas.extend(_formatear_matriz_calidad_zona(armado_calidad))

    # la misma matriz abierta por armador, para ver a donde arma cada uno segun
    # como le llego la pelota
    for jugador in _armadores_a_mostrar(armado_calidad_armador, armadores):
        lineas.append(f"Armado segun calidad de recepcion (armador {jugador}):")
        lineas.extend(_formatear_matriz_calidad_zona(armado_calidad_armador[jugador]))

    lineas.append("Ataques por jugador:")
    if not ataque:
        lineas.append("    (sin ataques)")
    else:
        for jugador in sorted(ataque):
            lineas.extend(_formatear_ataques_jugador(jugador, ataque[jugador]))

    # va aparte de la tabla de ataques para no mezclarse con sus porcentajes:
    # bloquear no es atacar, y hay jugadores que bloquean sin haber atacado
    lineas.append("Bloqueos punto por jugador:")
    lineas.extend(_formatear_bloqueos(bloqueo))

    return "\n".join(lineas)


def formatear_estadisticas(
    puntos: list[dict], nombres: dict | None = None, armadores: dict | None = None
) -> str:
    """Estadisticas de armado, recepcion y ataque agrupadas por equipo: todo el A, despues todo el B.

    "armadores" es {equipo: {numeros}} con los jugadores que en algun momento
    llevaron el flag _S; sirve para acotar el desglose por armador."""
    nombres = nombres or {"A": "A", "B": "B"}
    armadores = armadores or {}
    armado = calcular_estadisticas_armado(puntos)
    recepcion = calcular_estadisticas_recepcion(puntos)
    ataque = calcular_estadisticas_ataque(puntos)
    armado_calidad = calcular_armado_por_calidad_recepcion(puntos)
    armado_calidad_armador = calcular_armado_por_calidad_recepcion_por_armador(puntos)
    fases = calcular_puntos_por_fase(puntos)
    causas = calcular_puntos_por_causa(puntos)
    zona_armador = calcular_puntos_por_zona_armador(puntos)
    recepcion_tipo_saque = calcular_recepcion_por_tipo_saque(puntos)
    recepcion_por_set = calcular_estadisticas_recepcion_por_set(puntos)
    bloqueo = calcular_estadisticas_bloqueo(puntos)
    armado_por_set = calcular_estadisticas_armado_por_set(puntos)
    por_armador = calcular_armado_por_armador(puntos)
    por_armador_por_set = calcular_armado_por_armador_por_set(puntos)
    secciones = [
        _formatear_estadisticas_equipo(
            nombres[equipo], armado[equipo], recepcion[equipo], ataque[equipo], armado_calidad[equipo],
            recepcion_tipo_saque[equipo],
            {numero: datos[equipo] for numero, datos in recepcion_por_set.items()},
            bloqueo[equipo],
            {numero: datos[equipo] for numero, datos in armado_por_set.items()},
            por_armador[equipo],
            {numero: datos[equipo] for numero, datos in por_armador_por_set.items()},
            armadores.get(equipo),
            armado_calidad_armador[equipo],
            fases[equipo], causas[equipo], zona_armador[equipo],
        )
        for equipo in sorted(EQUIPOS)
    ]
    return "=== Estadisticas por equipo ===\n" + "\n\n".join(secciones)


def imprimir_estadisticas(
    puntos: list[dict], nombres: dict | None = None, armadores: dict | None = None
) -> None:
    print("\n" + formatear_estadisticas(puntos, nombres, armadores))


def guardar_reporte_txt(
    entradas_totales: list[str],
    puntos: list[dict],
    marcador: dict,
    nombres: dict | None = None,
    historial_sets: list[dict] | None = None,
    sets_ganados: dict | None = None,
    rotaciones_por_set: dict | None = None,
    cambios: list[dict] | None = None,
    armadores: dict | None = None,
) -> str:
    """Escribe un .txt con todos los inputs cargados (para copiar/pegar) y las stats finales."""
    nombres = nombres or {"A": "A", "B": "B"}
    nombre_archivo = carpeta_lista(CARPETA_DATOS) / f"partido_{datetime.now():%Y%m%d_%H%M%S}.txt"

    lineas = ["=== Jugadas cargadas ==="]
    lineas.extend(entradas_totales)
    lineas.append("")
    if rotaciones_por_set:
        lineas.append("=== Rotaciones (zonas 1 a 6, S = armador) ===")
        for numero in sorted(rotaciones_por_set):
            lineas.append(f"Set {numero}:")
            for letra in sorted(EQUIPOS):
                rotacion = rotaciones_por_set[numero].get(letra)
                if not rotacion:
                    continue
                jugadores = " / ".join(
                    f"{jugador}-S" if jugador == rotacion["armador"] else str(jugador)
                    for jugador in rotacion["jugadores"]
                )
                lineas.append(f"  {nombres[letra]}: {jugadores}")
        lineas.append("")
    if cambios:
        lineas.append("=== Cambios ===")
        for cambio in cambios:
            detalle = ""
            if cambio["armador"]:
                detalle = " (queda como armador)"
                if cambio.get("armador_desplazado") is not None:
                    detalle = f" (cambio de armador: entra por el {cambio['armador_desplazado']})"
            lineas.append(
                f"Set {cambio['set']} - {nombres[cambio['equipo']]}: "
                f"entra {cambio['entra']}, sale {cambio['sale']} (zona {cambio['zona']}){detalle}"
            )
        lineas.append("")
    lineas.append("=== Resultado final ===")
    if historial_sets and len(historial_sets) > 1:
        # hubo al menos un cambio de set (comando "w")
        lineas.append(f"Sets: {nombres['A']} {sets_ganados['A']} - {sets_ganados['B']} {nombres['B']}")
        for numero, resultado_set in enumerate(historial_sets, start=1):
            lineas.append(f"  Set {numero}: {nombres['A']} {resultado_set['A']} - {resultado_set['B']} {nombres['B']}")
        lineas.append(f"Marcador del set actual: {nombres['A']} {marcador['A']} - {marcador['B']} {nombres['B']}")
    else:
        lineas.append(f"Marcador final: {nombres['A']} {marcador['A']} - {marcador['B']} {nombres['B']}")
    lineas.append(f"Total de puntos cargados: {len(puntos)}")
    lineas.append("")
    lineas.append(formatear_estadisticas(puntos, nombres, armadores))

    with open(nombre_archivo, "w", encoding="utf-8") as archivo:
        archivo.write("\n".join(lineas) + "\n")

    # Escribirlo en disco no alcanza cuando el disco es el /tmp de un
    # serverless: publicar() lo sube al blob, que es lo unico que sigue estando
    # manana. En la notebook no hace nada.
    alm.publicar(nombre_archivo)

    return str(nombre_archivo)


def preguntar_si_no(mensaje: str) -> bool:
    while True:
        respuesta = input(mensaje).strip().lower()
        if respuesta in ("s", "si", "sí", "y", "yes"):
            return True
        if respuesta in ("n", "no"):
            return False
        print("  Respuesta invalida, ingresa s o n.")

def contraseña_valida(texto) -> bool:
    """Dice si el texto es la clave de carga.

    La comparacion va con compare_digest y no con ==, que corta en la primera
    letra distinta: es la misma funcion que usa la web, donde los intentos
    llegan de afuera."""
    return secrets.compare_digest(str(texto or ""), CONTRASENA_CARGA)


def pedir_contraseña(mensaje: str) -> bool:
    """Pide la clave de carga por consola, sin mostrarla en pantalla.

    Devuelve True al primer acierto y False si se agotan los INTENTOS."""
    for intento in range(INTENTOS_CONTRASENA):
        if contraseña_valida(getpass.getpass(mensaje)):
            return True
        restantes = INTENTOS_CONTRASENA - intento - 1
        if restantes:
            print(f"  Contraseña incorrecta, quedan {restantes} intento(s).")
    return False

def generar_informe_excel(nombre_archivo_txt: str, nombres: dict) -> str | None:
    """Ofrece generar el informe Excel (generar_informe_volley.py) a partir del
    .txt recien guardado. Devuelve el nombre del .xlsx, o None si no se genero."""
    if not preguntar_si_no("\nQueres generar tambien el informe Excel? (s/n): "):
        return None

    try:
        import generar_informe_volley
    except ImportError as error:
        print(f"  No se pudo cargar generar_informe_volley.py: {error}")
        print("  (el informe Excel necesita openpyxl: pip install openpyxl)")
        return None

    mensaje = f"Para que equipo es el informe? A) {nombres['A']}  B) {nombres['B']}: "
    equipo = preguntar_equipo(mensaje, nombres)
    equipo_nombre = nombres[equipo]
    rival_nombre = nombres[otro_equipo(equipo)]

    with open(nombre_archivo_txt, encoding="utf-8") as archivo:
        parsed = generar_informe_volley.parse_volcado(archivo.read())

    if equipo_nombre not in parsed["teams"]:
        print(f"  El equipo {equipo_nombre} no aparece en el volcado, no se genera el Excel.")
        return None

    libro, avisos = generar_informe_volley.build_workbook(equipo_nombre, rival_nombre, parsed)
    fecha = (generar_informe_volley.guess_fecha_from_filename(nombre_archivo_txt)
             or f"{datetime.now():%Y-%m-%d}")
    salida = carpeta_lista(CARPETA_INFORMES) / f"Informe_{equipo_nombre}_vs_{rival_nombre}_{fecha}.xlsx"

    try:
        archivo, avisos_guardado = generar_informe_volley.guardar_informe(libro, salida)
    except PermissionError:
        print(f"  No se pudo escribir {salida.name}: cerralo en Excel si lo tenes abierto y volve a intentar.")
        return None

    print(f"  Informe Excel generado: {archivo}")
    for aviso in avisos_guardado:
        print(f"    {aviso}")
    if avisos:
        print("  Inconsistencias detectadas en el volcado:")
        for aviso in avisos:
            print(f"    - {aviso}")
    return salida


def ejecutar_partido() -> dict:
    """El loop de carga de un partido, sin imprimir el cierre ni guardar nada.

    Lee todo con input(), asi que la consola lo usa tal cual y la interfaz web
    lo alimenta con las lineas ya escritas. Devuelve el estado completo."""
    puntos = []
    entradas_por_punto = []
    entradas_totales = []
    historial_sets = []
    sets_ganados = {"A": 0, "B": 0}
    puntos_al_iniciar_set = 0
    # valores por defecto: hacen falta para poder devolver el estado aunque la
    # carga se corte antes de contestar los nombres o la rotacion
    nombres = {"A": "A", "B": "B"}
    rotaciones, rotaciones_por_set, cambios, armadores = {}, {}, [], {}
    marcador = {"A": 0, "B": 0}
    equipo_saca = "A"
    esperando = None   # que pregunta quedo sin contestar, si la carga se corto

    print("=== Carga de jugadas ===")
    print(f"Escribi {'/'.join(COMANDOS_SALIDA)} en cualquier momento para terminar.")
    print(f'Escribi "{COMANDO_CAMBIO_SET}" para cerrar el set actual y pasar al siguiente.')
    print(f'Escribi "{COMANDO_DESHACER}" solo (sin cargar nada del punto) para deshacer el punto anterior.')
    print(f'Escribi "{COMANDO_ERROR_JUEGO}" en cualquier momento para un error en juego (punto directo para el rival).')
    print('Escribi "C_entra_sale" en el prompt del saque para registrar un cambio (ej. C_7_28),')
    print('  con _S sobre el que entra si es cambio de armador (ej. C_7_S_28).\n')

    try:
        nombres, entradas_nombres = preguntar_nombres_equipos()
        entradas_totales.extend(entradas_nombres)

        rotaciones, entradas_rotaciones = preguntar_rotaciones(nombres)
        entradas_totales.extend(entradas_rotaciones)
        rotaciones_por_set = {1: copiar_rotaciones(rotaciones)} if rotaciones else {}
        cambios = []
        # todos los que en algun momento llevaron el flag _S, para el desglose por armador
        armadores = {letra: {rotacion["armador"]} for letra, rotacion in rotaciones.items()}

        mensaje_saque = f"\nQue equipo saca primero? A) {nombres['A']}  B) {nombres['B']}: "
        with _esperando({"que": "saque_inicial", "set": 1}):
            equipo_saca = preguntar_equipo(mensaje_saque, nombres)
        entradas_totales.append(equipo_saca)
        marcador = {"A": 0, "B": 0}

        while True:
            numero_set = len(historial_sets) + 1
            resultado = jugar_punto(
                equipo_saca, nombres,
                jugador_que_saca(rotaciones, puntos, numero_set, equipo_saca),
            )
            if resultado is None:
                break

            if resultado[0] == "CAMBIO_SET":
                entradas_totales.append(resultado[1])

                historial_sets.append(dict(marcador))
                ganador_set = "A" if marcador["A"] > marcador["B"] else "B"
                sets_ganados[ganador_set] += 1
                print(
                    f"\n>> Fin del set {len(historial_sets)}: "
                    f"{nombres['A']} {marcador['A']} - {marcador['B']} {nombres['B']}  |  "
                    f"Sets {nombres['A']} {sets_ganados['A']} - {sets_ganados['B']} {nombres['B']}\n"
                )
                marcador = {"A": 0, "B": 0}
                puntos_al_iniciar_set = len(puntos)

                # cada set arranca con formacion nueva; el indice de rotacion se
                # reinicia solo porque se cuenta sobre los puntos de este set
                if rotaciones:
                    with _esperando({"que": "mantener_rotacion",
                                     "set": len(historial_sets) + 1}):
                        mantiene = preguntar_si_no(
                            f"Mantener la misma rotacion para el set {len(historial_sets) + 1}? (s/n): "
                        )
                    entradas_totales.append("s" if mantiene else "n")
                    if not mantiene:
                        rotaciones, entradas_rotaciones = preguntar_rotaciones(nombres)
                        entradas_totales.extend(entradas_rotaciones)
                    if rotaciones:
                        rotaciones_por_set[len(historial_sets) + 1] = copiar_rotaciones(rotaciones)
                    for letra, rotacion in rotaciones.items():
                        armadores.setdefault(letra, set()).add(rotacion["armador"])

                mensaje_saque = (
                    f"Que equipo saca primero en el set {len(historial_sets) + 1}? "
                    f"A) {nombres['A']}  B) {nombres['B']}: "
                )
                with _esperando({"que": "saque_inicial", "set": len(historial_sets) + 1}):
                    equipo_saca = preguntar_equipo(mensaje_saque, nombres)
                entradas_totales.append(equipo_saca)
                continue

            if resultado[0] == "CAMBIO":
                cambio = aplicar_cambio(
                    rotaciones, resultado[1], nombres, puntos, len(historial_sets) + 1
                )
                if cambio is not None:
                    entradas_totales.append(resultado[1])
                    cambios.append({"set": len(historial_sets) + 1, **cambio})
                    if cambio["armador"]:
                        armadores.setdefault(cambio["equipo"], set()).add(cambio["entra"])
                continue

            if resultado[0] == "DESHACER":
                if len(puntos) <= puntos_al_iniciar_set:
                    print("  No hay ningun punto para deshacer en este set.\n")
                    continue

                punto_deshecho = puntos.pop()
                entradas_del_punto = entradas_por_punto.pop()
                if entradas_del_punto:
                    entradas_totales = entradas_totales[: -len(entradas_del_punto)]

                equipo_ganador_deshecho = punto_deshecho["equipo_gana"]
                marcador[equipo_ganador_deshecho] -= 1
                equipo_saca = punto_deshecho["equipo_saca"]

                print(
                    f"  Deshecho: se elimino el ultimo punto (era de {nombres[equipo_ganador_deshecho]}). "
                    f"Marcador {nombres['A']} {marcador['A']} - {marcador['B']} {nombres['B']}\n"
                )
                continue

            equipo_ganador, secuencia, entradas_punto = resultado
            entradas_totales.extend(entradas_punto)
            entradas_por_punto.append(entradas_punto)
            marcador[equipo_ganador] += 1
            puntos.append({
                "set": len(historial_sets) + 1,
                "equipo_saca": equipo_saca,
                "equipo_gana": equipo_ganador,
                # se guarda ahora porque despues no se puede reconstruir: los
                # cambios mueven al armador y la rotacion sigue girando
                "zona_armador": {
                    letra: zona_del_armador(
                        rotaciones, puntos, len(historial_sets) + 1, letra
                    )
                    for letra in EQUIPOS
                },
                "jugadas": secuencia,
            })

            print(
                f"  >> Punto para {nombres[equipo_ganador]}  |  "
                f"Marcador {nombres['A']} {marcador['A']} - {marcador['B']} {nombres['B']}"
            )

            equipo_saca = equipo_ganador
    except SinMasEntradas as corte:
        # la web corta aca: se devuelve el estado hasta donde llego, y con el
        # la pregunta que quedo sin contestar. El punto a medias viaja adentro
        # de "esperando" y no entra en "puntos": sigue sin contar para el
        # marcador ni para las estadisticas, igual que antes.
        esperando = getattr(corte, "esperando", None)

    return {
        "nombres": nombres, "puntos": puntos, "marcador": marcador,
        "historial_sets": historial_sets, "sets_ganados": sets_ganados,
        "rotaciones": rotaciones, "rotaciones_por_set": rotaciones_por_set,
        "cambios": cambios, "armadores": armadores,
        "entradas_totales": entradas_totales, "equipo_saca": equipo_saca,
        "puntos_al_iniciar_set": puntos_al_iniciar_set,
        "esperando": esperando,
    }


def cargar_jugadas() -> list[dict]:
    """Carga un partido por consola y al terminar guarda el reporte."""
    if not pedir_contraseña("Contraseña para cargar jugadas: "):
        print("  Sin la contraseña no se carga nada.")
        return []
    estado = ejecutar_partido()
    nombres = estado["nombres"]
    puntos = estado["puntos"]
    marcador = estado["marcador"]
    historial_sets = estado["historial_sets"]
    sets_ganados = estado["sets_ganados"]
    armadores = estado["armadores"]

    historial_sets.append(dict(marcador))

    if len(historial_sets) > 1:
        print(f"\nSets: {nombres['A']} {sets_ganados['A']} - {sets_ganados['B']} {nombres['B']}")
        for numero, resultado_set in enumerate(historial_sets, start=1):
            print(f"  Set {numero}: {nombres['A']} {resultado_set['A']} - {resultado_set['B']} {nombres['B']}")
    else:
        print(f"\nMarcador final: {nombres['A']} {marcador['A']} - {marcador['B']} {nombres['B']}")
    print(f"Total de puntos cargados: {len(puntos)}")
    imprimir_estadisticas(puntos, nombres, armadores)

    nombre_archivo = guardar_reporte_txt(
        estado["entradas_totales"], puntos, marcador, nombres, historial_sets, sets_ganados,
        estado["rotaciones_por_set"], estado["cambios"], armadores,
    )
    print(f"\nArchivo generado: {nombre_archivo}")

    generar_informe_excel(nombre_archivo, nombres)

    return puntos


if __name__ == "__main__":
    puntos_cargados = cargar_jugadas()
