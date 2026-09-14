"""Tests de la ficha de jugador que alimenta la pestana Jugadores."""
import shutil
import tempfile
import unittest
from pathlib import Path

import estadisticas_jugadores as ej
import sesion_web

DATOS_REALES = Path(__file__).resolve().parent / "Datos"


class TestDeduplicado(unittest.TestCase):
    """Contar dos veces el mismo partido duplicaria en silencio las cifras de
    todos los jugadores, asi que es lo primero que hay que asegurar."""

    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.carpeta, ignore_errors=True)

    def _copiar(self, origen, nombre):
        shutil.copyfile(DATOS_REALES / origen, self.carpeta / nombre)

    def test_dos_copias_del_mismo_partido_cuentan_una(self):
        self._copiar("partido_20260908_141643.txt", "partido_20260101_000000.txt")
        self._copiar("partido_20260908_141643.txt", "partido_20260202_000000.txt")
        elegidos, descartados = ej.partidos_unicos(self.carpeta)
        self.assertEqual(len(elegidos), 1)
        self.assertEqual(len(descartados), 1)
        self.assertIn("mismo partido", descartados[0]["motivo"])

    def test_una_recarga_a_medias_no_suma_otra_vez_el_primer_set(self):
        # el 180710 es el mismo partido que el 141454 pero solo con el set 1
        self._copiar("partido_20260908_141454.txt", "partido_20260101_000000.txt")
        self._copiar("partido_20260903_180710.txt", "partido_20260202_000000.txt")
        elegidos, descartados = ej.partidos_unicos(self.carpeta)
        self.assertEqual([e["archivo"] for e in elegidos], ["partido_20260101_000000.txt"])
        self.assertIn("con menos sets", descartados[0]["motivo"])

    def test_partidos_distintos_no_se_descartan(self):
        self._copiar("partido_20260908_141643.txt", "partido_20260101_000000.txt")
        self._copiar("partido_20260908_141454.txt", "partido_20260202_000000.txt")
        elegidos, descartados = ej.partidos_unicos(self.carpeta)
        self.assertEqual(len(elegidos), 2)
        self.assertEqual(descartados, [])

    def test_entre_dos_copias_gana_la_que_tiene_mas_secciones(self):
        # el volcado viejo no trae "Armado por armador": quedarse con el
        # perderia los armados de todo el partido
        self._copiar("partido_20260904_120440.txt", "partido_20260101_000000.txt")
        self._copiar("partido_20260908_141643.txt", "partido_20260202_000000.txt")
        elegidos, _ = ej.partidos_unicos(self.carpeta)
        self.assertEqual(len(elegidos), 1)
        self.assertTrue(elegidos[0]["volcado"]["teams"]["Palestino"]["armado_armador"])

    def test_una_carpeta_vacia_no_rompe(self):
        self.assertEqual(ej.partidos_unicos(self.carpeta), ([], []))


