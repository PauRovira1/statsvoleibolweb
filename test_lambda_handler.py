"""
Tests de lambda_handler.py: la traduccion entre AWS Lambda y el manejador.

Se corren con:
    python -m unittest test_lambda_handler

No tocan la red ni AWS: se arman a mano los eventos con el formato que manda
un Function URL (payload version 2.0) y se mira lo que contesta.

Lo que cuidan es que la traduccion no pierda nada por el camino -- el metodo,
la query, el cuerpo, el tipo de contenido -- porque cuando se pierde algo la
app no falla con un error claro: contesta 400 o 500 desde adentro del motor y
parece un problema del partido.
"""
import base64
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

import almacenamiento as alm
import lambda_handler as lh
import servidor_voley as srv


def evento(metodo="GET", ruta="/", *, consulta="", cuerpo=None,
           token=None, base64_cuerpo=False, cabeceras=None):
    """Un pedido con la forma que manda un Lambda Function URL."""
    todas = {"content-type": "application/json"}
    todas.update(cabeceras or {})
    if token:
        todas["x-clave"] = token

    crudo = json.dumps(cuerpo) if cuerpo is not None else ""
    if base64_cuerpo:
        crudo = base64.b64encode(crudo.encode("utf-8")).decode("ascii")

    return {
        "version": "2.0",
        "rawPath": ruta,
        "rawQueryString": consulta,
        "headers": todas,
        "requestContext": {"http": {"method": metodo, "path": ruta}},
        "body": crudo,
        "isBase64Encoded": base64_cuerpo,
    }


class BaseLambda(unittest.TestCase):

    def setUp(self):
        # Nada de lo que escriban los tests toca el proyecto. Hacen falta
        # los tres parches: _ES_LOCAL decide si ademas de la carpeta de
        # escritura se lee la del repo (alojado se leen las dos), y
        # CARPETA_DATOS la resuelve analisis_voley al importarse, asi que no
        # se entera de que cambio la de abajo.
        self.carpeta = Path(tempfile.mkdtemp())
        for objeto, nombre, valor in (
            (alm, "CARPETA_ESCRITURA", self.carpeta),
            (alm, "_ES_LOCAL", False),
            (srv.av, "CARPETA_DATOS", self.carpeta / "Datos"),
        ):
            parche = mock.patch.object(objeto, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)
        # la sesion es de modulo: si no se vacia, un test arrastra al otro
        srv.sesion.reemplazar([])
        self.addCleanup(srv.sesion.reemplazar, [])
        self.clave = mock.patch.object(srv.av, "CONTRASENA_CARGA", "test123")
        self.clave.start()
        self.addCleanup(self.clave.stop)

    def entrar(self) -> str:
        respuesta = lh.handler(evento("POST", "/api/clave", cuerpo={"clave": "test123"}))
        return json.loads(respuesta["body"])["token"]


class TestLoBasico(BaseLambda):

    def test_la_pantalla_se_sirve(self):
        respuesta = lh.handler(evento("GET", "/"))
        self.assertEqual(respuesta["statusCode"], 200)
        self.assertIn("text/html", respuesta["headers"].get("Content-Type", ""))
        self.assertIn("<!doctype html>", respuesta["body"])

    def test_el_html_no_viaja_en_base64(self):
        # si viajara, CloudFront lo entregaria como texto ilegible
        respuesta = lh.handler(evento("GET", "/"))
        self.assertFalse(respuesta["isBase64Encoded"])

    def test_una_ruta_que_no_existe_da_404(self):
        self.assertEqual(lh.handler(evento("GET", "/nada"))["statusCode"], 404)

    def test_las_cabeceras_de_la_respuesta_llegan(self):
        respuesta = lh.handler(evento("GET", "/api/notacion"))
        self.assertIn("Content-Type", respuesta["headers"])
        self.assertEqual(respuesta["headers"]["Content-Type"],
                         "application/json; charset=utf-8")


