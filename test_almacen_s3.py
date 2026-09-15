"""
Tests de almacen_s3.py: la parte que habla con S3.

Se corren con:
    python -m unittest test_almacen_s3

No tocan la red. Hay dos clases de prueba distintas y las dos hacen falta:

1. La firma se compara contra los vectores que publica AWS. Es la unica forma
   de saber que esta bien sin probar contra S3 de verdad: si un byte del
   pedido canonico no coincide, AWS contesta 403 "SignatureDoesNotMatch" sin
   decir que parte esta mal, y se puede perder un dia entero ahi.

2. Las operaciones se prueban contra un bucket simulado que contesta como
   contesta S3 (XML en el listado, etag entre comillas, 404 cuando no esta).
"""
import io
import os
import unittest
import urllib.error
import urllib.parse
from collections import Counter
from unittest import mock

import almacen_s3 as s3
import almacenamiento as alm


ENTORNO = {
    "VOLEY_S3_BUCKET": "voley-prueba",
    "VOLEY_S3_REGION": "us-east-1",
    "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
    "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    "AWS_SESSION_TOKEN": "",
    "BLOB_READ_WRITE_TOKEN": "",
}


# ----------------------------------------------------------------------
# 1. La firma, contra los vectores de AWS
# ----------------------------------------------------------------------

class TestLaFirma(unittest.TestCase):
    """Los valores salen del ejemplo "GET Object" de la documentacion de S3.

    Se usan las credenciales de mentira que AWS publica justamente para esto,
    asi que el resultado tiene que dar identico o la firma esta mal."""

    CABECERAS = {
        "host": "examplebucket.s3.amazonaws.com",
        "range": "bytes=0-9",
        "x-amz-content-sha256": s3.CUERPO_VACIO,
        "x-amz-date": "20130524T000000Z",
    }
    CANONICO = (
        "GET\n/test.txt\n\n"
        "host:examplebucket.s3.amazonaws.com\nrange:bytes=0-9\n"
        f"x-amz-content-sha256:{s3.CUERPO_VACIO}\nx-amz-date:20130524T000000Z\n\n"
        "host;range;x-amz-content-sha256;x-amz-date\n" + s3.CUERPO_VACIO
    )
    FIRMA = "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"

    def setUp(self):
        entorno = dict(ENTORNO, VOLEY_S3_BUCKET="examplebucket")
        self.entorno = mock.patch.dict(os.environ, entorno)
        self.entorno.start()
        self.addCleanup(self.entorno.stop)

    def test_el_pedido_canonico_es_el_de_la_doc(self):
        canonico, firmadas = s3.pedido_canonico(
            "GET", "/test.txt", {}, self.CABECERAS, s3.CUERPO_VACIO)
        self.assertEqual(canonico, self.CANONICO)
        self.assertEqual(firmadas, "host;range;x-amz-content-sha256;x-amz-date")

    def test_la_firma_es_la_de_la_doc(self):
        auth = s3.autorizacion("GET", "/test.txt", {}, self.CABECERAS,
                               s3.CUERPO_VACIO, "20130524T000000Z")
        self.assertIn(f"Signature={self.FIRMA}", auth)

    def test_la_autorizacion_lleva_el_alcance_completo(self):
        auth = s3.autorizacion("GET", "/test.txt", {}, self.CABECERAS,
                               s3.CUERPO_VACIO, "20130524T000000Z")
        self.assertIn("Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request",
                      auth)

    def test_la_virgulilla_no_se_codifica(self):
        # si se codifica, la firma no coincide y AWS contesta 403 sin decir
        # por que: es el error clasico de implementar SigV4 con quote() pelado
        self.assertEqual(s3.codificar("a~b"), "a~b")
        self.assertEqual(s3.codificar("a b"), "a%20b")

    def test_las_barras_solo_pasan_en_la_ruta(self):
        self.assertEqual(s3.codificar("Datos/x.txt", barras=True), "Datos/x.txt")
        self.assertEqual(s3.codificar("Datos/x.txt"), "Datos%2Fx.txt")

    def test_la_clave_de_firma_depende_del_dia_y_la_region(self):
        una = s3.clave_de_firma("secreto", "20240101", "us-east-1")
        otra = s3.clave_de_firma("secreto", "20240102", "us-east-1")
        lejos = s3.clave_de_firma("secreto", "20240101", "sa-east-1")
        self.assertNotEqual(una, otra)
        self.assertNotEqual(una, lejos)

    def test_el_token_de_sesion_entra_en_la_firma(self):
        # en Lambda las credenciales son temporales y vienen con token; si no
        # se firma, AWS rechaza el pedido
        with mock.patch.dict(os.environ, {"AWS_SESSION_TOKEN": "abc123"}):
            with mock.patch.object(s3.urllib.request, "urlopen") as abrir:
                abrir.return_value = _Respuesta()
                s3.pedir("GET", "/x.txt")
        pedido = abrir.call_args[0][0]
        self.assertEqual(pedido.get_header("X-amz-security-token"), "abc123")
        self.assertIn("x-amz-security-token", pedido.get_header("Authorization"))


