"""
Tests de almacenamiento.py: la parte que habla con Vercel Blob.

Se corren con:
    python -m unittest test_almacenamiento

No tocan la red: se reemplaza _pedir por un store simulado que guarda de
verdad lo que se sube, asi que la cabeza y el listado contestan lo mismo que
contestaria el servicio.

Lo que cuidan es cuantas operaciones se piden, no solo que el resultado sea
correcto. En Vercel Blob listar y subir cuentan como ADVANCED (2.000 al mes en
el plan Hobby) y pedir la cabeza como SIMPLE (10.000): con una llamada de mas
por jugada, un partido no entra en el plan gratis.
"""
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from collections import Counter
from unittest import mock

import almacenamiento as alm


class BlobSimulado:
    """Un store de mentira que cuenta que le piden.

    Con cabeza=False simula un servicio que no contesta la cabeza, para
    comprobar que el codigo se cae al listado y sigue funcionando igual."""

    def __init__(self, cabeza=True):
        self.archivos = {}          # pathname -> (contenido, etag)
        self.cuenta = Counter()
        self.cabeza = cabeza
        self._subidas = 0

    @property
    def advanced(self) -> int:
        return self.cuenta["PUT"] + self.cuenta["LIST"]

    def pedir(self, url, *, metodo="GET", cuerpo=None, cabeceras=None, timeout=10):
        if metodo == "PUT":
            nombre = urllib.parse.unquote(url[len(alm.API_BLOB) + 1:])
            self._subidas += 1
            etag = f"etag{self._subidas}"
            self.archivos[nombre] = (cuerpo, etag)
            self.cuenta["PUT"] += 1
            return json.dumps({"url": f"https://falso/{nombre}",
                               "pathname": nombre, "etag": etag}).encode()

        if metodo == "GET" and url.startswith(alm.API_BLOB) and "url=" in url:
            self.cuenta["HEAD"] += 1
            if not self.cabeza:
                raise alm.ErrorDeBlob("HEAD -> HTTP 400 no existe", 400)
            nombre = urllib.parse.unquote(url.split("url=", 1)[1])
            if nombre not in self.archivos:
                raise alm.ErrorDeBlob("HEAD -> HTTP 404", 404)
            contenido, etag = self.archivos[nombre]
            return json.dumps({"pathname": nombre, "etag": etag, "uploadedAt": etag,
                               "size": len(contenido),
                               "url": f"https://falso/{nombre}",
                               "downloadUrl": f"https://falso/{nombre}"}).encode()

        if metodo == "GET" and url.startswith(alm.API_BLOB):
            self.cuenta["LIST"] += 1
            return json.dumps({"hasMore": False, "blobs": [
                {"pathname": n, "etag": e, "uploadedAt": e, "size": len(c),
                 "url": f"https://falso/{n}", "downloadUrl": f"https://falso/{n}"}
                for n, (c, e) in self.archivos.items()]}).encode()

        self.cuenta["BAJADA"] += 1
        nombre = url.split("https://falso/", 1)[1].split("?")[0]
        return self.archivos[urllib.parse.unquote(nombre)][0]


class BaseBlob(unittest.TestCase):

    CON_CABEZA = True

    def setUp(self):
        self.blob = BlobSimulado(cabeza=self.CON_CABEZA)
        # guardar_sesion escribe siempre una copia local antes de subir: va a
        # una carpeta temporal para no dejar un sesion/ en el proyecto
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        parches = [
            mock.patch.object(alm, "_pedir", self.blob.pedir),
            mock.patch.object(alm, "hay_blob", lambda: True),
            mock.patch.object(alm, "token_blob", lambda: "falso"),
            mock.patch.object(alm, "CARPETA_ESCRITURA", Path(carpeta.name)),
            mock.patch.object(alm, "_hay_cabeza", True),
            mock.patch.object(alm, "_ultima_version", {}),
            mock.patch.object(alm, "_ultimo_listado", {}),
        ]
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)


class TestVersionDeLaSesion(BaseBlob):
    """La version es lo que dice si la sesion guardada cambio. Tiene que salir
    de la propia subida, que es lo que evita una llamada por jugada."""

    def test_guardar_devuelve_la_version_con_la_que_quedo(self):
        version = alm.guardar_sesion(["a", "b"])
        self.assertTrue(version)
        self.assertEqual(version, alm.version_de_sesion())

    def test_guardar_no_pregunta_nada_despues_de_subir(self):
        alm.guardar_sesion(["a"])
        self.assertEqual(self.blob.cuenta["PUT"], 1)
        self.assertEqual(self.blob.cuenta["LIST"], 0)
        self.assertEqual(self.blob.cuenta["HEAD"], 0)

    def test_la_version_cambia_cuando_cambian_las_lineas(self):
        primera = alm.guardar_sesion(["a"])
        segunda = alm.guardar_sesion(["a", "b"])
        self.assertNotEqual(primera, segunda)

    def test_preguntar_la_version_no_gasta_una_advanced(self):
        alm.guardar_sesion(["a"])
        self.blob.cuenta.clear()
        alm.version_de_sesion()
        self.assertEqual(self.blob.cuenta["HEAD"], 1)
        self.assertEqual(self.blob.advanced, 0)

    def test_sin_sesion_guardada_la_version_esta_vacia(self):
        self.assertEqual(alm.version_de_sesion(), "")

    def test_leer_la_sesion_devuelve_las_lineas_y_la_version(self):
        guardada = alm.guardar_sesion(["Local", "Rival"])
        self.assertEqual(alm.leer_sesion(), (["Local", "Rival"], guardada))

    def test_leer_la_sesion_tampoco_lista_el_store(self):
        alm.guardar_sesion(["a"])
        self.blob.cuenta.clear()
        alm.leer_sesion()
        self.assertEqual(self.blob.cuenta["LIST"], 0)


