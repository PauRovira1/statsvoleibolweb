"""
El servidor de las pantallas de video (video/servidor_video.py), contestando
de verdad en un puerto suelto.

Tres cosas: que solo sirve la lista blanca (ninguna ruta del pedido llega al
disco), que el video va por rangos (sin eso el navegador no puede saltar a
la mitad del partido), y que las armadas marcadas quedan: se marcan 20, se
cierra el servidor, se abre otro y estan las 20.

No hace falta ffmpeg: el "proxy" de estos tests son bytes cualesquiera, que
para servir por rangos da igual.
"""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from video import proyecto, servidor_video
from video.servidor_video import FUERA, leer_rango

META = {"duracion": 600.0, "fps": 30.0, "ancho": 1280, "alto": 720, "rotacion": 0,
        "codec": "h264"}
CONTENIDO = bytes(range(256)) * 40          # 10240 bytes


class ConServidor(unittest.TestCase):

    def setUp(self):
        temporal = tempfile.TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.base = Path(temporal.name) / "Videos"
        self.base.mkdir()
        original = self.base / "Palestino vs Español.mp4"
        original.write_bytes(b"original" * 1000)
        self.p = proyecto.crear(original, META, base=self.base)
        self.p.ruta_proxy.write_bytes(CONTENIDO)
        self.nombre = self.p.nombre
        self.levantar()

    def levantar(self):
        self.servidor = servidor_video.Servidor(("127.0.0.1", 0), self.base)
        self.puerto = self.servidor.server_address[1]
        # poll_interval corto: si no, cada cierre espera medio segundo
        self.hilo = threading.Thread(target=self.servidor.serve_forever,
                                     kwargs={"poll_interval": 0.05}, daemon=True)
        self.hilo.start()
        self.addCleanup(self.bajar, self.servidor, self.hilo)

    @staticmethod
    def bajar(servidor, hilo):
        servidor.shutdown()
        servidor.server_close()
        hilo.join(timeout=5)

    def pedir(self, metodo, ruta, cuerpo=None, encabezados=None):
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        encabezados = dict(encabezados or {})
        datos = None
        if cuerpo is not None:
            datos = json.dumps(cuerpo).encode("utf-8")
            encabezados.setdefault("Content-Type", "application/json")
        conexion.request(metodo, ruta, body=datos, headers=encabezados)
        respuesta = conexion.getresponse()
        contenido = respuesta.read()
        conexion.close()
        return respuesta, contenido

    def api(self, metodo, ruta, cuerpo=None, encabezados=None):
        respuesta, contenido = self.pedir(metodo, ruta, cuerpo, encabezados)
        return respuesta.status, json.loads(contenido.decode("utf-8"))

    def operar(self, op, edicion):
        return self.api("POST", f"/api/videos/{self.nombre}/operar",
                        {"edicion": edicion, "op": op})


class TestListaBlanca(ConServidor):

    def test_las_paginas(self):
        for ruta, tipo in (("/", "text/html"), ("/revision.html", "text/html"),
                           ("/galeria.html", "text/html"), ("/video.css", "text/css"),
                           ("/comun.js", "application/javascript"),
                           ("/revision.js", "application/javascript")):
            with self.subTest(ruta=ruta):
                respuesta, contenido = self.pedir("GET", ruta)
                self.assertEqual(respuesta.status, 200)
                self.assertTrue(respuesta.getheader("Content-Type").startswith(tipo))
                self.assertTrue(contenido)

    def test_nada_fuera_de_la_lista(self):
        for ruta in ("/../servidor_voley.py", "/servidor_video.py", "/web/inicio.html",
                     "/video/servidor_video.py", f"/videos/{self.nombre}/fuente.json",
                     f"/videos/{self.nombre}/revision.json",
                     f"/videos/{self.nombre}/../../servidor_voley.py",
                     "/videos/..%2F..%2Fservidor_voley/proxy.mp4",
                     "/videos/no-existe/proxy.mp4", "/api/videos/No-Valido",
                     "/api/videos/no-existe"):
            with self.subTest(ruta=ruta):
                respuesta, _ = self.pedir("GET", ruta)
                self.assertEqual(respuesta.status, 404)

    def test_un_host_ajeno_no_pasa(self):
        # una pagina de otro dominio que resuelve a 127.0.0.1 (DNS rebinding)
        respuesta, _ = self.pedir("GET", "/api/videos", encabezados={"Host": "malo.com:8001"})
        self.assertEqual(respuesta.status, 403)
        estado, _ = self.api("POST", f"/api/videos/{self.nombre}/operar",
                             {"edicion": 0, "op": {"tipo": "marcar", "t": 1.0}},
                             encabezados={"Host": "malo.com"})
        self.assertEqual(estado, 403)
        respuesta, _ = self.pedir("GET", "/api/videos", encabezados={"Host": "localhost:8001"})
        self.assertEqual(respuesta.status, 200)

    def test_escribir_pide_json(self):
        # lo que un formulario de otro sitio si puede mandar sin preguntar
        conexion = http.client.HTTPConnection("127.0.0.1", self.puerto, timeout=10)
        conexion.request("POST", f"/api/videos/{self.nombre}/operar",
                         body=b'{"edicion":0,"op":{"tipo":"marcar","t":1}}',
                         headers={"Content-Type": "text/plain"})
        respuesta = conexion.getresponse()
        respuesta.read()
        conexion.close()
        self.assertEqual(respuesta.status, 415)
        self.assertEqual(self.p.revision()["decisiones"], [])