# ----------------------------------------------------------------------
# 2. Las operaciones, contra un bucket simulado
# ----------------------------------------------------------------------

class _Respuesta:
    """Lo que devuelve urlopen: se lee una vez y se usa como context manager."""

    def __init__(self, cuerpo=b"", cabeceras=None):
        self._cuerpo = cuerpo
        self.headers = cabeceras or {}

    def read(self):
        return self._cuerpo

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class S3Simulado:
    """Un bucket de mentira que cuenta que le piden.

    Contesta con la forma real de S3, que es lo que importa: el listado es XML
    con espacio de nombres, el etag viene entre comillas y lo que no esta da
    404 y no una respuesta vacia."""

    def __init__(self):
        self.archivos = {}          # clave -> (contenido, etag)
        self.cuenta = Counter()
        self._subidas = 0

    def urlopen(self, pedido, timeout=None):
        partes = urllib.parse.urlsplit(pedido.full_url)
        clave = urllib.parse.unquote(partes.path.lstrip("/"))
        consulta = dict(urllib.parse.parse_qsl(partes.query))
        metodo = pedido.method

        if metodo == "GET" and consulta.get("list-type") == "2":
            self.cuenta["LIST"] += 1
            return _Respuesta(self._listado(consulta))

        if metodo == "PUT":
            self._subidas += 1
            etag = f"etag{self._subidas}"
            self.archivos[clave] = (pedido.data, etag)
            self.cuenta["PUT"] += 1
            return _Respuesta(cabeceras={"ETag": f'"{etag}"'})

        if metodo == "DELETE":
            self.cuenta["DELETE"] += 1
            self.archivos.pop(clave, None)
            return _Respuesta()

        if clave not in self.archivos:
            self.cuenta["HEAD" if metodo == "HEAD" else "GET"] += 1
            raise urllib.error.HTTPError(
                pedido.full_url, 404, "Not Found", {},
                io.BytesIO(b"<Error><Code>NoSuchKey</Code></Error>"))

        contenido, etag = self.archivos[clave]
        if metodo == "HEAD":
            self.cuenta["HEAD"] += 1
            return _Respuesta(cabeceras={"ETag": f'"{etag}"',
                                         "Last-Modified": "Fri, 24 May 2013 00:00:00 GMT",
                                         "Content-Length": str(len(contenido))})
        self.cuenta["GET"] += 1
        return _Respuesta(contenido)

    def _listado(self, consulta) -> bytes:
        """El XML del listado, paginando de a dos para probar el cursor."""
        prefijo = consulta.get("prefix", "")
        claves = sorted(n for n in self.archivos if n.startswith(prefijo))
        desde = consulta.get("continuation-token")
        if desde:
            claves = claves[claves.index(desde):]
        pagina, resto = claves[:2], claves[2:]

        filas = "".join(
            f"<Contents><Key>{n}</Key>"
            f"<LastModified>2013-05-24T00:00:00.000Z</LastModified>"
            f"<ETag>&quot;{self.archivos[n][1]}&quot;</ETag>"
            f"<Size>{len(self.archivos[n][0])}</Size></Contents>"
            for n in pagina)
        mas = (f"<IsTruncated>true</IsTruncated>"
               f"<NextContinuationToken>{resto[0]}</NextContinuationToken>"
               if resto else "<IsTruncated>false</IsTruncated>")
        return (f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-01-01/">'
                f'{filas}{mas}</ListBucketResult>'
                ).replace("2006-01-01", "2006-03-01").encode("utf-8")


