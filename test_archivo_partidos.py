"""
Tests para archivo_partidos.py y para los endpoints de solo lectura del
servidor.

Se corren con:
    python -m unittest test_archivo_partidos.py -v
"""

import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import almacenamiento as alm
import archivo_partidos as ap


_token_de_verdad = alm.token_blob


def setUpModule():
    """Ningun test de este archivo habla con el Blob.

    Sin esto, el que corre las pruebas con BLOB_READ_WRITE_TOKEN en el entorno
    (que es lo normal si ademas despliega esto) los hace salir a la red: el
    listado sincroniza antes de listar, y los tests pasarian de dos segundos a
    veinte, o borrarian del store de verdad."""
    alm.token_blob = lambda: ""


def tearDownModule():
    alm.token_blob = _token_de_verdad


# El volcado mas corto que igual tiene todo lo que mira el listado: nombres,
# sets, parciales, cambios, rotaciones y el corte de las estadisticas.
VOLCADO = """=== Jugadas cargadas ===
Palestino
UVC
28 15 99_S 88 10 13

B
1_1_1_X/28_0/88_1_X/13_F_3

=== Rotaciones (zonas 1 a 6, S = armador) ===
Set 1:
  Palestino: 28 / 15 / 99-S / 88 / 10 / 13
  UVC: 1 / 2 / 3-S / 4 / 5 / 6
Set 2:
  Palestino: 3-S / 88 / 9 / 13 / 40 / 15

=== Cambios ===
Set 1 - Palestino: entra 40, sale 28 (zona 6)
Set 2 - Palestino: entra 3, sale 99 (zona 6) (queda como armador)

=== Resultado final ===
Sets: Palestino 2 - 1 UVC
  Set 1: Palestino 25 - 18 UVC
  Set 2: Palestino 22 - 25 UVC
  Set 3: Palestino 25 - 20 UVC
  Set 4: Palestino 0 - 0 UVC
Marcador del set actual: Palestino 0 - 0 UVC
Total de puntos cargados: 95

=== Estadisticas por equipo ===
--- Palestino ---
Puntos por fase del rally:
  Hechos: 52
      K1: 18 (34.6%) - ganados 14, por error 4
"""

VOLCADO_UN_SET = """=== Jugadas cargadas ===
Local
Visita

=== Resultado final ===
Marcador final: Local 25 - 21 Visita
Total de puntos cargados: 46

=== Estadisticas por equipo ===
--- Local ---
"""


def escribir(carpeta: Path, nombre: str, texto: str = VOLCADO) -> Path:
    ruta = carpeta / nombre
    ruta.write_text(texto, encoding="utf-8")
    return ruta


