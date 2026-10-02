"""
Tests de los partidos guardados en privado.

Se corren con:
    python -m unittest test_privados

Guardar el .txt PUBLICA el partido: queda en Datos, sale en la pestana
Partidos y entra en las estadisticas de todos. Guardar en privado sube las
mismas lineas a otro lado, para poder cortar a mitad de partido, apagar la
maquina y seguir despues.

Lo que cuidan estos tests es lo que hace que eso sirva de algo:

  - que un partido guardado se pueda volver a abrir tal cual quedo;
  - que guardar dos veces el MISMO partido lo actualice en vez de dejar dos,
    y que guardar OTRO no pise al anterior;
  - que nada de esto aparezca en Datos, que es lo que lo hace privado;
  - y que una falla de red al leer no borre lo que ya habia guardado, que es
    la unica forma de perder un partido que este boton podria causar.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import almacenamiento as alm
import lambda_handler as lh
import sesion_web
import servidor_voley as srv
from test_lambda_handler import evento


# Un partido a medio cargar: dos equipos, la rotacion del local, quien saca y
# unos puntos. Es lo que hay en la pantalla cuando alguien tiene que cortar.
SETUP = ["Palestino", "UVC", "28_S 5 13 88 3 40", "", "B"]
PUNTOS = ["9_1_5_X/3_3/28_4/13_1_P", "1_5_A", "1_5_E"]


def sesion_con(lineas):
    sesion = sesion_web.SesionPartido()
    for linea in lineas:
        sesion.enviar(linea)
    return sesion


class BasePrivados(unittest.TestCase):

    def setUp(self):
        # carpeta temporal: nada toca los partidos de verdad
        self.carpeta = Path(tempfile.mkdtemp())
        for objeto, nombre, valor in ((alm, "CARPETA_ESCRITURA", self.carpeta),
                                      (alm, "_ES_LOCAL", False)):
            parche = mock.patch.object(objeto, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)

    def archivo(self) -> Path:
        return self.carpeta / "privados" / "partidos.json"

    def guardado(self) -> dict:
        return json.loads(self.archivo().read_text("utf-8"))


class TestGuardarYVolverAAbrir(BasePrivados):

    def test_se_guarda_y_se_vuelve_a_abrir_igual(self):
        lineas = SETUP + PUNTOS
        alm.guardar_privado("p1", "Palestino vs UVC", lineas, {})
        self.assertEqual(alm.leer_privado("p1")["lineas"], lineas)

    def test_el_partido_que_vuelve_esta_donde_habia_quedado(self):
        """Lo que importa no es que las lineas vuelvan sino que el partido
        vuelva: mismo marcador, mismo set, misma rotacion."""
        antes = sesion_con(SETUP + PUNTOS)
        alm.guardar_privado("p1", "Palestino vs UVC", antes.lineas, {})

        despues = sesion_web.SesionPartido()
        srv.abrir_privado(despues, "p1")
        self.assertEqual(despues.instantanea()["marcador"],
                         antes.instantanea()["marcador"])
        self.assertEqual(despues.instantanea()["rotaciones"],
                         antes.instantanea()["rotaciones"])

    def test_abrir_uno_que_no_esta_no_toca_el_partido_cargado(self):
        sesion = sesion_con(SETUP + PUNTOS)
        r = srv.abrir_privado(sesion, "no-existe")
        self.assertFalse(r["ok"])
        self.assertEqual(sesion.lineas, SETUP + PUNTOS)

    def test_no_se_guarda_un_partido_vacio(self):
        r = srv.guardar_en_privado(sesion_web.SesionPartido(), "p1", "")
        self.assertFalse(r["ok"])
        self.assertFalse(self.archivo().exists())


class TestNoSePisanEntreSi(BasePrivados):

    def test_guardar_dos_veces_el_mismo_partido_lo_actualiza(self):
        sesion = sesion_con(SETUP + PUNTOS)
        srv.guardar_en_privado(sesion, "p1", "")
        sesion.enviar("9_1_5_X/3_0/88_4/13_1_O")
        srv.guardar_en_privado(sesion, "p1", "")

        self.assertEqual(len(alm.listar_privados()), 1)
        self.assertEqual(alm.leer_privado("p1")["lineas"], sesion.lineas)

    def test_otro_partido_no_pisa_al_anterior(self):
        """Dos partidos contra el mismo rival el mismo dia se llaman igual.
        Por eso el que manda es el id que pone la pantalla y no el nombre: si
        mandara el nombre, el segundo se comeria al primero."""
        primero = sesion_con(SETUP + PUNTOS)
        srv.guardar_en_privado(primero, "p1", "")
        segundo = sesion_con(SETUP + PUNTOS[:1])
        srv.guardar_en_privado(segundo, "p2", "")

        guardados = alm.listar_privados()
        self.assertEqual(len(guardados), 2)
        self.assertEqual({g["nombre"] for g in guardados}, {"Palestino vs UVC"})
        self.assertEqual(alm.leer_privado("p1")["lineas"], primero.lineas)
        self.assertEqual(alm.leer_privado("p2")["lineas"], segundo.lineas)

    def test_sin_id_no_se_guarda(self):
        with self.assertRaises(ValueError):
            alm.guardar_privado("", "Palestino vs UVC", SETUP, {})

    def test_hay_un_tope(self):
        """Van todos en un unico JSON que se lee entero cada vez. Pasado el
        tope se avisa en vez de seguir agrandandolo, y lo guardado sigue
        estando: se borra uno y se guarda."""
        for numero in range(alm.MAXIMO_PRIVADOS):
            alm.guardar_privado(f"p{numero}", "Partido", SETUP, {})
        with self.assertRaises(ValueError):
            alm.guardar_privado("uno-mas", "Partido", SETUP, {})
        # el que no entro no se llevo puesto a ninguno de los que si estaban
        self.assertEqual(len(alm.listar_privados()), alm.MAXIMO_PRIVADOS)

    def test_borrar_saca_solo_ese(self):
        alm.guardar_privado("p1", "Uno", SETUP, {})
        alm.guardar_privado("p2", "Otro", SETUP, {})
        self.assertTrue(alm.borrar_privado("p1"))
        self.assertEqual([g["id"] for g in alm.listar_privados()], ["p2"])

    def test_borrar_uno_que_no_esta_avisa(self):
        self.assertFalse(alm.borrar_privado("p1"))
        self.assertFalse(srv.olvidar_privado("p1")["ok"])


class TestLaLista(BasePrivados):

    def test_dice_como_iba_el_partido(self):
        """La lista tiene que dejar reconocer cual de dos partidos empezados
        es el que se estaba cargando, sin abrirlos."""
        sesion = sesion_con(SETUP + PUNTOS)
        srv.guardar_en_privado(sesion, "p1", "")
        resumen = alm.listar_privados()[0]["resumen"]
        self.assertEqual(resumen["A"], "Palestino")
        self.assertEqual(resumen["B"], "UVC")
        self.assertEqual(resumen["marcador"], "2 - 1")
        self.assertEqual(resumen["set"], 1)
        self.assertEqual(resumen["puntos"], 3)

    def test_no_arrastra_las_lineas_de_cada_partido(self):
        """Son la mayor parte del archivo y la lista no las usa: se bajan
        recien cuando se abre uno."""
        alm.guardar_privado("p1", "Uno", SETUP + PUNTOS, {})
        fila = alm.listar_privados()[0]
        self.assertEqual(fila["lineas"], len(SETUP + PUNTOS))   # el numero, no la lista
        self.assertNotIn("28_S 5 13 88 3 40", json.dumps(fila))

    def test_el_ultimo_guardado_va_primero(self):
        alm.guardar_privado("viejo", "Viejo", SETUP, {})
        alm.guardar_privado("nuevo", "Nuevo", SETUP, {})
        self.assertEqual([g["id"] for g in alm.listar_privados()], ["nuevo", "viejo"])


class TestEsPrivado(BasePrivados):

    def test_no_escribe_nada_en_datos(self):
        """Lo que lo hace privado: no esta en Datos, asi que no lo ve la
        pestana Partidos ni entra en las estadisticas de nadie."""
        srv.guardar_en_privado(sesion_con(SETUP + PUNTOS), "p1", "")
        self.assertTrue(self.archivo().exists())
        self.assertFalse((self.carpeta / alm.DATOS).exists())

    def test_las_cuatro_rutas_piden_la_contraseña(self):
        """Tambien para LEER, que es lo unico que las hace privadas: sin clave
        no se puede ni saber que existen."""
        for ruta in ("/api/privados", "/api/privado/guardar",
                     "/api/privado/abrir", "/api/privado/borrar"):
            self.assertIn(ruta, srv.RUTAS_CON_CLAVE)


class TestPorLaRutaDeVerdad(BasePrivados):
    """Los mismos pedidos que hace la pantalla, por el manejador entero.

    Aca no se llaman las funciones sueltas: entra un pedido HTTP y sale una
    respuesta, que es lo unico que prueba que la ruta existe, que pide la
    contraseña y que la pantalla va a poder usarla."""

    def setUp(self):
        super().setUp()
        for objeto, nombre, valor in ((srv.av, "CARPETA_DATOS", self.carpeta / "Datos"),
                                      (srv.av, "CONTRASENA_CARGA", "test123")):
            parche = mock.patch.object(objeto, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)
        # la sesion compartida es de modulo: si no se vacia, un test arrastra
        # al otro
        srv.sesion.reemplazar([])
        self.addCleanup(srv.sesion.reemplazar, [])

    def pedir(self, metodo, ruta, cuerpo=None, token=None):
        respuesta = lh.handler(evento(metodo, ruta, cuerpo=cuerpo, token=token))
        return respuesta["statusCode"], json.loads(respuesta["body"])

    def entrar(self):
        return self.pedir("POST", "/api/clave", {"clave": "test123"})[1]["token"]

    def test_sin_contraseña_no_se_puede_ni_saber_que_hay(self):
        codigo, _ = self.pedir("POST", "/api/privados", {})
        self.assertEqual(codigo, 401)

    def test_por_get_no_contesta(self):
        """do_GET no mira RUTAS_CON_CLAVE, asi que todo lo que contesta por
        GET contesta sin contraseña. Por eso la lista va por POST: si algun
        dia se agrega aca, deja de ser privada."""
        self.assertEqual(self.pedir("GET", "/api/privados")[0], 404)

    def test_guardar_seguir_y_borrar(self):
        token = self.entrar()
        lineas = SETUP + PUNTOS

        codigo, r = self.pedir("POST", "/api/privado/guardar",
                               {"lineas": lineas, "id": "p1"}, token)
        self.assertEqual(codigo, 200)
        self.assertTrue(r["ok"], r["mensaje"])

        # otra pantalla, que no tiene nada cargado: pide la lista y sigue
        codigo, r = self.pedir("POST", "/api/privados", {}, token)
        self.assertEqual([g["id"] for g in r["privados"]], ["p1"])

        codigo, r = self.pedir("POST", "/api/privado/abrir",
                               {"lineas": [], "id": "p1"}, token)
        self.assertTrue(r["ok"], r["mensaje"])
        self.assertEqual(r["estado"]["lineas"], lineas)

        codigo, r = self.pedir("POST", "/api/privado/borrar", {"id": "p1"}, token)
        self.assertTrue(r["ok"], r["mensaje"])
        self.assertEqual(r["privados"], [])

    def test_guardar_en_privado_no_publica_el_partido(self):
        """Lo que lo separa de "Guardar .txt": la pestana Partidos queda
        exactamente como estaba."""
        token = self.entrar()
        antes = self.pedir("GET", "/api/partidos")[1]["partidos"]
        self.pedir("POST", "/api/privado/guardar",
                   {"lineas": SETUP + PUNTOS, "id": "p1"}, token)
        self.assertEqual(self.pedir("GET", "/api/partidos")[1]["partidos"], antes)


class TestNoPierdeLoGuardado(BasePrivados):
    """La unica forma de perder un partido que este boton podria causar.

    Con almacenamiento remoto, guardar es leer la lista entera, agregarle uno
    y volver a subirla. Si la lectura falla y se sigue igual, lo que se sube
    es una lista sin los partidos de los demas: guardar el propio borraria los
    otros. Por eso el que va a escribir lee en modo estricto."""

    def entorno(self, leer):
        for nombre, valor in (("hay_blob", lambda: True), ("_blob_puntual", leer)):
            parche = mock.patch.object(alm, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)
        self.subidas = []
        parche = mock.patch.object(
            alm, "subir_blob",
            lambda ruta, crudo, tipo: self.subidas.append(json.loads(crudo)))
        parche.start()
        self.addCleanup(parche.stop)

    def test_si_no_se_puede_leer_no_se_sube_nada(self):
        def explota(*args, **kwargs):
            raise alm.ErrorDeBlob("no se pudo leer")
        self.entorno(explota)

        with self.assertRaises(alm.ErrorDeBlob):
            alm.guardar_privado("p1", "Uno", SETUP, {})
        self.assertEqual(self.subidas, [])

    def test_y_la_pantalla_lo_dice_en_vez_de_contestar_que_guardo(self):
        def explota(*args, **kwargs):
            raise alm.ErrorDeBlob("no se pudo leer")
        self.entorno(explota)

        r = srv.guardar_en_privado(sesion_con(SETUP + PUNTOS), "p1", "")
        self.assertFalse(r["ok"])
        self.assertIn("no se pudo", r["mensaje"].lower())

    def test_guardar_conserva_los_que_ya_estaban(self):
        previos = {"otro": {"nombre": "De otro", "lineas": ["Local", "Rival"],
                            "resumen": {}, "guardado": 1.0}}
        self.entorno(lambda *a, **k: {"pathname": alm.RUTA_PRIVADOS})
        parche = mock.patch.object(alm, "_bajar_json", lambda blob, **k: previos)
        parche.start()
        self.addCleanup(parche.stop)

        alm.guardar_privado("p1", "Uno", SETUP, {})
        self.assertEqual(sorted(self.subidas[-1]), ["otro", "p1"])


if __name__ == "__main__":
    unittest.main()