class TestRangos(ConServidor):

    def proxy(self, rango=None, metodo="GET"):
        return self.pedir(metodo, f"/videos/{self.nombre}/proxy.mp4",
                          encabezados={"Range": rango} if rango else None)

    def test_sin_rango_va_entero(self):
        respuesta, contenido = self.proxy()
        self.assertEqual(respuesta.status, 200)
        self.assertEqual(contenido, CONTENIDO)
        self.assertEqual(respuesta.getheader("Accept-Ranges"), "bytes")
        self.assertEqual(respuesta.getheader("Content-Type"), "video/mp4")

    def test_un_pedazo(self):
        for rango, desde, hasta in (("bytes=0-9", 0, 9), ("bytes=10000-", 10000, 10239),
                                    ("bytes=-100", 10140, 10239),
                                    ("bytes=10200-99999", 10200, 10239)):
            with self.subTest(rango=rango):
                respuesta, contenido = self.proxy(rango)
                self.assertEqual(respuesta.status, 206)
                self.assertEqual(contenido, CONTENIDO[desde:hasta + 1])
                self.assertEqual(respuesta.getheader("Content-Range"),
                                 f"bytes {desde}-{hasta}/{len(CONTENIDO)}")

    def test_afuera_del_archivo(self):
        respuesta, contenido = self.proxy("bytes=20000-")
        self.assertEqual(respuesta.status, 416)
        self.assertEqual(respuesta.getheader("Content-Range"), f"bytes */{len(CONTENIDO)}")
        self.assertEqual(contenido, b"")

    def test_lo_que_no_se_entiende_se_ignora(self):
        for rango in ("bytes=0-1,5-6", "items=0-5", "bytes=9-2"):
            with self.subTest(rango=rango):
                respuesta, contenido = self.proxy(rango)
                self.assertEqual((respuesta.status, len(contenido)), (200, len(CONTENIDO)))

    def test_head_no_manda_el_cuerpo(self):
        respuesta, contenido = self.proxy(metodo="HEAD")
        self.assertEqual(respuesta.status, 200)
        self.assertEqual(respuesta.getheader("Content-Length"), str(len(CONTENIDO)))
        self.assertEqual(contenido, b"")

    def test_sin_proxy_lo_dice(self):
        self.p.ruta_proxy.unlink()
        estado, datos = self.api("GET", f"/videos/{self.nombre}/proxy.mp4")
        self.assertEqual(estado, 404)
        self.assertIn("python -m video nuevo", datos["mensaje"])

    def test_leer_rango(self):
        self.assertEqual(leer_rango("bytes=5-", 10), (5, 9))
        self.assertEqual(leer_rango("bytes=-3", 10), (7, 9))
        self.assertEqual(leer_rango("bytes=-30", 10), (0, 9))
        self.assertEqual(leer_rango("bytes=10-", 10), FUERA)
        self.assertEqual(leer_rango("bytes=-0", 10), FUERA)
        self.assertEqual(leer_rango("bytes=0-", 0), FUERA)
        self.assertIsNone(leer_rango("bytes=-", 10))
        self.assertIsNone(leer_rango(None, 10))