class TestCacheDeLectura(BaseBlob):
    """Mirar el marcador no puede costar una consulta por vista."""

    def test_las_lecturas_seguidas_se_contestan_de_lo_guardado(self):
        alm.guardar_sesion(["a"])
        self.blob.cuenta.clear()
        for _ in range(10):
            alm.version_de_sesion(refrescar=False)
        self.assertEqual(sum(self.blob.cuenta.values()), 0)

    def test_una_escritura_siempre_vuelve_a_preguntar(self):
        alm.guardar_sesion(["a"])
        self.blob.cuenta.clear()
        for _ in range(3):
            alm.version_de_sesion()
        self.assertEqual(self.blob.cuenta["HEAD"], 3)

    def test_guardar_invalida_lo_cacheado(self):
        alm.guardar_sesion(["a"])
        alm.version_de_sesion(refrescar=False)
        nueva = alm.guardar_sesion(["a", "b"])
        self.assertEqual(alm.version_de_sesion(refrescar=False), nueva)


class TestSinCabeza(BaseBlob):
    """Si el servicio no contesta la cabeza, el codigo se cae al listado de
    siempre: gasta mas, pero no se rompe nada."""

    CON_CABEZA = False

    def test_la_version_se_sigue_sabiendo(self):
        guardada = alm.guardar_sesion(["a", "b"])
        self.assertEqual(alm.version_de_sesion(), guardada)

    def test_la_sesion_se_sigue_leyendo(self):
        alm.guardar_sesion(["Local", "Rival"])
        self.assertEqual(alm.leer_sesion()[0], ["Local", "Rival"])

    def test_se_deja_de_intentar_despues_del_primer_fallo(self):
        alm.guardar_sesion(["a"])
        alm.version_de_sesion()
        alm.version_de_sesion()
        alm.version_de_sesion()
        # una sola vez se prueba la cabeza; despues va derecho al listado
        self.assertEqual(self.blob.cuenta["HEAD"], 1)
        self.assertEqual(self.blob.cuenta["LIST"], 3)


class TestConfirmarQueSubio(BaseBlob):
    """Despues de guardar un .txt o un Excel se confirma que llego. Preguntar
    por ese archivo no tiene por que costar listar el store entero."""

    def test_confirma_sin_listar(self):
        alm.subir_blob("Datos/partido.txt", b"x", "text/plain")
        self.blob.cuenta.clear()
        self.assertTrue(alm.publicado("Datos", "partido.txt"))
        self.assertEqual(self.blob.cuenta["LIST"], 0)
        self.assertEqual(self.blob.cuenta["HEAD"], 1)

    def test_dice_que_no_cuando_no_esta(self):
        self.assertFalse(alm.publicado("Datos", "no_existe.txt"))


class TestConfirmarSinCabeza(BaseBlob):
    CON_CABEZA = False

    def test_se_cae_al_listado(self):
        alm.subir_blob("Datos/partido.txt", b"x", "text/plain")
        self.assertTrue(alm.publicado("Datos", "partido.txt"))
        self.assertFalse(alm.publicado("Datos", "no_existe.txt"))


class TestCuantoCuestaUnPartido(BaseBlob):
    """La cuenta que importa: cuantas advanced sale cargar un partido."""

    LINEAS = ["Local", "Rival", "1_S 2 3 4 5 6", "", "A"] + ["1_5_A"] * 40

    def _cargar(self):
        version = ""
        for linea in self.LINEAS:
            remota = alm.version_de_sesion()          # el servidor se pone al dia
            if remota and remota != version:
                leido = alm.leer_sesion()
                version = leido[1] if leido else version
            version = alm.guardar_sesion(self.LINEAS[:self.LINEAS.index(linea) + 1])
        return version

    def test_una_advanced_por_linea_y_nada_mas(self):
        self._cargar()
        # una subida por linea, y ningun listado
        self.assertEqual(self.blob.cuenta["PUT"], len(self.LINEAS))
        self.assertEqual(self.blob.cuenta["LIST"], 0)
        self.assertEqual(self.blob.advanced, len(self.LINEAS))


