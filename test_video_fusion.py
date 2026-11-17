"""
Propuestas + decisiones = armadas (video/fusion.py) y como una operacion de la
pantalla se vuelve decision (video/decisiones.py).

Lo que mas importa aca es la regla 4 del plan: rehacer las propuestas (otro
detector, otros umbrales) no pisa nada de lo que decidio una persona. Los
tests de TestRehacerLasPropuestas la prueban caso por caso: la aceptada sigue
aceptada y como se la acepto, la descartada no vuelve, la que pierde su
propuesta queda con sus datos.

Todo esto es Python puro: no hace falta video ni ffmpeg.
"""
import copy
import unittest

from video import decisiones, fusion
from video.decisiones import OperacionInvalida


def propuesta(ident, t, lado="cerca", **otros):
    return {"id": ident, "t_armado": t, "lado": lado, "tipo": "armada", "zona_destino": 4,
            "t_ataque": round(t + 0.8, 3), "t_toque_previo": round(t - 1.2, 3),
            "confianza": 0.8, "motivos": [], **otros}


def propuestas(*lista):
    return {"version": 1, "armadas": list(lista)}


def revision_vacia():
    return {"version": 1, "edicion": 0, "sets": [], "decisiones": []}


def operar(revision, props, *ops, duracion=None):
    """Aplica las operaciones en orden, como las mandaria la pantalla."""
    clave = armadas = None
    for op in ops:
        revision, clave, armadas = decisiones.aplicar(revision, props, op, duracion)
    return revision, clave, armadas


def la(armadas, clave):
    return next(a for a in armadas if a["clave"] == clave)


class TestMarcasAMano(unittest.TestCase):
    """La etapa 1: no hay propuestas, todo lo marca la persona."""

    def test_una_marca_es_una_armada_aceptada(self):
        _, clave, armadas = operar(revision_vacia(), None,
                                   {"tipo": "marcar", "t": 100.0, "campos": {"armador": 3}})
        self.assertEqual(clave, "d:d1")
        a = la(armadas, clave)
        self.assertEqual((a["estado"], a["origen"], a["armador"]), ("aceptada", "manual", 3))
        self.assertEqual(a["t_armado"], 100.0)
        self.assertFalse(a["huerfana"])

    def test_el_recorte_por_defecto_rodea_al_armado(self):
        _, clave, armadas = operar(revision_vacia(), None, {"tipo": "marcar", "t": 100.0})
        a = la(armadas, clave)
        # toque previo estimado 1,5 s antes, menos 1 s; ataque estimado 1 s
        # despues, mas 2 s
        self.assertEqual((a["t_inicio"], a["t_fin"]), (97.5, 103.0))

    def test_el_recorte_no_se_sale_del_video(self):
        _, clave, armadas = operar(revision_vacia(), None,
                                   {"tipo": "marcar", "t": 1.0}, duracion=60.0)
        self.assertEqual(la(armadas, clave)["t_inicio"], 0.0)
        _, clave, armadas = operar(revision_vacia(), None,
                                   {"tipo": "marcar", "t": 59.0}, duracion=60.0)
        self.assertEqual(la(armadas, clave)["t_fin"], 60.0)

    def test_los_ids_no_se_repiten(self):
        revision, _, armadas = operar(revision_vacia(), None,
                                      {"tipo": "marcar", "t": 10.0},
                                      {"tipo": "marcar", "t": 20.0},
                                      {"tipo": "marcar", "t": 30.0})
        self.assertEqual([d["id"] for d in revision["decisiones"]], ["d1", "d2", "d3"])
        self.assertEqual([a["t_armado"] for a in armadas], [10.0, 20.0, 30.0])

    def test_el_ataque_marcado_da_el_vuelo_y_el_tempo(self):
        _, clave, armadas = operar(revision_vacia(), None,
                                   {"tipo": "marcar", "t": 100.0},
                                   {"tipo": "cambiar", "clave": "d:d1",
                                    "campos": {"t_ataque": 100.74}})
        a = la(armadas, clave)
        self.assertEqual((a["tiempo_vuelo"], a["tempo"]), (0.74, "media"))
        # y el recorte se estira hasta 2 s despues del ataque
        self.assertEqual(a["t_fin"], 102.74)

    def test_descartar_una_marca_propia_la_borra(self):
        revision, clave, armadas = operar(revision_vacia(), None,
                                          {"tipo": "marcar", "t": 10.0},
                                          {"tipo": "descartar", "clave": "d:d1"})
        self.assertIsNone(clave)
        self.assertEqual(revision["decisiones"], [])
        self.assertEqual(armadas, [])


