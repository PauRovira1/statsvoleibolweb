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

    def test_armador_no_es_una_posicion_de_esta_lista(self):
        # sale del _S de la rotacion; ponerlo a mano seria tener el dato en dos
        # lugares que pueden discrepar
        self.assertNotIn("Armador", alm.POSICIONES)
        alm.guardar_posiciones("Palestino", {"3": "Armador"})
        self.assertEqual(alm.posiciones_del_equipo("Palestino"), {})


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


if __name__ == "__main__":
    unittest.main()
