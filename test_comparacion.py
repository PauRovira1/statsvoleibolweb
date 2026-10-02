"""
Tests del promedio contra el que se compara a un jugador.

Se corren con:
    python -m unittest test_comparacion

La ficha de cada jugador termina en una tabla "el jugador contra los que hacen
lo mismo". El promedio de esa tabla tiene que salir SOLO de los que hacen esa
accion. Promediando sobre todo el plantel el numero no describe a nadie: en un
equipo de doce, el promedio de recepcion se reparte entre los cuatro que
reciben y los ocho que no, asi que da la mitad de lo que recibe un receptor de
verdad y cualquiera que reciba aparece muy por encima del equipo sin haber
hecho nada especial. Con los porcentajes es peor: el que nunca ataco entra al
promedio de efectividad como un 0%.

Que filas se muestran segun de que juega cada uno (un libero no ataca ni
bloquea) se decide en la pantalla, igual que las demas tablas de la ficha, y
se prueba desde el navegador.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import almacenamiento as alm
import estadisticas_jugadores as ej
import servidor_voley as srv
import sesion_web


# Un partido armado para que cada jugador haga UNA cosa, asi el promedio de
# cada accion se puede calcular a mano:
#
#   3  -> 4 recepciones (3, 3, 2, 1)      40 -> 1 recepcion (3)
#   13 -> 5 ataques, 3 puntos             88 -> 1 ataque, 0 puntos
#   5  -> 1 defensa (calidad 2), 1 bloqueo punto
#   28 -> 6 armados
PARTIDO = [
    "Palestino", "UVC", "28_S 5 13 88 3 40", "", "B",
    "9_1_5_X/3_3/28_4/13_1_P", "1_5_E",
    "9_1_5_X/3_3/28_4/13_1_P", "1_5_E",
    "9_1_5_X/3_2/28_4/13_1_O",
    "9_1_5_X/40_3/28_4/88_1_D", "7_2/1_5/9_1_D", "5_2/28_4/13_1_P", "1_5_E",
    "9_1_5_X/3_1/28_4/13_1_D", "7_2/1_5/9_1_B_5_P",
]
CUANTOS_JUGADORES = 6


class BaseComparacion(unittest.TestCase):

    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp())
        for objeto, nombre, valor in ((alm, "CARPETA_ESCRITURA", self.carpeta),
                                      # solo la carpeta temporal: con False se
                                      # leerian tambien los volcados del repo
                                      (alm, "_ES_LOCAL", True),
                                      (srv.av, "CARPETA_DATOS", self.carpeta / "Datos")):
            parche = mock.patch.object(objeto, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)
        sesion_web.SesionPartido(PARTIDO).guardar()
        self.agregado = ej.agregar()
        self.promedio = ej._promedio_equipo(self.agregado, "Palestino")

    def media_sobre_todos(self, calcular):
        """Como se calculaba antes: sobre el plantel entero."""
        jugadores = list(self.agregado["equipos"]["Palestino"].values())
        return sum(calcular(j) for j in jugadores) / len(jugadores)


class TestSoloEntreLosQueLaHacen(BaseComparacion):

    def test_el_partido_es_el_que_creemos(self):
        """Si el partido cambia, los numeros de abajo dejan de querer decir lo
        que dicen sus comentarios."""
        jugadores = self.agregado["equipos"]["Palestino"]
        self.assertEqual(len(jugadores), CUANTOS_JUGADORES)
        self.assertEqual(sum(jugadores["3"]["recepcion"].values()), 4)
        self.assertEqual(sum(jugadores["40"]["recepcion"].values()), 1)
        self.assertEqual(jugadores["13"]["ataque"]["totales"], 5)
        self.assertEqual(jugadores["88"]["ataque"]["totales"], 1)

    def test_recepciones_solo_entre_los_que_reciben(self):
        # (4 del 3 + 1 del 40) / 2, y no repartido entre los seis
        self.assertEqual(self.promedio["recepciones"]["valor"], 2.5)
        self.assertEqual(self.promedio["recepciones"]["jugadores"], 2)

    def test_ataques_solo_entre_los_que_atacan(self):
        # (5 del 13 + 1 del 88) / 2
        self.assertEqual(self.promedio["ataques"]["valor"], 3.0)
        self.assertEqual(self.promedio["ataques"]["jugadores"], 2)

    def test_defensas_bloqueos_y_armados_tambien(self):
        for clave, valor in (("defensas", 1.0), ("bloqueos_punto", 1.0),
                             ("armados", 6.0)):
            self.assertEqual(self.promedio[clave]["valor"], valor, clave)
            self.assertEqual(self.promedio[clave]["jugadores"], 1, clave)

    def test_el_que_no_hace_esa_accion_no_entra(self):
        """Lo que arregla esto: repartir entre todos da otro numero, y mas
        bajo, asi que cualquiera que haga la accion parece destacarse."""
        antes = self.media_sobre_todos(lambda j: sum(j["recepcion"].values()))
        self.assertAlmostEqual(antes, 5 / CUANTOS_JUGADORES)
        self.assertGreater(self.promedio["recepciones"]["valor"], antes)


class TestLosPorcentajes(BaseComparacion):
    """Es donde mas se notaba: el que nunca ataco entraba como un 0%."""

    def test_positiva_no_cuenta_a_los_que_no_reciben(self):
        # 3 del 4 del receptor 3 (0.75) y 1 de 1 del 40 (1.0)
        self.assertAlmostEqual(self.promedio["positiva"]["valor"], 0.875)

    def test_perfecta_no_cuenta_a_los_que_no_reciben(self):
        # 2 de 4 (0.5) y 1 de 1 (1.0)
        self.assertAlmostEqual(self.promedio["perfecta"]["valor"], 0.75)

    def test_punto_de_ataque_no_cuenta_a_los_que_no_atacan(self):
        # 3 de 5 del 13 (0.6) y 0 de 1 del 88 (0.0)
        self.assertAlmostEqual(self.promedio["punto"]["valor"], 0.3)

    def test_un_cero_de_nadie_hundia_el_promedio(self):
        """Los cuatro que no atacaron entraban como 0%, y el promedio de
        efectividad del equipo daba un tercio del real."""
        antes = self.media_sobre_todos(
            lambda j: ej._porcentaje(j["ataque"]["puntos"], j["ataque"]["totales"]))
        self.assertAlmostEqual(antes, 0.6 / CUANTOS_JUGADORES)
        self.assertGreater(self.promedio["punto"]["valor"], antes)


class TestLoQueNadieHace(BaseComparacion):

    def test_sin_nadie_que_la_haga_el_promedio_es_cero_entre_cero(self):
        """La pantalla usa ese 0 para no dibujar la fila: seria 0 contra 0
        para todo el mundo."""
        solo_recepcion = ["Palestino", "UVC", "28_S 5 13 88 3 40", "", "B",
                          "9_1_5_X/3_3/28_4/13_1_P"]
        carpeta = Path(tempfile.mkdtemp())
        with mock.patch.object(alm, "CARPETA_ESCRITURA", carpeta), \
                mock.patch.object(srv.av, "CARPETA_DATOS", carpeta / "Datos"):
            sesion_web.SesionPartido(solo_recepcion).guardar()
            promedio = ej._promedio_equipo(ej.agregar(), "Palestino")
        self.assertEqual(promedio["bloqueos_punto"]["jugadores"], 0)
        self.assertEqual(promedio["bloqueos_punto"]["valor"], 0.0)
        self.assertEqual(promedio["defensas"]["jugadores"], 0)

    def test_un_equipo_sin_partidos_no_tiene_promedio(self):
        self.assertEqual(ej._promedio_equipo(self.agregado, "No existe"), {})


class TestLlegaALaFicha(BaseComparacion):

    def test_la_ficha_lo_trae_con_su_cuenta_de_jugadores(self):
        ficha = srv.responder_jugador("Palestino", "3")["jugador"]
        promedio = ficha["promedio_equipo"]
        self.assertEqual(promedio["recepciones"], {"valor": 2.5, "jugadores": 2})
        # y el propio jugador sigue estando en sus indicadores
        self.assertEqual(ficha["indicadores"]["recepciones"], 4)

    def test_todas_las_metricas_tienen_la_misma_forma(self):
        """La pantalla lee valor/jugadores de todas por igual: una sola que
        viniera como numero pelado la rompe."""
        for clave, dato in self.promedio.items():
            self.assertEqual(sorted(dato), ["jugadores", "valor"], clave)


if __name__ == "__main__":
    unittest.main()
