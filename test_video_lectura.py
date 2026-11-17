"""
Metadatos y proxy (video/lectura.py) y la orden "nuevo" de punta a punta,
sobre videos sinteticos que arma el mismo ffmpeg.

Se saltean solos si no esta imageio-ffmpeg (requirements-video.txt): la app
de carga no lo necesita y su suite tiene que pasar sin el.

Las rutas tienen espacios y acentos a proposito: son las de un partido real
("Palestino vs Español") y en Windows son las que fallan.
"""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from video import lectura, proyecto

RAIZ = Path(__file__).resolve().parent
HAY_FFMPEG = lectura.hay_ffmpeg()


def sintetico(destino: Path, ancho: int, alto: int, segundos: float, fps: int = 30) -> Path:
    """Un video con cuadros de prueba y un tono, con un cuadro clave cada 250
    cuadros: como un celular, que pone pocos."""
    subprocess.run([lectura.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc2=size={ancho}x{alto}:rate={fps}",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-t", str(segundos), "-c:v", "libx264", "-preset", "ultrafast",
                    "-g", "250", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
                    str(destino)], check=True, timeout=120)
    return destino


def cuadros_clave(ruta: Path) -> list[float]:
    salida = subprocess.run([lectura.ffmpeg(), "-hide_banner", "-i", str(ruta), "-vf",
                             "select='eq(pict_type,I)',showinfo", "-f", "null", "-"],
                            capture_output=True, text=True, timeout=120)
    return [round(float(linea.split("pts_time:")[1].split()[0]), 2)
            for linea in salida.stderr.splitlines() if "pts_time:" in linea]


@unittest.skipUnless(HAY_FFMPEG, "falta imageio-ffmpeg (requirements-video.txt)")
class TestLectura(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temporal = tempfile.TemporaryDirectory()
        cls.carpeta = Path(cls.temporal.name) / "Partido con eñe y espacios"
        cls.carpeta.mkdir()
        cls.grande = sintetico(cls.carpeta / "Palestino vs Español.mp4", 1920, 1080, 3.5)
        cls.chico = sintetico(cls.carpeta / "chico.mp4", 640, 360, 2)

    @classmethod
    def tearDownClass(cls):
        cls.temporal.cleanup()

    def test_metadatos(self):
        meta = lectura.metadatos(self.grande)
        self.assertEqual((meta["ancho"], meta["alto"], meta["fps"], meta["rotacion"]),
                         (1920, 1080, 30.0, 0))
        self.assertAlmostEqual(meta["duracion"], 3.5, delta=0.1)
        self.assertEqual(meta["codec"], "h264")

    def test_lo_que_no_es_video(self):
        texto = self.carpeta / "notas.mp4"
        texto.write_text("esto no es un video", encoding="utf-8")
        with self.assertRaises(lectura.ErrorDeLectura):
            lectura.metadatos(texto)

    def test_el_proxy_es_720_con_un_cuadro_clave_por_segundo(self):
        destino = self.carpeta / "proxy grande.mp4"
        avances = []
        lectura.hacer_proxy(self.grande, destino, 3.5,
                            lambda hecho, total, vel: avances.append(hecho))
        meta = lectura.metadatos(destino)
        self.assertEqual((meta["ancho"], meta["alto"], meta["codec"]), (1280, 720, "h264"))
        self.assertAlmostEqual(meta["duracion"], 3.5, delta=0.1)
        # el original tiene uno solo al principio; el proxy, uno por segundo
        self.assertEqual(cuadros_clave(self.grande), [0.0])
        self.assertEqual(cuadros_clave(destino), [0.0, 1.0, 2.0, 3.0])
        self.assertTrue(avances)
        self.assertFalse((self.carpeta / "proxy grande.parcial.mp4").exists())

    def test_un_original_chico_no_se_agranda(self):
        destino = self.carpeta / "proxy chico.mp4"
        lectura.hacer_proxy(self.chico, destino, 2.0)
        meta = lectura.metadatos(destino)
        self.assertEqual((meta["ancho"], meta["alto"]), (640, 360))

    def test_un_proxy_que_falla_no_deja_nada(self):
        texto = self.carpeta / "roto.mp4"
        texto.write_text("no", encoding="utf-8")
        destino = self.carpeta / "proxy roto.mp4"
        with self.assertRaises(lectura.ErrorDeLectura):
            lectura.hacer_proxy(texto, destino, 2.0)
        self.assertFalse(destino.exists())
        self.assertFalse((self.carpeta / "proxy roto.parcial.mp4").exists())


@unittest.skipUnless(HAY_FFMPEG, "falta imageio-ffmpeg (requirements-video.txt)")
class TestOrdenNuevo(unittest.TestCase):
    """python -m video nuevo, como lo corre la persona."""

    def setUp(self):
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.base = Path(temporal.name) / "Videos con eñe"
        self.base.mkdir()

    def correr(self, *argumentos):
        return subprocess.run([sys.executable, "-m", "video", "--carpeta", str(self.base),
                               *argumentos], cwd=RAIZ, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=300)

    def test_dar_de_alta_lo_suelto_y_no_repetir(self):
        sintetico(self.base / "Palestino vs Español.mp4", 1280, 720, 2)
        salida = self.correr("nuevo")
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        p = proyecto.abrir("palestino-vs-espanol", self.base)
        self.assertTrue(p.hay_proxy())
        self.assertEqual(p.fuente()["titulo"], "Palestino vs Español")

        salida = self.correr("nuevo")
        self.assertEqual(salida.returncode, 0)
        self.assertIn("No hay videos nuevos", salida.stdout)

        salida = self.correr("lista")
        self.assertIn("palestino-vs-espanol", salida.stdout)

    def test_retoma_el_que_quedo_sin_proxy(self):
        video = sintetico(self.base / "partido.mp4", 640, 360, 2)
        p = proyecto.crear(video, lectura.metadatos(video), base=self.base)
        self.assertFalse(p.hay_proxy())
        salida = self.correr("nuevo")
        self.assertEqual(salida.returncode, 0, salida.stdout + salida.stderr)
        self.assertTrue(p.hay_proxy())

    def test_un_archivo_que_no_existe(self):
        salida = self.correr("nuevo", str(self.base / "no-esta.mp4"))
        self.assertEqual(salida.returncode, 1)
        self.assertIn("No existe", salida.stdout)


if __name__ == "__main__":
    unittest.main()
