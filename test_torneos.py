"""
Tests de las etiquetas de campeonato de cada partido.

Se corren con:
    python -m unittest test_torneos

El volcado no sabe en que campeonato se jugo, asi que la etiqueta se anota a
mano y se pega encima, igual que el resto de los arreglos del resumen. Lo que
cuidan estos tests es que "pegar encima" no sea "pisar" -- poner una etiqueta
no puede cambiar el marcador -- y que la normalizacion agrupe de verdad: sin
ella "#Apertura" y "apertura" serian dos campeonatos distintos.
"""
import unittest

import archivo_partidos as ap


class TestComoSeNormalizan(unittest.TestCase):

    def test_se_les_pone_el_numeral(self):
        self.assertEqual(ap.etiquetas_de("nacional2026"), ["#nacional2026"])
        self.assertEqual(ap.etiquetas_de("#nacional2026"), ["#nacional2026"])

    def test_van_en_minusculas_para_que_agrupen(self):
        self.assertEqual(ap.etiquetas_de("#Apertura"), ["#apertura"])
        self.assertEqual(ap.etiquetas_de("APERTURA"), ["#apertura"])

    def test_un_partido_puede_tener_varias(self):
        # del nacional Y semifinal a la vez
        self.assertEqual(ap.etiquetas_de("#nacional2026 #semifinal"),
                         ["#nacional2026", "#semifinal"])

    def test_se_separan_por_espacios_o_comas(self):
        self.assertEqual(ap.etiquetas_de("nacional, semifinal"),
                         ["#nacional", "#semifinal"])
        self.assertEqual(ap.etiquetas_de("nacional   semifinal"),
                         ["#nacional", "#semifinal"])

    def test_no_se_repiten(self):
        self.assertEqual(ap.etiquetas_de("#apertura Apertura #APERTURA"), ["#apertura"])

    def test_sin_nada_no_hay_etiquetas(self):
        for vacio in ("", "   ", None, "#", "  #  "):
            self.assertEqual(ap.etiquetas_de(vacio), [], repr(vacio))


class TestLaEtiquetaViveEnLaFila(unittest.TestCase):

    def fila(self, correcciones=None):
        base = {"id": "partido_20260914_120000.txt", "equipo": "Palestino",
                "rival": "UVC", "fecha": "2026-09-14", "hora": "12:00",
                "sets": "2-0", "parciales": [], "puntos": 50,
                "volcado": "partido_20260914_120000.txt", "informe": None,
                "torneo": ""}
        return ap.aplicar_correccion(base, correcciones or {})

    def test_sin_etiqueta_la_lista_esta_vacia(self):
        fila = self.fila()
        self.assertEqual(fila["torneo"], "")
        self.assertEqual(fila["etiquetas"], [])

    def test_la_etiqueta_puesta_a_mano_llega_partida(self):
        fila = self.fila({"partido_20260914_120000.txt":
                          {"torneo": "#Nacional2026 semifinal"}})
        self.assertEqual(fila["torneo"], "#Nacional2026 semifinal")
        self.assertEqual(fila["etiquetas"], ["#nacional2026", "#semifinal"])

    def test_queda_marcada_como_corregida_a_mano(self):
        # la pantalla muestra que campos no salen del .txt
        fila = self.fila({"partido_20260914_120000.txt": {"torneo": "#apertura"}})
        self.assertIn("torneo", fila["corregido"])

    def test_poner_la_etiqueta_no_toca_el_resto_del_resumen(self):
        fila = self.fila({"partido_20260914_120000.txt": {"torneo": "#apertura"}})
        self.assertEqual(fila["sets"], "2-0")
        self.assertEqual(fila["rival"], "UVC")
        self.assertEqual(fila["puntos"], 50)

    def test_es_un_campo_corregible_mas(self):
        self.assertIn("torneo", ap.CAMPOS_CORREGIBLES)


class TestDesdeElListadoDeVerdad(unittest.TestCase):

    def test_todas_las_filas_traen_los_dos_campos(self):
        filas = ap.listar_partidos()
        if not filas:
            self.skipTest("no hay partidos guardados")
        self.assertTrue(all("torneo" in f and "etiquetas" in f for f in filas))
        self.assertTrue(all(isinstance(f["etiquetas"], list) for f in filas))


if __name__ == "__main__":
    unittest.main()
