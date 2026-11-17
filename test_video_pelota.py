"""
Los detectores de pelota (video/pelota.py) y el lector de cuadros
(lectura.cuadros), sobre cuadros inventados.

Se saltean solos sin numpy/cv2 (y sin onnxruntime o el modelo, los del
modelo): la app de carga no los necesita y su suite tiene que pasar igual.

Lo que se prueba del detector de movimiento: que encuentra una pelota chica
que vuela sobre un fondo con textura, aunque haya un "jugador" grande
moviendose y una lampara quieta. Del modelo no se puede probar que vea la
pelota (para eso esta la etapa 2 con videos de verdad): se prueba que a cada
cuadro que entra le toca su salida, con su tiempo, incluido el ultimo grupo
que no llega a 9.
"""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

HAY_CV2 = all(importlib.util.find_spec(m) for m in ("numpy", "cv2"))
HAY_ONNX = HAY_CV2 and importlib.util.find_spec("onnxruntime") is not None

ANCHO, ALTO, FPS = 640, 360, 29.0


def pelota_en(i):
    t = i / FPS
    return 120 + 260 * t, 300 - 420 * t + 350 * t * t


def cuadros_inventados(n=40, con_jugador=True, semilla=0):
    import numpy as np
    azar = np.random.default_rng(semilla)
    fondo = (azar.integers(60, 120, (ALTO, ANCHO, 3))).astype(np.uint8)
    import cv2
    fondo = cv2.GaussianBlur(fondo, (5, 5), 0)
    salida = []
    for i in range(n):
        cuadro = fondo.copy()
        ruido = azar.integers(-3, 4, cuadro.shape)
        cuadro = np.clip(cuadro.astype(int) + ruido, 0, 255).astype(np.uint8)
        cv2.circle(cuadro, (560, 40), 5, (255, 255, 255), -1)                 # lampara quieta
        if con_jugador:
            x = 40 + 6 * i                                                     # jugador que camina
            cv2.rectangle(cuadro, (x, 200), (x + 40, 330), (20, 30, 25), -1)
        bx, by = pelota_en(i)
        cv2.circle(cuadro, (int(bx), int(by)), 4, (40, 210, 240), -1)          # amarilla
        salida.append((i / FPS, cuadro))
    return salida


@unittest.skipUnless(HAY_CV2, "faltan numpy/cv2 (requirements-video.txt)")
class TestMovimiento(unittest.TestCase):

    def test_encuentra_la_pelota_y_no_la_lampara(self):
        from video.pelota import DetectorMovimiento
        resultado = list(DetectorMovimiento().detectar(cuadros_inventados()))
        self.assertEqual(len(resultado), 38)            # sin el primero ni el ultimo
        cerca, lampara = 0, 0
        for t, hallados in resultado:
            bx, by = pelota_en(round(t * FPS))
            if any(abs(c.x * ANCHO - bx) <= 3 and abs(c.y * ALTO - by) <= 3 for c in hallados):
                cerca += 1
            lampara += any(abs(c.x * ANCHO - 560) <= 4 and abs(c.y * ALTO - 40) <= 4 for c in hallados)
        self.assertGreaterEqual(cerca, 0.9 * len(resultado))
        self.assertEqual(lampara, 0)

    def test_coordenadas_en_fraccion(self):
        from video.pelota import DetectorMovimiento
        for _, hallados in DetectorMovimiento().detectar(cuadros_inventados(10)):
            for c in hallados:
                self.assertTrue(0 <= c.x <= 1 and 0 <= c.y <= 1)


@unittest.skipUnless(HAY_ONNX, "faltan numpy/cv2/onnxruntime (requirements-video.txt)")
class TestModelo(unittest.TestCase):

    def setUp(self):
        from video import modelos
        self.modelo = modelos.CATALOGO["fastv1"]
        if not modelos.esta_bien(self.modelo):
            self.skipTest("falta el modelo: python -m video modelos")
        self.ruta = modelos.ruta(self.modelo)

    def test_cada_cuadro_tiene_su_salida_y_su_tiempo(self):
        from video.pelota import DetectorModelo
        entrada = cuadros_inventados(22)        # 2 grupos de 9 y uno de 4
        salida = list(DetectorModelo(self.modelo, self.ruta).detectar(entrada))
        self.assertEqual([t for t, _ in salida], [t for t, _ in entrada])
        for t, hallados in salida:
            self.assertLessEqual(len(hallados), DetectorModelo.MAXIMO_POR_CUADRO)
            for c in hallados:
                self.assertEqual(c.t, t)
                self.assertTrue(0 <= c.x <= 1 and 0 <= c.y <= 1 and 0 <= c.puntaje <= 1)


@unittest.skipUnless(HAY_CV2, "faltan numpy/cv2 (requirements-video.txt)")
class TestCuadros(unittest.TestCase):
    """lectura.cuadros: el tiempo de cada cuadro sale del video, y saltar a la
    mitad da el mismo cuadro que leer desde el principio."""

    @classmethod
    def setUpClass(cls):
        from video import lectura
        if not lectura.hay_ffmpeg():
            raise unittest.SkipTest("falta ffmpeg (requirements-video.txt)")
        cls.temporal = tempfile.TemporaryDirectory()
        cls.video = Path(cls.temporal.name) / "con eñe.mp4"
        subprocess.run([lectura.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=29", "-t", "6",
                        "-c:v", "libx264", "-preset", "ultrafast", "-g", "60",
                        "-pix_fmt", "yuv420p", str(cls.video)], check=True, timeout=120)

    @classmethod
    def tearDownClass(cls):
        cls.temporal.cleanup()

    def test_tiempos_del_video(self):
        from video import lectura
        tiempos = [t for t, _ in lectura.cuadros(self.video)]
        self.assertEqual(len(tiempos), 174)
        self.assertEqual(tiempos[0], 0.0)
        pasos = {round(b - a, 4) for a, b in zip(tiempos, tiempos[1:])}
        self.assertEqual(pasos, {round(1 / 29, 4)})

    def test_saltar_da_el_mismo_cuadro(self):
        import numpy as np
        from video import lectura
        todos = dict(lectura.cuadros(self.video))
        desde = sorted(todos)[100]
        t, cuadro = next(lectura.cuadros(self.video, desde, desde + 1))
        self.assertAlmostEqual(t, desde, places=3)
        self.assertTrue(np.array_equal(cuadro, todos[desde]))
        tramo = [t for t, _ in lectura.cuadros(self.video, 2.0, 3.0)]
        self.assertTrue(2.0 <= tramo[0] < 2.0 + 1 / 29 and tramo[-1] <= 3.0)


if __name__ == "__main__":
    unittest.main()
