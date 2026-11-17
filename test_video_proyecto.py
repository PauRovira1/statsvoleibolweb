"""
La carpeta de cada video (video/proyecto.py) y el aislamiento del paquete.

Lo de los archivos: nombres seguros para URL y Windows, alta idempotente,
guardado que no se pisa entre pestanas y que deja la version anterior, y un
archivo escrito por un codigo mas nuevo que no se toca.

Lo del aislamiento es la regla 1 del plan: la app de carga no se entera de
que existe video/, y ni el codigo ni los videos viajan al sitio alojado.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from video import proyecto

RAIZ = Path(__file__).resolve().parent
META = {"duracion": 60.0, "fps": 30.0, "ancho": 1280, "alto": 720, "rotacion": 0,
        "codec": "h264"}


class ConCarpeta(unittest.TestCase):

    def setUp(self):
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.base = Path(temporal.name) / "Videos"
        self.base.mkdir()

    def archivo(self, nombre, contenido=b"no es un video, pero pesa algo" * 100):
        ruta = self.base / nombre
        ruta.write_bytes(contenido)
        return ruta


class TestNombres(unittest.TestCase):

    def test_nombre_para(self):
        casos = {"Palestino vs Español (set 1)": "palestino-vs-espanol-set-1",
                 "O'sommer  2026": "o-sommer-2026",
                 "  ": "video",
                 "ÁÉÍÓÚ ñandú": "aeiou-nandu"}
        for texto, esperado in casos.items():
            with self.subTest(texto=texto):
                self.assertEqual(proyecto.nombre_para(texto), esperado)
                self.assertRegex(esperado, proyecto.NOMBRE_VALIDO)

    def test_abrir_no_arma_rutas_con_cualquier_cosa(self):
        for nombre in ("../servidor_voley", "..", "Mayusculas", "", "a/b", "a\\b", None, 3):
            with self.subTest(nombre=nombre), self.assertRaises(proyecto.NoExiste):
                proyecto.abrir(nombre, RAIZ)


class TestAlta(ConCarpeta):

    def test_crear_listar_abrir(self):
        original = self.archivo("Palestino vs Español.mp4")
        p = proyecto.crear(original, META, base=self.base)
        self.assertEqual(p.nombre, "palestino-vs-espanol")
        fuente = p.fuente()
        self.assertEqual((fuente["titulo"], fuente["duracion"], fuente["version"]),
                         ("Palestino vs Español", 60.0, proyecto.VERSION))
        self.assertEqual(fuente["original"], str(original.resolve()))
        self.assertEqual([x.nombre for x in proyecto.listar(self.base)], ["palestino-vs-espanol"])
        self.assertEqual(proyecto.abrir("palestino-vs-espanol", self.base).carpeta, p.carpeta)
        self.assertFalse(p.hay_proxy())

    def test_volver_a_dar_de_alta_el_mismo_video_lo_retoma(self):
        original = self.archivo("partido.mp4")
        p1 = proyecto.crear(original, META, base=self.base)
        alta = p1.fuente()["alta"]
        p2 = proyecto.crear(original, META, base=self.base)
        self.assertEqual((p2.carpeta, p2.fuente()["alta"]), (p1.carpeta, alta))

    def test_el_mismo_video_movido_anota_donde_esta(self):
        original = self.archivo("partido.mp4")
        proyecto.crear(original, META, base=self.base)
        otra = self.base / "sub"
        otra.mkdir()
        movido = otra / "partido.mp4"
        original.rename(movido)
        p = proyecto.crear(movido, META, nombre="partido", base=self.base)
        self.assertEqual(p.fuente()["original"], str(movido.resolve()))

    def test_otro_video_con_el_mismo_nombre_no_pisa(self):
        proyecto.crear(self.archivo("partido.mp4"), META, base=self.base)
        otro = self.base / "otra"
        otro.mkdir()
        (otro / "partido.mp4").write_bytes(b"otro contenido")
        with self.assertRaises(proyecto.ErrorDeProyecto):
            proyecto.crear(otro / "partido.mp4", META, base=self.base)

    def test_nombre_elegido_invalido(self):
        with self.assertRaises(proyecto.ErrorDeProyecto):
            proyecto.crear(self.archivo("x.mp4"), META, nombre="Con Espacios", base=self.base)

    def test_videos_sin_alta(self):
        dado = self.archivo("ya.mp4")
        proyecto.crear(dado, META, base=self.base)
        self.archivo("nuevo.MOV")
        self.archivo("notas.txt")
        self.assertEqual([r.name for r in proyecto.videos_sin_alta(self.base)], ["nuevo.MOV"])

    def test_la_huella_distingue_contenidos(self):
        a = self.archivo("a.mp4", b"x" * 10)
        b = self.archivo("b.mp4", b"y" * 10)
        grande = self.archivo("c.mp4", os.urandom(9 * 1024 * 1024))
        self.assertNotEqual(proyecto.hash_parcial(a), proyecto.hash_parcial(b))
        self.assertEqual(len(proyecto.hash_parcial(grande)), 32)


class TestRevision(ConCarpeta):

    def setUp(self):
        super().setUp()
        self.p = proyecto.crear(self.archivo("partido.mp4"), META, base=self.base)

    def decision(self, ident="d1", t=10.0):
        return {"id": ident, "t_armado": t, "lado": None, "estado": "aceptada",
                "origen": "manual", "propuesta": None, "cambios": {}, "armador": None,
                "etiquetas": [], "nota": ""}

    def test_sin_archivo_es_una_revision_vacia(self):
        self.assertEqual(self.p.revision(), proyecto.revision_vacia())
        self.assertEqual(self.p.propuestas()["armadas"], [])

    def test_guardar_suma_una_edicion_y_deja_la_anterior(self):
        r1 = self.p.guardar_revision({"sets": [], "decisiones": [self.decision()]}, 0)
        self.assertEqual(r1["edicion"], 1)
        self.assertFalse((self.p.carpeta / proyecto.REVISION_ANTERIOR).exists())
        self.p.guardar_revision({"sets": [], "decisiones": []}, 1)
        anterior = json.loads((self.p.carpeta / proyecto.REVISION_ANTERIOR)
                              .read_text(encoding="utf-8"))
        self.assertEqual(len(anterior["decisiones"]), 1)
        self.assertEqual(self.p.revision()["edicion"], 2)

    def test_otra_pestana_guardo_antes(self):
        self.p.guardar_revision({"sets": [], "decisiones": [self.decision()]}, 0)
        with self.assertRaises(proyecto.Desactualizado):
            self.p.guardar_revision({"sets": [], "decisiones": []}, 0)
        self.assertEqual(len(self.p.revision()["decisiones"]), 1)

    def test_no_se_guarda_algo_mal_formado(self):
        for mala in ({"sets": [], "decisiones": [{"id": "d1"}]},
                     {"sets": [], "decisiones": [self.decision(), self.decision()]},
                     {"sets": [{"desde": 1, "set": 1, "lado": "arriba"}], "decisiones": []}):
            with self.subTest(mala=mala), self.assertRaises(proyecto.ErrorDeProyecto):
                self.p.guardar_revision(mala, 0)
        self.assertFalse((self.p.carpeta / proyecto.REVISION).exists())

    def test_un_archivo_roto_se_avisa(self):
        (self.p.carpeta / proyecto.REVISION).write_text("{ esto no es json", encoding="utf-8")
        with self.assertRaises(proyecto.ErrorDeProyecto) as error:
            self.p.revision()
        self.assertIn(proyecto.REVISION_ANTERIOR, str(error.exception))

    def test_un_archivo_de_un_codigo_mas_nuevo_no_se_toca(self):
        ruta = self.p.carpeta / proyecto.REVISION
        mas_nuevo = {"version": proyecto.VERSION + 1, "edicion": 3, "sets": [],
                     "decisiones": [], "algo_nuevo": True}
        ruta.write_text(json.dumps(mas_nuevo), encoding="utf-8")
        with self.assertRaises(proyecto.ErrorDeProyecto):
            self.p.guardar_revision({"sets": [], "decisiones": []}, 3)
        self.assertEqual(json.loads(ruta.read_text(encoding="utf-8")), mas_nuevo)


class TestAislamiento(unittest.TestCase):
    """La app de carga y el sitio alojado no se enteran del video."""

    def test_la_app_de_carga_no_importa_video(self):
        codigo = ("import sys, servidor_voley, lambda_handler, notacion, sesion_web; "
                  "print([m for m in sys.modules if m == 'video' or m.startswith('video.')])")
        salida = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(salida.returncode, 0, salida.stderr)
        self.assertEqual(salida.stdout.strip().splitlines()[-1], "[]")

    def test_video_no_importa_la_app_de_carga(self):
        codigo = ("import sys, video.servidor_video, video.decisiones, video.__main__; "
                  "print(sorted(m for m in ('servidor_voley', 'analisis_voley', "
                  "'sesion_web', 'notacion') if m in sys.modules))")
        salida = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(salida.returncode, 0, salida.stderr)
        self.assertEqual(salida.stdout.strip(), "[]")

    def test_nada_de_video_viaja_al_sitio(self):
        ignorados = (RAIZ / ".vercelignore").read_text(encoding="utf-8").split()
        for entrada in ("video/", "Videos/", "requirements-video.txt", "test_*.py"):
            self.assertIn(entrada, ignorados)
        # el zip de Lambda usa una lista explicita: que no la haya tocado nadie
        import empaquetar_lambda
        self.assertNotIn("video", " ".join(map(str, empaquetar_lambda.CARPETAS)).lower())
        self.assertFalse(any("video" in str(a).lower() for a in empaquetar_lambda.MODULOS))

    def test_los_videos_no_entran_al_repo(self):
        ignorados = (RAIZ / ".gitignore").read_text(encoding="utf-8").split()
        self.assertIn("Videos/", ignorados)
        self.assertIn("video/modelos/*.onnx", ignorados)

    def test_las_dependencias_del_sitio_no_cambian(self):
        requisitos = (RAIZ / "requirements.txt").read_text(encoding="utf-8")
        self.assertNotIn("imageio", requisitos)


if __name__ == "__main__":
    unittest.main()
