"""
La medicion de la etapa 2 (video/prueba_pelota.py) y la bajada de modelos
(video/modelos.py), en lo que no toca video ni red: elegir el tramo, contar
cuadros del vuelo, el ruido, y que un modelo que no es el que tiene que ser
nunca quede con el nombre del bueno.
"""
import hashlib
import io
import random
import tempfile
import unittest
from pathlib import Path

from video import modelos, prueba_pelota as pp
from video.pelota import Candidato

FPS = 29.0
ANCHO, ALTO = 640, 360


def cuadros(desde, hasta):
    n = int(round((hasta - desde) * FPS))
    return [round(desde + i / FPS, 4) for i in range(n + 1)]


class TestTramo(unittest.TestCase):

    def test_elige_el_tramo_con_mas_armadas(self):
        tiempos = [10, 50, 400, 410, 420, 430, 700]
        desde, hasta = pp.tramo_con_mas_armadas(tiempos, minutos=1)
        adentro = [t for t in tiempos if desde + pp.VUELO_ANTES <= t <= hasta - pp.VUELO_DESPUES]
        self.assertEqual(adentro, [400, 410, 420, 430])
        self.assertEqual(hasta - desde, 60)

    def test_sin_armadas(self):
        with self.assertRaises(ValueError):
            pp.tramo_con_mas_armadas([], 5)

    def test_relojes(self):
        self.assertEqual(pp.leer_reloj("1:08:46"), 4126)
        self.assertEqual(pp.leer_reloj("22:06"), 1326)
        self.assertEqual(pp.leer_reloj("90.5"), 90.5)
        self.assertEqual(pp.reloj(4126.9), "1:08:46")
        self.assertEqual(pp.reloj(66), "1:06")


class TestMedirVuelo(unittest.TestCase):

    def setUp(self):
        self.tiempos = cuadros(99.0, 102.0)
        self.t_armado = 100.0
        azar = random.Random(4)
        self.por_cuadro = {}
        for t in self.tiempos:
            d = t - 99.5
            # la pelota, en pixeles -> fraccion; y dos falsos por cuadro
            x, y = 200 + 150 * d, 60 - 200 * d + 250 * d * d
            hallados = [Candidato(t, x / ANCHO, y / ALTO, 0.9)]
            hallados += [Candidato(t, azar.random(), azar.random(), 0.2) for _ in range(2)]
            self.por_cuadro[t] = hallados

    def test_cuenta_los_cuadros_del_vuelo(self):
        medida = pp.medir_vuelo(self.t_armado, self.tiempos, self.por_cuadro, ANCHO, ALTO, 0.0)
        esperados = len([t for t in self.tiempos
                         if self.t_armado - pp.VUELO_ANTES <= t <= self.t_armado + pp.VUELO_DESPUES])
        self.assertEqual(medida.cuadros, esperados)
        self.assertEqual(medida.con_algo, esperados)
        self.assertGreaterEqual(medida.en_arco, 0.9 * esperados)

    def test_el_umbral_saca_lo_dudoso(self):
        # con corte 0,5 los falsos (0,2) no pasan: queda la pelota (0,9) sola
        medida = pp.medir_vuelo(self.t_armado, self.tiempos, self.por_cuadro, ANCHO, ALTO, 0.5)
        self.assertEqual(medida.con_algo, medida.cuadros)

    def test_sin_nada_no_hay_vuelo_visto(self):
        medida = pp.medir_vuelo(self.t_armado, self.tiempos, {}, ANCHO, ALTO, 0.0)
        self.assertEqual((medida.con_algo, medida.en_arco), (0, 0))

    def test_ruido_fuera_de_los_vuelos(self):
        valor = pp.ruido(self.tiempos, self.por_cuadro, [self.t_armado], 0.0)
        self.assertAlmostEqual(valor, 3.0)
        self.assertAlmostEqual(pp.ruido(self.tiempos, self.por_cuadro, [self.t_armado], 0.5), 1.0)


class TestModelos(unittest.TestCase):
    """Bajar un modelo, con una red de mentira."""

    CONTENIDO = b"pesos de un modelo de mentira" * 100

    def setUp(self):
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.carpeta = Path(temporal.name)
        self.modelo = modelos.Modelo(
            nombre="prueba", archivo="prueba.onnx",
            sha256=hashlib.sha256(self.CONTENIDO).hexdigest(), tamano=len(self.CONTENIDO),
            cuadros=9, ancho=512, alto=288, descripcion="de mentira")

    def red(self, contenido):
        pedidos = []

        def abrir(pedido, timeout):
            pedidos.append(pedido)
            return io.BytesIO(contenido)
        return abrir, pedidos

    def test_el_catalogo_esta_completo(self):
        for modelo in modelos.CATALOGO.values():
            self.assertRegex(modelo.sha256, r"^[0-9a-f]{64}$")
            self.assertTrue(modelo.archivo.endswith(".onnx"))
        self.assertIn(modelos.COMMIT, modelos.ORIGEN)

    def test_baja_y_verifica(self):
        abrir, pedidos = self.red(self.CONTENIDO)
        ruta = modelos.bajar(self.modelo, self.carpeta, abrir=abrir)
        self.assertEqual(ruta.read_bytes(), self.CONTENIDO)
        self.assertTrue(modelos.esta_bien(self.modelo, self.carpeta))
        self.assertTrue(pedidos[0].full_url.endswith("/prueba.onnx"))
        # ya esta: no se vuelve a bajar
        abrir, pedidos = self.red(b"otra cosa")
        modelos.bajar(self.modelo, self.carpeta, abrir=abrir)
        self.assertEqual(pedidos, [])

    def test_otra_huella_no_queda(self):
        abrir, _ = self.red(b"un modelo cambiado")
        with self.assertRaises(modelos.ErrorDeModelo):
            modelos.bajar(self.modelo, self.carpeta, abrir=abrir)
        self.assertEqual(list(self.carpeta.iterdir()), [])

    def test_asegurar(self):
        with self.assertRaises(modelos.ErrorDeModelo) as error:
            modelos.asegurar(self.modelo, self.carpeta)
        self.assertIn("python -m video modelos", str(error.exception))
        modelos.ruta(self.modelo, self.carpeta).write_bytes(b"tocado")
        with self.assertRaises(modelos.ErrorDeModelo):
            modelos.asegurar(self.modelo, self.carpeta)


if __name__ == "__main__":
    unittest.main()