class TestResumenVolcado(unittest.TestCase):

    def test_nombres_sets_y_puntos(self):
        resumen = ap.resumen_volcado(VOLCADO)
        self.assertEqual(resumen["equipo"], "Palestino")
        self.assertEqual(resumen["rival"], "UVC")
        self.assertEqual(resumen["sets"], "2-1")
        self.assertEqual(resumen["puntos"], 95)

    def test_el_set_sin_jugar_no_es_un_parcial(self):
        # el "Set 4: 0 - 0" es el marcador del set en curso al guardar
        self.assertEqual(ap.resumen_volcado(VOLCADO)["parciales"],
                         ["25-18", "22-25", "25-20"])

    def test_un_solo_set_no_tiene_linea_de_sets(self):
        resumen = ap.resumen_volcado(VOLCADO_UN_SET)
        self.assertEqual((resumen["equipo"], resumen["rival"]), ("Local", "Visita"))
        self.assertEqual(resumen["parciales"], ["25-21"])
        self.assertEqual(resumen["sets"], "1-0")

    def test_volcado_sin_resultado(self):
        resumen = ap.resumen_volcado("=== Jugadas cargadas ===\nPalestino\nUVC\n")
        self.assertIsNone(resumen["equipo"])
        self.assertIsNone(resumen["sets"])
        self.assertEqual(resumen["parciales"], [])

    def test_la_cabecera_corta_antes_de_las_estadisticas(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = escribir(Path(tmp), "partido_20260908_141643.txt")
            cabecera = ap.cabecera_volcado(ruta)
        self.assertIn("Total de puntos cargados: 95", cabecera)
        self.assertNotIn("Puntos por fase del rally", cabecera)


class TestSeccionesDeCancha(unittest.TestCase):

    def test_rotaciones_por_set(self):
        rotaciones = ap.secciones_de_cancha(VOLCADO)["rotaciones"]
        self.assertEqual([r["set"] for r in rotaciones], [1, 2])
        primero = rotaciones[0]["equipos"][0]
        self.assertEqual(primero["equipo"], "Palestino")
        self.assertEqual(primero["jugadores"], ["28", "15", "99", "88", "10", "13"])
        self.assertEqual(primero["armador"], "99")
        self.assertEqual(len(rotaciones[0]["equipos"]), 2)

    def test_cambios(self):
        cambios = ap.secciones_de_cancha(VOLCADO)["cambios"]
        self.assertEqual(len(cambios), 2)
        self.assertEqual(cambios[0], {"set": 1, "equipo": "Palestino", "entra": "40",
                                      "sale": "28", "zona": "6", "detalle": ""})
        self.assertEqual(cambios[1]["detalle"], "queda como armador")

    def test_sin_esas_secciones(self):
        vacias = ap.secciones_de_cancha(VOLCADO_UN_SET)
        self.assertEqual(vacias, {"rotaciones": [], "cambios": []})


class TestListarPartidos(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.datos = Path(self.tmp.name) / "Datos"
        self.informes = Path(self.tmp.name) / "Informes"
        self.datos.mkdir()
        self.informes.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def listar(self):
        return ap.listar_partidos(self.datos, self.informes)

    def test_una_fila_por_volcado_y_la_mas_nueva_arriba(self):
        escribir(self.datos, "partido_20260903_180710.txt")
        escribir(self.datos, "partido_20260908_141643.txt")
        filas = self.listar()
        self.assertEqual([f["fecha"] for f in filas], ["2026-09-08", "2026-09-03"])
        self.assertEqual(filas[0]["hora"], "14:16")
        self.assertEqual(filas[0]["equipo"], "Palestino")
        self.assertEqual(filas[0]["rival"], "UVC")
        self.assertEqual(filas[0]["sets"], "2-1")
        self.assertEqual(filas[0]["puntos"], 95)
        self.assertTrue(all(f["informe"] is None for f in filas))

    def test_el_informe_se_pega_al_volcado_del_mismo_partido(self):
        escribir(self.datos, "partido_20260908_141643.txt")
        (self.informes / "Informe_Palestino_vs_UVC_2026-09-08.xlsx").write_bytes(b"x")
        filas = self.listar()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["informe"], "Informe_Palestino_vs_UVC_2026-09-08.xlsx")
        self.assertEqual(filas[0]["volcado"], "partido_20260908_141643.txt")

    def test_el_informe_se_pega_aunque_este_hecho_del_otro_lado(self):
        # Informe_<rival>_vs_<equipo> es el mismo partido visto desde el otro
        # banco, no un partido nuevo
        escribir(self.datos, "partido_20260908_141643.txt")
        (self.informes / "Informe_UVC_vs_Palestino_2026-09-08.xlsx").write_bytes(b"x")
        filas = self.listar()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["informe"], "Informe_UVC_vs_Palestino_2026-09-08.xlsx")

    def test_un_informe_sin_volcado_igual_aparece(self):
        (self.informes / "Informe_Palestino_vs_O'sommer_2026-09-08.xlsx").write_bytes(b"x")
        filas = self.listar()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["equipo"], "Palestino")
        self.assertEqual(filas[0]["rival"], "O'sommer")
        self.assertIsNone(filas[0]["volcado"])
        self.assertEqual(filas[0]["id"], "Informe_Palestino_vs_O'sommer_2026-09-08.xlsx")

    def test_los_temporales_de_excel_no_son_informes(self):
        escribir(self.datos, "partido_20260908_141643.txt")
        (self.informes / "~$Informe_Palestino_vs_UVC_2026-09-08.xlsx").write_bytes(b"x")
        filas = self.listar()
        self.assertEqual(len(filas), 1)
        self.assertIsNone(filas[0]["informe"])

    def test_el_sin_formulas_no_duplica_la_fila(self):
        escribir(self.datos, "partido_20260908_141643.txt")
        (self.informes / "Informe_Palestino_vs_UVC_2026-09-08.xlsx").write_bytes(b"x")
        (self.informes / "Informe_Palestino_vs_UVC_2026-09-08_sin_formulas.xlsx").write_bytes(b"x")
        filas = self.listar()
        self.assertEqual(len(filas), 1)
        self.assertEqual(filas[0]["informe"], "Informe_Palestino_vs_UVC_2026-09-08.xlsx")

    def test_los_xlsx_que_no_son_informes_se_ignoran(self):
        (self.informes / "planilla_del_club.xlsx").write_bytes(b"x")
        self.assertEqual(self.listar(), [])

    def test_carpetas_que_no_existen(self):
        self.assertEqual(ap.listar_partidos(Path(self.tmp.name) / "no_esta",
                                            Path(self.tmp.name) / "tampoco"), [])

    def test_el_cache_se_da_cuenta_de_que_el_archivo_cambio(self):
        ruta = escribir(self.datos, "partido_20260908_141643.txt")
        self.assertEqual(self.listar()[0]["puntos"], 95)

        ruta.write_text(VOLCADO.replace("Total de puntos cargados: 95",
                                        "Total de puntos cargados: 96"), encoding="utf-8")
        # el mtime se adelanta a mano: en Windows dos escrituras seguidas
        # pueden quedar con la misma marca de tiempo y el cache no se enteraria
        marca = os.stat(ruta).st_mtime + 10
        os.utime(ruta, (marca, marca))
        self.assertEqual(self.listar()[0]["puntos"], 96)


