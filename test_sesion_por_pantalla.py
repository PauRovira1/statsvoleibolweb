"""
El partido en curso es de la pantalla, no del servidor.

Antes habia una sola sesion en el servidor y dos personas cargando al mismo
tiempo escribian sobre el mismo partido. Ahora cada pantalla guarda sus lineas
y las manda en cada pedido; el servidor las corre por el motor y contesta como
quedo, sin guardarse nada. Lo que se prueba aca es justamente eso: que dos
partidos a la vez no se mezclan, que la sesion compartida queda intacta, y que
un pedido sin lineas sigue cayendo en esa sesion (una pantalla con el .js
viejo en cache, o la consola de pruebas).
"""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import analisis_voley as av
import servidor_voley as sv

# Dos partidos distintos, escritos como se tipearian: los dos nombres, las dos
# rotaciones, quien saca, y un punto.
PARTIDO_A = ["Palestino", "Aguante", "1 2 3_S 4 5 6", "11 12 13_S 14 15 16", "A",
             "1_5_X/13_3/12_4/14_1_P"]
PARTIDO_B = ["Boca", "River", "21 22 23_S 24 25 26", "31 32 33_S 34 35 36", "B",
             "1_5_X/23_3/22_4/24_1_P"]


class BaseServidor(unittest.TestCase):
    """El servidor de verdad, contestando en un puerto suelto."""

    @classmethod
    def setUpClass(cls):
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), sv.Manejador)
        cls.base = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.hilo.join(timeout=5)

    def setUp(self):
        # la sesion compartida es de modulo: si no se vacia, un test arrastra
        # al otro
        sv.sesion.reemplazar([])
        self.addCleanup(sv.sesion.reemplazar, [])
        self.token = self.post("/api/clave", {"clave": av.CONTRASENA_CARGA})["token"]

    def post(self, ruta, cuerpo, token=None):
        pedido = urllib.request.Request(
            self.base + ruta, method="POST",
            data=json.dumps(cuerpo).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     **({"X-Clave": token} if token else {})})
        with urllib.request.urlopen(pedido, timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))

    def cargar(self, lineas, token=None):
        """Lo que hace el navegador: manda su copia y se queda con la que
        contesta el motor."""
        quedan = []
        for linea in lineas:
            r = self.post("/api/enviar", {"lineas": quedan, "linea": linea},
                          token or self.token)
            quedan = r["estado"]["lineas"]
        return quedan


class TestDosPantallas(BaseServidor):

    def test_dos_partidos_al_mismo_tiempo_no_se_mezclan(self):
        # intercalados linea por linea, que es lo que pasa en la cancha
        a, b = [], []
        for la, lb in zip(PARTIDO_A, PARTIDO_B):
            a = self.post("/api/enviar", {"lineas": a, "linea": la},
                          self.token)["estado"]["lineas"]
            b = self.post("/api/enviar", {"lineas": b, "linea": lb},
                          self.token)["estado"]["lineas"]

        estado_a = self.post("/api/estado", {"lineas": a})["estado"]
        estado_b = self.post("/api/estado", {"lineas": b})["estado"]
        self.assertEqual(estado_a["nombres"], {"A": "Palestino", "B": "Aguante"})
        self.assertEqual(estado_b["nombres"], {"A": "Boca", "B": "River"})
        self.assertEqual(estado_a["puntos_cargados"], 1)
        self.assertEqual(estado_b["puntos_cargados"], 1)

    def test_el_pedido_con_lineas_no_toca_la_sesion_compartida(self):
        self.cargar(PARTIDO_A)
        self.assertEqual(sv.sesion.lineas, [])

    def test_deshacer_borra_de_la_pantalla_que_lo_pidio(self):
        a = self.cargar(PARTIDO_A)
        b = self.cargar(PARTIDO_B)
        r = self.post("/api/deshacer", {"lineas": a}, self.token)
        self.assertEqual(len(r["estado"]["lineas"]), len(a) - 1)
        # el otro partido quedo donde estaba
        otro = self.post("/api/estado", {"lineas": b})["estado"]
        self.assertEqual(otro["puntos_cargados"], 1)

    def test_las_estadisticas_son_las_del_partido_que_se_manda(self):
        b = self.cargar(PARTIDO_B)
        texto = self.post("/api/estadisticas", {"lineas": b})["texto"]
        self.assertIn("Boca", texto)
        self.assertNotIn("Palestino", texto)

    def test_la_linea_que_el_motor_rechaza_no_entra(self):
        a = self.cargar(PARTIDO_A)
        r = self.post("/api/enviar", {"lineas": a, "linea": "esto no es una jugada"},
                      self.token)
        self.assertFalse(r["ok"])
        self.assertEqual(r["estado"]["lineas"], a)

    def test_cargar_un_volcado_entero_reemplaza_solo_esa_pantalla(self):
        a = self.cargar(PARTIDO_A)
        r = self.post("/api/cargar", {"lineas": a, "texto": "\n".join(PARTIDO_B)},
                      self.token)
        self.assertTrue(r["ok"])
        self.assertEqual(r["estado"]["nombres"], {"A": "Boca", "B": "River"})
        self.assertEqual(sv.sesion.lineas, [])

    def test_sin_el_token_no_se_carga_ni_con_lineas_propias(self):
        with self.assertRaises(urllib.error.HTTPError) as caso:
            self.post("/api/enviar", {"lineas": [], "linea": "Palestino"})
        self.assertEqual(caso.exception.code, 401)

    def test_lineas_que_no_son_una_lista_se_rechazan(self):
        with self.assertRaises(urllib.error.HTTPError) as caso:
            self.post("/api/enviar", {"lineas": "Palestino", "linea": "x"}, self.token)
        self.assertEqual(caso.exception.code, 400)