class TestSinBlob(unittest.TestCase):
    """Sin token no se habla con nadie: todo queda en el archivo local."""

    def setUp(self):
        # a una carpeta temporal, para no dejar un sesion/ en el proyecto
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        parches = [
            mock.patch.object(alm, "hay_blob", lambda: False),
            mock.patch.object(alm, "CARPETA_ESCRITURA", Path(carpeta.name)),
        ]
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)

    def test_guardar_y_leer_sin_blob(self):
        version = alm.guardar_sesion(["Local", "Rival"])
        self.assertTrue(version)
        self.assertEqual(alm.leer_sesion()[0], ["Local", "Rival"])
        self.assertEqual(alm.version_de_sesion(), version)

    def test_sin_nada_guardado_no_hay_sesion(self):
        self.assertIsNone(alm.leer_sesion())
        self.assertEqual(alm.version_de_sesion(), "")


if __name__ == "__main__":
    unittest.main()


class TestNombreParaArchivo(unittest.TestCase):
    """El informe se llama Informe_<equipo>_vs_<rival>_<fecha>.xlsx, asi que el
    nombre del equipo termina adentro de un nombre de archivo. El volcado no
    (se llama partido_<fecha>.txt): por eso un nombre con un caracter prohibido
    hacia que el .txt se guardara y el Excel no."""

    def test_saca_los_caracteres_que_windows_no_acepta(self):
        for prohibido in '<>:"/\|?*':
            with self.subTest(caracter=prohibido):
                limpio = alm.nombre_para_archivo(f"Club{prohibido}A")
                self.assertNotIn(prohibido, limpio)

    def test_una_barra_no_puede_mandar_el_archivo_a_otra_carpeta(self):
        self.assertNotIn("/", alm.nombre_para_archivo("Palestino/B"))
        self.assertNotIn("\\", alm.nombre_para_archivo("Palestino\B"))

    def test_un_nombre_normal_no_se_toca(self):
        for nombre in ("Palestino", "O'sommer", "Español", "UVC 2026"):
            with self.subTest(nombre=nombre):
                self.assertEqual(alm.nombre_para_archivo(nombre), nombre)

    def test_saca_los_puntos_y_espacios_del_final(self):
        self.assertEqual(alm.nombre_para_archivo("Palestino. "), "Palestino")

    def test_nunca_devuelve_vacio(self):
        # un nombre vacio dejaria el archivo como "Informe__vs_..."
        for entrada in ("", "   ", ".", None):
            with self.subTest(entrada=entrada):
                self.assertTrue(alm.nombre_para_archivo(entrada))

    def test_saca_los_caracteres_de_control(self):
        self.assertEqual(alm.nombre_para_archivo("Pale\tstino"), "Pale-stino")


class TestCorrecciones(unittest.TestCase):
    """El resumen de un partido sale leido del .txt. Lo que el archivo no puede
    saber (cual de varios informes del mismo dia le toca) se arregla a mano, y
    ese arreglo tiene que ganar y poder sacarse."""

    def setUp(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        parches = [
            mock.patch.object(alm, "hay_blob", lambda: False),
            mock.patch.object(alm, "CARPETA_ESCRITURA", Path(carpeta.name)),
            mock.patch.object(alm, "_correcciones", None),
            mock.patch.object(alm, "_momento_correcciones", 0.0),
        ]
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)

    def test_sin_correcciones_no_hay_ninguna(self):
        self.assertEqual(alm.leer_correcciones(refrescar=True), {})

    def test_se_guarda_y_se_vuelve_a_leer(self):
        alm.guardar_correccion("partido_1.txt", {"informe": "Informe_X.xlsx"})
        self.assertEqual(alm.leer_correcciones(refrescar=True),
                         {"partido_1.txt": {"informe": "Informe_X.xlsx"}})

    def test_guardar_vacio_la_saca(self):
        alm.guardar_correccion("partido_1.txt", {"informe": "Informe_X.xlsx"})
        alm.guardar_correccion("partido_1.txt", {})
        self.assertEqual(alm.leer_correcciones(refrescar=True), {})

    def test_cada_partido_tiene_la_suya(self):
        alm.guardar_correccion("partido_1.txt", {"equipo": "Palestino"})
        alm.guardar_correccion("partido_2.txt", {"equipo": "UVC"})
        correcciones = alm.leer_correcciones(refrescar=True)
        self.assertEqual(sorted(correcciones), ["partido_1.txt", "partido_2.txt"])

    def test_sobrevive_a_reiniciar_el_proceso(self):
        alm.guardar_correccion("partido_1.txt", {"puntos": 92})
        with mock.patch.object(alm, "_correcciones", None):
            self.assertEqual(alm.leer_correcciones(refrescar=True),
                             {"partido_1.txt": {"puntos": 92}})
