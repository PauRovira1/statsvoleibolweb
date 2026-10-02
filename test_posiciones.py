"""
Tests de las etiquetas de posicion: Libero, Punta, Opuesto y Central.

Se corren con:
    python -m unittest test_posiciones

Las posiciones se anotan a mano y viven junto a los nombres, porque son lo
mismo: datos del jugador que el volcado no guarda. "Armador" NO esta entre
ellas y no se pone a mano -- sale del _S de las rotaciones, o sea del propio
partido. Anotarlo tambien seria tener el mismo dato en dos lugares que pueden
discrepar, y eso es justo lo que estos tests cuidan.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import almacenamiento as alm
import estadisticas_jugadores as ej
import servidor_voley as srv


class BasePosiciones(unittest.TestCase):

    def setUp(self):
        # un plantel de mentira en una carpeta temporal: nada toca el real
        self.carpeta = Path(tempfile.mkdtemp())
        # _ES_LOCAL tambien: decide si ademas de la carpeta de escritura se
        # lee la del repo. Sin esto los volcados de Datos/ no se ven y los
        # tests de integracion se saltean solos sin que se note.
        for objeto, nombre, valor in ((alm, "CARPETA_ESCRITURA", self.carpeta),
                                      (alm, "_ES_LOCAL", False),
                                      (alm, "_plantel", None),
                                      (alm, "_momento_plantel", 0.0)):
            parche = mock.patch.object(objeto, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)

    def guardado(self) -> dict:
        return json.loads((self.carpeta / "plantel" / "lista.json").read_text("utf-8"))


class TestGuardarLasPosiciones(BasePosiciones):

    def test_se_guardan_y_se_leen(self):
        alm.guardar_posiciones("Palestino", {"9": "Libero", "13": "Punta"})
        self.assertEqual(alm.posiciones_del_equipo("Palestino"),
                         {"9": "Libero", "13": "Punta"})

    def test_conviven_con_los_nombres_en_el_mismo_archivo(self):
        # se editan en la misma pantalla; guardar una no puede pisar la otra
        alm.guardar_plantel("Palestino", {"9": "Sofia"})
        alm.guardar_posiciones("Palestino", {"9": "Libero"})
        self.assertEqual(alm.leer_plantel()["Palestino"], {"9": "Sofia"})
        self.assertEqual(alm.posiciones_del_equipo("Palestino"), {"9": "Libero"})
        self.assertEqual(sorted(self.guardado()), ["plantel", "posiciones"])

    def test_guardar_nombres_despues_no_borra_las_posiciones(self):
        alm.guardar_posiciones("Palestino", {"9": "Libero"})
        alm.guardar_plantel("Palestino", {"9": "Sofia", "13": "Ana"})
        self.assertEqual(alm.posiciones_del_equipo("Palestino"), {"9": "Libero"})

    def test_cada_equipo_tiene_las_suyas(self):
        alm.guardar_posiciones("Palestino", {"9": "Libero"})
        alm.guardar_posiciones("Palestino B", {"9": "Central"})
        self.assertEqual(alm.posiciones_del_equipo("Palestino"), {"9": "Libero"})
        self.assertEqual(alm.posiciones_del_equipo("Palestino B"), {"9": "Central"})

    def test_un_dorsal_sin_posicion_se_saca(self):
        alm.guardar_posiciones("Palestino", {"9": "Libero", "13": "Punta"})
        alm.guardar_posiciones("Palestino", {"9": "Libero", "13": ""})
        self.assertEqual(alm.posiciones_del_equipo("Palestino"), {"9": "Libero"})


class TestLoQueSeAcepta(BasePosiciones):

    def test_se_guarda_siempre_la_forma_canonica(self):
        # si no, filtrar por etiqueta dependeria de como se tipeo
        alm.guardar_posiciones("Palestino", {"9": "libero", "13": "LÍBERO",
                                             "15": "  Central  "})
        self.assertEqual(alm.posiciones_del_equipo("Palestino"),
                         {"9": "Libero", "13": "Libero", "15": "Central"})

    def test_una_posicion_inventada_no_entra(self):
        alm.guardar_posiciones("Palestino", {"9": "Libero", "13": "Wing Spiker"})
        self.assertEqual(alm.posiciones_del_equipo("Palestino"), {"9": "Libero"})

    def test_armador_tambien_se_puede_poner_a_mano(self):
        """Antes no se podia: se sacaba solo del _S de la rotacion. Pero un
        partido cargado sin rotacion no tiene ningun _S, y ahi el armador no
        figuraba como tal por mas que hubiera armado los tres sets.

        Que las dos fuentes no se contradigan lo cuida
        estadisticas_jugadores.marcado_como_armador: la etiqueta suma, nunca
        le saca el rol a quien el volcado marco."""
        self.assertIn("Armador", alm.POSICIONES)
        alm.guardar_posiciones("Palestino", {"3": "armador"})
        self.assertEqual(alm.posiciones_del_equipo("Palestino"), {"3": "Armador"})


class TestDesdeElServidor(BasePosiciones):

    def test_se_pueden_guardar_solas_sin_tocar_los_nombres(self):
        alm.guardar_plantel("Palestino", {"9": "Sofia"})
        r = srv.guardar_nombres("Palestino", None, None, {"9": "Libero"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["posiciones"], {"9": "Libero"})
        self.assertEqual(alm.leer_plantel()["Palestino"], {"9": "Sofia"})

    def test_se_guardan_junto_con_los_nombres(self):
        r = srv.guardar_nombres("Palestino", {"9": "Sofia"}, None, {"9": "Libero"})
        self.assertEqual(alm.leer_plantel()["Palestino"], {"9": "Sofia"})
        self.assertEqual(alm.posiciones_del_equipo("Palestino"), {"9": "Libero"})
        self.assertIn("posicion", r["mensaje"])

    def test_sin_nombres_el_mensaje_no_dice_que_los_borro(self):
        r = srv.guardar_nombres("Palestino", {}, None, {"9": "Libero"})
        self.assertNotIn("vuelve a usar", r["mensaje"])
        self.assertIn("1 posicion", r["mensaje"])

    def test_sin_equipo_no_se_guarda_nada(self):
        with self.assertRaises(srv.arch.RutaInvalida):
            srv.guardar_nombres("", None, None, {"9": "Libero"})


class TestLaFichaLasPublica(BasePosiciones):
    """La pantalla necesita la posicion en los dos lados: en el listado para
    poder filtrar sin pedir cada ficha, y en la ficha para decidir que tablas
    mostrar."""

    def test_el_listado_trae_la_posicion_de_cada_uno(self):
        equipos = ej.listado()["equipos"]
        if not equipos:
            self.skipTest("no hay partidos guardados")
        equipo = equipos[0]
        alm.guardar_posiciones(equipo["nombre"],
                               {equipo["jugadores"][0]["dorsal"]: "Central"})
        de_nuevo = ej.listado()["equipos"][0]
        marcado = next(j for j in de_nuevo["jugadores"]
                       if j["dorsal"] == equipo["jugadores"][0]["dorsal"])
        self.assertEqual(marcado["posicion"], "Central")
        self.assertTrue(all("posicion" in j for j in de_nuevo["jugadores"]))

    def test_la_ficha_trae_la_posicion(self):
        equipos = ej.listado()["equipos"]
        if not equipos:
            self.skipTest("no hay partidos guardados")
        equipo, dorsal = equipos[0]["nombre"], equipos[0]["jugadores"][0]["dorsal"]
        alm.guardar_posiciones(equipo, {dorsal: "Opuesto"})
        ficha = ej.ficha(equipo, dorsal)
        self.assertEqual(ficha["posicion"], "Opuesto")

    def test_la_posicion_y_el_flag_de_armador_son_campos_distintos(self):
        equipos = ej.listado()["equipos"]
        if not equipos:
            self.skipTest("no hay partidos guardados")
        armador = next((j for e in equipos for j in e["jugadores"] if j["armador"]), None)
        if armador is None:
            self.skipTest("ningun armador marcado en los volcados")
        self.assertEqual(armador["posicion"], "")   # nadie lo anoto a mano
        self.assertTrue(armador["armador"])         # y aun asi es armador


class TestElTagArmador(unittest.TestCase):
    """El armador tiene dos fuentes y tienen que sumarse, no competir.

    El _S de la rotacion lo dice el propio partido. La etiqueta a mano existe
    porque un partido cargado SIN rotacion no tiene ningun _S: ahi el armador
    no figuraba como tal por mas que hubiera armado los tres sets.

    La regla que hace que no se contradigan: la etiqueta solo puede agregar el
    rol. Nunca se lo quita a quien el volcado marco."""

    # el 28 lleva _S; el 13 y el 3 no
    PARTIDO = ["Palestino", "UVC", "28_S 5 13 88 3 40", "", "B",
               "9_1_5_X/3_3/28_4/13_1_P", "1_5_E",
               "9_1_5_X/3_3/28_4/13_1_P"]

    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp())
        for objeto, nombre, valor in ((alm, "CARPETA_ESCRITURA", self.carpeta),
                                      (alm, "_ES_LOCAL", True),
                                      (alm, "_plantel", None),
                                      (alm, "_momento_plantel", 0.0),
                                      (srv.av, "CARPETA_DATOS", self.carpeta / "Datos")):
            parche = mock.patch.object(objeto, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)
        import sesion_web
        sesion_web.SesionPartido(self.PARTIDO).guardar()

    def armador(self, dorsal) -> bool:
        return ej.ficha("Palestino", dorsal)["armador"]

    def test_sin_etiquetas_manda_el_S_de_la_rotacion(self):
        self.assertTrue(self.armador("28"))
        self.assertFalse(self.armador("13"))

    def test_la_etiqueta_a_mano_tambien_lo_marca(self):
        alm.guardar_posiciones("Palestino", {"13": "Armador"})
        self.assertTrue(self.armador("13"))
        self.assertEqual(ej.ficha("Palestino", "13")["posicion"], "Armador")

    def test_la_etiqueta_no_le_saca_el_rol_a_quien_lo_tiene_por_el_volcado(self):
        """Lo que hace imposible que las dos fuentes se contradigan."""
        alm.guardar_posiciones("Palestino", {"28": "Punta"})
        self.assertTrue(self.armador("28"))
        self.assertEqual(ej.ficha("Palestino", "28")["posicion"], "Punta")

    def test_el_listado_lo_marca_igual_que_la_ficha(self):
        """Las dos pantallas leen lo mismo: si discreparan, el selector
        mostraria la etiqueta y la ficha de al lado no."""
        alm.guardar_posiciones("Palestino", {"13": "Armador"})
        jugadores = {j["dorsal"]: j for j in ej.listado()["equipos"][0]["jugadores"]}
        self.assertTrue(jugadores["13"]["armador"])
        self.assertTrue(jugadores["28"]["armador"])
        self.assertFalse(jugadores["3"]["armador"])


if __name__ == "__main__":
    unittest.main()