class TestLaSesionCompartidaSigueAhi(BaseServidor):
    """Un pedido sin "lineas" es de antes del cambio: una pantalla con el .js
    viejo en cache. Sigue contestando la sesion del servidor, como siempre."""

    def test_sin_lineas_se_usa_la_sesion_del_servidor(self):
        for linea in PARTIDO_A:
            self.post("/api/enviar", {"linea": linea}, self.token)
        self.assertEqual(sv.sesion.lineas, PARTIDO_A)
        estado = self.post("/api/estado", {})["estado"]
        self.assertEqual(estado["nombres"], {"A": "Palestino", "B": "Aguante"})

    def test_una_pantalla_nueva_no_ve_lo_de_la_vieja(self):
        for linea in PARTIDO_A:
            self.post("/api/enviar", {"linea": linea}, self.token)
        estado = self.post("/api/estado", {"lineas": []})["estado"]
        self.assertEqual(estado["nombres"], {"A": "A", "B": "B"})
        self.assertEqual(estado["puntos_cargados"], 0)


class TestGuardarDesdeDosPantallas(BaseServidor):

    def test_dos_partidos_guardados_en_el_mismo_segundo_no_se_pisan(self):
        a = self.cargar(PARTIDO_A)
        b = self.cargar(PARTIDO_B)
        with tempfile.TemporaryDirectory() as carpeta:
            with mock.patch.object(av, "CARPETA_DATOS", Path(carpeta)):
                ra = self.post("/api/guardar", {"lineas": a}, self.token)
                rb = self.post("/api/guardar", {"lineas": b}, self.token)
            self.assertTrue(ra["ok"] and rb["ok"])
            self.assertNotEqual(ra["archivo"], rb["archivo"])
            guardados = sorted(p.name for p in Path(carpeta).glob("*.txt"))
            self.assertEqual(len(guardados), 2, guardados)

            texto_a = (Path(carpeta) / ra["archivo"]).read_text(encoding="utf-8")
            texto_b = (Path(carpeta) / rb["archivo"]).read_text(encoding="utf-8")
            self.assertIn("Palestino", texto_a)
            self.assertNotIn("Boca", texto_a)
            self.assertIn("Boca", texto_b)
            self.assertNotIn("Palestino", texto_b)


class TestElNombreDelVolcado(unittest.TestCase):
    """El nombre lleva la hora al segundo: dos personas pueden apretar Guardar
    en el mismo segundo y el segundo volcado no puede pisar al primero."""

    def test_el_segundo_del_mismo_segundo_lleva_sufijo(self):
        with tempfile.TemporaryDirectory() as carpeta:
            with mock.patch.object(av, "CARPETA_DATOS", Path(carpeta)):
                nombres = []
                for _ in range(3):
                    ruta = av.nombre_de_volcado_libre()
                    ruta.write_text("x", encoding="utf-8")
                    nombres.append(ruta.name)
        base = nombres[0][:-len(".txt")]
        self.assertEqual(nombres, [f"{base}.txt", f"{base}_2.txt", f"{base}_3.txt"])

    def test_el_listado_sigue_sacando_la_fecha_y_la_hora(self):
        import archivo_partidos as arch

        self.assertEqual(arch._fecha_y_hora("partido_20260916_101010_2.txt"),
                         ("2026-09-16", "10:10"))


if __name__ == "__main__":
    unittest.main()
