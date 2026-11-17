"""
Tests de la carga visual (notacion.py).

Se corren con:
    python -m unittest test_carga_visual

El que importa es TestEquivalencia: agarra los volcados completos de Datos/ y,
para cada jugada, busca la secuencia de toques que la genera y compara el
texto con el original. Si sale una sola letra distinta, el .txt y el Excel
dejan de coincidir con lo que se cargo escribiendo.
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import analisis_voley as av
import notacion
import sesion_web

CARPETA = Path(__file__).resolve().parent
CARPETA_DATOS = CARPETA / "Datos"
ARMADOR_JS = CARPETA / "public" / "armador.js"
NODE = shutil.which("node")


def lineas_del_volcado(archivo: Path) -> list[str]:
    """Los inputs crudos de un volcado: desde el nombre del equipo A hasta la
    ultima jugada (el .txt sigue despues con las estadisticas)."""
    lineas = []
    with open(archivo, encoding="utf-8") as texto:
        for linea in texto:
            linea = linea.rstrip("\n")
            if linea.startswith("==="):
                if lineas:
                    break
                continue
            lineas.append(linea)
    while lineas and not lineas[-1].strip():
        lineas.pop()
    return lineas


def buscar_toques(armador: notacion.Armador, objetivo: str,
                  candidatos: list[int]) -> list | None:
    """La secuencia de toques que produce exactamente esta linea, o None.

    Busca con backtracking en vez de ir eligiendo la opcion mas larga: con
    dorsales de uno y dos digitos ("/1" y "/13" son las dos prefijo de
    "/13_5") elegir de a una se equivoca, y lo que hay que demostrar es que la
    secuencia EXISTE."""
    if armador.cerrada:
        return [] if armador.linea == objetivo else None
    # con la linea ya completa todavia puede faltar un toque que no escribe
    # nada y cierra (el "Sigue" del libre y del toque), asi que se sigue
    # buscando en vez de dar la linea por imposible
    if not objetivo.startswith(armador.linea):
        return None

    for opcion in armador.opciones():
        numeros = candidatos if opcion["tipo"] == "numero" else [None]
        for numero in numeros:
            copia = armador.copiar()
            copia.tocar(opcion["id"], numero)
            resto = buscar_toques(copia, objetivo, candidatos)
            if resto is not None:
                return [(opcion["id"], numero)] + resto
    return None


def lo_que_dice_el_motor(instantanea: dict) -> dict:
    """Con que se construye el armador en el estado en el que esta el partido.
    Todo se lo dice el motor: que bloque toca, de quien es la pelota, si el
    dorsal del sacador se completa solo, quien arma y a quien se le arma en
    cada zona. Es lo mismo que arma interfaz.js con la respuesta del servidor."""
    pendiente = instantanea["pendiente"]
    rotaciones = instantanea["rotaciones"]
    # sin "juego" (equipo sin rotacion, o sin armador en la cancha) no se
    # asume a nadie
    con_puestos = {letra: r for letra, r in rotaciones.items() if r.get("juego")}
    return {
        "espera": pendiente["espera"],
        "equipo_saca": instantanea["equipo_saca"],
        "equipo_con_la_pelota": pendiente["equipo_con_la_pelota"],
        # los que se pueden tocar son los que estan realmente en la cancha
        "planteles": {letra: r["formacion"] for letra, r in rotaciones.items()},
        "sacador_conocido": instantanea["jugador_saca"] is not None,
        "armadores": {letra: r["armador"] for letra, r in con_puestos.items()},
        "atacantes": {letra: r["juego"]["atacantes"] for letra, r in con_puestos.items()},
    }


def armador_para(instantanea: dict) -> notacion.Armador:
    return notacion.Armador(**lo_que_dice_el_motor(instantanea))


# Los mismos datos, con los nombres que usa el constructor de armador.js.
NOMBRE_EN_JS = {
    "espera": "espera", "equipo_saca": "equipoSaca",
    "equipo_con_la_pelota": "equipoConLaPelota", "planteles": "planteles",
    "sacador_conocido": "sacadorConocido", "armadores": "armadores",
    "atacantes": "atacantes",
}


def contexto_js(argumentos: dict) -> dict:
    return {NOMBRE_EN_JS[nombre]: valor for nombre, valor in argumentos.items()}


def rastro(armador: notacion.Armador, toques: list) -> dict:
    """Lo que el armador ofrece, pregunta y asume antes de cada toque, y que
    arrastra al cerrar. Es lo que se compara con el interprete del navegador:
    que escriban la misma linea no alcanza, porque un atajo que uno ofrece y
    el otro no deja la pantalla distinta de lo que se testeo."""
    pasos = []
    for identificador, valor in toques:
        pasos.append({
            "ofrece": [[o["id"], o.get("texto")] for o in armador.opciones()],
            "titulo": armador.titulo(),
            "asumido": armador.asumido(),
        })
        armador.tocar(identificador, valor)
    return {"pasos": pasos, "arrastre": armador.arrastre}


# Con que campo del bloque que arma el MOTOR se compara el lado que encendio
# la pantalla en cada paso. Es lo que evita que la cancha ofrezca los circulos
# del equipo equivocado: como cualquier dorsal se puede cargar por teclado, el
# texto sale bien igual y comparar solo el texto no lo veria.
CAMPO_DEL_EQUIPO = {
    "RECIBE_JUGADOR": ("equipo_receptor", "equipo_set", "equipo_atacante"),
    "ARMA_JUGADOR": ("equipo_set",),
    "ATACA_JUGADOR": ("equipo_atacante",),
    "SEGUNDA_JUGADOR": ("equipo_atacante",),
    "PRIMERA_JUGADOR": ("equipo_atacante",),
    "BLOQUEO_PUNTO": ("equipo_bloqueo",),
    "BLOQUEO_USADO": ("equipo_bloqueo",),
    "BLOQUEO_REJUGABLE": ("equipo_bloqueo",),
}


def ultimo_bloque(sesion) -> dict | None:
    """El bloque que el motor acaba de armar con la ultima linea."""
    pendiente = sesion.instantanea()["pendiente"]["jugadas"]
    if pendiente:
        return pendiente[-1]
    puntos = sesion.estado["puntos"]
    if puntos and puntos[-1]["jugadas"]:
        return puntos[-1]["jugadas"][-1]
    return None


def como_se_escribe_hoy(linea: str) -> str:
    """La misma jugada, en la notacion de ahora.

    La defensa que no se pudo jugar se escribia "7_-2" y ahora es un 0 como
    cualquier otra defensa: "7_0". El motor sigue leyendo la forma vieja
    porque los volcados de Datos/ estan llenos de ella, pero tocando sale la
    de ahora, que es con la que hay que comparar."""
    defensor, _, final = linea.partition("_")
    if final == "-2" and defensor.isdigit():
        return defensor + "_0"
    return linea


# Una defensa calidad 0 seguida de armado y ataque: "7_0/3_4/9_1_P".
# Se cargaba asi cuando el 0 no cerraba el punto. Ahora si lo cierra, asi que
# esa linea no se puede armar tocando -- el boton del 0 termina la jugada.
RE_CERO_QUE_SEGUIA = re.compile(r"^\d+_0/")

# El toque ("9_T_8"): ya no hay boton para cargarlo, ahora es un ataque
# colocado / finta.
RE_TOQUE = re.compile(r"\d_T_\d")


def usa_notacion_retirada(linea: str) -> bool:
    """Si la linea se escribio con una regla que ya no rige.

    No se puede armar tocando y no tiene sentido pedir que se pueda: la
    pantalla ofrece la notacion de HOY. El motor igual la sigue leyendo, que es
    lo que hace que los partidos viejos se puedan volver a cargar; eso lo
    cuida test_analisis_voley, no este archivo."""
    return bool(RE_CERO_QUE_SEGUIA.match(linea) or RE_TOQUE.search(linea))


def es_jugada(linea: str, espera: str) -> bool:
    """Si esta linea es una jugada y no un comando, un nombre o una rotacion."""
    if espera == "saque":
        return av.parsear_bloque_saque(linea) is not None
    return av.parsear_bloque_defensa(linea) is not None


class TestEquivalencia(unittest.TestCase):
    """Tocando tiene que salir exactamente la misma linea que escribiendo."""

    def _revisar(self, archivo: Path):
        sesion = sesion_web.SesionPartido()
        revisadas = 0
        for numero, linea in enumerate(lineas_del_volcado(archivo), start=1):
            instantanea = sesion.instantanea()
            espera = instantanea["pendiente"]["espera"]
            if espera and es_jugada(linea, espera) and not usa_notacion_retirada(linea):
                armador = armador_para(instantanea)
                hoy = como_se_escribe_hoy(linea)
                candidatos = [int(n) for n in dict.fromkeys(re.findall(r"\d+", linea))]
                toques = buscar_toques(armador, hoy, candidatos)
                self.assertIsNotNone(
                    toques,
                    f"{archivo.name} linea {numero}: no hay forma de armar {linea!r} "
                    f"tocando (estado inicial {armador.estado}, "
                    f"pelota de {armador.equipo_con_la_pelota})",
                )
                # se rearma desde cero con esos toques y tiene que dar igual
                repetido = armador_para(instantanea)
                lados = {}
                la_levanta = None
                for identificador, valor in toques:
                    paso = notacion.PASOS[repetido.estado]
                    ofrecidos = [o["id"] for o in repetido.opciones()]
                    self.assertEqual(len(ofrecidos), len(set(ofrecidos)),
                                     f"{archivo.name} linea {numero}: en {repetido.estado} "
                                     f"hay dos toques con el mismo nombre: {ofrecidos}")
                    if paso["pide"] == "jugador":
                        lados[repetido.estado] = repetido.equipo_de(paso["lado"])
                    opcion = repetido.tocar(identificador, valor)
                    # el circulo que vale por un boton: tambien tiene que ser
                    # del equipo que dice el motor
                    if paso.get("directo") and opcion["tipo"] == "jugador":
                        equipo = repetido.equipo_de(paso["directo"]["lado"])
                        if opcion.get("arrastra") is not None:
                            la_levanta = equipo
                        else:
                            boton = next(o for o in paso["opciones"]
                                         if o["id"] == paso["directo"]["por"])
                            lados[boton["siguiente"]] = equipo
                self.assertEqual(repetido.linea, hoy, f"{archivo.name} linea {numero}")
                self.assertTrue(repetido.cerrada, f"{archivo.name} linea {numero}")
                revisadas += 1
                sesion.enviar(linea)
                self._revisar_lados(lados, ultimo_bloque(sesion), instantanea,
                                    f"{archivo.name} linea {numero}: {linea}")
                if la_levanta is not None:
                    # el rival que se toco para decir "Defendido" queda tocado
                    # en la linea que viene: la pelota tiene que ser de el
                    despues = sesion.instantanea()["pendiente"]
                    if despues["espera"] == "continuacion":
                        self.assertEqual(
                            despues["equipo_con_la_pelota"], la_levanta,
                            f"{archivo.name} linea {numero}: {linea}: el que defiende "
                            f"se ofrecio de {la_levanta}")
                continue
            sesion.enviar(linea)
        return revisadas

    def _revisar_lados(self, lados, bloque, instantanea, donde):
        """El equipo que la pantalla encendio en cada paso tiene que ser el
        mismo que el motor le adjudico a esa jugada."""
        if bloque is None:
            return
        for estado, equipo in lados.items():
            if estado == "SAQUE_JUGADOR":
                self.assertEqual(equipo, instantanea["equipo_saca"],
                                 f"{donde}: el saque se pidio del equipo equivocado")
                continue
            campos = CAMPO_DEL_EQUIPO.get(estado, ())
            esperado = next((bloque[c] for c in campos if bloque.get(c)), None)
            if esperado is None:
                continue
            self.assertEqual(
                equipo, esperado,
                f"{donde}: en {estado} se encendieron los circulos de {equipo} "
                f"y el motor dice que la jugada fue de {esperado}")

    def test_los_volcados_guardados_salen_identicos(self):
        archivos = sorted(CARPETA_DATOS.glob("*.txt"))
        self.assertTrue(archivos, "no hay volcados en Datos/ para comparar")
        total = 0
        for archivo in archivos:
            with self.subTest(archivo=archivo.name):
                total += self._revisar(archivo)
        # si un dia el motor deja de aceptar estas lineas, el test tiene que
        # gritar en vez de pasar sin revisar nada
        self.assertGreater(total, 200, "se revisaron muy pocas jugadas")


class TestCasosRaros(unittest.TestCase):
    """Cada caso de la notacion cargado de punta a punta, con los toques a la
    vista. Si alguno cambia, se ve aca cual."""

    PLANTELES = {"A": [1, 2, 3, 4, 5, 6], "B": [7, 8, 9, 10, 11, 12]}

    def armar(self, *toques, espera="saque", sacador_conocido=True):
        """Toca en orden y devuelve (linea, cerrada). Saca A, la pelota (en el
        bloque de saque) es de B."""
        armador = notacion.Armador(
            espera=espera, equipo_saca="A",
            equipo_con_la_pelota="B" if espera == "saque" else "B",
            planteles=self.PLANTELES, sacador_conocido=sacador_conocido,
        )
        for toque in toques:
            identificador, numero = toque if isinstance(toque, tuple) else (toque, None)
            armador.tocar(identificador, numero)
        return armador

    def test_as(self):
        self.assertEqual(self.armar("z1", "z6", "as").linea, "1_6_A")

    def test_error_de_saque(self):
        self.assertEqual(self.armar("z1", "z6", "error").linea, "1_6_E")

    def test_sin_rotacion_el_dorsal_del_sacador_va_adelante(self):
        armador = self.armar(("otro", 5), "z1", "z6", "as", sacador_conocido=False)
        self.assertEqual(armador.linea, "5_1_6_A")

    def test_punto_en_el_primer_ataque(self):
        armador = self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                             "j9", "z1", "sin_forma", "punto")
        self.assertEqual(armador.linea, "1_6_X/7_3/8_4/9_1_P")
        self.assertTrue(armador.cerrada)

    def test_como_ataco_y_que_paso_van_en_ese_orden(self):
        # un toque de la grilla escribe las dos cosas, la forma primero
        armador = self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                             "j9", "z1")
        self.assertEqual(armador.estado, "ATACA_FORMA")
        armador.tocar("potente+malla")
        self.assertEqual(armador.linea, "1_6_X/7_3/8_4/9_1_PO_M")
        self.assertTrue(armador.cerrada)
        colocado = self.armar("primera", "j9", "z5", "colocado+punto",
                              espera="continuacion")
        self.assertEqual(colocado.linea, "9_A_5_CO_P")

    def test_overpass_en_la_recepcion(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "overpass").linea, "1_6_X/7_-1")

    def test_overpass_en_el_armado(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "arma_pasa").linea,
            "1_6_X/7_3/8_-1")

    def test_armada_mala(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "arma_mala").linea,
            "1_6_X/7_3/8_-2")

    def test_armado_que_no_cuenta(self):
        armador = self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                             "sin_armado", "j9", "z1", "sin_forma", "punto")
        self.assertEqual(armador.linea, "1_6_X/7_3/8_4_X/9_1_P")

    def test_el_marcador_de_sin_armado_no_se_puede_poner_dos_veces(self):
        armador = self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4", "sin_armado")
        self.assertNotIn("sin_armado", [o["id"] for o in armador.opciones()])

    def test_libre(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                       "j9", "libre", "z8").linea,
            "1_6_X/7_3/8_4/9_F_8")

    def test_el_toque_ya_no_se_ofrece(self):
        # ahora es un ataque colocado / finta; el "_T_" viejo se sigue leyendo
        # y tampoco hay que elegir "Ataque": tocar la zona ya es atacar
        armador = self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4", "j9")
        self.assertEqual([o["id"] for o in armador.opciones()],
                         ["z1", "z6", "z5", "libre"])

    def test_pasada_de_segunda_despues_del_saque(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "segunda", "j10", "z6",
                       "defendido").linea,
            "1_6_X/7_3/10_S_6_D")

    def test_pasada_de_segunda_en_una_continuacion(self):
        self.assertEqual(
            self.armar("j7", "c2", "segunda", "j10", "z6", "defendido",
                       espera="continuacion").linea,
            "7_2/10_S_6_D")

    def test_ataque_de_primera(self):
        self.assertEqual(
            self.armar("primera", "j9", "z1", "sin_forma", "punto", espera="continuacion").linea,
            "9_A_1_P")

    def test_el_ataque_de_primera_no_existe_en_el_bloque_de_saque(self):
        armador = self.armar("z1", "z6", "sigue")
        self.assertNotIn("primera", [o["id"] for o in armador.opciones()])

    def test_bloqueo_punto(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                       "j9", "z1", "sin_forma", "bloqueo_punto", "j6").linea,
            "1_6_X/7_3/8_4/9_1_B_6_P")

    def test_toque_de_bloqueo(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                       "j9", "z1", "sin_forma", "bloqueo_usado", "j6").linea,
            "1_6_X/7_3/8_4/9_1_U_6")

    def test_bloqueo_rejugable(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                       "j9", "z1", "sin_forma", "bloqueo_rejugable", "j6").linea,
            "1_6_X/7_3/8_4/9_1_R_6")

    def test_malla(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                       "j9", "z1", "sin_forma", "malla").linea,
            "1_6_X/7_3/8_4/9_1_M")

    def test_el_cero_de_defensa_cierra_el_punto(self):
        """Una defensa calidad 0 termina la jugada: esa pelota no se pudo
        jugar y el punto es del que la mando.

        Antes habia dos botones -- un 0 que seguia y otro que cerraba -- y
        quedo uno solo."""
        cae = self.armar("j7", "c0_cae", espera="continuacion")
        self.assertEqual(cae.linea, "7_0")
        self.assertTrue(cae.cerrada)

    def test_el_cero_no_se_ofrece_en_la_recepcion_del_saque(self):
        """En recepcion el 0 es un pase malo que igual se juega, no una pelota
        perdida: ahi el boton tiene que seguir llevando al armado."""
        saque = self.armar("z1", "z6", "sigue", "j7", "c0")
        self.assertFalse(saque.cerrada)
        self.assertEqual(saque.linea, "1_6_X/7_0")
        # y el de defensa no se ofrece ahi
        pide = self.armar("z1", "z6", "sigue", "j7")
        self.assertNotIn("c0_cae", [o["id"] for o in pide.opciones()])

    def test_el_bloqueador_sale_del_equipo_rival(self):
        armador = self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                             "j9", "z1", "sin_forma", "bloqueo_punto")
        # ataca B, asi que el que bloquea es A
        dorsales = [o["valor"] for o in armador.opciones() if o["tipo"] == "jugador"]
        self.assertEqual(dorsales, self.PLANTELES["A"])

    def test_el_libero_se_carga_con_el_teclado_aunque_haya_rotacion(self):
        # el 31 no esta entre los 6 de B: sin la salida "otro" no habria forma
        armador = self.armar("j7", espera="continuacion")
        armador.deshacer()
        armador.tocar("otro", 31)
        armador.tocar("c1")
        self.assertEqual(armador.linea, "31_1")


# Dos equipos con rotacion, como los manda el motor. Saca A.
#
#   B (recibe):  arma el 8, parado en zona 2. A 4 ataca el 10 (punta), a 3 el
#                9 (central), a 1 el 12 (opuesto zaguero) y a 6 el 7 (punta
#                zaguero). En 5 esta el 11 y a ese no se le arma.
#   A (saca):    arma el 1, que esta sacando. A 2 ataca el 4 (opuesto).
PLANTELES_CON_PUESTOS = {"A": [1, 2, 3, 4, 5, 6], "B": [7, 8, 9, 10, 11, 12]}
ARMADORES = {"A": 1, "B": 8}
ATACANTES = {"A": [None, 4, 3, 2, None, 5], "B": [12, None, 9, 10, None, 7]}

# Lo que se toca y la linea que tiene que salir. Esta tabla se le pasa tambien
# al interprete del navegador (ver TestInterpreteDelNavegador).
#   (que se esta esperando, toques, linea)
LINEAS_CON_ATAJOS = [
    # el punto de libro: saque, recibe el 7, arma el armador a 4, ataca el
    # punta a 1, potente y punto. Siete toques; escrito a mano eran doce.
    ("saque", ["z1", "z6", "j7", "c3", "z4", "z1", "potente+punto"],
     "1_6_X/7_3/8_4/10_1_PO_P"),
    # la potencia del saque va antes de la X, y el receptor despues
    ("saque", ["z1", "z6", "potencia", "j7", "overpass"], "1_6_P_X/7_-1"),
    # el camino largo sigue estando, y escribe lo mismo
    ("saque", ["z1", "z6", "sigue", "j7", "c3", "arma_otro", "j8", "z4", "j10",
               "z1", "potente+punto"], "1_6_X/7_3/8_4/10_1_PO_P"),
    # con el armador asumido, lo que se toca en vez de la zona tambien es de el
    ("saque", ["z1", "z6", "j7", "c3", "arma_pasa"], "1_6_X/7_3/8_-1"),
    ("saque", ["z1", "z6", "j7", "c3", "arma_mala"], "1_6_X/7_3/8_-2"),
    # armo otro: hay que decir quien
    ("saque", ["z1", "z6", "j7", "c1", "arma_otro", "j11", "z4", "z5", "colocado+afuera"],
     "1_6_X/7_1/11_4/10_5_CO_O"),
    # recibio el armador: arma otro, y se pregunta de una
    ("saque", ["z1", "z6", "j8", "c2", "j12", "z3", "z6", "potente+defendido"],
     "1_6_X/8_2/12_3/9_6_PO_D"),
    # la pasada de segunda no es del armador asumido: se elige quien
    ("saque", ["z1", "z6", "j7", "c3", "segunda", "j10", "z6", "defendido"],
     "1_6_X/7_3/10_S_6_D"),
    # se armo a 4 pero ataco otro: se toca al otro y despues la zona
    ("saque", ["z1", "z6", "j7", "c3", "z4", "j9", "z1", "potente+punto"],
     "1_6_X/7_3/8_4/9_1_PO_P"),
    # las marcas del armado van pegadas a la zona, antes del atacante asumido
    ("saque", ["z1", "z6", "j7", "c3", "z4", "armado_mas", "z1", "potente+punto"],
     "1_6_X/7_3/8_4_A+/10_1_PO_P"),
    ("saque", ["z1", "z6", "j7", "c3", "z4", "sin_armado", "armado_menos", "z1",
               "sin_forma", "punto"], "1_6_X/7_3/8_4_X_A-/10_1_P"),
    # a la zona 5 no se le asume atacante: hay que tocarlo
    ("saque", ["z1", "z6", "j7", "c3", "z5", "j11", "z6", "potente+malla"],
     "1_6_X/7_3/8_5/11_6_PO_M"),
    # zagueros
    ("saque", ["z1", "z6", "j7", "c3", "z1", "z5", "potente+punto"],
     "1_6_X/7_3/8_1/12_5_PO_P"),
    ("saque", ["z1", "z6", "j7", "c3", "z6", "z1", "colocado+punto"],
     "1_6_X/7_3/8_6/7_1_CO_P"),
    # el libre del atacante asumido, con las tres formas de terminar
    ("saque", ["z1", "z6", "j7", "c3", "z4", "libre", "z8", "sigue"],
     "1_6_X/7_3/8_4/10_F_8"),
    ("saque", ["z1", "z6", "j7", "c3", "z4", "libre", "z8", "j3"],
     "1_6_X/7_3/8_4/10_F_8"),
    ("saque", ["z1", "z6", "j7", "c3", "z4", "libre", "libre_malo"],
     "1_6_X/7_3/8_4/10_F_0"),
    # tocar al rival que la defendio es "Defendido"
    ("saque", ["z1", "z6", "j7", "c3", "z4", "z1", "sin_forma", "j3"],
     "1_6_X/7_3/8_4/10_1_D"),
    ("saque", ["z1", "z6", "j7", "c3", "segunda", "j10", "z6", "j5"],
     "1_6_X/7_3/10_S_6_D"),
    # los bloqueos salen de la grilla y despues piden al bloqueador
    ("saque", ["z1", "z6", "j7", "c3", "z4", "z1", "potente+bloqueo_punto", "j6"],
     "1_6_X/7_3/8_4/10_1_PO_B_6_P"),
    ("saque", ["z1", "z6", "j7", "c3", "z4", "z1", "colocado+bloqueo_usado", "j2"],
     "1_6_X/7_3/8_4/10_1_CO_U_2"),
    # en una continuacion es igual, sin el saque
    ("continuacion", ["j7", "c2", "z4", "z5", "colocado+punto"], "7_2/8_4/10_5_CO_P"),
    ("continuacion", ["primera", "j9", "z1", "sin_forma", "j2"], "9_A_1_D"),
    ("continuacion", ["primera", "j9", "z5", "potente+defendido"], "9_A_5_PO_D"),
    # un dorsal por teclado en el lugar del asumido
    ("continuacion", ["j7", "c2", "z4", ("otro", 31), "z5", "potente+punto"],
     "7_2/8_4/31_5_PO_P"),
]


def con_numero(toques) -> list:
    """Los toques como pares (id, dorsal tecleado o None)."""
    return [list(t) if isinstance(t, tuple) else [t, None] for t in toques]


class TestAtajos(unittest.TestCase):
    """Los toques que valen por dos pasos: tocar al que recibe, el armador y
    el atacante que se dan por hechos, y la grilla de forma y resultado."""

    def armador(self, *toques, espera="saque", **cambios):
        """Saca A; la pelota es de B, tanto despues del saque como en la
        continuacion."""
        argumentos = dict(espera=espera, equipo_saca="A", equipo_con_la_pelota="B",
                          planteles=PLANTELES_CON_PUESTOS,
                          armadores=ARMADORES, atacantes=ATACANTES)
        argumentos.update(cambios)
        armador = notacion.Armador(**argumentos)
        for identificador, numero in con_numero(toques):
            armador.tocar(identificador, numero)
        return armador

    def ofrece(self, armador):
        return [opcion["id"] for opcion in armador.opciones()]

    def test_cada_camino_escribe_su_linea(self):
        for espera, toques, linea in LINEAS_CON_ATAJOS:
            with self.subTest(linea=linea, toques=toques):
                armador = self.armador(*toques, espera=espera)
                self.assertEqual(armador.linea, linea)
                self.assertTrue(armador.cerrada)

    def test_el_punto_de_libro_son_siete_toques(self):
        espera, toques, linea = LINEAS_CON_ATAJOS[0]
        self.assertEqual(linea, "1_6_X/7_3/8_4/10_1_PO_P")
        self.assertEqual(len(toques), 7)

    def test_nunca_hay_dos_toques_con_el_mismo_nombre(self):
        # la pantalla busca la opcion por su id: si hubiera dos iguales, uno
        # de los dos no se podria tocar
        for espera, toques, linea in LINEAS_CON_ATAJOS:
            armador = self.armador(espera=espera)
            for identificador, numero in con_numero(toques):
                ofrecidos = self.ofrece(armador)
                self.assertEqual(len(ofrecidos), len(set(ofrecidos)),
                                 f"{linea} en {armador.estado}: {ofrecidos}")
                armador.tocar(identificador, numero)

    # ---------------- el que recibe ----------------
    def test_tocar_al_que_recibe_dice_que_el_saque_siguio(self):
        armador = self.armador("z1", "z6", "j7")
        self.assertEqual(armador.linea, "1_6_X/7")
        self.assertEqual(armador.estado, "RECIBE_CALIDAD")

    def test_el_receptor_directo_se_deshace_de_un_toque(self):
        armador = self.armador("z1", "z6", "j7")
        armador.deshacer()
        self.assertEqual(armador.linea, "1_6")
        self.assertEqual(armador.estado, "SAQUE_RESULTADO")

    def test_despues_del_saque_se_ofrecen_los_que_reciben_y_no_los_que_sacan(self):
        armador = self.armador("z1", "z6")
        dorsales = [o["valor"] for o in armador.opciones() if o["tipo"] == "jugador"]
        self.assertEqual(dorsales, PLANTELES_CON_PUESTOS["B"])
        self.assertEqual(armador.titulo(), "Toca al que recibe (o como termino el saque)")

    def test_el_receptor_directo_no_necesita_rotacion(self):
        # es un atajo de la notacion, no de los puestos
        armador = self.armador("z1", "z6", "j7", armadores=None, atacantes=None)
        self.assertEqual(armador.linea, "1_6_X/7")

    # ---------------- el armador ----------------
    def test_se_asume_que_arma_el_armador(self):
        armador = self.armador("z1", "z6", "j7", "c3")
        self.assertEqual(armador.estado, "ARMA_JUGADOR")
        self.assertEqual(armador.asumido(), 8)
        self.assertEqual(armador.titulo(), "Arma el 8: hacia que zona")
        self.assertEqual(self.ofrece(armador),
                         ["z1", "z2", "z3", "z4", "z5", "z6", "arma_pasa", "arma_mala",
                          "arma_otro", "segunda"])

    def test_la_zona_de_armado_escribe_tambien_al_armador(self):
        armador = self.armador("z1", "z6", "j7", "c3", "z4")
        self.assertEqual(armador.linea, "1_6_X/7_3/8_4")
        self.assertEqual(armador.estado, "ATACA_JUGADOR")
        armador.deshacer()
        self.assertEqual(armador.linea, "1_6_X/7_3")
        self.assertEqual(armador.estado, "ARMA_JUGADOR")

    def test_si_el_armador_hizo_el_primer_toque_no_se_asume(self):
        # nadie la toca dos veces seguidas: armo otro y hay que decir quien
        armador = self.armador("z1", "z6", "j8", "c3")
        self.assertIsNone(armador.asumido())
        self.assertEqual(armador.titulo(), "Quien arma")
        self.assertEqual(self.ofrece(armador),
                         ["j7", "j8", "j9", "j10", "j11", "j12", "otro", "segunda"])

    def test_armo_otro_jugador_vuelve_a_los_circulos(self):
        armador = self.armador("z1", "z6", "j7", "c3", "arma_otro")
        self.assertEqual(armador.linea, "1_6_X/7_3")
        self.assertIsNone(armador.asumido())
        self.assertIn("j9", self.ofrece(armador))
        self.assertNotIn("z4", self.ofrece(armador))
        self.assertNotIn("arma_otro", self.ofrece(armador))
        # y se arrepiente de un toque
        armador.deshacer()
        self.assertEqual(armador.asumido(), 8)
        self.assertIn("z4", self.ofrece(armador))

    def test_no_se_asume_a_un_armador_que_no_esta_en_la_cancha(self):
        armador = self.armador("z1", "z6", "j7", "c3", armadores={"B": 99})
        self.assertIsNone(armador.asumido())
        self.assertIn("j8", self.ofrece(armador))

    def test_el_armador_asumido_es_el_del_equipo_que_tiene_la_pelota(self):
        armador = self.armador("j2", "c3", espera="continuacion",
                               equipo_con_la_pelota="A")
        self.assertEqual(armador.asumido(), 1)

    # ---------------- el atacante ----------------
    def test_se_asume_el_que_juega_en_la_zona_a_la_que_se_armo(self):
        for zona, atacante in ((4, 10), (3, 9), (1, 12), (6, 7)):
            with self.subTest(zona=zona):
                armador = self.armador("z1", "z6", "j7", "c3", f"z{zona}")
                self.assertEqual(armador.asumido(), atacante)
                self.assertEqual(armador.titulo(),
                                 f"Ataca el {atacante}: hacia que zona (o toca a otro)")

    def test_con_atacante_asumido_los_circulos_siguen_vivos(self):
        armador = self.armador("z1", "z6", "j7", "c3", "z4")
        self.assertEqual(self.ofrece(armador),
                         ["z1", "z6", "z5", "libre",
                          "j7", "j8", "j9", "j10", "j11", "j12", "otro",
                          "sin_armado", "armado_mas", "armado_cero", "armado_menos"])

    def test_a_la_zona_del_armador_y_a_la_5_no_se_les_asume_nadie(self):
        for zona in (2, 5):
            with self.subTest(zona=zona):
                armador = self.armador("z1", "z6", "j7", "c3", f"z{zona}")
                self.assertIsNone(armador.asumido())
                self.assertEqual(armador.titulo(), "Quien ataca")
                self.assertNotIn("z1", self.ofrece(armador))

    def test_no_se_asume_que_ataca_el_mismo_que_armo(self):
        # armo el punta (el 10) hacia 4, que es donde ataca el: fue otro
        armador = self.armador("z1", "z6", "j7", "c3", "arma_otro", "j10", "z4")
        self.assertIsNone(armador.asumido())

    def test_no_se_asume_que_ataca_el_que_armo_aunque_se_haya_tecleado(self):
        # el dorsal por teclado llega como texto desde la pantalla
        armador = self.armador("z1", "z6", "j7", "c3", "arma_otro", ("otro", "10"), "z4")
        self.assertIsNone(armador.asumido())

    def test_el_atacante_asumido_sobrevive_a_las_marcas_del_armado(self):
        armador = self.armador("z1", "z6", "j7", "c3", "z4", "sin_armado", "armado_mas")
        self.assertEqual(armador.asumido(), 10)
        self.assertEqual(armador.linea, "1_6_X/7_3/8_4_X_A+")

    def test_sin_rotacion_se_carga_toque_por_toque(self):
        armador = self.armador("z1", "z6", "j7", "c3", armadores=None, atacantes=None)
        self.assertIsNone(armador.asumido())
        self.assertIn("j8", self.ofrece(armador))
        self.assertNotIn("arma_otro", self.ofrece(armador))
        armador.tocar("j8")
        armador.tocar("z4")
        self.assertIsNone(armador.asumido())
        self.assertNotIn("z1", self.ofrece(armador))

    def test_se_asume_solo_al_equipo_que_tiene_puestos(self):
        # B sin rotacion, A con: del lado de B no se asume nada
        armador = self.armador("z1", "z6", "j7", "c3",
                               armadores={"A": 1}, atacantes={"A": ATACANTES["A"]})
        self.assertIsNone(armador.asumido())

    # ---------------- forma y resultado ----------------
    def test_la_grilla_tiene_una_fila_por_forma(self):
        armador = self.armador("z1", "z6", "j7", "c3", "z4", "z1")
        self.assertEqual(armador.estado, "ATACA_FORMA")
        filas = {}
        for opcion in armador.opciones():
            filas.setdefault(opcion.get("fila"), []).append(opcion["id"])
        resultados = [o["id"] for o in notacion.PASOS["ATACA_RESULTADO"]["opciones"]]
        self.assertEqual(filas, {
            "Ataque potente": [f"potente+{r}" for r in resultados],
            "Colocado / finta": [f"colocado+{r}" for r in resultados],
            None: ["sin_forma"],
        })

    def test_en_la_grilla_no_se_ofrece_tocar_al_rival(self):
        # el circulo no puede decir a la vez como fue el ataque
        armador = self.armador("z1", "z6", "j7", "c3", "z4", "z1")
        self.assertFalse([o for o in armador.opciones() if o["tipo"] == "jugador"])

    # ---------------- el que defiende ----------------
    def test_tocar_al_rival_cierra_con_defendido_y_lo_arrastra(self):
        armador = self.armador("z1", "z6", "j7", "c3", "z4", "z1", "sin_forma", "j3")
        self.assertEqual(armador.linea, "1_6_X/7_3/8_4/10_1_D")
        self.assertTrue(armador.cerrada)
        # el 3 no se escribe en esta linea: es el primero de la que viene
        self.assertEqual(armador.arrastre, 3)

    def test_el_boton_defendido_no_arrastra_a_nadie(self):
        armador = self.armador("z1", "z6", "j7", "c3", "z4", "z1", "sin_forma", "defendido")
        self.assertEqual(armador.linea, "1_6_X/7_3/8_4/10_1_D")
        self.assertIsNone(armador.arrastre)

    def test_los_que_defienden_son_del_otro_equipo(self):
        armador = self.armador("z1", "z6", "j7", "c3", "z4", "z1", "sin_forma")
        dorsales = [o["valor"] for o in armador.opciones() if o["tipo"] == "jugador"]
        self.assertEqual(dorsales, PLANTELES_CON_PUESTOS["A"])
        self.assertEqual(armador.titulo(), "Que paso (o toca al rival que la defendio)")

    def test_el_libre_que_sigue_arrastra_al_rival_que_la_levanta(self):
        armador = self.armador("z1", "z6", "j7", "c3", "z4", "libre", "z8", "j3")
        self.assertEqual(armador.linea, "1_6_X/7_3/8_4/10_F_8")
        self.assertTrue(armador.cerrada)
        self.assertEqual(armador.arrastre, 3)

    def test_una_linea_abierta_no_arrastra_nada(self):
        self.assertIsNone(self.armador("z1", "z6", "j7").arrastre)
        self.assertIsNone(self.armador().arrastre)

    def test_la_copia_conserva_lo_que_dijo_el_motor(self):
        copia = self.armador("z1", "z6", "j7", "c3").copiar()
        self.assertEqual(copia.asumido(), 8)
        copia.tocar("z4")
        self.assertEqual(copia.asumido(), 10)


class TestDeshacer(unittest.TestCase):
    """Deshacer un paso es sacar el ultimo de la pila. No recalcula nada, asi
    que no se puede desincronizar de la linea."""

    def _armador(self):
        return notacion.Armador(espera="saque", equipo_saca="A",
                                equipo_con_la_pelota="B",
                                planteles={"A": [1, 2, 3, 4, 5, 6],
                                           "B": [7, 8, 9, 10, 11, 12]})

    def test_vuelve_exactamente_al_paso_anterior(self):
        armador = self._armador()
        for toque in ("z1", "z6", "sigue", "j7", "c3"):
            armador.tocar(toque)
        self.assertEqual(armador.linea, "1_6_X/7_3")
        self.assertEqual(armador.estado, "ARMA_JUGADOR")
        armador.deshacer()
        self.assertEqual(armador.linea, "1_6_X/7")
        self.assertEqual(armador.estado, "RECIBE_CALIDAD")

    def test_deshace_tambien_los_toques_que_no_escriben_nada(self):
        # elegir "Libre" no agrega texto pero si cambia lo que se pregunta
        armador = self._armador()
        for toque in ("z1", "z6", "sigue", "j7", "c3", "j8", "z4", "j9", "libre"):
            armador.tocar(toque)
        self.assertEqual(armador.linea, "1_6_X/7_3/8_4/9")
        self.assertEqual(armador.estado, "LIBRE_ZONA")
        armador.deshacer()
        self.assertEqual(armador.linea, "1_6_X/7_3/8_4/9")
        self.assertEqual(armador.estado, "ATACA_ZONA")

    def test_deshacer_hasta_el_principio_deja_la_linea_vacia(self):
        armador = self._armador()
        for toque in ("z1", "z6", "sigue", "j7", "c3"):
            armador.tocar(toque)
        while armador.deshacer():
            pass
        self.assertEqual(armador.linea, "")
        self.assertEqual(armador.estado, "SAQUE_DESDE")
        self.assertFalse(armador.deshacer())


class TestTabla(unittest.TestCase):
    """La tabla viaja al navegador como JSON y se interpreta alla. Estos tests
    cuidan que no tenga un estado colgado ni un salto a la nada."""

    def test_todos_los_saltos_llegan_a_un_paso_que_existe(self):
        for nombre, paso in notacion.PASOS.items():
            destinos = [paso.get("siguiente")] + [
                opcion.get("siguiente") for opcion in paso.get("opciones", ())]
            for destino in destinos:
                if destino is not None:
                    self.assertIn(destino, notacion.PASOS,
                                  f"{nombre} salta a {destino}, que no existe")

    def test_todos_los_pasos_se_alcanzan_desde_algun_arranque(self):
        arranques = {notacion.primer_paso("saque", True),
                     notacion.primer_paso("saque", False),
                     notacion.primer_paso("continuacion", True)}
        vistos, pendientes = set(), list(arranques)
        while pendientes:
            nombre = pendientes.pop()
            if nombre in vistos:
                continue
            vistos.add(nombre)
            paso = notacion.PASOS[nombre]
            for destino in [paso.get("siguiente")] + [
                    o.get("siguiente") for o in paso.get("opciones", ())]:
                if destino:
                    pendientes.append(destino)
        self.assertEqual(vistos, set(notacion.PASOS))

    def test_cada_paso_termina_o_sigue(self):
        for nombre, paso in notacion.PASOS.items():
            if paso["pide"] == "boton":
                for opcion in paso["opciones"]:
                    self.assertTrue(opcion.get("siguiente") or opcion.get("cierra"),
                                    f"{nombre}/{opcion['id']} no sigue ni cierra")
            else:
                self.assertTrue(paso.get("siguiente") or paso.get("cierra"),
                                f"{nombre} no sigue ni cierra")

    def test_la_tabla_viaja_entera(self):
        tabla = notacion.tabla()
        self.assertEqual(json.loads(json.dumps(tabla))["pasos"].keys(),
                         notacion.PASOS.keys())

    # Los tres atajos estan escritos en la tabla y los dos interpretes los
    # leen a ciegas: si uno queda mal escrito, lo que falla es la pantalla.
    def test_el_circulo_directo_vale_por_un_boton_que_existe(self):
        for nombre, paso in notacion.PASOS.items():
            directo = paso.get("directo")
            if not directo:
                continue
            self.assertEqual(paso["pide"], "boton", nombre)
            self.assertIn(directo["lado"], ("pelota", "rival"), nombre)
            boton = next((o for o in paso["opciones"] if o["id"] == directo["por"]), None)
            self.assertIsNotNone(boton, f"{nombre}: no hay boton {directo['por']}")
            if not boton.get("cierra"):
                # el circulo contesta el paso al que lleva el boton
                self.assertEqual(notacion.PASOS[boton["siguiente"]]["pide"], "jugador",
                                 nombre)

    def test_solo_se_asume_un_jugador_donde_se_pide_un_jugador(self):
        for nombre, paso in notacion.PASOS.items():
            asume = paso.get("asume")
            if not asume:
                continue
            self.assertEqual(paso["pide"], "jugador", nombre)
            self.assertIn(asume["quien"], ("armador", "atacante"), nombre)
            self.assertIn("{jugador}", asume["titulo"], nombre)
            # lo que se ofrece en su lugar es la zona del paso que sigue
            self.assertEqual(notacion.PASOS[paso["siguiente"]]["pide"], "zona", nombre)
            if asume.get("otro"):
                propios = [o["id"] for o in paso.get("opciones", ())]
                self.assertNotIn(asume["otro"]["id"], propios, nombre)

    def test_lo_que_se_junta_son_dos_pasos_de_botones(self):
        for nombre, paso in notacion.PASOS.items():
            for opcion in paso.get("opciones", ()):
                # el "+" es el que arma el id de la grilla
                self.assertNotIn("+", opcion["id"], f"{nombre}/{opcion['id']}")
                if opcion.get("junta"):
                    self.assertEqual(paso["pide"], "boton", nombre)
                    self.assertEqual(notacion.PASOS[opcion["siguiente"]]["pide"], "boton",
                                     f"{nombre}/{opcion['id']}")


# El interprete del navegador solo apila texto y mueve el cursor, pero es el
# que termina escribiendo la linea que se guarda. Si hay node a mano se le
# pasan los mismos toques y se compara; si no hay, este test se saltea y el de
# arriba (que corre siempre) sigue cuidando la tabla.
CRUCE_JS = """
const fs = require("fs");
const codigo = fs.readFileSync(process.argv[2], "utf8");
// armador.js no es un modulo: se evalua y se sacan los nombres de adentro
const modulo = eval(codigo + "\\n;({A: Armador, cargar: cargarNotacion})");
const datos = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
modulo.cargar(datos.tabla);