class BaseS3(unittest.TestCase):

    def setUp(self):
        self.entorno = mock.patch.dict(os.environ, ENTORNO)
        self.entorno.start()
        self.addCleanup(self.entorno.stop)
        self.bucket = S3Simulado()
        self.parche = mock.patch.object(s3.urllib.request, "urlopen",
                                        self.bucket.urlopen)
        self.parche.start()
        self.addCleanup(self.parche.stop)


class TestLasOperaciones(BaseS3):

    def test_subir_devuelve_el_etag_sin_comillas(self):
        # S3 lo manda entre comillas y el resto del codigo no las espera
        datos = s3.subir("Datos/x.txt", b"hola", "text/plain")
        self.assertEqual(datos["etag"], "etag1")
        self.assertEqual(datos["pathname"], "Datos/x.txt")

    def test_subir_y_bajar_devuelve_lo_mismo(self):
        s3.subir("Datos/x.txt", b"hola mundo", "text/plain")
        self.assertEqual(s3.bajar("Datos/x.txt"), b"hola mundo")

    def test_subir_pisa_el_anterior(self):
        # regenerar un informe es reemplazarlo, no crear otro
        s3.subir("Datos/x.txt", b"viejo", "text/plain")
        s3.subir("Datos/x.txt", b"nuevo", "text/plain")
        self.assertEqual(s3.bajar("Datos/x.txt"), b"nuevo")
        self.assertEqual(len(self.bucket.archivos), 1)

    def test_la_cabeza_no_baja_el_archivo(self):
        s3.subir("sesion/actual.json", b"x" * 5000, "application/json")
        self.bucket.cuenta.clear()
        datos = s3.cabeza("sesion/actual.json")
        self.assertEqual(datos["etag"], "etag1")
        self.assertEqual(self.bucket.cuenta["HEAD"], 1)
        self.assertEqual(self.bucket.cuenta["GET"], 0)

    def test_la_cabeza_de_lo_que_no_esta_es_none(self):
        # pasa siempre al empezar: todavia no hay sesion guardada
        self.assertIsNone(s3.cabeza("sesion/actual.json"))

    def test_borrar_lo_saca(self):
        s3.subir("Datos/x.txt", b"hola", "text/plain")
        s3.borrar("Datos/x.txt")
        self.assertIsNone(s3.cabeza("Datos/x.txt"))

    def test_el_listado_trae_lo_del_prefijo_y_nada_mas(self):
        s3.subir("Datos/a.txt", b"a", "text/plain")
        s3.subir("Informes/b.xlsx", b"b", "text/plain")
        nombres = [x["pathname"] for x in s3.listar("Datos/")]
        self.assertEqual(nombres, ["Datos/a.txt"])

    def test_el_listado_pagina_hasta_traer_todo(self):
        # el simulado corta de a dos: con cinco archivos hacen falta 3 vueltas
        for letra in "abcde":
            s3.subir(f"Datos/{letra}.txt", b"x", "text/plain")
        self.bucket.cuenta.clear()
        nombres = [x["pathname"] for x in s3.listar("Datos/")]
        self.assertEqual(len(nombres), 5)
        self.assertEqual(self.bucket.cuenta["LIST"], 3)

    def test_el_listado_trae_el_tamano_y_la_fecha(self):
        s3.subir("Datos/a.txt", b"hola", "text/plain")
        uno = s3.listar("Datos/")[0]
        self.assertEqual(uno["size"], 4)
        self.assertTrue(uno["uploadedAt"])

    def test_un_error_que_no_es_404_se_levanta(self):
        def rota(pedido, timeout=None):
            raise urllib.error.HTTPError(pedido.full_url, 403, "Forbidden", {},
                                         io.BytesIO(b"<Error>AccessDenied</Error>"))
        with mock.patch.object(s3.urllib.request, "urlopen", rota):
            with self.assertRaises(s3.ErrorDeS3) as caso:
                s3.subir("Datos/x.txt", b"hola", "text/plain")
        self.assertEqual(caso.exception.codigo, 403)
        self.assertIn("AccessDenied", str(caso.exception))