class TestPendientes(unittest.TestCase):

    def test_sin_decidir_todo_es_pendiente(self):
        armadas = fusion.fusionar(propuestas(propuesta("p2", 20.0), propuesta("p1", 10.0)),
                                  revision_vacia())
        self.assertEqual([(a["clave"], a["estado"]) for a in armadas],
                         [("p:p1", "pendiente"), ("p:p2", "pendiente")])

    def test_aceptar_copia_lo_que_se_vio(self):
        props = propuestas(propuesta("p1", 10.0))
        revision, clave, armadas = operar(revision_vacia(), props,
                                          {"tipo": "aceptar", "clave": "p:p1"})
        decision = revision["decisiones"][0]
        self.assertEqual((decision["estado"], decision["origen"]), ("aceptada", "auto"))
        self.assertEqual(decision["propuesta"]["zona_destino"], 4)
        self.assertEqual(decision["propuesta"]["t_ataque"], 10.8)
        self.assertEqual(clave, "d:d1")
        self.assertEqual(la(armadas, clave)["propuesta"], "p1")

    def test_corregir_una_pendiente_la_acepta(self):
        props = propuestas(propuesta("p1", 10.0))
        _, clave, armadas = operar(revision_vacia(), props,
                                   {"tipo": "cambiar", "clave": "p:p1",
                                    "campos": {"zona_destino": 3}})
        a = la(armadas, clave)
        self.assertEqual((a["estado"], a["zona_destino"], a["corregido"]),
                         ("aceptada", 3, ["zona_destino"]))

    def test_descartar_una_pendiente_la_recuerda(self):
        props = propuestas(propuesta("p1", 10.0))
        _, clave, armadas = operar(revision_vacia(), props,
                                   {"tipo": "descartar", "clave": "p:p1"})
        self.assertEqual(la(armadas, clave)["estado"], "descartada")

    def test_la_clave_vieja_de_una_pendiente_sigue_sirviendo(self):
        # Dos toques seguidos desde la pantalla: el segundo sale con la clave
        # que la armada tenia antes del primero.
        props = propuestas(propuesta("p1", 10.0))
        _, clave, armadas = operar(revision_vacia(), props,
                                   {"tipo": "cambiar", "clave": "p:p1",
                                    "campos": {"zona_destino": 2}},
                                   {"tipo": "descartar", "clave": "p:p1"})
        self.assertEqual(len(armadas), 1)
        self.assertEqual((la(armadas, clave)["estado"], la(armadas, clave)["zona_destino"]),
                         ("descartada", 2))