class TestElCuerpoYLaQuery(BaseLambda):

    def test_el_cuerpo_del_post_llega_entero(self):
        respuesta = lh.handler(evento("POST", "/api/clave", cuerpo={"clave": "test123"}))
        self.assertEqual(respuesta["statusCode"], 200)
        self.assertTrue(json.loads(respuesta["body"])["token"])

    def test_la_clave_equivocada_no_entra(self):
        respuesta = lh.handler(evento("POST", "/api/clave", cuerpo={"clave": "otra"}))
        self.assertFalse(json.loads(respuesta["body"]).get("ok"))

    def test_un_cuerpo_en_base64_se_decodifica(self):
        # Lambda manda asi el cuerpo cuando lo considera binario
        respuesta = lh.handler(evento("POST", "/api/clave",
                                      cuerpo={"clave": "test123"}, base64_cuerpo=True))
        self.assertTrue(json.loads(respuesta["body"])["token"])

    def test_el_content_length_se_recalcula(self):
        # si se copiara el del evento, un cuerpo que vino en base64 tendria el
        # largo codificado y el manejador leeria de menos, colgandose
        respuesta = lh.handler(evento("POST", "/api/clave",
                                      cuerpo={"clave": "test123"},
                                      base64_cuerpo=True,
                                      cabeceras={"content-length": "9999"}))
        self.assertEqual(respuesta["statusCode"], 200)

    def test_la_query_llega(self):
        respuesta = lh.handler(evento("GET", "/api/partido",
                                      consulta="archivo=no_existe.txt"))
        # que conteste algo distinto de 200 prueba que leyo el parametro
        self.assertIn(respuesta["statusCode"], (200, 400, 404))
        self.assertIn("no_existe", respuesta["body"] + json.dumps(respuesta["headers"]))


class TestUnPartidoEntero(BaseLambda):

    LINEAS = ["Local", "Rival", "1_S 2 3 4 5 6", "7_S 8 9 10 11 12", "A",
              "1_5_A", "C_20_3"]

    def test_se_carga_un_partido_pedido_por_pedido(self):
        token = self.entrar()
        for linea in self.LINEAS:
            respuesta = lh.handler(evento("POST", "/api/enviar",
                                          cuerpo={"linea": linea}, token=token))
            self.assertEqual(respuesta["statusCode"], 200, linea)

        estado = json.loads(respuesta["body"])["estado"]
        self.assertEqual(estado["marcador"], {"A": 1, "B": 0})
        self.assertEqual(estado["rotaciones"]["A"]["jugadores"], [1, 2, 20, 4, 5, 6])

    def test_sin_token_no_se_carga_nada(self):
        respuesta = lh.handler(evento("POST", "/api/enviar", cuerpo={"linea": "Local"}))
        self.assertEqual(respuesta["statusCode"], 401)

    def test_el_txt_guardado_queda_en_la_carpeta_de_escritura(self):
        token = self.entrar()
        for linea in self.LINEAS:
            lh.handler(evento("POST", "/api/enviar", cuerpo={"linea": linea}, token=token))
        respuesta = lh.handler(evento("POST", "/api/guardar", token=token, cuerpo={}))
        self.assertEqual(respuesta["statusCode"], 200)
        self.assertTrue(list((self.carpeta / "Datos").glob("partido_*.txt")))


class TestLoBinario(BaseLambda):
    """Un .xlsx no entra en un JSON: tiene que viajar en base64 y volver byte
    por byte, o el Excel que se baja esta corrupto."""

    def _un_informe(self) -> Path:
        informes = sorted(Path("Informes").glob("*.xlsx"))
        if not informes:
            self.skipTest("no hay ningun .xlsx en Informes/")
        return informes[0]

    def test_el_xlsx_viaja_en_base64(self):
        informe = self._un_informe()
        consulta = urllib.parse.urlencode({"archivo": informe.name, "tipo": "xlsx"})
        respuesta = lh.handler(evento("GET", "/api/descargar", consulta=consulta))
        self.assertEqual(respuesta["statusCode"], 200)
        self.assertTrue(respuesta["isBase64Encoded"])

    def test_el_xlsx_vuelve_identico(self):
        informe = self._un_informe()
        consulta = urllib.parse.urlencode({"archivo": informe.name, "tipo": "xlsx"})
        respuesta = lh.handler(evento("GET", "/api/descargar", consulta=consulta))
        self.assertEqual(base64.b64decode(respuesta["body"]), informe.read_bytes())

    def test_el_txt_viaja_como_texto(self):
        volcados = sorted(Path("Datos").glob("*.txt"))
        if not volcados:
            self.skipTest("no hay ningun .txt en Datos/")
        consulta = urllib.parse.urlencode({"archivo": volcados[0].name, "tipo": "txt"})
        respuesta = lh.handler(evento("GET", "/api/descargar", consulta=consulta))
        self.assertFalse(respuesta["isBase64Encoded"])
        self.assertIn("=== Jugadas cargadas ===", respuesta["body"])


if __name__ == "__main__":
    unittest.main()
