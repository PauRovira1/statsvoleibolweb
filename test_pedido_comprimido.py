"""
Tests del pedido comprimido entre la pantalla y el servidor.

Se corren con:
    python -m unittest test_pedido_comprimido

Cada pedido lleva el partido entero. Alojado en AWS, el WAF de CloudFront
corta con un 403 los cuerpos de mas de 8 KB (y sus reglas contra ataques
pueden confundir una jugada con uno), y eso pasaba a mitad de un partido largo.
Por eso la pantalla manda {"z": gzip en base64}. Lo que se cuida aca:

* que lo que comprime el navegador lo abra el servidor tal cual;
* que el pedido sin comprimir se siga aceptando;
* que un comprimido roto o gigante se rechace en vez de colgar el servidor.
"""
import base64
import gzip
import json
import shutil
import subprocess
import unittest
from pathlib import Path

import servidor_voley as sv

CARPETA = Path(__file__).resolve().parent
NODE = shutil.which("node")

# Un partido largo con la notacion de ahora: sin comprimir pasa los 8 KB.
LINEAS = (["Local", "Rival", "3_S 88 15 13 16 21  9_L_15_21", "1 2_S 3 4 5 6", "A"]
          + ["1_5_X/4_2/2_3_A+/3_1_PO_D", "7_2/1_5_A-/9_5_CO_BD_6", "8_1/3_4_A0/13_1_PO_P"] * 120)


def comprimir(datos) -> dict:
    return {"z": base64.b64encode(gzip.compress(json.dumps(datos).encode())).decode()}


class TestDesempaquetar(unittest.TestCase):

    def test_ida_y_vuelta(self):
        datos = {"lineas": LINEAS, "linea": "5_1_6_A_7"}
        self.assertEqual(sv.desempaquetar(comprimir(datos)), datos)

    def test_el_pedido_de_siempre_pasa_igual(self):
        datos = {"lineas": ["Local"], "linea": "x"}
        self.assertEqual(sv.desempaquetar(datos), datos)
        # un pedido que casualmente tiene "z" junto con otras claves no se toca
        self.assertEqual(sv.desempaquetar({"z": "abc", "linea": "x"}), {"z": "abc", "linea": "x"})

    def test_comprimido_queda_muy_por_debajo_del_limite_del_waf(self):
        datos = {"lineas": LINEAS, "linea": "5_1_6_A_7"}
        self.assertGreater(len(json.dumps(datos)), 8 * 1024)
        self.assertLess(len(json.dumps(comprimir(datos))), 4 * 1024)

    def test_comprimido_roto(self):
        with self.assertRaises(ValueError):
            sv.desempaquetar({"z": "esto no es base64!"})
        with self.assertRaises(ValueError):
            sv.desempaquetar({"z": base64.b64encode(b"no es gzip").decode()})

    def test_no_se_descomprime_sin_limite(self):
        bomba = {"z": base64.b64encode(gzip.compress(b"0" * (sv.MAXIMO_DESCOMPRIMIDO + 10))).decode()}
        with self.assertRaises(ValueError):
            sv.desempaquetar(bomba)


@unittest.skipUnless(NODE, "no hay node para correr el codigo del navegador")
class TestLoQueMandaElNavegador(unittest.TestCase):
    """El empaquetar() de interfaz.js, corrido tal cual en node."""

    SCRIPT = """
const fs = require("fs");
const codigo = fs.readFileSync(process.argv[1], "utf8");
const desde = codigo.indexOf("async function empaquetar");
const hasta = codigo.indexOf("async function api(");
const empaquetar = eval("(" + codigo.slice(desde, hasta).trim() + ")");
empaquetar(JSON.parse(fs.readFileSync(0, "utf8"))).then(t => process.stdout.write(t));
"""

    def test_el_servidor_abre_lo_que_comprime_el_navegador(self):
        datos = {"lineas": LINEAS, "linea": "5_1_6_X/3_3/2_4_A+/4_1_PO_P"}
        salida = subprocess.run(
            [NODE, "-e", self.SCRIPT, str(CARPETA / "public" / "interfaz.js")],
            input=json.dumps(datos), capture_output=True, text=True, check=True,
        ).stdout
        cuerpo = json.loads(salida)
        self.assertEqual(set(cuerpo), {"z"})
        self.assertEqual(sv.desempaquetar(cuerpo), datos)


if __name__ == "__main__":
    unittest.main()