class TestRutasSeguras(unittest.TestCase):
    """El servidor escucha en toda la WiFi: lo unico que se abre es lo que
    esta en Datos/ o en Informes/."""

    def test_se_rechaza_salir_de_la_carpeta(self):
        for nombre in ["../../algo", "..\\..\\algo", "../servidor_voley.py",
                       "Datos/../../secreto.txt", "partido.txt/../../x.txt"]:
            with self.subTest(nombre=nombre):
                with self.assertRaises(ap.RutaInvalida):
                    ap.ruta_segura(nombre, [ap.CARPETA_DATOS])

    def test_se_rechaza_una_ruta_absoluta_de_afuera(self):
        with self.assertRaises(ap.RutaInvalida):
            ap.ruta_segura(str(Path(__file__).resolve()), [ap.CARPETA_DATOS])

    def test_se_rechaza_el_nombre_vacio(self):
        for nombre in ["", "   ", None]:
            with self.subTest(nombre=nombre):
                with self.assertRaises(ap.RutaInvalida):
                    ap.ruta_segura(nombre, [ap.CARPETA_DATOS])

    def test_un_nombre_de_la_carpeta_se_acepta(self):
        ruta = ap.ruta_segura("partido_20260908_141643.txt", [ap.CARPETA_DATOS])
        self.assertEqual(ruta.parent, Path(ap.CARPETA_DATOS).resolve())

    def test_una_ruta_absoluta_de_adentro_se_acepta(self):
        # es la que devuelve /api/excel, y el cliente la manda de vuelta
        adentro = Path(ap.CARPETA_INFORMES) / "Informe_A_vs_B_2026-09-08.xlsx"
        self.assertEqual(ap.ruta_segura(str(adentro), [ap.CARPETA_INFORMES]),
                         adentro.resolve())

    def test_el_tipo_manda_la_carpeta(self):
        ruta, tipo = ap.ruta_de_tipo("partido_20260908_141643.txt", "txt")
        self.assertEqual((ruta.parent, tipo), (Path(ap.CARPETA_DATOS).resolve(), "txt"))
        ruta, tipo = ap.ruta_de_tipo("Informe_A_vs_B_2026-09-08.xlsx", "xlsx")
        self.assertEqual((ruta.parent, tipo), (Path(ap.CARPETA_INFORMES).resolve(), "xlsx"))

    def test_el_tipo_se_deduce_de_la_extension(self):
        self.assertEqual(ap.ruta_de_tipo("partido_1.txt")[1], "txt")
        self.assertEqual(ap.ruta_de_tipo("Informe_A_vs_B_2026-01-01.xlsx")[1], "xlsx")

    def test_la_extension_tiene_que_coincidir_con_el_tipo(self):
        for nombre, tipo in [("partido_1.txt", "xlsx"), ("informe.xlsx", "txt"),
                             ("cualquiera.exe", None), ("script.py", "txt")]:
            with self.subTest(nombre=nombre, tipo=tipo):
                with self.assertRaises(ap.RutaInvalida):
                    ap.ruta_de_tipo(nombre, tipo)

    def test_no_se_sirve_un_temporal_de_excel(self):
        with self.assertRaises(ap.RutaInvalida):
            ap.ruta_de_tipo("~$Informe_A_vs_B_2026-09-08.xlsx", "xlsx")

    def test_es_temporal(self):
        self.assertTrue(ap.es_temporal("~$Informe_A_vs_B.xlsx"))
        self.assertFalse(ap.es_temporal("Informe_A_vs_B.xlsx"))