class TestLaConfiguracion(BaseS3):

    def test_sin_bucket_no_hay_s3(self):
        with mock.patch.dict(os.environ, {"VOLEY_S3_BUCKET": ""}):
            self.assertFalse(s3.hay_s3())

    def test_sin_credenciales_no_hay_s3(self):
        with mock.patch.dict(os.environ, {"AWS_ACCESS_KEY_ID": ""}):
            self.assertFalse(s3.hay_s3())

    def test_las_comillas_del_env_no_entran_en_el_valor(self):
        # copiar de un .env deja comillas pegadas, y un bucket con comillas da
        # un error de DNS que no se parece en nada a la causa
        with mock.patch.dict(os.environ, {"VOLEY_S3_BUCKET": '"voley-prueba"'}):
            self.assertEqual(s3.bucket(), "voley-prueba")

    def test_el_host_es_el_del_bucket_y_la_region(self):
        self.assertEqual(s3.anfitrion(), "voley-prueba.s3.us-east-1.amazonaws.com")

    def test_la_region_sale_de_lambda_si_no_se_forzo(self):
        with mock.patch.dict(os.environ, {"VOLEY_S3_REGION": "",
                                          "AWS_REGION": "sa-east-1"}):
            self.assertEqual(s3.region(), "sa-east-1")


# ----------------------------------------------------------------------
# 3. Visto desde almacenamiento.py, que es quien lo usa
# ----------------------------------------------------------------------

class TestDesdeAlmacenamiento(BaseS3):
    """El resto del proyecto no tiene que enterarse de cual de los dos
    almacenes esta atras: llama a las mismas funciones de siempre."""

    def test_con_bucket_configurado_se_usa_s3(self):
        self.assertTrue(alm.hay_blob())
        self.assertTrue(alm.en_s3())

    def test_subir_y_pedir_la_cabeza_pasan_por_s3(self):
        alm.subir_blob_detalle("sesion/actual.json", b"{}", "application/json")
        self.assertEqual(self.bucket.cuenta["PUT"], 1)
        datos = alm.cabeza_blob("sesion/actual.json")
        self.assertEqual(datos["etag"], "etag1")

    def test_la_version_sale_de_la_subida_sin_preguntar_de_nuevo(self):
        # es lo que evita una operacion de mas por cada jugada cargada
        subido = alm.subir_blob_detalle("sesion/actual.json", b"{}", "application/json")
        self.bucket.cuenta.clear()
        self.assertEqual(alm._version_de(subido), "etag1")
        self.assertEqual(sum(self.bucket.cuenta.values()), 0)

    def test_un_error_de_s3_se_cuenta_como_error_de_blob(self):
        # el resto del archivo caza ErrorDeBlob y mira su codigo
        def rota(pedido, timeout=None):
            raise urllib.error.HTTPError(pedido.full_url, 403, "Forbidden", {},
                                         io.BytesIO(b"<Error/>"))
        with mock.patch.object(s3.urllib.request, "urlopen", rota):
            with self.assertRaises(alm.ErrorDeBlob) as caso:
                alm.subir_blob_detalle("x.json", b"{}", "application/json")
        self.assertEqual(caso.exception.codigo, 403)

    def test_guardar_la_sesion_cuesta_una_sola_operacion(self):
        # con una llamada de mas por jugada, un partido de 230 jugadas se
        # come el presupuesto entero
        alm.guardar_sesion(["Local", "Rival"])
        self.assertEqual(self.bucket.cuenta["PUT"], 1)
        self.assertEqual(self.bucket.cuenta["LIST"], 0)

    def test_la_sesion_guardada_se_vuelve_a_leer(self):
        alm.guardar_sesion(["Local", "Rival", "1_S 2 3 4 5 6"])
        with mock.patch.object(alm, "CARPETA_ESCRITURA", Path_temporal()):
            leido = alm.leer_sesion()
        self.assertIsNotNone(leido)
        self.assertEqual(leido[0], ["Local", "Rival", "1_S 2 3 4 5 6"])


def Path_temporal():
    """Una carpeta vacia, para que leer_sesion no encuentre la copia local y
    tenga que ir a buscarla al bucket."""
    import tempfile
    from pathlib import Path
    return Path(tempfile.mkdtemp())


if __name__ == "__main__":
    unittest.main()