class TestApi(ConServidor):

    def test_la_lista_de_videos(self):
        estado, datos = self.api("GET", "/api/videos")
        self.assertEqual(estado, 200)
        [video] = datos["videos"]
        self.assertEqual((video["nombre"], video["titulo"], video["hay_proxy"]),
                         (self.nombre, "Palestino vs Español", True))
        self.assertEqual(video["cuentas"], {"aceptada": 0, "pendiente": 0, "descartada": 0})

    def test_marcar_y_deshacer(self):
        estado, datos = self.operar({"tipo": "marcar", "t": 12.5, "campos": {"armador": 3}}, 0)
        self.assertEqual(estado, 200, datos)
        self.assertEqual((datos["edicion"], datos["clave"], len(datos["armadas"])),
                         (1, "d:d1", 1))
        self.assertTrue(datos["se_puede_deshacer"])

        estado, datos = self.operar({"tipo": "deshacer"}, 1)
        self.assertEqual(estado, 200, datos)
        self.assertEqual((datos["edicion"], datos["armadas"]), (2, []))
        self.assertFalse(datos["se_puede_deshacer"])

        estado, datos = self.operar({"tipo": "deshacer"}, 2)
        self.assertEqual(estado, 400)
        self.assertIn("deshacer", datos["mensaje"])

    def test_una_pestana_vieja_no_pisa(self):
        self.operar({"tipo": "marcar", "t": 12.5}, 0)
        estado, datos = self.operar({"tipo": "marcar", "t": 40.0}, 0)
        self.assertEqual(estado, 409)
        self.assertTrue(datos["conflicto"])
        # trae lo de ahora, para que la pantalla se ponga al dia
        self.assertEqual((datos["edicion"], len(datos["armadas"])), (1, 1))

    def test_una_operacion_invalida_explica_por_que(self):
        estado, datos = self.operar({"tipo": "marcar", "t": 9999.0}, 0)
        self.assertEqual(estado, 400)
        self.assertIn("final del video", datos["mensaje"])
        estado, datos = self.api("POST", f"/api/videos/{self.nombre}/operar", {"op": {}})
        self.assertEqual(estado, 400)
        self.assertEqual(self.p.revision()["edicion"], 0)

    def test_un_video_que_no_existe(self):
        estado, _ = self.api("POST", "/api/videos/no-existe/operar",
                             {"edicion": 0, "op": {"tipo": "marcar", "t": 1.0}})
        self.assertEqual(estado, 404)

    def test_una_revision_rota_se_avisa_sin_tapar_a_los_demas(self):
        (self.p.carpeta / proyecto.REVISION).write_text("{roto", encoding="utf-8")
        estado, datos = self.api("GET", f"/api/videos/{self.nombre}")
        self.assertEqual(estado, 500)
        self.assertIn("roto", datos["mensaje"])
        estado, datos = self.api("GET", "/api/videos")
        self.assertEqual(estado, 200)
        self.assertIn("error", datos["videos"][0])


class TestMarcarCerrarYVolver(ConServidor):
    """El criterio de la etapa 1: marco 20 armadas, cierro, vuelvo a abrir y
    estan; y la galeria las tiene para filtrar por zona."""

    def test_las_veinte_armadas_quedan(self):
        edicion = 0
        for i in range(20):
            estado, datos = self.operar({"tipo": "marcar", "t": 10.0 + 25 * i,
                                         "campos": {"zona_destino": [4, 3, 2, 1, 6][i % 5],
                                                    "armador": 3}}, edicion)
            self.assertEqual(estado, 200, datos)
            edicion = datos["edicion"]
        self.operar({"tipo": "set", "desde": 0.0, "set": 1, "lado": "cerca"}, edicion)

        # se cierra este servidor y se abre otro sobre la misma carpeta
        self.bajar(self.servidor, self.hilo)
        self.levantar()

        estado, datos = self.api("GET", f"/api/videos/{self.nombre}")
        self.assertEqual(estado, 200)
        self.assertEqual(len(datos["armadas"]), 20)
        self.assertEqual({a["set"] for a in datos["armadas"]}, {1})
        # la historia para deshacer es de la sesion: con el servidor nuevo, no hay
        self.assertFalse(datos["se_puede_deshacer"])

        estado, galeria = self.api("GET", "/api/armadas")
        self.assertEqual(estado, 200)
        self.assertEqual(len(galeria["armadas"]), 20)
        self.assertEqual(galeria["videos"][self.nombre]["titulo"], "Palestino vs Español")
        a_zona_4 = [a for a in galeria["armadas"] if a["zona_destino"] == 4]
        self.assertEqual(len(a_zona_4), 4)
        self.assertTrue(all(a["video"] == self.nombre for a in a_zona_4))

    def test_la_galeria_solo_trae_las_aceptadas(self):
        propuestas = {"version": 1, "armadas": [
            {"id": "p1", "t_armado": 30.0, "lado": "cerca"},
            {"id": "p2", "t_armado": 60.0, "lado": "cerca"}]}
        (self.p.carpeta / proyecto.PROPUESTAS).write_text(json.dumps(propuestas),
                                                          encoding="utf-8")
        self.operar({"tipo": "aceptar", "clave": "p:p1"}, 0)
        _, galeria = self.api("GET", "/api/armadas")
        self.assertEqual([a["t_armado"] for a in galeria["armadas"]], [30.0])
        _, lista = self.api("GET", "/api/videos")
        self.assertEqual(lista["videos"][0]["cuentas"],
                         {"aceptada": 1, "pendiente": 1, "descartada": 0})


if __name__ == "__main__":
    unittest.main()