class TestLeerPartido(unittest.TestCase):

    def test_el_volcado_entero_ya_parseado(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = escribir(Path(tmp), "partido_20260908_141643.txt")
            partido = ap.leer_partido(ruta)

        self.assertEqual(partido["equipo"], "Palestino")
        self.assertEqual(partido["rival"], "UVC")
        self.assertEqual(partido["sets"], "2-1")
        self.assertEqual(partido["fecha"], "2026-09-08")
        self.assertEqual(partido["orden_equipos"], ["Palestino"])   # el unico bloque
        self.assertEqual(len(partido["rotaciones"]), 2)
        self.assertEqual(len(partido["cambios"]), 2)
        # las estadisticas salen del parser de generar_informe_volley
        self.assertEqual(partido["equipos"]["Palestino"]["fases"]["hechos"]["K1"],
                         {"total": 18, "ganados": 14, "error": 4})

    def test_se_puede_pasar_a_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            ruta = escribir(Path(tmp), "partido_20260908_141643.txt")
            texto = json.dumps(ap.leer_partido(ruta), ensure_ascii=False)
        self.assertIn("Palestino", texto)


@unittest.skipUnless(ap.HAY_OPENPYXL, "el informe .xlsx necesita openpyxl")
class TestLeerInforme(unittest.TestCase):
    """Un .xlsx recien escrito por openpyxl no tiene los resultados de las
    formulas: los calcula Excel al abrirlo. Como el informe se mira desde la
    web sin pasar por Excel, hay que evaluarlas."""

    def setUp(self):
        import generar_informe_volley as gi
        import openpyxl

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ruta = Path(self.tmp.name) / "Informe_A_vs_B_2026-09-08.xlsx"

        # se arma con los mismos helpers que el informe de verdad, para que el
        # test se rompa si cambian los colores con los que se pinta cada fila
        libro = openpyxl.Workbook()
        libro.remove(libro.active)
        hoja = gi.new_sheet(libro, "Recepcion")
        fila = gi.set_title(hoja, 1, 1, 3, "RECEPCION - A")
        fila = gi.set_subtitle(hoja, fila, 1, 3, "Recepciones por jugador")
        fila = gi.set_headers(hoja, fila, 1, ["Jugador", "Recepciones", "% del total"])
        primera = fila
        fila = gi.set_data_row(hoja, fila, 1, ["Jugador 28", 11, "=B5/$B$7"],
                               formats=[None, None, "0.0%"])
        fila = gi.set_data_row(hoja, fila, 1, ["Jugador 88", 25, "=B6/$B$7"],
                               formats=[None, None, "0.0%"])
        fila = gi.set_data_row(hoja, fila, 1,
                               ["TOTAL", f"=SUM(B{primera}:B{fila - 1})", "=B7/$B$7"],
                               formats=[None, None, "0.0%"], total=True)
        gi.set_footnote(hoja, fila, 1, 3, "Nota: los porcentajes son sobre el total.")
        libro.save(self.ruta)

    def test_las_formulas_se_ven_como_numeros(self):
        import openpyxl

        # el archivo no paso por Excel: leido asi, las formulas vienen vacias
        crudo = openpyxl.load_workbook(self.ruta, data_only=True)
        self.assertIsNone(crudo["Recepcion"]["B7"].value)

        hoja = ap.leer_informe(self.ruta)["hojas"][0]
        filas = {f["celdas"][0]: f for f in hoja["filas"] if f["celdas"]}
        self.assertEqual(filas["TOTAL"]["celdas"][1], "36")
        self.assertEqual(filas["Jugador 28"]["celdas"][2], "30.6%")
        self.assertEqual(filas["Jugador 88"]["celdas"][2], "69.4%")

    def test_cada_fila_dice_de_que_tipo_es(self):
        hoja = ap.leer_informe(self.ruta)["hojas"][0]
        tipos = [f["tipo"] for f in hoja["filas"]]
        self.assertEqual(tipos[:4], ["titulo", "vacia", "subtitulo", "encabezado"])
        self.assertIn("total", tipos)
        self.assertEqual(tipos[-1], "nota")
        self.assertEqual(hoja["nombre"], "Recepcion")
        self.assertEqual(hoja["columnas"], 3)

    def test_los_valores_que_cacheo_excel_se_respetan(self):
        # si el archivo ya tiene los resultados guardados se usan esos, sin
        # volver a evaluar nada
        import openpyxl

        libro = openpyxl.load_workbook(self.ruta)
        import valores_excel
        valores_excel.convertir_a_valores(libro)
        libro.save(self.ruta)

        hoja = ap.leer_informe(self.ruta)["hojas"][0]
        filas = {f["celdas"][0]: f for f in hoja["filas"] if f["celdas"]}
        self.assertEqual(filas["TOTAL"]["celdas"][1], "36")

    def test_una_formula_que_no_se_entiende_queda_a_la_vista(self):
        # antes que un cero inventado, la formula: se ve que no es un numero
        import openpyxl

        libro = openpyxl.load_workbook(self.ruta)
        libro["Recepcion"]["C5"] = "=VLOOKUP(A5,Z1:Z9,2,FALSE)"
        libro.save(self.ruta)

        informe = ap.leer_informe(self.ruta)
        filas = {f["celdas"][0]: f for f in informe["hojas"][0]["filas"] if f["celdas"]}
        self.assertTrue(filas["Jugador 28"]["celdas"][2].startswith("=VLOOKUP"))
        self.assertTrue(informe["avisos"])

    def test_no_existe(self):
        with self.assertRaises(FileNotFoundError):
            ap.leer_informe(Path(self.tmp.name) / "Informe_no_esta.xlsx")


class TestBorrar(unittest.TestCase):
    """Borrar un partido. Lo que hay que asegurar es que borrar de verdad
    borre, y que lo borrado deje de verse aunque el archivo siga en el disco
    (los que vienen en el deploy no se pueden borrar, solo ocultar)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.carpeta = Path(self.tmp.name)

    def _fingir_borrados(self, *nombres):
        """Hace como si esos "<carpeta>/<nombre>" estuvieran en la lista de
        borrados, sin necesitar un Blob de verdad."""
        borrados = set(nombres)
        original = alm.esta_borrado
        alm.esta_borrado = lambda logica, nombre: f"{logica}/{nombre}" in borrados
        self.addCleanup(setattr, alm, "esta_borrado", original)

    def test_un_borrado_no_aparece_en_el_listado(self):
        escribir(self.carpeta, "partido_20260908_141643.txt")
        escribir(self.carpeta, "partido_20260903_180710.txt")
        self._fingir_borrados("Datos/partido_20260908_141643.txt")

        nombres = [r.name for r in ap.archivos_de([self.carpeta], "*.txt", alm.DATOS)]
        self.assertEqual(nombres, ["partido_20260903_180710.txt"])

    def test_sin_carpeta_logica_no_se_filtra_nada(self):
        # es el caso de los tests y de quien pasa una carpeta suya: los
        # borrados del proyecto no tienen nada que ver con esos archivos
        escribir(self.carpeta, "partido_20260908_141643.txt")
        self._fingir_borrados("Datos/partido_20260908_141643.txt")
        self.assertEqual(len(ap.archivos_de([self.carpeta], "*.txt")), 1)

    def test_un_borrado_no_se_puede_leer_ni_descargar(self):
        # aunque el archivo siga estando, que es lo que pasa con los que
        # vienen en el deploy
        nombre = "partido_20260908_141643.txt"
        self._fingir_borrados(f"Datos/{nombre}")
        with self.assertRaises(FileNotFoundError):
            ap.ruta_de_tipo(nombre, "txt")

    def _carpeta_de_escritura_temporal(self) -> Path:
        carpeta_datos = self.carpeta / "Datos"
        carpeta_datos.mkdir(exist_ok=True)
        original = alm.CARPETA_ESCRITURA
        alm.CARPETA_ESCRITURA = self.carpeta
        self.addCleanup(setattr, alm, "CARPETA_ESCRITURA", original)
        return carpeta_datos

    def test_borrar_saca_el_archivo_del_disco(self):
        # un nombre que no exista ademas en la carpeta del proyecto, que es la
        # semilla: si estuviera en las dos, esto probaria el otro caso
        nombre = "partido_20261115_200000.txt"
        carpeta_datos = self._carpeta_de_escritura_temporal()
        escribir(carpeta_datos, nombre)

        pudo, mensaje = alm.borrar(alm.DATOS, nombre)
        self.assertTrue(pudo, mensaje)
        self.assertFalse((carpeta_datos / nombre).exists())

    def test_uno_que_viene_en_el_deploy_no_se_puede_borrar_sin_blob(self):
        """El archivo esta en la carpeta del proyecto, que alojado es de solo
        lectura. Se puede ocultar, pero eso necesita el Blob; sin el, lo
        honesto es decir que no se pudo y no que si."""
        nombre = "partido_20260908_141643.txt"      # este si esta en Datos/
        self.assertTrue((alm.carpeta_semilla(alm.DATOS) / nombre).exists())
        self._carpeta_de_escritura_temporal()

        pudo, mensaje = alm.borrar(alm.DATOS, nombre)
        self.assertFalse(pudo)
        self.assertIn("Blob", mensaje)

    def test_borrar_lo_que_no_esta_avisa_y_no_rompe(self):
        original = alm.CARPETA_ESCRITURA
        alm.CARPETA_ESCRITURA = self.carpeta
        self.addCleanup(setattr, alm, "CARPETA_ESCRITURA", original)
        pudo, mensaje = alm.borrar(alm.DATOS, "partido_20990101_000000.txt")
        self.assertFalse(pudo)
        self.assertIn("No existe", mensaje)


class TestEndpointsDeLectura(unittest.TestCase):
    """El servidor de verdad, contestando en un puerto suelto. Son endpoints
    de solo lectura: no tocan la sesion en curso."""

    @classmethod
    def setUpClass(cls):
        import servidor_voley as sv

        cls.sv = sv
        cls.servidor = ThreadingHTTPServer(("127.0.0.1", 0), sv.Manejador)
        cls.base = f"http://127.0.0.1:{cls.servidor.server_address[1]}"
        cls.hilo = threading.Thread(target=cls.servidor.serve_forever, daemon=True)
        cls.hilo.start()

    @classmethod
    def tearDownClass(cls):
        cls.servidor.shutdown()
        cls.servidor.server_close()
        cls.hilo.join(timeout=5)

    def pedir(self, ruta):
        with urllib.request.urlopen(self.base + ruta, timeout=10) as r:
            return r.status, r.read(), r.headers

    def pedir_json(self, ruta):
        codigo, cuerpo, _ = self.pedir(ruta)
        return codigo, json.loads(cuerpo.decode("utf-8"))

    def test_la_pagina_y_sus_dos_archivos(self):
        for ruta, esperado in [("/", "text/html"), ("/interfaz.css", "text/css"),
                               ("/interfaz.js", "application/javascript")]:
            with self.subTest(ruta=ruta):
                codigo, cuerpo, cabeceras = self.pedir(ruta)
                self.assertEqual(codigo, 200)
                self.assertIn(esperado, cabeceras["Content-Type"])
                self.assertTrue(cuerpo)

    def test_no_se_sirve_nada_mas_de_la_carpeta(self):
        for ruta in ["/servidor_voley.py", "/analisis_voley.py", "/interfaz.html.bak"]:
            with self.subTest(ruta=ruta):
                with self.assertRaises(urllib.error.HTTPError) as caso:
                    self.pedir(ruta)
                self.assertEqual(caso.exception.code, 404)

    def test_borrar_sin_la_clave_da_401(self):
        """Borrar es lo unico destructivo que se puede pedir de afuera: sin el
        token no se llega ni a mirar el disco."""
        pedido = urllib.request.Request(
            self.base + "/api/borrar", method="POST",
            data=json.dumps({"volcado": "partido_20260908_141643.txt"}).encode(),
            headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as caso:
            urllib.request.urlopen(pedido, timeout=10)
        self.assertEqual(caso.exception.code, 401)
        self.assertTrue(json.loads(caso.exception.read())["clave"])

    def test_listado_de_partidos(self):
        codigo, datos = self.pedir_json("/api/partidos")
        self.assertEqual(codigo, 200)
        self.assertTrue(datos["ok"])
        self.assertIsInstance(datos["partidos"], list)
        for fila in datos["partidos"]:
            self.assertEqual(sorted(fila), sorted(
                ["id", "fecha", "hora", "equipo", "rival", "sets", "parciales",
                 "puntos", "volcado", "informe"]))

    def test_descargar_fuera_de_la_carpeta_da_400_y_no_lee_nada(self):
        for ruta in ["/api/descargar?archivo=../../algo",
                     "/api/descargar?archivo=../servidor_voley.py&tipo=txt",
                     "/api/descargar?archivo=&tipo=txt",
                     "/api/descargar?archivo=servidor_voley.py&tipo=py"]:
            with self.subTest(ruta=ruta):
                with self.assertRaises(urllib.error.HTTPError) as caso:
                    self.pedir(ruta)
                self.assertEqual(caso.exception.code, 400)
                self.assertFalse(json.loads(caso.exception.read())["ok"])

    def test_un_partido_de_afuera_tambien_da_400(self):
        for ruta in ["/api/partido?archivo=../../algo",
                     "/api/informe?archivo=../../algo",
                     "/api/partido?archivo="]:
            with self.subTest(ruta=ruta):
                with self.assertRaises(urllib.error.HTTPError) as caso:
                    self.pedir(ruta)
                self.assertEqual(caso.exception.code, 400)

    def test_descargar_un_volcado_de_verdad(self):
        codigo, datos = self.pedir_json("/api/partidos")
        volcados = [f["volcado"] for f in datos["partidos"] if f["volcado"]]
        if not volcados:
            self.skipTest("no hay volcados en Datos/")
        codigo, cuerpo, cabeceras = self.pedir(
            "/api/descargar?archivo=" + urllib.parse.quote(volcados[0]) + "&tipo=txt")
        self.assertEqual(codigo, 200)
        self.assertIn("text/plain", cabeceras["Content-Type"])
        self.assertIn("attachment", cabeceras["Content-Disposition"])
        self.assertIn("=== Jugadas cargadas ===", cuerpo.decode("utf-8"))

    def test_un_archivo_que_no_esta_da_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caso:
            self.pedir("/api/partido?archivo=partido_20990101_000000.txt")
        self.assertEqual(caso.exception.code, 404)

    def test_la_sesion_en_curso_no_se_toca(self):
        antes = list(self.sv.sesion.lineas)
        self.pedir_json("/api/partidos")
        codigo, datos = self.pedir_json("/api/estado")
        self.assertEqual(self.sv.sesion.lineas, antes)
        self.assertTrue(datos["ok"])


if __name__ == "__main__":
    unittest.main()