class TestRehacerLasPropuestas(unittest.TestCase):
    """Se corre otro detector: las propuestas cambian de id y de tiempo."""

    def setUp(self):
        self.viejas = propuestas(propuesta("p1", 100.0), propuesta("p2", 200.0))

    def test_la_aceptada_sigue_aceptada_y_como_la_deje(self):
        revision, _, _ = operar(revision_vacia(), self.viejas,
                                {"tipo": "cambiar", "clave": "p:p1",
                                 "campos": {"zona_destino": 3, "armador": 7,
                                            "etiquetas": ["pipe"], "nota": "mala recepcion"}})
        nuevas = propuestas(propuesta("q9", 100.3, zona_destino=2,
                                      trayectoria=[[100.3, 0.5, 0.4]]))
        a = fusion.fusionar(nuevas, revision)[0]
        self.assertEqual(len(fusion.fusionar(nuevas, revision)), 1)
        self.assertEqual((a["estado"], a["zona_destino"], a["armador"], a["etiquetas"], a["nota"]),
                         ("aceptada", 3, 7, ["pipe"], "mala recepcion"))
        self.assertEqual(a["propuesta"], "q9")
        # lo nuevo que trae el detector (y que nadie decidio) si entra
        self.assertEqual(a["trayectoria"], [[100.3, 0.5, 0.4]])

    def test_lo_aceptado_sin_tocar_tambien_queda_como_se_vio(self):
        revision, _, _ = operar(revision_vacia(), self.viejas,
                                {"tipo": "aceptar", "clave": "p:p1"})
        nuevas = propuestas(propuesta("q9", 100.3, zona_destino=2))
        a = fusion.fusionar(nuevas, revision)[0]
        self.assertEqual((a["t_armado"], a["zona_destino"]), (100.0, 4))

    def test_la_descartada_no_vuelve_como_pendiente(self):
        revision, _, _ = operar(revision_vacia(), self.viejas,
                                {"tipo": "descartar", "clave": "p:p2"})
        armadas = fusion.fusionar(propuestas(propuesta("q1", 100.1), propuesta("q2", 199.8)),
                                  revision)
        self.assertEqual([a["estado"] for a in armadas], ["pendiente", "descartada"])

    def test_si_la_propuesta_desaparece_la_decision_queda_con_sus_datos(self):
        revision, _, _ = operar(revision_vacia(), self.viejas,
                                {"tipo": "cambiar", "clave": "p:p1",
                                 "campos": {"armador": 5}})
        armadas = fusion.fusionar(propuestas(), revision)
        self.assertEqual(len(armadas), 1)
        a = armadas[0]
        self.assertEqual((a["estado"], a["huerfana"], a["armador"]), ("aceptada", True, 5))
        self.assertEqual((a["t_armado"], a["t_ataque"], a["zona_destino"]), (100.0, 100.8, 4))

    def test_fuera_de_la_ventana_es_otra_armada(self):
        revision, _, _ = operar(revision_vacia(), self.viejas,
                                {"tipo": "aceptar", "clave": "p:p1"})
        armadas = fusion.fusionar(propuestas(propuesta("q1", 100.6)), revision)
        self.assertEqual([(a["estado"], a["huerfana"]) for a in armadas],
                         [("aceptada", True), ("pendiente", False)])

    def test_del_otro_lado_de_la_red_es_otra_armada(self):
        revision, _, _ = operar(revision_vacia(), self.viejas,
                                {"tipo": "aceptar", "clave": "p:p1"})
        armadas = fusion.fusionar(propuestas(propuesta("q1", 100.1, lado="lejos")), revision)
        self.assertEqual(sorted(a["estado"] for a in armadas), ["aceptada", "pendiente"])

    def test_una_propuesta_para_una_decision(self):
        revision, _, _ = operar(revision_vacia(), self.viejas,
                                {"tipo": "aceptar", "clave": "p:p1"})
        armadas = fusion.fusionar(propuestas(propuesta("q1", 100.4), propuesta("q2", 100.2)),
                                  revision)
        aceptada = next(a for a in armadas if a["estado"] == "aceptada")
        self.assertEqual(aceptada["propuesta"], "q2")
        self.assertEqual([a["propuesta"] for a in armadas if a["estado"] == "pendiente"], ["q1"])

    def test_la_mas_cercana_se_queda_con_la_propuesta(self):
        revision, _, _ = operar(revision_vacia(), None,
                                {"tipo": "marcar", "t": 100.0},
                                {"tipo": "marcar", "t": 100.45})
        armadas = fusion.fusionar(propuestas(propuesta("q1", 100.4)), revision)
        con_propuesta = [a for a in armadas if a["propuesta"] == "q1"]
        self.assertEqual([a["t_armado"] for a in con_propuesta], [100.45])
        self.assertEqual(len(armadas), 2)

    def test_la_corregida_encuentra_a_la_propuesta_que_ahora_acierta(self):
        # el detector viejo puso el armado en el toque equivocado y se lo
        # movio 0,8 s; el nuevo acierta
        revision, _, _ = operar(revision_vacia(), self.viejas,
                                {"tipo": "cambiar", "clave": "p:p1",
                                 "campos": {"t_armado": 100.8, "t_ataque": 101.6}})
        armadas = fusion.fusionar(propuestas(propuesta("q1", 100.75)), revision)
        self.assertEqual(len(armadas), 1)
        self.assertEqual((armadas[0]["propuesta"], armadas[0]["t_armado"]), ("q1", 100.8))

    def test_la_corregida_tambien_reconoce_al_error_de_siempre(self):
        revision, _, _ = operar(revision_vacia(), self.viejas,
                                {"tipo": "cambiar", "clave": "p:p1",
                                 "campos": {"t_armado": 100.8, "t_ataque": 101.6}})
        armadas = fusion.fusionar(propuestas(propuesta("q1", 100.0)), revision)
        self.assertEqual([(a["estado"], a["t_armado"]) for a in armadas],
                         [("aceptada", 100.8)])