class TestFicha(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.agregado = ej.agregar(DATOS_REALES)

    def test_suma_los_dos_partidos_de_un_atacante(self):
        f = ej.ficha("Palestino", "88", self.agregado)
        self.assertEqual(f["partidos"], 2)
        self.assertEqual(f["indicadores"]["ataques"], 27)      # 14 + 13
        self.assertEqual(f["indicadores"]["recepciones"], 15)  # 10 + 5
        self.assertFalse(f["armador"])
        self.assertIsNone(f["armado"])

    def test_suma_los_dos_partidos_de_un_armador(self):
        f = ej.ficha("Palestino", "3", self.agregado)
        self.assertTrue(f["armador"])
        self.assertEqual(f["indicadores"]["armados"], 89)      # 34 + 55
        self.assertEqual(f["armado"]["total"], 89)

    def test_el_total_por_zona_coincide_con_el_total_de_ataques(self):
        f = ej.ficha("Palestino", "88", self.agregado)
        por_zona = sum(z["ataques"] for z in f["ataque"]["por_zona"])
        self.assertEqual(por_zona, f["ataque"]["total"]["ataques"])

    def test_la_matriz_de_armado_no_supera_el_total(self):
        # solo entran los armados que vienen de una recepcion de saque
        f = ej.ficha("Palestino", "3", self.agregado)
        self.assertLessEqual(f["armado"]["con_recepcion"], f["armado"]["total"])
        suma = sum(sum(fila["valores"]) for fila in f["armado"]["matriz_calidad"])
        self.assertEqual(suma, f["armado"]["con_recepcion"])

    def test_el_flag_de_armador_sale_del_S_y_no_de_haber_armado(self):
        # sin rotacion cargada el volcado lista como armador a cualquiera que
        # haya armado de emergencia; esos no son armadores
        rival = next(e for e in ej.listado(DATOS_REALES)["equipos"]
                     if e["nombre"] == "O'sommer")
        self.assertEqual([j["dorsal"] for j in rival["jugadores"] if j["armador"]], [])
        propio = next(e for e in ej.listado(DATOS_REALES)["equipos"]
                      if e["nombre"] == "Palestino")
        self.assertEqual(sorted(j["dorsal"] for j in propio["jugadores"] if j["armador"]),
                         ["3", "99"])

    def test_cada_equipo_tiene_su_propio_dorsal_3(self):
        # los dos equipos tienen un jugador 3 y no son la misma persona
        propio = ej.ficha("Palestino", "3", self.agregado)
        rival = ej.ficha("O'sommer", "3", self.agregado)
        self.assertNotEqual(propio["indicadores"]["ataques"], rival["indicadores"]["ataques"])
        self.assertTrue(propio["armador"])
        self.assertFalse(rival["armador"])

    def test_un_dorsal_que_no_existe_devuelve_none(self):
        self.assertIsNone(ej.ficha("Palestino", "777", self.agregado))
        self.assertIsNone(ej.ficha("Equipo Inventado", "3", self.agregado))

    def test_una_linea_por_partido_con_su_etiqueta(self):
        f = ej.ficha("Palestino", "88", self.agregado)
        self.assertEqual(len(f["por_partido"]), 2)
        self.assertEqual(len(f["evolucion"]), 2)
        self.assertTrue(all(p["etiqueta"].startswith("vs ") for p in f["por_partido"]))
        # el total tiene que ser la suma de las lineas
        self.assertEqual(sum(p["ataques"] for p in f["por_partido"]),
                         f["indicadores"]["ataques"])


class TestListado(unittest.TestCase):

    def test_los_equipos_van_por_cantidad_de_partidos(self):
        # el equipo propio juega todos los partidos, asi que queda primero sin
        # necesidad de configurarlo (y "Palestino B" aparecera solo)
        equipos = ej.listado(DATOS_REALES)["equipos"]
        self.assertEqual(equipos[0]["nombre"], "Palestino")
        self.assertEqual([e["partidos"] for e in equipos],
                         sorted((e["partidos"] for e in equipos), reverse=True))

    def test_avisa_de_los_volcados_descartados(self):
        descartados = ej.listado(DATOS_REALES)["descartados"]
        self.assertTrue(descartados)
        self.assertTrue(all({"archivo", "motivo"} <= set(d) for d in descartados))


if __name__ == "__main__":
    unittest.main()


class TestGuardadosParcialesDelMismoPartido(unittest.TestCase):
    """Guardar el partido varias veces mientras avanza es lo normal. Los
    guardados intermedios no pueden contarse como partidos aparte: sus jugadas
    se sumarian de nuevo y todos los numeros de la ficha quedarian inflados.

    Compararlos por parciales no alcanza: un guardado hecho a mitad de un set
    dice 15-14 donde el completo dice 20-25."""

    LINEAS = (["Local", "Rival", "1_S 2 3 4 5 6", "7_S 8 9 10 11 12", "A"] +
              ["1_5_X/8_3/7_4/9_1_O"] * 10)

    def _carpeta_con_guardados(self, cortes):
        carpeta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, carpeta, ignore_errors=True)
        for numero, corte in enumerate(cortes):
            sesion = sesion_web.SesionPartido()
            for linea in self.LINEAS[:corte]:
                sesion.enviar(linea)
            guardado = Path(sesion.guardar())
            shutil.move(str(guardado), Path(carpeta) / f"partido_2026091{numero}_010000.txt")
        return carpeta

    def test_los_guardados_a_medias_no_cuentan_como_partidos(self):
        carpeta = self._carpeta_con_guardados([7, 9, 12, len(self.LINEAS)])
        elegidos, descartados = ej.partidos_unicos(carpeta)
        self.assertEqual(len(elegidos), 1, [e["archivo"] for e in elegidos])
        self.assertEqual(len(descartados), 3)

    def test_se_queda_con_el_mas_completo(self):
        carpeta = self._carpeta_con_guardados([7, len(self.LINEAS)])
        elegidos, _ = ej.partidos_unicos(carpeta)
        self.assertEqual(elegidos[0]["jugadas"][-1], self.LINEAS[-1])

    def test_las_jugadas_se_cuentan_una_sola_vez(self):
        completo, _ = ej.partidos_unicos(self._carpeta_con_guardados([len(self.LINEAS)]))
        con_parciales, _ = ej.partidos_unicos(
            self._carpeta_con_guardados([7, 9, 12, len(self.LINEAS)]))
        self.assertEqual(completo[0]["puntos"], con_parciales[0]["puntos"])

    def test_dos_partidos_de_verdad_siguen_siendo_dos(self):
        carpeta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, carpeta, ignore_errors=True)
        for numero, rival in enumerate(("Rival", "Otro")):
            sesion = sesion_web.SesionPartido()
            for linea in ["Local", rival, "1_S 2 3 4 5 6", "7_S 8 9 10 11 12", "A",
                          "1_5_A", "1_5_A"]:
                sesion.enviar(linea)
            guardado = Path(sesion.guardar())
            shutil.move(str(guardado), Path(carpeta) / f"partido_2026091{numero}_010000.txt")
        elegidos, descartados = ej.partidos_unicos(carpeta)
        self.assertEqual(len(elegidos), 2)
        self.assertEqual(descartados, [])