let fallos = 0;
const avisar = (caso, que) => {
  fallos++;
  if(fallos <= 5) console.log("DISTINTO en " + JSON.stringify(caso.esperado) + ": " + que);
};
const nulo = v => (v === undefined ? null : v);

for(const caso of datos.casos){
  const armador = new modulo.A(caso.contexto);
  const historia = [""];
  let igual = true;
  caso.toques.forEach(([id, valor], i) => {
    // antes de cada toque: lo mismo a la vista que en Python
    const aca = {
      ofrece: armador.opciones().map(o => [o.id, nulo(o.texto)]),
      titulo: armador.titulo(),
      asumido: nulo(armador.asumido()),
    };
    if(igual && JSON.stringify(aca) !== JSON.stringify(caso.rastro.pasos[i])){
      igual = false;
      avisar(caso, "toque " + i + " (" + id + ") ofrece " + JSON.stringify(aca) +
                   " y Python " + JSON.stringify(caso.rastro.pasos[i]));
    }
    armador.tocar(id, valor);
    historia.push(armador.linea);
  });
  if(!igual) continue;
  if(armador.linea !== caso.esperado || !armador.cerrada){
    avisar(caso, "salio " + JSON.stringify(armador.linea));
    continue;
  }
  if(nulo(armador.arrastre) !== caso.rastro.arrastre){
    avisar(caso, "arrastra " + armador.arrastre + " y Python " + caso.rastro.arrastre);
    continue;
  }
  // deshacer tiene que devolver la linea a cada paso anterior, exactamente
  for(let i = historia.length - 1; i > 0; i--){
    if(armador.linea !== historia[i]){ fallos++; break; }
    armador.deshacer();
  }
  if(armador.linea !== "") fallos++;
}
console.log("revisadas " + datos.casos.length + ", distintas " + fallos);
process.exit(fallos === 0 ? 0 : 1);
"""


@unittest.skipUnless(NODE, "no hay node para correr el interprete del navegador")
class TestInterpreteDelNavegador(unittest.TestCase):
    """El de Python y el del navegador leen la misma tabla: con los mismos
    toques tienen que ofrecer lo mismo en cada paso y escribir la misma
    linea."""

    def _caso(self, argumentos: dict, toques: list, esperado: str) -> dict:
        return {"esperado": esperado, "toques": toques,
                "contexto": contexto_js(argumentos),
                "rastro": rastro(notacion.Armador(**argumentos), toques)}

    def test_el_navegador_escribe_lo_mismo_que_python(self):
        casos = []
        # los atajos, con los dos equipos con puestos: en los partidos
        # guardados hay equipos sin rotacion y ahi no se ven
        for espera, toques, linea in LINEAS_CON_ATAJOS:
            casos.append(self._caso(
                dict(espera=espera, equipo_saca="A", equipo_con_la_pelota="B",
                     planteles=PLANTELES_CON_PUESTOS, sacador_conocido=True,
                     armadores=ARMADORES, atacantes=ATACANTES),
                con_numero(toques), linea))
        for archivo in sorted(CARPETA_DATOS.glob("*.txt")):
            sesion = sesion_web.SesionPartido()
            for linea in lineas_del_volcado(archivo):
                instantanea = sesion.instantanea()
                espera = instantanea["pendiente"]["espera"]
                if (espera and es_jugada(linea, espera)
                        and not usa_notacion_retirada(linea)):
                    armador = armador_para(instantanea)
                    hoy = como_se_escribe_hoy(linea)
                    candidatos = [int(n) for n in dict.fromkeys(re.findall(r"\d+", linea))]
                    toques = buscar_toques(armador, hoy, candidatos)
                    self.assertIsNotNone(toques, f"{archivo.name}: {linea!r}")
                    casos.append(self._caso(lo_que_dice_el_motor(instantanea),
                                            [list(toque) for toque in toques], hoy))
                sesion.enviar(linea)
        self.assertTrue(casos, "no hay jugadas para cruzar")

        with tempfile.TemporaryDirectory() as carpeta:
            guion = Path(carpeta) / "cruce.js"
            datos = Path(carpeta) / "casos.json"
            guion.write_text(CRUCE_JS, encoding="utf-8")
            datos.write_text(json.dumps({"tabla": notacion.tabla(), "casos": casos},
                                        ensure_ascii=False), encoding="utf-8")
            corrida = subprocess.run(
                [NODE, str(guion), str(ARMADOR_JS), str(datos)],
                capture_output=True, text=True)
        self.assertEqual(corrida.returncode, 0,
                         f"el interprete del navegador no coincide:\n{corrida.stdout}{corrida.stderr}")


if __name__ == "__main__":
    unittest.main()
