"""
Tests del filtro por campeonato en las estadisticas.

Se corren con:
    python -m unittest test_campeonatos

Un club juega varias ligas en el mismo año y los numeros de una no dicen nada
de la otra: 40% de eficacia contra equipos de primera y contra equipos de
cuarta sumados dan un promedio que no describe ningun partido real. Por eso
se puede mirar un campeonato solo.

Lo que cuidan estos tests:

  - que el filtro elija de verdad (y que sin filtro se sumen todos);
  - que se puedan elegir VARIOS y cada partido se cuente una sola vez,
    aunque tenga mas de una de las etiquetas elegidas; y que #todos no se
    combine con los demas, porque eso duplicaria;
  - que la lista de campeonatos salga de TODOS los partidos y no de los que
    quedan despues de filtrar, que es lo que dejaria al selector sin la
    opcion de volver;
  - y que el filtro llegue igual a la ficha del jugador, al resumen del
    equipo y al listado, que es donde se miran los numeros.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import almacenamiento as alm
import estadisticas_jugadores as ej
import servidor_voley as srv
import sesion_web


# Dos partidos distintos del mismo equipo. El segundo tiene un punto mas, asi
# que las cifras de cada uno se distinguen de las de la suma.
APERTURA = ["Palestino", "UVC", "28_S 5 13 88 3 40", "", "B",
            "9_1_5_X/3_3/28_4/13_1_P", "1_5_A"]
NACIONAL = ["Palestino", "Sarmiento", "28_S 5 13 88 3 40", "", "B",
            "9_1_5_X/3_3/28_4/13_1_P", "1_5_A", "1_5_A"]


class BaseCampeonatos(unittest.TestCase):

    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp())
        for objeto, nombre, valor in ((alm, "CARPETA_ESCRITURA", self.carpeta),
                                      # True = se lee SOLO la carpeta temporal.
                                      # Con False se leerian tambien los
                                      # volcados del repo y estos tests
                                      # contarian partidos que no son suyos.
                                      (alm, "_ES_LOCAL", True),
                                      (alm, "_correcciones", None),
                                      (alm, "_momento_correcciones", 0.0),
                                      (srv.av, "CARPETA_DATOS", self.carpeta / "Datos")):
            parche = mock.patch.object(objeto, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)

        self.archivos = {}
        for clave, lineas in (("apertura", APERTURA), ("nacional", NACIONAL)):
            self.archivos[clave] = Path(sesion_web.SesionPartido(lineas).guardar()).name
        self.etiquetar({self.archivos["apertura"]: "#apertura",
                        self.archivos["nacional"]: "#nacional2026"})

    def etiquetar(self, por_archivo: dict):
        """Las etiquetas no salen del .txt: se anotan sobre la fila."""
        destino = self.carpeta / "correcciones" / "lista.json"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(json.dumps(
            {"correcciones": {a: {"torneo": t} for a, t in por_archivo.items()}}),
            encoding="utf-8")
        alm._correcciones = None

    def partidos(self, campeonato=""):
        return [p["archivo"] for p in ej.agregar(campeonato=campeonato)["elegidos"]]


class TestElFiltroElige(BaseCampeonatos):

    def test_sin_campeonato_se_suman_todos(self):
        self.assertEqual(sorted(self.partidos()), sorted(self.archivos.values()))

    def test_con_campeonato_queda_solo_ese(self):
        self.assertEqual(self.partidos("#apertura"), [self.archivos["apertura"]])
        self.assertEqual(self.partidos("#nacional2026"), [self.archivos["nacional"]])

    def test_se_escribe_como_sea(self):
        """Lo que llega de la pantalla se normaliza igual que la etiqueta del
        partido: sin eso "Apertura" y "#apertura" serian dos campeonatos."""
        for escrito in ("#apertura", "apertura", "APERTURA", " #Apertura "):
            self.assertEqual(self.partidos(escrito), [self.archivos["apertura"]], escrito)

    def test_un_campeonato_que_no_existe_no_trae_nada(self):
        self.assertEqual(self.partidos("#no-existe"), [])

    def test_un_partido_sin_etiqueta_solo_esta_en_todos(self):
        self.etiquetar({self.archivos["apertura"]: "#apertura"})
        self.assertEqual(len(self.partidos()), 2)
        self.assertEqual(self.partidos("#apertura"), [self.archivos["apertura"]])


class TestVariosCampeonatos(BaseCampeonatos):
    """Se pueden elegir varios campeonatos juntos: se suman los partidos que
    tengan cualquiera de ellos, cada uno una sola vez."""

    def test_dos_campeonatos_juntos_suman_los_dos(self):
        self.assertEqual(sorted(self.partidos("#apertura #nacional2026")),
                         sorted(self.archivos.values()))
        self.assertEqual(sorted(self.partidos("apertura, nacional2026")),
                         sorted(self.archivos.values()))

    def test_un_partido_con_dos_etiquetas_elegidas_cuenta_una_vez(self):
        self.etiquetar({self.archivos["apertura"]: "#apertura #semifinal",
                        self.archivos["nacional"]: "#nacional2026"})
        self.assertEqual(self.partidos("#apertura #semifinal"), [self.archivos["apertura"]])
        jugador = ej.agregar(campeonato="#apertura #semifinal")["equipos"]["Palestino"]["13"]
        self.assertEqual(len(jugador["partidos"]), 1)

    def test_todos_no_se_combina(self):
        """#todos junto con otro no suma todo dos veces: se ignora y queda el
        campeonato elegido."""
        self.assertEqual(self.partidos("#todos #apertura"), [self.archivos["apertura"]])
        self.assertEqual(sorted(self.partidos("#todos")), sorted(self.archivos.values()))

    def test_dice_cuales_estan_puestos(self):
        self.assertEqual(ej.agregar(campeonato="nacional2026 apertura")["campeonato"],
                         "#nacional2026 #apertura")

    def test_la_ficha_y_el_equipo_con_dos(self):
        self.assertEqual(srv.responder_jugador(
            "Palestino", "13", "#apertura #nacional2026")["jugador"]["partidos"], 2)
        self.assertEqual(srv.responder_equipo(
            "Palestino", "#apertura #nacional2026")["equipo"]["partidos"], 2)

    def test_un_campeonato_solo_no_es_lo_mismo_que_todos(self):
        # si fueran lo mismo este filtro no serviria para nada
        una = ej.agregar(campeonato="#apertura")["equipos"]["Palestino"]
        todas = ej.agregar()["equipos"]["Palestino"]
        self.assertLess(len(una["13"]["partidos"]), len(todas["13"]["partidos"]))


class TestElSelectorNoSeQuedaSinOpciones(BaseCampeonatos):

    def test_los_campeonatos_salen_de_todos_los_partidos(self):
        """Aun con uno puesto se ofrecen los dos: si salieran de los partidos
        que quedan despues de filtrar, elegir uno borraria los demas del
        selector y no habria como volver."""
        for puesto in ("", "#apertura", "#nacional2026"):
            self.assertEqual(ej.agregar(campeonato=puesto)["campeonatos"],
                             ["#apertura", "#nacional2026"], puesto)

    def test_dice_cual_esta_puesto(self):
        self.assertEqual(ej.agregar()["campeonato"], "")
        self.assertEqual(ej.agregar(campeonato="apertura")["campeonato"], "#apertura")


class TestLlegaALasPantallas(BaseCampeonatos):

    def test_el_listado_cuenta_solo_los_de_ese_campeonato(self):
        self.assertEqual(ej.listado()["equipos"][0]["partidos"], 2)
        self.assertEqual(ej.listado(campeonato="#apertura")["equipos"][0]["partidos"], 1)

    def test_el_listado_trae_los_campeonatos_para_pintar_el_selector(self):
        datos = ej.listado(campeonato="#apertura")
        self.assertEqual(datos["campeonatos"], ["#apertura", "#nacional2026"])
        self.assertEqual(datos["campeonato"], "#apertura")

    def test_la_ficha_del_jugador_cambia_con_el_campeonato(self):
        """El 13 ataca en los dos partidos: con el campeonato puesto su ficha
        tiene que hablar de uno solo. Es el ultimo eslabon -- el filtro no
        sirve de nada si llega al listado pero no a los numeros."""
        todos = srv.responder_jugador("Palestino", "13")["jugador"]
        uno = srv.responder_jugador("Palestino", "13", "#nacional2026")["jugador"]
        self.assertEqual(todos["partidos"], 2)
        self.assertEqual(uno["partidos"], 1)

    def test_el_resumen_del_equipo_tambien(self):
        """Las dos pantallas salen del mismo listado: si el filtro valiera
        para una sola, Equipo mostraria el recuento de partidos de una liga
        con las estadisticas de todas."""
        self.assertEqual(srv.responder_equipo("Palestino")["equipo"]["partidos"], 2)
        self.assertEqual(
            srv.responder_equipo("Palestino", "#apertura")["equipo"]["partidos"], 1)

    def test_si_el_equipo_no_jugo_ese_campeonato_lo_dice(self):
        respuesta = srv.responder_equipo("Palestino", "#no-existe")
        self.assertFalse(respuesta["ok"])
        self.assertIn("#no-existe", respuesta["mensaje"])


if __name__ == "__main__":
    unittest.main()
