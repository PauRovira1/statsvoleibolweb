"""
Tests del resumen del equipo.

Se corren con:
    python -m unittest test_resumen_equipo

Casi todo se arma sumando varios partidos, asi que lo que hay que cuidar es
que la suma sea la suma. Los tests construyen volcados chicos con numeros
elegidos a mano y comprueban el total, en vez de comparar contra lo que salga
de los partidos reales: eso cambia cada vez que se carga uno y el test dejaria
de decir nada.
"""
import unittest

import estadisticas_jugadores as ej


def volcado(nombre_a="Palestino", **cambios):
    """Un partido de mentira con la forma que devuelve parse_volcado."""
    datos = {
        "fases": {
            "hechos": {"K1": {"total": 10, "ganados": 7, "error": 3},
                       "K2": {"total": 5, "ganados": 3, "error": 2},
                       "K3": {"total": 4, "ganados": 2, "error": 2},
                       "Saque": {"total": 1, "ganados": 1, "error": 0},
                       "Sin fase": {"total": 0, "ganados": 0, "error": 0}},
            "recibidos": {"K1": {"total": 6, "ganados": 4, "error": 2},
                          "K2": {"total": 3, "ganados": 1, "error": 2},
                          "K3": {"total": 2, "ganados": 1, "error": 1},
                          "Saque": {"total": 1, "ganados": 0, "error": 1},
                          "Sin fase": {"total": 0, "ganados": 0, "error": 0}},
        },
        "causas": {"hechos": {"Ataque punto": 8, "Bloqueo punto": 2, "Ataque afuera": 3},
                   "recibidos": {"Ataque punto": 5, "Error de saque": 1}},
        "zona_armador": {"1": {"hechos": 3, "recibidos": 2}},
        "armado_zona": {"2": 6, "4": 10, "3": 4},
        # la calidad viene como entero y la zona como texto: asi lo devuelve
        # parse_volcado, y es justo lo que una vez rompio esta tabla
        "armado_calidad": {3: {"2": 4, "3": 3}, 0: {"4": 5}},
        "recepcion_tipo_saque": {"1 a 5": {"tipo": "Paralelo", "cal3": 2, "cal2": 1,
                                           "cal1": 1, "cal0": 0, "pase": 0}},
        "recepciones": {"Jugador 9": {"cal3": 2, "cal2": 1, "cal1": 1, "cal0": 0, "pase": 0},
                        "Jugador 8": {"cal3": 1, "cal2": 0, "cal1": 0, "cal0": 1, "pase": 1}},
        "ataques_jugador": {"Jugador 13": {"totales": 10, "puntos": 4,
                                           "defendidos": 4, "fuera": 2}},
        "ataques_detalle": [["Jugador 13", "4", "6", 3, 2, 1],
                            ["Jugador 13", "4", "1", 1, 2, 1],
                            ["Jugador 13", "2", "5", 0, 0, 0]],
        "bloqueos_jugador": {"Jugador 15": 2},
    }
    datos.update(cambios)
    return {"teams": {nombre_a: datos, "Rival": dict(datos)}}


class BaseResumen(unittest.TestCase):
    """Se le pasa el agregado ya armado, sin tocar el disco: lo que se prueba
    es la suma y la presentacion, no la lectura de los archivos."""

    def resumen(self, cuantos=2, equipo="Palestino"):
        crudo = ej._cero_equipo()
        for i in range(cuantos):
            ej._acumular_equipo(crudo, volcado()["teams"][equipo], f"vs Rival {i}", 2)
        return ej.resumen_equipo(equipo, {"por_equipo": {equipo: crudo}})


class TestLaSumaEsLaSuma(BaseResumen):

    def test_los_puntos_se_suman_entre_partidos(self):
        uno, dos = self.resumen(1), self.resumen(2)
        self.assertEqual(uno["indicadores"]["hechos"], 20)      # 10+5+4+1
        self.assertEqual(dos["indicadores"]["hechos"], 40)
        self.assertEqual(dos["indicadores"]["recibidos"], 24)   # (6+3+2+1)*2

    def test_las_recepciones_juntan_a_todos_los_jugadores(self):
        r = self.resumen(1)["recepcion"]["total"]
        self.assertEqual(r["recepciones"], 7)      # 4 del 9 mas 3 del 8
        self.assertEqual(r["cal3"], 3)
        self.assertEqual(r["pase"], 1)

    def test_el_porcentaje_sale_del_total_y_no_del_promedio(self):
        # promediar los porcentajes de cada partido daria otro numero, y le
        # daria el mismo peso a un set suelto que a un partido entero
        self.assertAlmostEqual(self.resumen(2)["indicadores"]["positiva"], 8 / 14)

    def test_los_bloqueos_los_sets_y_los_partidos_se_acumulan(self):
        r = self.resumen(3)
        self.assertEqual(r["indicadores"]["bloqueos_punto"], 6)
        self.assertEqual(r["sets"], 6)
        self.assertEqual(r["partidos"], 3)