class TestMarcaAManoYPropuesta(unittest.TestCase):
    """Lo marcado en la etapa 1 se cruza con lo que proponga la etapa 5."""

    def test_se_juntan_y_manda_la_marca(self):
        revision, _, _ = operar(revision_vacia(), None,
                                {"tipo": "marcar", "t": 50.0,
                                 "campos": {"zona_destino": 3, "armador": 9}})
        props = propuestas(propuesta("q1", 50.2, trayectoria=[[50.2, 0.1, 0.2]]))
        armadas = fusion.fusionar(props, revision)
        self.assertEqual(len(armadas), 1)
        a = armadas[0]
        self.assertEqual((a["origen"], a["t_armado"], a["zona_destino"], a["armador"]),
                         ("manual", 50.0, 3, 9))
        # lo que la marca no decia lo completa la propuesta
        self.assertEqual((a["t_ataque"], a["trayectoria"]), (51.0, [[50.2, 0.1, 0.2]]))

    def test_un_ataque_propuesto_antes_de_la_marca_no_es_de_ella(self):
        # la marca se puso tarde, con el video andando
        revision, _, _ = operar(revision_vacia(), None, {"tipo": "marcar", "t": 50.6})
        props = propuestas(propuesta("q1", 50.2, t_ataque=50.5))
        a = fusion.fusionar(props, revision)[0]
        self.assertIsNone(a["t_ataque"])
        self.assertIsNone(a["tiempo_vuelo"])


class TestSets(unittest.TestCase):

    SETS = [{"desde": 10.0, "set": 1, "lado": "cerca"},
            {"desde": 1000.0, "set": 2, "lado": "lejos"}]

    def test_cada_armada_cae_en_su_set(self):
        revision = {**revision_vacia(), "sets": self.SETS}
        revision, _, armadas = operar(revision, None,
                                      {"tipo": "marcar", "t": 5.0},
                                      {"tipo": "marcar", "t": 500.0},
                                      {"tipo": "marcar", "t": 1500.0})
        self.assertEqual([(a["set"], a["lado"]) for a in armadas],
                         [(None, None), (1, "cerca"), (2, "lejos")])

    def test_la_marca_va_del_lado_de_mi_equipo(self):
        # en el set 2 mi equipo esta lejos: una propuesta cerca no es de la marca
        revision = {**revision_vacia(), "sets": self.SETS}
        revision, _, _ = operar(revision, None, {"tipo": "marcar", "t": 1500.0})
        armadas = fusion.fusionar(propuestas(propuesta("q1", 1500.1, lado="cerca")), revision)
        self.assertEqual(len(armadas), 2)

    def test_poner_reemplazar_y_quitar_sets(self):
        revision, clave, _ = operar(revision_vacia(), None,
                                    {"tipo": "set", "desde": 1000.0, "set": 2, "lado": "lejos"},
                                    {"tipo": "set", "desde": 10.0, "set": 1, "lado": "cerca"})
        self.assertIsNone(clave)
        self.assertEqual([s["set"] for s in revision["sets"]], [1, 2])
        # otra vez casi en el mismo lugar: se corrige el que estaba
        revision, _, _ = operar(revision, None,
                                {"tipo": "set", "desde": 1000.4, "set": 2, "lado": "cerca"})
        self.assertEqual(revision["sets"][1], {"desde": 1000.4, "set": 2, "lado": "cerca"})
        revision, _, _ = operar(revision, None, {"tipo": "quitar_set", "desde": 10.0})
        self.assertEqual([s["set"] for s in revision["sets"]], [2])

    def test_sets_invalidos(self):
        for op in ({"tipo": "set", "desde": 1.0, "set": 6, "lado": "cerca"},
                   {"tipo": "set", "desde": 1.0, "set": 1, "lado": "izquierda"},
                   {"tipo": "set", "desde": -1.0, "set": 1, "lado": "cerca"},
                   {"tipo": "quitar_set", "desde": 99.0}):
            with self.subTest(op=op), self.assertRaises(OperacionInvalida):
                operar(revision_vacia(), None, op)


