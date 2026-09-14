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
    if armador.linea == objetivo:
        return [] if armador.cerrada else None
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


def armador_para(instantanea: dict) -> notacion.Armador:
    """El armador que corresponde al estado en el que esta el partido. Todo lo
    que necesita saber se lo dice el motor: que bloque toca, de quien es la
    pelota y si el dorsal del sacador se completa solo."""
    pendiente = instantanea["pendiente"]
    return notacion.Armador(
        espera=pendiente["espera"],
        equipo_saca=instantanea["equipo_saca"],
        equipo_con_la_pelota=pendiente["equipo_con_la_pelota"],
        # los que se pueden tocar son los que estan realmente en la cancha
        planteles={letra: rotacion["formacion"]
                   for letra, rotacion in instantanea["rotaciones"].items()},
        sacador_conocido=instantanea["jugador_saca"] is not None,
    )


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
            if espera and es_jugada(linea, espera):
                armador = armador_para(instantanea)
                candidatos = [int(n) for n in dict.fromkeys(re.findall(r"\d+", linea))]
                toques = buscar_toques(armador, linea, candidatos)
                self.assertIsNotNone(
                    toques,
                    f"{archivo.name} linea {numero}: no hay forma de armar {linea!r} "
                    f"tocando (estado inicial {armador.estado}, "
                    f"pelota de {armador.equipo_con_la_pelota})",
                )
                # se rearma desde cero con esos toques y tiene que dar igual
                repetido = armador_para(instantanea)
                lados = {}
                for identificador, valor in toques:
                    paso = notacion.PASOS[repetido.estado]
                    if paso["pide"] == "jugador":
                        lados[repetido.estado] = repetido.equipo_de(paso["lado"])
                    repetido.tocar(identificador, valor)
                self.assertEqual(repetido.linea, linea, f"{archivo.name} linea {numero}")
                self.assertTrue(repetido.cerrada, f"{archivo.name} linea {numero}")
                revisadas += 1
                sesion.enviar(linea)
                self._revisar_lados(lados, ultimo_bloque(sesion), instantanea,
                                    f"{archivo.name} linea {numero}: {linea}")
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
                             "j9", "ataque", "z1", "punto")
        self.assertEqual(armador.linea, "1_6_X/7_3/8_4/9_1_P")
        self.assertTrue(armador.cerrada)

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
                             "sin_armado", "j9", "ataque", "z1", "punto")
        self.assertEqual(armador.linea, "1_6_X/7_3/8_4_X/9_1_P")

    def test_el_marcador_de_sin_armado_no_se_puede_poner_dos_veces(self):
        armador = self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4", "sin_armado")
        self.assertNotIn("sin_armado", [o["id"] for o in armador.opciones()])

    def test_libre(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                       "j9", "libre", "z8").linea,
            "1_6_X/7_3/8_4/9_F_8")

    def test_toque(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                       "j9", "toque", "z8").linea,
            "1_6_X/7_3/8_4/9_T_8")

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
            self.armar("primera", "j9", "z1", "punto", espera="continuacion").linea,
            "9_A_1_P")

    def test_el_ataque_de_primera_no_existe_en_el_bloque_de_saque(self):
        armador = self.armar("z1", "z6", "sigue")
        self.assertNotIn("primera", [o["id"] for o in armador.opciones()])

    def test_bloqueo_punto(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                       "j9", "ataque", "z1", "bloqueo_punto", "j6").linea,
            "1_6_X/7_3/8_4/9_1_B_6_P")

    def test_toque_de_bloqueo(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                       "j9", "ataque", "z1", "bloqueo_usado", "j6").linea,
            "1_6_X/7_3/8_4/9_1_U_6")

    def test_bloqueo_rejugable(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                       "j9", "ataque", "z1", "bloqueo_rejugable", "j6").linea,
            "1_6_X/7_3/8_4/9_1_R_6")

    def test_malla(self):
        self.assertEqual(
            self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                       "j9", "ataque", "z1", "malla").linea,
            "1_6_X/7_3/8_4/9_1_M")

    def test_defensa_perdida_solo_en_una_continuacion(self):
        self.assertEqual(
            self.armar("j7", "c0", espera="continuacion").linea, "7_0")
        continuacion = self.armar("j7", espera="continuacion")
        self.assertIn("perdida", [o["id"] for o in continuacion.opciones()])
        saque = self.armar("z1", "z6", "sigue", "j7")
        self.assertNotIn("perdida", [o["id"] for o in saque.opciones()])

    def test_el_bloqueador_sale_del_equipo_rival(self):
        armador = self.armar("z1", "z6", "sigue", "j7", "c3", "j8", "z4",
                             "j9", "ataque", "z1", "bloqueo_punto")
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
        self.assertEqual(armador.estado, "ATACA_TIPO")

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
for(const caso of datos.casos){
  const armador = new modulo.A(caso.contexto);
  const historia = [""];
  for(const [id, valor] of caso.toques){
    armador.tocar(id, valor);
    historia.push(armador.linea);
  }
  if(armador.linea !== caso.esperado || !armador.cerrada){
    fallos++;
    if(fallos <= 5) console.log("DISTINTO: " + JSON.stringify(caso.esperado) +
                                " salio " + JSON.stringify(armador.linea));
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
    """El de Python y el del navegador leen la misma tabla: tienen que
    escribir la misma linea con los mismos toques."""

    def test_el_navegador_escribe_lo_mismo_que_python(self):
        casos = []
        for archivo in sorted(CARPETA_DATOS.glob("*.txt")):
            sesion = sesion_web.SesionPartido()
            for linea in lineas_del_volcado(archivo):
                instantanea = sesion.instantanea()
                espera = instantanea["pendiente"]["espera"]
                if espera and es_jugada(linea, espera):
                    armador = armador_para(instantanea)
                    candidatos = [int(n) for n in dict.fromkeys(re.findall(r"\d+", linea))]
                    toques = buscar_toques(armador, linea, candidatos)
                    self.assertIsNotNone(toques, f"{archivo.name}: {linea!r}")
                    casos.append({
                        "esperado": linea,
                        "toques": toques,
                        "contexto": {
                            "espera": espera,
                            "equipoSaca": instantanea["equipo_saca"],
                            "equipoConLaPelota": instantanea["pendiente"]["equipo_con_la_pelota"],
                            # la formacion, no la rotacion nominal: es la que
                            # tiene al libero puesto (ver armador_para)
                            "planteles": {letra: rotacion["formacion"]
                                          for letra, rotacion in instantanea["rotaciones"].items()},
                            "sacadorConocido": instantanea["jugador_saca"] is not None,
                        },
                    })
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
