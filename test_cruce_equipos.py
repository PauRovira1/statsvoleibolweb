"""
Tests del cruce por nombre entre los equipos del club.

Se corren con:
    python -m unittest test_cruce_equipos

Un club tiene primera, segunda y a veces mas, y la misma persona puede jugar
en dos. El numero no sirve para cruzarlas -- puede ser la 13 en la A y la 7 en
la B -- asi que el cruce va por nombre.

Lo que cuidan estos tests es lo que puede salir mal callado: que dos personas
distintas se mezclen en una, y que las cifras de la A se sumen con las de la B
y tapen justamente la diferencia que se quiere mirar.
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import almacenamiento as alm
import estadisticas_jugadores as ej


def volcado_de(equipo: str, rival: str) -> str:
    """Un volcado real con los equipos renombrados.

    Se parte de uno de verdad en vez de inventar el texto: el parser lee
    muchas secciones y un volcado falso a mano se desincroniza en cuanto el
    formato cambia."""
    base = sorted(Path("Datos").glob("*.txt"))
    if not base:
        raise unittest.SkipTest("no hay volcados de donde partir")
    texto = base[0].read_text(encoding="utf-8")
    lineas = texto.splitlines()
    # las dos primeras lineas despues del encabezado son los nombres
    for i, linea in enumerate(lineas[:6]):
        if linea.strip() == "=== Jugadas cargadas ===":
            lineas[i + 1], lineas[i + 2] = equipo, rival
            break
    texto = "\n".join(lineas)
    # y los nombres tambien aparecen en los titulos de las secciones
    viejo_equipo, viejo_rival = base[0].read_text(encoding="utf-8").splitlines()[1:3]
    return texto.replace(f"--- {viejo_equipo} ---", f"--- {equipo} ---") \
                .replace(f"--- {viejo_rival} ---", f"--- {rival} ---")


class BaseCruce(unittest.TestCase):
    """Dos equipos del club con un volcado cada uno, en una carpeta propia."""

    def setUp(self):
        self.carpeta = Path(tempfile.mkdtemp())
        (self.carpeta / "Datos").mkdir()
        for equipo, rival, nombre in (("Palestino A", "UVC", "partido_20260101_120000.txt"),
                                      ("Palestino B", "Sarmiento", "partido_20260102_120000.txt")):
            (self.carpeta / "Datos" / nombre).write_text(volcado_de(equipo, rival),
                                                         encoding="utf-8")
        for objeto, atributo, valor in ((alm, "CARPETA_ESCRITURA", self.carpeta),
                                        (alm, "_ES_LOCAL", True),
                                        (alm, "_plantel", None),
                                        (alm, "_momento_plantel", 0.0)):
            parche = mock.patch.object(objeto, atributo, valor)
            parche.start()
            self.addCleanup(parche.stop)
        self.addCleanup(shutil.rmtree, self.carpeta, True)

    def agregado(self):
        return ej.agregar(self.carpeta / "Datos")

    def un_dorsal(self, equipo):
        return next(iter(self.agregado()["equipos"][equipo]))


class TestLosEquiposSeSeparan(BaseCruce):

    def test_cada_nombre_de_equipo_es_un_equipo(self):
        equipos = sorted(self.agregado()["equipos"])
        self.assertEqual(equipos, ["Palestino A", "Palestino B"])

    def test_las_cifras_no_se_mezclan_entre_equipos(self):
        # el mismo volcado en los dos, asi que los totales tienen que dar igual
        # pero por separado, no sumados
        a = ej.resumen_equipo("Palestino A", self.agregado())
        b = ej.resumen_equipo("Palestino B", self.agregado())
        self.assertEqual(a["indicadores"]["ataques"], b["indicadores"]["ataques"])
        self.assertEqual(a["partidos"], 1)
        self.assertEqual(b["partidos"], 1)


class TestElCrucePorNombre(BaseCruce):

    def test_sin_nombres_anotados_no_cruza_a_nadie(self):
        # suponer que el 13 de la A es el 13 de la B mezclaria dos personas
        self.assertEqual(ej.por_nombre(self.agregado()), {})

    def test_el_mismo_nombre_en_dos_equipos_es_una_persona(self):
        alm.guardar_plantel("Palestino A", {self.un_dorsal("Palestino A"): "Ana Perez"})
        alm.guardar_plantel("Palestino B", {self.un_dorsal("Palestino B"): "Ana Perez"})
        gente = ej.por_nombre(self.agregado())
        self.assertEqual(len(gente), 1)
        ficha = next(iter(gente.values()))
        self.assertEqual(ficha["nombre"], "Ana Perez")
        self.assertEqual(sorted(e["equipo"] for e in ficha["equipos"]),
                         ["Palestino A", "Palestino B"])

    def test_cruza_aunque_el_numero_sea_distinto(self):
        # es la razon de cruzar por nombre y no por dorsal
        dorsales = sorted(self.agregado()["equipos"]["Palestino A"])
        alm.guardar_plantel("Palestino A", {dorsales[0]: "Ana Perez"})
        alm.guardar_plantel("Palestino B", {dorsales[1]: "Ana Perez"})
        self.assertNotEqual(dorsales[0], dorsales[1])
        ficha = next(iter(ej.por_nombre(self.agregado()).values()))
        self.assertEqual(len(ficha["equipos"]), 2)

    def test_el_mismo_nombre_escrito_distinto_sigue_siendo_uno(self):
        # nadie tipea "Sofía" igual las dos veces
        alm.guardar_plantel("Palestino A", {self.un_dorsal("Palestino A"): "Sofía Gómez"})
        alm.guardar_plantel("Palestino B", {self.un_dorsal("Palestino B"): "sofia gomez"})
        self.assertEqual(len(ej.por_nombre(self.agregado())), 1)

    def test_dos_nombres_distintos_son_dos_personas(self):
        alm.guardar_plantel("Palestino A", {self.un_dorsal("Palestino A"): "Ana Perez"})
        alm.guardar_plantel("Palestino B", {self.un_dorsal("Palestino B"): "Luz Rojas"})
        self.assertEqual(len(ej.por_nombre(self.agregado())), 2)

    def test_un_dorsal_sin_nombre_no_entra_al_cruce(self):
        alm.guardar_plantel("Palestino A", {self.un_dorsal("Palestino A"): "Ana Perez"})
        gente = ej.por_nombre(self.agregado())
        self.assertEqual(len(gente), 1)
        self.assertEqual(len(next(iter(gente.values()))["equipos"]), 1)


class TestLaFichaLoMuestra(BaseCruce):

    def cruzada(self):
        self.a, self.b = self.un_dorsal("Palestino A"), self.un_dorsal("Palestino B")
        alm.guardar_plantel("Palestino A", {self.a: "Ana Perez"})
        alm.guardar_plantel("Palestino B", {self.b: "Ana Perez"})
        return ej.ficha("Palestino A", self.a, self.agregado())

    def test_dice_en_que_otros_equipos_juega(self):
        ficha = self.cruzada()
        self.assertEqual(len(ficha["tambien_en"]), 1)
        self.assertEqual(ficha["tambien_en"][0]["equipo"], "Palestino B")
        self.assertEqual(str(ficha["tambien_en"][0]["dorsal"]), str(self.b))

    def test_trae_las_cifras_de_cada_equipo_por_separado(self):
        ficha = self.cruzada()
        self.assertEqual(ficha["aqui"]["equipo"], "Palestino A")
        for clave in ("partidos", "recepciones", "ataques", "punto", "bloqueos"):
            self.assertIn(clave, ficha["aqui"])
            self.assertIn(clave, ficha["tambien_en"][0])

    def test_no_se_lista_a_si_mismo(self):
        ficha = self.cruzada()
        self.assertNotIn("Palestino A", [e["equipo"] for e in ficha["tambien_en"]])

    def test_quien_juega_en_uno_solo_no_tiene_la_seccion(self):
        alm.guardar_plantel("Palestino A", {self.un_dorsal("Palestino A"): "Ana Perez"})
        ficha = ej.ficha("Palestino A", self.un_dorsal("Palestino A"), self.agregado())
        self.assertEqual(ficha["tambien_en"], [])

    def test_el_listado_dice_en_cuantos_equipos_juega(self):
        self.cruzada()
        # listado() lee de la carpeta de escritura, que es la del test
        datos = ej.listado(self.carpeta / "Datos")
        equipo_a = next(e for e in datos["equipos"] if e["nombre"] == "Palestino A")
        cruzada = next(j for j in equipo_a["jugadores"] if j["dorsal"] == self.a)
        otra = next(j for j in equipo_a["jugadores"] if j["dorsal"] != self.a)
        self.assertEqual(cruzada["equipos"], 2)
        self.assertEqual(otra["equipos"], 0)


class TestComoSeComparanLosNombres(unittest.TestCase):

    def test_ignora_acentos_mayusculas_y_espacios(self):
        iguales = ["Sofía Gómez", "sofia gomez", "  SOFIA   GOMEZ  ", "Sofia Gomez"]
        claves = {ej._mismo_nombre(x) for x in iguales}
        self.assertEqual(len(claves), 1)

    def test_no_junta_nombres_parecidos(self):
        self.assertNotEqual(ej._mismo_nombre("Ana Perez"), ej._mismo_nombre("Ana Peres"))
        self.assertNotEqual(ej._mismo_nombre("Ana"), ej._mismo_nombre("Ana Perez"))

    def test_lo_vacio_no_es_una_persona(self):
        for vacio in ("", "   ", None):
            self.assertEqual(ej._mismo_nombre(vacio), "")


if __name__ == "__main__":
    unittest.main()