class TestTempo(unittest.TestCase):

    def test_cortes(self):
        self.assertIsNone(fusion.tempo_de(None))
        self.assertEqual([fusion.tempo_de(v) for v in (0.3, 0.5, 0.99, 1.0, 1.6)],
                         ["rapida", "media", "media", "alta", "alta"])


class TestValidacion(unittest.TestCase):

    def setUp(self):
        self.revision, _, _ = operar(revision_vacia(), None, {"tipo": "marcar", "t": 100.0})

    def cambiar(self, campos, duracion=None):
        return operar(self.revision, None, {"tipo": "cambiar", "clave": "d:d1",
                                            "campos": campos}, duracion=duracion)

    def test_lo_que_no_se_acepta(self):
        malos = [{"zona_destino": 7}, {"zona_destino": True}, {"zona_destino": "4"},
                 {"armador": "3"}, {"armador": -1}, {"t_armado": -2},
                 {"t_armado": float("nan")}, {"etiquetas": "pipe"}, {"nota": 5},
                 {"lado": "medio"}, {"tipo": "saque"}, {"color": "rojo"}, {}]
        for campos in malos:
            with self.subTest(campos=campos), self.assertRaises(OperacionInvalida):
                self.cambiar(campos)

    def test_nada_despues_del_final(self):
        with self.assertRaises(OperacionInvalida):
            self.cambiar({"t_ataque": 130.0}, duracion=120.0)

    def test_operaciones_y_claves_desconocidas(self):
        for op in ({"tipo": "borrar_todo"}, "marcar", {"tipo": "aceptar", "clave": "d:d99"},
                   {"tipo": "marcar"}):
            with self.subTest(op=op), self.assertRaises(OperacionInvalida):
                operar(self.revision, None, op)

    def test_etiquetas_limpias(self):
        _, clave, armadas = self.cambiar({"etiquetas": ["  Pipe ", "pipe", "", "rápida  x"]})
        self.assertEqual(la(armadas, clave)["etiquetas"], ["Pipe", "rápida x"])

    def test_el_recorte_tiene_que_mostrar_el_armado(self):
        with self.assertRaises(OperacionInvalida):
            self.cambiar({"t_inicio": 101.0})
        with self.assertRaises(OperacionInvalida):
            self.cambiar({"t_fin": 99.0})
        _, clave, armadas = self.cambiar({"t_inicio": 98.0, "t_fin": 104.0})
        self.assertEqual((la(armadas, clave)["t_inicio"], la(armadas, clave)["t_fin"]),
                         (98.0, 104.0))

    def test_el_ataque_va_despues_del_armado(self):
        with self.assertRaises(OperacionInvalida):
            self.cambiar({"t_ataque": 99.5})

    def test_mover_el_armado_fuera_del_recorte_lo_rehace(self):
        revision, _, _ = self.cambiar({"t_inicio": 98.0})
        _, clave, armadas = operar(revision, None, {"tipo": "cambiar", "clave": "d:d1",
                                                    "campos": {"t_armado": 110.0}})
        a = la(armadas, clave)
        self.assertEqual((a["t_armado"], a["t_inicio"], a["t_fin"]), (110.0, 107.5, 113.0))

    def test_una_operacion_rechazada_no_toca_la_revision(self):
        antes = copy.deepcopy(self.revision)
        with self.assertRaises(OperacionInvalida):
            self.cambiar({"t_inicio": 101.0})
        self.assertEqual(self.revision, antes)


class TestNoTocaLoQueRecibe(unittest.TestCase):

    def test_fusionar_y_aplicar_no_modifican_sus_entradas(self):
        props = propuestas(propuesta("p1", 10.0, trayectoria=[[10.0, 0.5, 0.5]]))
        revision, _, _ = operar(revision_vacia(), props,
                                {"tipo": "cambiar", "clave": "p:p1", "campos": {"armador": 2}})
        copia_props, copia_rev = copy.deepcopy(props), copy.deepcopy(revision)
        fusion.fusionar(props, revision)
        decisiones.aplicar(revision, props, {"tipo": "marcar", "t": 50.0})
        self.assertEqual((props, revision), (copia_props, copia_rev))


if __name__ == "__main__":
    unittest.main()
