"""
Arcos de caida libre entre candidatos sueltos (video/trayectorias.py).

Es lo que en la etapa 2 decide si lo que encontro un detector se porta como
una pelota en el aire, y en la etapa 5 lo que arma las armadas. Todo con
datos inventados: una parabola vista por una camara, con ruido, cuadros sin
deteccion y candidatos falsos alrededor.
"""
import random
import unittest

from video import trayectorias

FPS = 30.0


def parabola(t, t0=0.0, x0=300.0, vx=180.0, y0=120.0, vy=-260.0, g=500.0):
    d = t - t0
    return x0 + vx * d, y0 + vy * d + 0.5 * g * d * d


def vuelo(desde=0.0, hasta=1.0, faltan=0.0, ruido=1.0, falsos=0, semilla=1, **forma):
    """Candidatos (t, x, y, puntaje) de una pelota en vuelo, con lo que se
    pida de ruido, cuadros perdidos y candidatos falsos por cuadro."""
    azar = random.Random(semilla)
    candidatos, verdaderos = [], []
    n = int(round((hasta - desde) * FPS))
    for i in range(n + 1):
        t = round(desde + i / FPS, 4)
        if azar.random() >= faltan:
            x, y = parabola(t, **forma)
            p = (t, x + azar.gauss(0, ruido), y + azar.gauss(0, ruido), 0.8)
            candidatos.append(p)
            verdaderos.append(p)
        for _ in range(falsos):
            candidatos.append((t, azar.uniform(0, 640), azar.uniform(0, 360), azar.uniform(0.1, 0.9)))
    return candidatos, verdaderos


class TestAjuste(unittest.TestCase):

    def test_recupera_la_parabola(self):
        puntos = [(t / FPS, *parabola(t / FPS)) for t in range(10)]
        arco = trayectorias.ajustar(puntos, t0=0.0)
        self.assertAlmostEqual(arco.x[1], 180.0, places=6)
        self.assertAlmostEqual(arco.gravedad, 500.0, places=4)
        self.assertAlmostEqual(arco.en(0.5)[1], parabola(0.5)[1], places=6)

    def test_sin_tiempos_distintos_no_hay_arco(self):
        self.assertIsNone(trayectorias.ajustar([(1.0, 5, 5), (1.0, 6, 6), (1.0, 7, 7)]))
        self.assertIsNone(trayectorias.ajustar([(1.0, 5, 5), (2.0, 6, 6)]))


class TestBuscarArcos(unittest.TestCase):

    def test_una_pelota_entre_falsos_y_huecos(self):
        candidatos, verdaderos = vuelo(faltan=0.3, falsos=2)
        arcos = trayectorias.buscar_arcos(candidatos, tolerancia=6.0)
        self.assertGreaterEqual(len(arcos), 1)
        explicados = {p for a in arcos for p in a.puntos}
        bien = explicados & set(verdaderos)
        self.assertGreaterEqual(len(bien), 0.9 * len(verdaderos))
        self.assertLessEqual(len(explicados - bien), 2)
        self.assertAlmostEqual(arcos[0].gravedad, 500.0, delta=150.0)

    def test_algo_quieto_no_es_un_arco(self):
        # una lampara que el detector ve en todos los cuadros, y la pelota
        candidatos, verdaderos = vuelo()
        azar = random.Random(3)
        lampara = [(p[0], 100 + azar.gauss(0, 0.5), 40 + azar.gauss(0, 0.5), 0.95) for p in verdaderos]
        arcos = trayectorias.buscar_arcos(candidatos + lampara, tolerancia=6.0)
        explicados = {p for a in arcos for p in a.puntos}
        self.assertFalse(explicados & set(lampara))
        self.assertGreaterEqual(len(explicados & set(verdaderos)), 0.9 * len(verdaderos))

    def test_una_curva_para_arriba_no_es_caida_libre(self):
        # Entera, nunca. Un pedazo corto de cualquier curva suave se parece a
        # una recta y puede pasar: sin la calibracion de la etapa 3 no hay
        # forma de exigir "la gravedad de esta cancha" (ver el docstring).
        candidatos, verdaderos = vuelo(g=-500.0)
        for semilla in range(5):
            arcos = trayectorias.buscar_arcos(candidatos, tolerancia=6.0, semilla=semilla)
            self.assertTrue(all(len(a.puntos) < 0.5 * len(verdaderos) for a in arcos))

    def test_dos_arcos_seguidos(self):
        # recepcion que baja hasta el armador, y la armada que sale de ahi
        llega, _ = vuelo(0.0, 0.6, x0=200, vx=150, y0=40, vy=60, g=500)
        x_toque, y_toque = parabola(0.6, x0=200, vx=150, y0=40, vy=60, g=500)
        sale, _ = vuelo(0.6 + 1 / FPS, 1.4, t0=0.6, x0=x_toque, vx=-120, y0=y_toque, vy=-300,
                        g=500, semilla=2)
        arcos = trayectorias.buscar_arcos(llega + sale, tolerancia=6.0)
        self.assertEqual(len(arcos), 2)
        tramos = sorted((round(a.desde, 2), round(a.hasta, 2)) for a in arcos)
        self.assertLessEqual(tramos[0][1], 0.62)
        self.assertGreaterEqual(tramos[1][0], 0.6)

    def test_pocos_cuadros_no_alcanzan(self):
        candidatos, _ = vuelo(0.0, 0.1)
        self.assertEqual(trayectorias.buscar_arcos(candidatos, tolerancia=6.0, minimo=6), [])
        self.assertEqual(trayectorias.buscar_arcos([], tolerancia=6.0), [])

    def test_misma_semilla_mismo_resultado(self):
        candidatos, _ = vuelo(faltan=0.2, falsos=3)
        uno = trayectorias.buscar_arcos(candidatos, tolerancia=6.0, semilla=7)
        otro = trayectorias.buscar_arcos(candidatos, tolerancia=6.0, semilla=7)
        self.assertEqual([a.puntos for a in uno], [a.puntos for a in otro])


if __name__ == "__main__":
    unittest.main()