class TestLasFases(BaseResumen):

    def test_cada_fase_trae_hechos_recibidos_y_saldo(self):
        k1 = next(f for f in self.resumen(2)["fases"] if f["fase"] == "K1")
        self.assertEqual((k1["hechos"], k1["recibidos"]), (20, 12))
        self.assertEqual(k1["saldo"], 8)
        self.assertEqual((k1["hechos_ganados"], k1["hechos_error"]), (14, 6))

    def test_el_reparto_de_las_fases_suma_uno(self):
        fases = self.resumen(2)["fases"]
        self.assertAlmostEqual(sum(f["hechos_reparto"] for f in fases), 1.0)

    def test_una_fase_con_saldo_negativo_se_ve(self):
        # el saldo es el numero que dice que fase regala puntos
        crudo = ej._cero_equipo()
        flojo = volcado()["teams"]["Palestino"]
        flojo["fases"]["recibidos"]["K1"]["total"] = 30
        ej._acumular_equipo(crudo, flojo, "vs Rival", 2)
        resumen = ej.resumen_equipo("Palestino", {"por_equipo": {"Palestino": crudo}})
        k1 = next(f for f in resumen["fases"] if f["fase"] == "K1")
        self.assertEqual(k1["saldo"], -20)


class TestLaDistribucion(BaseResumen):
    """Con recepcion perfecta el armador puede repartir; con recepcion mala el
    juego se achica a una zona sola. Esa es la pregunta de esta tabla."""

    def test_cada_calidad_reparte_su_propio_cien_por_ciento(self):
        d = self.resumen(2)["distribucion"]
        cal3 = next(f for f in d["filas"] if f["calidad"] == "3")
        self.assertEqual(cal3["total"], 14)          # (4+3)*2
        self.assertAlmostEqual(sum(cal3["reparto"]), 1.0)

    def test_la_calidad_entra_aunque_venga_como_numero(self):
        # parse_volcado la devuelve como entero; buscarla como texto dejaba la
        # tabla entera en cero sin que nada avisara
        d = self.resumen(1)["distribucion"]
        self.assertTrue(any(f["total"] for f in d["filas"]))
        cal0 = next(f for f in d["filas"] if f["calidad"] == "0")
        self.assertEqual(cal0["total"], 5)

    def test_las_zonas_van_en_el_orden_de_la_cancha(self):
        self.assertEqual(self.resumen(1)["distribucion"]["zonas"], ["2", "3", "4"])


class TestLaDireccion(BaseResumen):

    def test_dice_cuantos_ataques_salieron_de_cada_zona(self):
        z4 = next(f for f in self.resumen(2)["direccion"]["filas"] if f["zona"] == "4")
        self.assertEqual(z4["ataques"], 20)          # (3+2+1 + 1+2+1) * 2

    def test_reparte_hacia_1_5_y_6(self):
        z4 = next(f for f in self.resumen(1)["direccion"]["filas"] if f["zona"] == "4")
        hacia = {h["direccion"]: h["ataques"] for h in z4["hacia"]}
        self.assertEqual(hacia, {"1": 4, "5": 0, "6": 6})
        self.assertAlmostEqual(sum(h["reparto"] for h in z4["hacia"]), 1.0)

    def test_dice_que_parte_de_cada_direccion_fue_punto(self):
        z4 = next(f for f in self.resumen(1)["direccion"]["filas"] if f["zona"] == "4")
        hacia6 = next(h for h in z4["hacia"] if h["direccion"] == "6")
        self.assertAlmostEqual(hacia6["punto"], 3 / 6)

    def test_una_zona_sin_un_solo_ataque_no_es_una_fila(self):
        # el volcado lista zonas que nadie ataco nunca
        # en el fixture la zona 2 tiene 0-0-0: esa es la que no tiene que salir
        zonas = [f["zona"] for f in self.resumen(1)["direccion"]["filas"]]
        self.assertEqual(zonas, ["4"])


class TestLaRecepcionPorSaque(BaseResumen):

    def test_conserva_de_que_saque_vino(self):
        # el sumador tiraba los textos y la columna llegaba vacia a la pantalla
        fila = self.resumen(2)["recepcion"]["por_tipo"][0]
        self.assertEqual(fila["tipo"], "Paralelo")
        self.assertEqual(fila["ruta"], "1 a 5")

    def test_suma_las_recepciones_de_esa_ruta(self):
        fila = self.resumen(2)["recepcion"]["por_tipo"][0]
        self.assertEqual(fila["recepciones"], 8)     # (2+1+1)*2
        self.assertAlmostEqual(fila["positiva"], 6 / 8)


class TestUnaFilaPorPartido(BaseResumen):

    def test_hay_una_por_cada_partido_cargado(self):
        r = self.resumen(3)
        self.assertEqual([p["etiqueta"] for p in r["por_partido"]],
                         ["vs Rival 0", "vs Rival 1", "vs Rival 2"])

    def test_cada_fila_es_de_ese_partido_y_no_el_acumulado(self):
        uno = self.resumen(3)["por_partido"][0]
        self.assertEqual(uno["hechos"], 20)
        self.assertEqual(uno["recepciones"], 7)


class TestDesdeLosVolcadosDeVerdad(unittest.TestCase):

    def test_el_equipo_del_rival_no_tiene_resumen(self):
        # solo se arman fichas de los equipos propios
        self.assertIsNone(ej.resumen_equipo("UVC"))

    def test_un_equipo_sin_partidos_no_tiene_resumen(self):
        self.assertIsNone(ej.resumen_equipo("Palestino", {"por_equipo": {}}))

    def test_el_agregado_real_trae_el_bloque_por_equipo(self):
        agregado = ej.agregar()
        if not agregado["por_equipo"]:
            self.skipTest("no hay partidos guardados")
        equipo = next(iter(agregado["por_equipo"]))
        resumen = ej.resumen_equipo(equipo, agregado)
        self.assertEqual(resumen["partidos"], len(agregado["partidos"][equipo]))
        self.assertGreater(resumen["indicadores"]["ataques"], 0)
        self.assertTrue(resumen["direccion"]["filas"])


if __name__ == "__main__":
    unittest.main()
