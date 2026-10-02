# -*- coding: utf-8 -*-
"""
Genera el "Informe de partido en Excel" descrito en Prompt_Informe_Volley.md
a partir del volcado de estadisticas de un partido de volleyball.

Uso:
    python generar_informe_volley.py volcado.txt
    python generar_informe_volley.py volcado.txt --equipo Palestino --fecha 2026-09-05
    type volcado.txt | python generar_informe_volley.py

El volcado debe tener el mismo formato que exporta la app de estadisticas
(bloques "=== Resultado final ===" y "=== Estadisticas por equipo ===",
con "--- <Equipo> ---" por cada equipo).

Todas las tablas agregadas del Excel se calculan con formulas de Excel
(SUM/SUMIF/SUMIFS + IFERROR) sobre una hoja oculta "Datos_Base" que contiene
los datos tal como vienen en el volcado, para que el archivo recalcule solo
si se corrige un dato ahi.
"""
import argparse
import datetime
import pathlib
import re
import sys
from collections import defaultdict

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter, column_index_from_string

import almacenamiento as alm

# ======================================================================
# 1) PARSER DEL VOLCADO
# ======================================================================

RE_SET_LINE = re.compile(r"^Set\s+(\d+):\s*(.+?)\s+(\d+)\s*-\s*(\d+)\s+(.+)$")
RE_TOTAL_PUNTOS = re.compile(r"^Total de puntos cargados:\s*(\d+)$")
# Un partido de un solo set no escribe lineas "Set N:", solo el marcador final.
RE_MARCADOR_FINAL = re.compile(r"^Marcador final:\s*(.+?)\s+(\d+)\s*-\s*(\d+)\s+(.+)$")
RE_TEAM_HDR = re.compile(r"^---\s*(.+?)\s*---$")

RE_FASES_HDR = re.compile(r"^Puntos por fase del rally:$")
RE_FASE_CLASE = re.compile(r"^(Hechos|Recibidos):\s*(\d+)$")
RE_FASE_ITEM = re.compile(
    r"^(K1|K2|K3|Saque|Sin fase):\s*(\d+)\s*\([\d.]+%\)"
    r"\s*-\s*ganados\s+(\d+),\s*por error\s+(\d+)$"
)
FASES_RALLY = ["K1", "K2", "K3", "Saque", "Sin fase"]

RE_ZARM_HDR = re.compile(r"^Puntos con el armador en cada zona:$")
RE_ZARM_ZONA = re.compile(r"^Zona (\d):$")
RE_ZARM_ITEM = re.compile(r"^(Hechos|Recibidos):\s*(\d+)\s*-\s*(.+)$")
ZONAS_ARMADOR = [1, 2, 3, 4, 5, 6]
# En este desglose el saque va partido: un as y un error de saque del rival no
# son la misma situacion (en uno sacamos nosotros, en el otro ellos).
COLUMNAS_ZARM = ["K1", "K2", "K3", "As", "Error de saque", "Sin fase"]

RE_CAUSAS_HDR = re.compile(r"^Puntos por causa:$")
RE_CAUSA_ITEM = re.compile(r"^([A-Za-z][A-Za-z0-9 ]+):\s*(\d+)$")
# el orden y el agrupado tienen que coincidir con analisis_voley.py
CAUSAS_GANADAS = ["Ataque punto", "Ataque usando el bloqueo",
                  "Pelota no defendida", "Bloqueo punto", "As de saque",
                  "Libre punto", "Toque punto",
                  "Libre usando el bloqueo", "Toque usando el bloqueo"]
CAUSAS_ERROR = ["Ataque afuera", "Ataque a la malla", "Error de saque",
                "Armado malo", "Libre malo", "Toque malo", "Error en juego"]
CAUSAS_PUNTO = CAUSAS_GANADAS + CAUSAS_ERROR
# Como se llamaba antes cada causa en los volcados ya guardados. Sin esto los
# partidos viejos perderian esos puntos al releerse: el nombre no estaria en
# CAUSAS_PUNTO y la linea se descartaria sin decir nada.
# Los volcados viejos traen esta causa con otros nombres. Se traducen al leer
# para que un partido guardado hace meses siga cuadrando con uno de hoy.
CAUSAS_RENOMBRADAS = {"Defensa perdida": "Pelota no defendida",
                      "Defensa 0": "Pelota no defendida"}

RE_ARMADO_ZONA_HDR = re.compile(r"^Armado por zona:$")
RE_ARMADO_ZONA_SET_HDR = re.compile(r"^Armado por zona \(set (\d+)\):$")
RE_ZONA_ITEM = re.compile(r"^Zona\s+([\w-]+):\s*(\d+)\s*\([\d.]+%\)$")

RE_ARMADOR_HDR = re.compile(r"^Armado por armador:$")
RE_ARMADOR_SET_HDR = re.compile(r"^Armado por armador \(set (\d+)\):$")
RE_JUG_ARM = re.compile(r"^Jugador\s+(\S+):\s*(\d+)\s*armados$")

RE_DEF_HDR = re.compile(r"^Defensas por jugador:$")
RE_DEF_SET_HDR = re.compile(r"^Defensas por jugador \(set (\d+)\):$")
RE_JUG_DEF = re.compile(r"^Jugador\s+(\S+):\s*(\d+)\s*defensas$")
# Fila de los volcados viejos: esas pelotas ahora son defensas de calidad 0 y
# se suman ahi al leerlas.
RE_PERDIDA = re.compile(r"^Defensa perdida:\s*(\d+)\s*\([\d.]+%\)$")

RE_RECEP_HDR = re.compile(r"^Recepciones por jugador:$")
RE_RECEP_SET_HDR = re.compile(r"^Recepciones por jugador \(set (\d+)\):$")
RE_JUG_REC = re.compile(r"^Jugador\s+(\S+):\s*(\d+)\s*recepciones$")
RE_PASE = re.compile(r"^Pase al otro lado:\s*(\d+)\s*\([\d.]+%\)$")
RE_CALIDAD_CNT = re.compile(r"^Calidad\s+(\d+):\s*(\d+)\s*\([\d.]+%\)$")

RE_RECTIPO_HDR = re.compile(r"^Recepcion segun tipo de saque", re.IGNORECASE)
RE_TIPO_SAQUE = re.compile(r"^(Paralelo|Cruzado):\s*(\d+)\s*recibidos$")
RE_PAR_SAQUE = re.compile(r"^De\s+(\d+)\s+a\s+(\d+):\s*(\d+)\s*recibidos$")

# Orden de despliegue de los pares de zonas dentro de cada tipo de saque
# (debe coincidir con la clasificacion que hace analisis_voley.py).
PARES_POR_TIPO_SAQUE = {
    "Paralelo": ["1 a 5", "5 a 1", "6 a 6"],
    "Cruzado": ["1 a 1", "5 a 5", "6 a 1", "6 a 5"],
}

# Ojo: esta va SIN anclar al final, asi que hay que probar antes la variante
# por armador o se come sus lineas y pisa la matriz global.
RE_ARM_CAL_ARMADOR_HDR = re.compile(
    r"^Armado segun calidad de recepcion \(armador (\S+)\):$", re.IGNORECASE
)
RE_ARM_CAL_HDR = re.compile(r"^Armado segun calidad de recepcion", re.IGNORECASE)
RE_CALIDAD_HDR = re.compile(r"^Calidad\s+(\d+):$")
RE_HACIA_CNT = re.compile(r"^Hacia zona\s+([\w-]+):\s*(\d+)$")

RE_ATAQUES_HDR = re.compile(r"^Ataques por jugador:$")
RE_JUG_ATK = re.compile(r"^Jugador\s+(\S+):$")
RE_AT_TOTALES = re.compile(r"^Ataques totales:\s*(\d+)$")
RE_AT_EFECT = re.compile(r"^Efectivos/Punto Directo:\s*(\d+)")
RE_AT_DEF = re.compile(r"^Defendidos:\s*(\d+)")
RE_AT_FUERA = re.compile(r"^Fuera:\s*(\d+)")
RE_BLOQUEO_HDR = re.compile(r"^Bloqueos punto por jugador:$")
RE_JUG_BLOQ = re.compile(r"^Jugador\s+(\S+):\s*(\d+)\s*bloqueos punto")
RE_POR_ZONA_HDR = re.compile(r"^Por zona\s+([\w-]+):$")

RE_CALARM_HDR = re.compile(r"^Calidad de armado por armador:$")
RE_CALARM_ITEM = re.compile(
    r"^Jugador\s+(\S+):\s*A\+\s+(\d+),\s*A0\s+(\d+),\s*A-\s+(\d+),"
    r"\s*AX\s+(\d+),\s*sin calificar\s+(\d+)$"
)
CALIDADES_ARMADO = ["A+", "A0", "A-", "AX", "Sin calificar"]
CALIDADES_ARMADO_ATAQUE = ["A+", "A0", "A-", "Sin calificar"]

RE_ATKCAL_HDR = re.compile(r"^Ataque segun calidad del armado:$")
RE_ATKCAL_ITEM = re.compile(
    r"^Jugador\s+(\S+):\s*A\+\s+(\d+)-(\d+)-(\d+),\s*A0\s+(\d+)-(\d+)-(\d+),"
    r"\s*A-\s+(\d+)-(\d+)-(\d+),\s*sin calificar\s+(\d+)-(\d+)-(\d+)$"
)

RE_ATKTIPO_HDR = re.compile(r"^Ataque por tipo y direccion:$")
RE_ATKTIPO_ITEM = re.compile(
    r"^Jugador\s+(\S+)\s+-\s+(Potente|Colocado|Block out|Sin tipo)\s+-\s+zona\s+(\d):"
    r"\s*(\d+)-(\d+)-(\d+)$"
)
TIPOS_RESOLUCION = ["Potente", "Colocado", "Block out", "Sin tipo"]
DIRECCIONES_ATAQUE = ["1", "5", "6"]

RE_TOQBLOQ_HDR = re.compile(r"^Toques de bloqueo por jugador:$")
RE_JUG_TOQBLOQ = re.compile(r"^Jugador\s+(\S+):\s*(\d+)\s*toques de bloqueo")

RE_LIBRES_HDR = re.compile(r"^Libres y toques por jugador:$")
RE_JUG_LIBRE = re.compile(r"^Jugador\s+(\S+):$")
RE_LIBRE_ITEM = re.compile(
    r"^(Libre|Toque):\s*(\d+)\s*-\s*punto\s+(\d+),\s*usando el bloqueo\s+(\d+),"
    r"\s*sigue\s+(\d+),\s*malo\s+(\d+)$"
)
TIPOS_LIBRE = ["Libre", "Toque"]

RE_SAQUES_HDR = re.compile(r"^Saques por jugador:$")
RE_JUG_SAQ = re.compile(r"^Jugador\s+(\S+):\s*(\d+)\s*saques$")
RE_SAQ_ITEM = re.compile(r"^(Normal|Potencia):\s*(\d+)\s*-\s*as\s+(\d+),\s*error\s+(\d+)$")
TIPOS_SAQUE_FUERZA = ["Normal", "Potencia"]
RE_HACIA_PDF = re.compile(r"^Hacia zona\s+([\w-]+):\s*(\d+)-(\d+)-(\d+)$")


def empty_team_data():
    return {
        "fases": {"hechos": {}, "recibidos": {}},   # fase -> {total,ganados,error}
        "causas": {"hechos": {}, "recibidos": {}},  # causa -> puntos
        "zona_armador": {},         # zona(int) -> {"hechos"|"recibidos": {fase: puntos}}
        "armado_zona": {},          # zona -> cantidad
        "armado_zona_por_set": {},  # set(int) -> {zona: cantidad}
        "armado_armador": {},       # "Jugador N" -> {zona: cantidad}
        "armado_armador_por_set": {},  # set(int) -> {"Jugador N": {zona: cantidad}}
        # defender un ataque no es recibir un saque: van aparte, aunque las
        # calidades sean las mismas
        "defensas": {},             # "Jugador N" -> {cal3..cal0, pase}
        "defensas_por_set": {},     # set(int) -> {"Jugador N": {...}}
        "recepciones": {},          # "Jugador N" -> {cal3,cal2,cal1,cal0,pase}
        "recepciones_por_set": {},  # set(int) -> {"Jugador N": {cal3,...,pase}}
        "recepcion_tipo_saque": {}, # "1 a 1" -> {tipo, cal3,cal2,cal1,cal0,pase}
        "armado_calidad": {},       # calidad(int) -> {zona: cantidad}
        "armado_calidad_armador": {},  # "Jugador N" -> {calidad: {zona: cantidad}}
        "ataques_jugador": {},      # "Jugador N" -> {totales,puntos,defendidos,fuera}
        "ataques_detalle": [],      # [(jugador, zona, direccion, p, d, f), ...]
        "bloqueos_jugador": {},     # "Jugador N" -> cantidad de bloqueos punto
        # el bloqueo que toca y deja la pelota viva de su lado
        "toques_bloqueo_jugador": {},  # "Jugador N" -> cantidad
        # "Jugador N" -> {"Libre"|"Toque": {total,punto,usado,sigue,malo}}
        "libres_jugador": {},
        # "Jugador N" -> {"Normal"|"Potencia": {saques,as,error}}
        "saques_jugador": {},
        # "Jugador N" -> {"A+"|"A0"|"A-"|"AX"|"Sin calificar": cantidad}
        "calidad_armado_jugador": {},
        # "Jugador N" -> {"A+"|"A0"|"A-"|"Sin calificar": (puntos, defendidos, fuera)}
        "ataque_calidad": {},
        # [(jugador, tipo de resolucion, direccion, puntos, defendidos, fuera)]
        "ataque_tipo": [],
    }


def parse_team_block(lines):
    data = empty_team_data()
    section = None
    cur_player_rec = None
    cur_player_def = None
    cur_set_def = None
    cur_set_rec = None
    cur_set_arm = None
    cur_set_armador = None
    cur_armador = None
    cur_mat_armador = None
    cur_clase_fase = None
    cur_zona_arm = None
    cur_tipo_saque = None
    cur_par_saque = None
    cur_calidad_arm = None
    cur_player_atk = None
    cur_zona_atk = None
    cur_player_libre = None
    cur_player_saq = None

    for raw in lines:
        s = raw.strip()
        if not s:
            continue

        if RE_FASES_HDR.match(s):
            section = "fases"
            cur_clase_fase = None
            continue
        if RE_ZARM_HDR.match(s):
            section = "zona_armador"
            cur_zona_arm = None
            continue
        if RE_CAUSAS_HDR.match(s):
            section = "causas"
            cur_clase_fase = None
            continue
        m = RE_ARMADO_ZONA_SET_HDR.match(s)
        if m:
            section = "armado_zona_set"
            cur_set_arm = int(m.group(1))
            data["armado_zona_por_set"].setdefault(cur_set_arm, {})
            continue
        m = RE_ARMADOR_SET_HDR.match(s)
        if m:
            section = "armador_set"
            cur_set_armador = int(m.group(1))
            data["armado_armador_por_set"].setdefault(cur_set_armador, {})
            cur_armador = None
            continue
        if RE_ARMADOR_HDR.match(s):
            section = "armador"
            cur_armador = None
            continue
        if RE_ARMADO_ZONA_HDR.match(s):
            section = "armado_zona"
            continue
        if RE_RECTIPO_HDR.match(s):
            section = "recepcion_tipo_saque"
            cur_tipo_saque = None
            continue
        m = RE_DEF_SET_HDR.match(s)
        if m:
            section = "defensas_set"
            cur_set_def = int(m.group(1))
            data["defensas_por_set"].setdefault(cur_set_def, {})
            cur_player_def = None
            continue
        if RE_DEF_HDR.match(s):
            section = "defensas"
            cur_player_def = None
            continue
        m = RE_RECEP_SET_HDR.match(s)
        if m:
            section = "recepciones_set"
            cur_set_rec = int(m.group(1))
            data["recepciones_por_set"].setdefault(cur_set_rec, {})
            cur_player_rec = None
            continue
        if RE_RECEP_HDR.match(s):
            section = "recepciones"
            cur_player_rec = None
            continue
        m = RE_ARM_CAL_ARMADOR_HDR.match(s)
        if m:
            section = "armado_calidad_armador"
            cur_mat_armador = f"Jugador {m.group(1)}"
            data["armado_calidad_armador"].setdefault(cur_mat_armador, {})
            cur_calidad_arm = None
            continue
        if RE_ARM_CAL_HDR.match(s):
            section = "armado_calidad"
            cur_calidad_arm = None
            continue
        if RE_ATAQUES_HDR.match(s):
            section = "ataques"
            cur_player_atk = None
            cur_zona_atk = None
            continue
        if RE_BLOQUEO_HDR.match(s):
            section = "bloqueos"
            continue
        if RE_TOQBLOQ_HDR.match(s):
            section = "toques_bloqueo"
            continue
        if RE_CALARM_HDR.match(s):
            section = "calidad_armado"
            continue
        if RE_ATKCAL_HDR.match(s):
            section = "ataque_calidad"
            continue
        if RE_ATKTIPO_HDR.match(s):
            section = "ataque_tipo"
            continue
        if RE_LIBRES_HDR.match(s):
            section = "libres"
            cur_player_libre = None
            continue
        if RE_SAQUES_HDR.match(s):
            section = "saques"
            cur_player_saq = None
            continue

        if section == "fases":
            m = RE_FASE_CLASE.match(s)
            if m:
                cur_clase_fase = m.group(1).lower()
                continue
            m = RE_FASE_ITEM.match(s)
            if m and cur_clase_fase:
                data["fases"][cur_clase_fase][m.group(1)] = {
                    "total": int(m.group(2)),
                    "ganados": int(m.group(3)),
                    "error": int(m.group(4)),
                }
            continue

        if section == "zona_armador":
            m = RE_ZARM_ZONA.match(s)
            if m:
                cur_zona_arm = int(m.group(1))
                data["zona_armador"].setdefault(cur_zona_arm, {"hechos": {}, "recibidos": {}})
                continue
            m = RE_ZARM_ITEM.match(s)
            if m and cur_zona_arm is not None:
                destino = data["zona_armador"][cur_zona_arm][m.group(1).lower()]
                for parte in m.group(3).split(", "):
                    fase, cantidad = parte.rsplit(" ", 1)
                    destino[fase] = int(cantidad)
            continue

        if section == "causas":
            m = RE_FASE_CLASE.match(s)
            if m:
                cur_clase_fase = m.group(1).lower()
                continue
            m = RE_CAUSA_ITEM.match(s)
            # los subtotales "Ganados"/"Por error" se recalculan, no se leen
            causa = CAUSAS_RENOMBRADAS.get(m.group(1), m.group(1)) if m else None
            if m and cur_clase_fase and causa in CAUSAS_PUNTO:
                data["causas"][cur_clase_fase][causa] = int(m.group(2))
            continue

        if section == "armado_zona":
            m = RE_ZONA_ITEM.match(s)
            if m:
                data["armado_zona"][m.group(1)] = int(m.group(2))
            continue

        if section == "armado_zona_set":
            m = RE_ZONA_ITEM.match(s)
            if m:
                data["armado_zona_por_set"][cur_set_arm][m.group(1)] = int(m.group(2))
            continue

        if section in ("armador", "armador_set"):
            destino = (data["armado_armador"] if section == "armador"
                       else data["armado_armador_por_set"][cur_set_armador])
            m = RE_JUG_ARM.match(s)
            if m:
                cur_armador = f"Jugador {m.group(1)}"
                destino[cur_armador] = {}
                continue
            m = RE_ZONA_ITEM.match(s)
            if m and cur_armador:
                destino[cur_armador][m.group(1)] = int(m.group(2))
            # la linea "Otros jugadores: N armados" se ignora a proposito: se
            # recalcula en el Excel como total del equipo menos los armadores
            continue

        if section in ("defensas", "defensas_set"):
            destino = (data["defensas"] if section == "defensas"
                       else data["defensas_por_set"][cur_set_def])
            m = RE_JUG_DEF.match(s)
            if m:
                cur_player_def = f"Jugador {m.group(1)}"
                destino[cur_player_def] = {"cal3": 0, "cal2": 0, "cal1": 0,
                                           "cal0": 0, "pase": 0}
                continue
            if not cur_player_def:
                continue
            m = RE_PERDIDA.match(s)
            if m:
                destino[cur_player_def]["cal0"] += int(m.group(1))
                continue
            m = RE_PASE.match(s)
            if m:
                destino[cur_player_def]["pase"] = int(m.group(1))
                continue
            m = RE_CALIDAD_CNT.match(s)
            if m:
                # suma y no asigna: en un volcado viejo la fila "Defensa
                # perdida" viene ANTES que "Calidad 0" y las dos van al mismo
                # lugar; asignando, la segunda pisaba a la primera
                destino[cur_player_def][f"cal{m.group(1)}"] += int(m.group(2))
                continue
            continue

        if section == "recepciones":
            m = RE_JUG_REC.match(s)
            if m:
                cur_player_rec = f"Jugador {m.group(1)}"
                data["recepciones"][cur_player_rec] = {"cal3": 0, "cal2": 0, "cal1": 0, "cal0": 0, "pase": 0}
                continue
            m = RE_PASE.match(s)
            if m and cur_player_rec:
                data["recepciones"][cur_player_rec]["pase"] = int(m.group(1))
                continue
            m = RE_CALIDAD_CNT.match(s)
            if m and cur_player_rec:
                data["recepciones"][cur_player_rec][f"cal{m.group(1)}"] = int(m.group(2))
                continue
            continue

        if section == "recepciones_set":
            destino = data["recepciones_por_set"][cur_set_rec]
            m = RE_JUG_REC.match(s)
            if m:
                cur_player_rec = f"Jugador {m.group(1)}"
                destino[cur_player_rec] = {"cal3": 0, "cal2": 0, "cal1": 0, "cal0": 0, "pase": 0}
                continue
            m = RE_PASE.match(s)
            if m and cur_player_rec:
                destino[cur_player_rec]["pase"] = int(m.group(1))
                continue
            m = RE_CALIDAD_CNT.match(s)
            if m and cur_player_rec:
                destino[cur_player_rec][f"cal{m.group(1)}"] = int(m.group(2))
                continue
            continue

        if section == "recepcion_tipo_saque":
            m = RE_TIPO_SAQUE.match(s)
            if m:
                cur_tipo_saque = m.group(1)
                cur_par_saque = None
                continue
            m = RE_PAR_SAQUE.match(s)
            if m and cur_tipo_saque:
                cur_par_saque = f"{m.group(1)} a {m.group(2)}"
                data["recepcion_tipo_saque"][cur_par_saque] = {
                    "tipo": cur_tipo_saque, "cal3": 0, "cal2": 0, "cal1": 0, "cal0": 0, "pase": 0,
                }
                continue
            m = RE_PASE.match(s)
            if m and cur_par_saque:
                data["recepcion_tipo_saque"][cur_par_saque]["pase"] = int(m.group(1))
                continue
            m = RE_CALIDAD_CNT.match(s)
            if m and cur_par_saque:
                data["recepcion_tipo_saque"][cur_par_saque][f"cal{m.group(1)}"] = int(m.group(2))
                continue
            continue

        if section == "armado_calidad":
            m = RE_CALIDAD_HDR.match(s)
            if m:
                cur_calidad_arm = int(m.group(1))
                data["armado_calidad"].setdefault(cur_calidad_arm, {})
                continue
            m = RE_HACIA_CNT.match(s)
            if m and cur_calidad_arm is not None:
                data["armado_calidad"][cur_calidad_arm][m.group(1)] = int(m.group(2))
                continue
            continue

        if section == "armado_calidad_armador":
            destino = data["armado_calidad_armador"][cur_mat_armador]
            m = RE_CALIDAD_HDR.match(s)
            if m:
                cur_calidad_arm = int(m.group(1))
                destino.setdefault(cur_calidad_arm, {})
                continue
            m = RE_HACIA_CNT.match(s)
            if m and cur_calidad_arm is not None:
                destino[cur_calidad_arm][m.group(1)] = int(m.group(2))
                continue
            continue

        if section == "ataques":
            m = RE_JUG_ATK.match(s)
            if m:
                cur_player_atk = f"Jugador {m.group(1)}"
                cur_zona_atk = None
                data["ataques_jugador"][cur_player_atk] = {"totales": 0, "puntos": 0, "defendidos": 0, "fuera": 0}
                continue
            m = RE_AT_TOTALES.match(s)
            if m and cur_player_atk:
                data["ataques_jugador"][cur_player_atk]["totales"] = int(m.group(1))
                continue
            m = RE_AT_EFECT.match(s)
            if m and cur_player_atk:
                data["ataques_jugador"][cur_player_atk]["puntos"] = int(m.group(1))
                continue
            m = RE_AT_DEF.match(s)
            if m and cur_player_atk:
                data["ataques_jugador"][cur_player_atk]["defendidos"] = int(m.group(1))
                continue
            m = RE_AT_FUERA.match(s)
            if m and cur_player_atk:
                data["ataques_jugador"][cur_player_atk]["fuera"] = int(m.group(1))
                continue
            m = RE_POR_ZONA_HDR.match(s)
            if m:
                cur_zona_atk = m.group(1)
                continue
            m = RE_HACIA_PDF.match(s)
            if m and cur_player_atk and cur_zona_atk:
                p, d, f = int(m.group(2)), int(m.group(3)), int(m.group(4))
                if p or d or f:
                    data["ataques_detalle"].append((cur_player_atk, cur_zona_atk, m.group(1), p, d, f))
                continue
            continue

        if section == "bloqueos":
            m = RE_JUG_BLOQ.match(s)
            if m:
                # el volcado trae tambien una linea "Total:", que se ignora
                data["bloqueos_jugador"][f"Jugador {m.group(1)}"] = int(m.group(2))
            continue

        if section == "calidad_armado":
            m = RE_CALARM_ITEM.match(s)
            if m:
                data["calidad_armado_jugador"][f"Jugador {m.group(1)}"] = {
                    calidad: int(m.group(i)) for i, calidad in enumerate(CALIDADES_ARMADO, start=2)
                }
            continue

        if section == "ataque_calidad":
            m = RE_ATKCAL_ITEM.match(s)
            if m:
                numeros = [int(x) for x in m.groups()[1:]]
                data["ataque_calidad"][f"Jugador {m.group(1)}"] = {
                    calidad: tuple(numeros[3 * i:3 * i + 3])
                    for i, calidad in enumerate(CALIDADES_ARMADO_ATAQUE)
                }
            continue

        if section == "ataque_tipo":
            m = RE_ATKTIPO_ITEM.match(s)
            if m:
                data["ataque_tipo"].append((f"Jugador {m.group(1)}", m.group(2), m.group(3),
                                            int(m.group(4)), int(m.group(5)), int(m.group(6))))
            continue

        if section == "toques_bloqueo":
            m = RE_JUG_TOQBLOQ.match(s)
            if m:
                data["toques_bloqueo_jugador"][f"Jugador {m.group(1)}"] = int(m.group(2))
            continue

        if section == "libres":
            m = RE_JUG_LIBRE.match(s)
            if m:
                cur_player_libre = f"Jugador {m.group(1)}"
                data["libres_jugador"][cur_player_libre] = {}
                continue
            m = RE_LIBRE_ITEM.match(s)
            if m and cur_player_libre:
                total, punto, usado, sigue, malo = (int(m.group(i)) for i in range(2, 7))
                data["libres_jugador"][cur_player_libre][m.group(1)] = {
                    "total": total, "punto": punto, "usado": usado,
                    "sigue": sigue, "malo": malo,
                }
            continue

        if section == "saques":
            m = RE_JUG_SAQ.match(s)
            if m:
                cur_player_saq = f"Jugador {m.group(1)}"
                data["saques_jugador"][cur_player_saq] = {}
                continue
            m = RE_SAQ_ITEM.match(s)
            if m and cur_player_saq:
                data["saques_jugador"][cur_player_saq][m.group(1)] = {
                    "saques": int(m.group(2)), "as": int(m.group(3)), "error": int(m.group(4)),
                }
            continue

    return data


def reconcile_sin_registrar(data, warnings, team_name):
    """Agrega filas 'Sin registrar' cuando el detalle por zona/direccion no
    alcanza al total declarado por jugador, y avisa de la diferencia."""
    detalle_sum = defaultdict(lambda: [0, 0, 0])
    for jugador, _zona, _dir, p, d, f in data["ataques_detalle"]:
        s = detalle_sum[jugador]
        s[0] += p
        s[1] += d
        s[2] += f

    extra_rows = []
    for jugador, tot in data["ataques_jugador"].items():
        s = detalle_sum.get(jugador, [0, 0, 0])
        miss_p = tot["puntos"] - s[0]
        miss_d = tot["defendidos"] - s[1]
        miss_f = tot["fuera"] - s[2]
        if miss_p < 0 or miss_d < 0 or miss_f < 0:
            warnings.append(
                f"[{team_name}] {jugador}: el detalle por zona/direccion de ataque supera el total "
                f"declarado (revisar volcado original)."
            )
            continue
        if miss_p or miss_d or miss_f:
            extra_rows.append((jugador, "Sin registrar", "Sin registrar", miss_p, miss_d, miss_f))
            warnings.append(
                f"[{team_name}] {jugador}: {miss_p + miss_d + miss_f} ataque(s) sin zona/direccion "
                f"registrada en el volcado (Puntos {miss_p}, Defendidos {miss_d}, Fuera {miss_f})."
            )
    data["ataques_detalle"].extend(extra_rows)


def parse_volcado(text):
    lines = text.splitlines()

    sets_rows = []       # [(set_num, team1_score, team2_score), ...]
    team1_name = team2_name = None
    total_puntos_cargados = None
    marcador_final = None

    teams_raw = {}  # team_name -> list of lines belonging to that block

    idx_equipo_section = None
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s == "=== Estadisticas por equipo ===":
            idx_equipo_section = i
            break
        m = RE_SET_LINE.match(s)
        if m:
            set_num = int(m.group(1))
            team1_name = team1_name or m.group(2).strip()
            team2_name = team2_name or m.group(5).strip()
            sets_rows.append((set_num, int(m.group(3)), int(m.group(4))))
            continue
        m = RE_MARCADOR_FINAL.match(s)
        if m:
            marcador_final = (m.group(1).strip(), int(m.group(2)),
                              int(m.group(3)), m.group(4).strip())
            continue
        m = RE_TOTAL_PUNTOS.match(s)
        if m:
            total_puntos_cargados = int(m.group(1))

    if not sets_rows and marcador_final is not None:
        # partido de un solo set: se arma la unica fila con el marcador final,
        # porque sin filas los rangos de la hoja Partido quedan vacios y las
        # formulas terminan referenciandose a si mismas
        team1_name, tantos1, tantos2, team2_name = marcador_final
        sets_rows.append((1, tantos1, tantos2))

    if idx_equipo_section is not None:
        current_team = None
        for raw in lines[idx_equipo_section + 1:]:
            s = raw.strip()
            m = RE_TEAM_HDR.match(s)
            if m:
                current_team = m.group(1)
                teams_raw[current_team] = []
                continue
            if current_team is not None:
                teams_raw[current_team].append(raw)

    teams = {name: parse_team_block(block_lines) for name, block_lines in teams_raw.items()}

    return {
        "sets_rows": sets_rows,
        "team1_name": team1_name,
        "team2_name": team2_name,
        "total_puntos_cargados": total_puntos_cargados,
        "teams": teams,
    }


# ======================================================================
# 2) ESTILOS Y HELPERS DE EXCEL
# ======================================================================

DARK_BLUE = "1F3864"
MED_BLUE = "2E5C9A"
LIGHT_GRAY = "F2F2F2"
WHITE = "FFFFFF"
GRAY_BORDER = "BFBFBF"
FONT_NAME = "Arial"
PCT_FMT = "0.0%"

thin = Side(style="thin", color=GRAY_BORDER)
BORDER_ALL = Border(left=thin, right=thin, top=thin, bottom=thin)

title_font = Font(name=FONT_NAME, size=14, bold=True, color=WHITE)
title_fill = PatternFill("solid", fgColor=DARK_BLUE)
subtitle_font = Font(name=FONT_NAME, size=11, bold=True, color=WHITE)
subtitle_fill = PatternFill("solid", fgColor=MED_BLUE)
header_font = Font(name=FONT_NAME, size=10, bold=True, color=WHITE)
header_fill = PatternFill("solid", fgColor=MED_BLUE)
data_font = Font(name=FONT_NAME, size=10)
data_font_bold = Font(name=FONT_NAME, size=10, bold=True)
total_fill = PatternFill("solid", fgColor=LIGHT_GRAY)
footnote_font = Font(name=FONT_NAME, size=9, italic=True, color="595959")

center = Alignment(horizontal="center", vertical="center", wrap_text=True)
center_nowrap = Alignment(horizontal="center", vertical="center")
left = Alignment(horizontal="left", vertical="center")


def new_sheet(wb, name):
    ws = wb.create_sheet(name)
    ws.sheet_view.showGridLines = False
    return ws


def set_title(ws, row, col_start, col_end, text):
    ws.merge_cells(start_row=row, start_column=col_start, end_row=row, end_column=col_end)
    c = ws.cell(row=row, column=col_start, value=text)
    c.font = title_font
    c.alignment = center_nowrap
    ws.row_dimensions[row].height = 22
    for col in range(col_start, col_end + 1):
        ws.cell(row=row, column=col).fill = title_fill
    return row + 2


def set_subtitle(ws, row, col_start, col_end, text):
    ws.merge_cells(start_row=row, start_column=col_start, end_row=row, end_column=col_end)
    c = ws.cell(row=row, column=col_start, value=text)
    c.font = subtitle_font
    c.alignment = center_nowrap
    ws.row_dimensions[row].height = 18
    for col in range(col_start, col_end + 1):
        ws.cell(row=row, column=col).fill = subtitle_fill
    return row + 1


def set_nota(ws, row, col_start, col_end, texto):
    """Una linea de texto explicando la hoja, debajo del titulo.

    Va adentro del archivo y no en un instructivo aparte: el Excel se manda
    por WhatsApp y se abre en el celular de alguien que no tiene el resto a
    mano."""
    ws.merge_cells(start_row=row, start_column=col_start, end_row=row, end_column=col_end)
    c = ws.cell(row=row, column=col_start, value=texto)
    c.font = Font(name="Calibri", size=9, italic=True, color="5B6B7E")
    c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
    ws.row_dimensions[row].height = 30
    return row + 2


def set_headers(ws, row, col_start, headers):
    for i, h in enumerate(headers):
        c = ws.cell(row=row, column=col_start + i, value=h)
        c.font = header_font
        c.fill = header_fill
        c.alignment = center
        c.border = BORDER_ALL
    return row + 1


# Cuando una tabla no tiene filas (o no tiene columnas) el rango del total sale
# dado vuelta: SUM(B5:B4) si faltan filas, SUM(B11:A11) si faltan columnas.
# Excel los lee al reves, con lo cual el rango termina incluyendo a la propia
# celda del total y da referencia circular. Si no hay nada que sumar, es 0.
RE_RANGO_PROPIO = re.compile(r"SUM\(\$?([A-Z]{1,3})\$?(\d+):\$?([A-Z]{1,3})\$?(\d+)\)")


def sin_rangos_invertidos(formula: str) -> str:
    def reemplazo(m):
        col1, fila1, col2, fila2 = m.group(1), int(m.group(2)), m.group(3), int(m.group(4))
        vacio = (fila2 < fila1
                 or column_index_from_string(col2) < column_index_from_string(col1))
        return "0" if vacio else m.group(0)

    return RE_RANGO_PROPIO.sub(reemplazo, formula)


def set_data_row(ws, row, col_start, values, formats=None, total=False):
    for i, v in enumerate(values):
        if isinstance(v, str) and v.startswith("="):
            v = sin_rangos_invertidos(v)
        c = ws.cell(row=row, column=col_start + i, value=v)
        c.border = BORDER_ALL
        if i == 0:
            c.font = data_font_bold
            c.alignment = left
        else:
            c.font = data_font
            c.alignment = center_nowrap
        if formats and formats[i]:
            c.number_format = formats[i]
        if total:
            c.fill = total_fill
            c.font = Font(name=FONT_NAME, size=10, bold=True)
    return row + 1


def set_footnote(ws, row, col_start, col_end, text):
    ws.merge_cells(start_row=row, start_column=col_start, end_row=row, end_column=col_end)
    c = ws.cell(row=row, column=col_start, value=text)
    c.font = footnote_font
    c.alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)
    ws.row_dimensions[row].height = 26
    return row + 1


def autosize(ws, widths):
    for col, width in widths.items():
        ws.column_dimensions[col].width = width


def col_letter(n):
    return get_column_letter(n)


# ======================================================================
# 3) CONSTRUCCION DEL LIBRO
# ======================================================================

def poner_nombres(data, nombres):
    """Le agrega el nombre a cada "Jugador N" de este equipo.

    Se renombra la CLAVE y no solo la etiqueta que se ve. En el informe el
    mismo texto es las dos cosas: lo que dice la celda y el criterio con el
    que las formulas suman desde Datos_Base. Cambiar una sola de las dos
    dejaria las tablas en cero, que es justo el bug que costo encontrar la
    otra vez."""
    if not nombres:
        return data

    def etiqueta(clave):
        dorsal = str(clave).replace("Jugador", "").strip()
        nombre = nombres.get(dorsal)
        return f"{clave} · {nombre}" if nombre else clave

    por_jugador = ("armado_armador", "recepciones", "armado_calidad_armador",
                   "ataques_jugador", "bloqueos_jugador", "toques_bloqueo_jugador",
                   "libres_jugador", "saques_jugador", "calidad_armado_jugador",
                   "ataque_calidad")
    for campo in por_jugador:
        data[campo] = {etiqueta(j): v for j, v in data[campo].items()}
    for campo in ("armado_armador_por_set", "recepciones_por_set"):
        data[campo] = {s: {etiqueta(j): v for j, v in por.items()}
                       for s, por in data[campo].items()}
    for campo in ("ataques_detalle", "ataque_tipo"):
        data[campo] = [(etiqueta(j),) + tuple(resto) for j, *resto in data[campo]]
    return data


def build_workbook(equipo_name, rival_name, parsed, nombres=None):
    data = poner_nombres(parsed["teams"][equipo_name], nombres)
    warnings = []
    reconcile_sin_registrar(data, warnings, equipo_name)

    # --- ordenes de despliegue (por volumen), calculados desde los datos ---
    rec_players = sorted(data["recepciones"].keys(),
                          key=lambda j: -sum(v for k, v in data["recepciones"][j].items()))

    def_players = sorted(data["defensas"].keys(),
                         key=lambda j: -sum(v for k, v in data["defensas"][j].items()))

    armz_zonas = sorted(data["armado_zona"].keys(), key=lambda z: -data["armado_zona"][z])
    arm_sets = sorted(data["armado_zona_por_set"])
    armadores = sorted(data["armado_armador"],
                       key=lambda j: -sum(data["armado_armador"][j].values()))

    armq_zonas_set = set()
    for cal, zonas in data["armado_calidad"].items():
        armq_zonas_set |= set(zonas.keys())
    matriz_arm_zonas = armz_zonas + [z for z in sorted(armq_zonas_set) if z not in armz_zonas]

    atk_players = sorted(data["ataques_jugador"].keys(), key=lambda j: -data["ataques_jugador"][j]["totales"])
    bloq_players = sorted(data["bloqueos_jugador"], key=lambda j: (-data["bloqueos_jugador"][j], j))
    toqbloq_players = sorted(data["toques_bloqueo_jugador"],
                             key=lambda j: (-data["toques_bloqueo_jugador"][j], j))
    # solo las combinaciones jugador/tipo que pasaron alguna vez
    libre_filas = sorted(
        ((j, tipo) for j, tipos in data["libres_jugador"].items()
         for tipo in TIPOS_LIBRE if tipos.get(tipo, {}).get("total")),
        key=lambda jt: (-data["libres_jugador"][jt[0]][jt[1]]["total"], jt[0], jt[1]))
    calarm_players = sorted(
        data["calidad_armado_jugador"],
        key=lambda j: (-sum(data["calidad_armado_jugador"][j].values()), j))
    # (jugador, calidad) que tuvieron algun ataque, ordenados por jugador
    atkcal_filas = [(j, cal) for j in sorted(data["ataque_calidad"],
                                             key=lambda j: -sum(map(sum, data["ataque_calidad"][j].values())))
                    for cal in CALIDADES_ARMADO_ATAQUE if sum(data["ataque_calidad"][j][cal])]
    vol_tipo = defaultdict(int)
    for j, tipo, _dr, p_, d_, f_ in data["ataque_tipo"]:
        vol_tipo[(j, tipo)] += p_ + d_ + f_
    atktipo_filas = sorted(vol_tipo, key=lambda jt: (-sum(v for (j, _), v in vol_tipo.items()
                                                          if j == jt[0]), jt[0],
                                                     TIPOS_RESOLUCION.index(jt[1])))
    saq_players = sorted(
        data["saques_jugador"],
        key=lambda j: (-sum(t["saques"] for t in data["saques_jugador"][j].values()), j))

    zona_vol, dir_vol = defaultdict(int), defaultdict(int)
    for jugador, zona, direccion, p, d, f in data["ataques_detalle"]:
        if zona != "Sin registrar":
            zona_vol[zona] += p + d + f
        if direccion != "Sin registrar":
            dir_vol[direccion] += p + d + f
    atk_zonas = sorted(zona_vol.keys(), key=lambda z: -zona_vol[z])
    atk_dirs = sorted(dir_vol.keys(), key=lambda d: -dir_vol[d])

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    # ------------------------------------------------------------------
    # Hoja oculta Datos_Base
    # ------------------------------------------------------------------
    db = new_sheet(wb, "Datos_Base")

    db["A1"] = "Jugador"; db["B1"] = "Cal3"; db["C1"] = "Cal2"; db["D1"] = "Cal1"; db["E1"] = "Cal0"; db["F1"] = "Pase"
    rec_items = list(data["recepciones"].items())
    for i, (j, v) in enumerate(rec_items, start=2):
        db.cell(row=i, column=1, value=j)
        db.cell(row=i, column=2, value=v["cal3"])
        db.cell(row=i, column=3, value=v["cal2"])
        db.cell(row=i, column=4, value=v["cal1"])
        db.cell(row=i, column=5, value=v["cal0"])
        db.cell(row=i, column=6, value=v["pase"])
    REC_LAST = 1 + max(len(rec_items), 1)

    db["AJ1"] = "Set"; db["AK1"] = "Jugador"; db["AL1"] = "Cal3"; db["AM1"] = "Cal2"
    db["AN1"] = "Cal1"; db["AO1"] = "Cal0"; db["AP1"] = "Pase"
    recset_rows = [
        (numero, jugador, v)
        for numero in sorted(data["recepciones_por_set"])
        for jugador, v in data["recepciones_por_set"][numero].items()
    ]
    for i, (numero, jugador, v) in enumerate(recset_rows, start=2):
        db.cell(row=i, column=36, value=numero)
        db.cell(row=i, column=37, value=jugador)
        db.cell(row=i, column=38, value=v["cal3"])
        db.cell(row=i, column=39, value=v["cal2"])
        db.cell(row=i, column=40, value=v["cal1"])
        db.cell(row=i, column=41, value=v["cal0"])
        db.cell(row=i, column=42, value=v["pase"])
    RECSET_LAST = 1 + max(len(recset_rows), 1)

    # Defensa: las mismas columnas que recepcion. La pelota que no se llega a
    # jugar es una defensa de calidad 0 y se cuenta en Cal0.
    db["CB1"] = "Jugador"; db["CC1"] = "Cal3"; db["CD1"] = "Cal2"; db["CE1"] = "Cal1"
    db["CF1"] = "Cal0"; db["CG1"] = "Pase"
    def_items = list(data["defensas"].items())
    for i, (j, v) in enumerate(def_items, start=2):
        for columna, clave in ((80, None), (81, "cal3"), (82, "cal2"), (83, "cal1"),
                               (84, "cal0"), (85, "pase")):
            db.cell(row=i, column=columna, value=j if clave is None else v.get(clave, 0))
    DEF_LAST = 1 + max(len(def_items), 1)

    db["CJ1"] = "Set"; db["CK1"] = "Jugador"; db["CL1"] = "Cal3"; db["CM1"] = "Cal2"
    db["CN1"] = "Cal1"; db["CO1"] = "Cal0"; db["CP1"] = "Pase"
    defset_rows = [
        (numero, jugador, v)
        for numero in sorted(data["defensas_por_set"])
        for jugador, v in data["defensas_por_set"][numero].items()
    ]
    for i, (numero, jugador, v) in enumerate(defset_rows, start=2):
        db.cell(row=i, column=88, value=numero)
        db.cell(row=i, column=89, value=jugador)
        for columna, clave in ((90, "cal3"), (91, "cal2"), (92, "cal1"),
                               (93, "cal0"), (94, "pase")):
            db.cell(row=i, column=columna, value=v.get(clave, 0))
    DEFSET_LAST = 1 + max(len(defset_rows), 1)

    db["AB1"] = "TipoSaque"; db["AC1"] = "ParZonas"; db["AD1"] = "Cal3"; db["AE1"] = "Cal2"
    db["AF1"] = "Cal1"; db["AG1"] = "Cal0"; db["AH1"] = "Pase"
    rectipo_items = list(data["recepcion_tipo_saque"].items())
    for i, (par, v) in enumerate(rectipo_items, start=2):
        db.cell(row=i, column=28, value=v["tipo"])
        db.cell(row=i, column=29, value=par)
        db.cell(row=i, column=30, value=v["cal3"])
        db.cell(row=i, column=31, value=v["cal2"])
        db.cell(row=i, column=32, value=v["cal1"])
        db.cell(row=i, column=33, value=v["cal0"])
        db.cell(row=i, column=34, value=v["pase"])
    RECTIPO_LAST = 1 + max(len(rectipo_items), 1)

    db["H1"] = "Zona"; db["I1"] = "Armados"
    armz_items = list(data["armado_zona"].items())
    for i, (z, v) in enumerate(armz_items, start=2):
        db.cell(row=i, column=8, value=z)
        db.cell(row=i, column=9, value=v)
    ARMZ_LAST = 1 + max(len(armz_items), 1)

    db["K1"] = "Calidad"; db["L1"] = "Zona"; db["M1"] = "Cantidad"
    armq_rows = [(cal, z, cnt) for cal, zonas in data["armado_calidad"].items() for z, cnt in zonas.items()]
    for i, (cal, z, cnt) in enumerate(armq_rows, start=2):
        db.cell(row=i, column=11, value=cal)
        db.cell(row=i, column=12, value=z)
        db.cell(row=i, column=13, value=cnt)
    ARMQ_LAST = 1 + max(len(armq_rows), 1)

    db["O1"] = "Jugador"; db["P1"] = "AtaquesTotales"; db["Q1"] = "Puntos"; db["R1"] = "Defendidos"; db["S1"] = "Fuera"
    atkj_items = list(data["ataques_jugador"].items())
    for i, (j, v) in enumerate(atkj_items, start=2):
        db.cell(row=i, column=15, value=j)
        db.cell(row=i, column=16, value=v["totales"])
        db.cell(row=i, column=17, value=v["puntos"])
        db.cell(row=i, column=18, value=v["defendidos"])
        db.cell(row=i, column=19, value=v["fuera"])
    ATKJ_LAST = 1 + max(len(atkj_items), 1)

    db["U1"] = "Jugador"; db["V1"] = "ZonaOrigen"; db["W1"] = "Direccion"; db["X1"] = "Puntos"; db["Y1"] = "Defendidos"; db["Z1"] = "Fuera"
    atkd_rows = data["ataques_detalle"]
    for i, (j, z, dr, p, d, f) in enumerate(atkd_rows, start=2):
        db.cell(row=i, column=21, value=j)
        db.cell(row=i, column=22, value=z)
        db.cell(row=i, column=23, value=dr)
        db.cell(row=i, column=24, value=p)
        db.cell(row=i, column=25, value=d)
        db.cell(row=i, column=26, value=f)
    ATKD_LAST = 1 + max(len(atkd_rows), 1)

    db["AU1"] = "Set"; db["AV1"] = "Zona"; db["AW1"] = "Armados"
    armzset_rows = [(numero, z, cnt)
                    for numero in sorted(data["armado_zona_por_set"])
                    for z, cnt in data["armado_zona_por_set"][numero].items()]
    for i, (numero, z, cnt) in enumerate(armzset_rows, start=2):
        db.cell(row=i, column=47, value=numero)
        db.cell(row=i, column=48, value=z)
        db.cell(row=i, column=49, value=cnt)
    ARMZSET_LAST = 1 + max(len(armzset_rows), 1)

    db["AY1"] = "Armador"; db["AZ1"] = "Zona"; db["BA1"] = "Armados"
    armador_rows = [(j, z, cnt)
                    for j in data["armado_armador"]
                    for z, cnt in data["armado_armador"][j].items()]
    for i, (j, z, cnt) in enumerate(armador_rows, start=2):
        db.cell(row=i, column=51, value=j)
        db.cell(row=i, column=52, value=z)
        db.cell(row=i, column=53, value=cnt)
    ARMADOR_LAST = 1 + max(len(armador_rows), 1)

    db["BC1"] = "Set"; db["BD1"] = "Armador"; db["BE1"] = "Zona"; db["BF1"] = "Armados"
    armadorset_rows = [(numero, j, z, cnt)
                       for numero in sorted(data["armado_armador_por_set"])
                       for j in data["armado_armador_por_set"][numero]
                       for z, cnt in data["armado_armador_por_set"][numero][j].items()]
    for i, (numero, j, z, cnt) in enumerate(armadorset_rows, start=2):
        db.cell(row=i, column=55, value=numero)
        db.cell(row=i, column=56, value=j)
        db.cell(row=i, column=57, value=z)
        db.cell(row=i, column=58, value=cnt)
    ARMADORSET_LAST = 1 + max(len(armadorset_rows), 1)

    db["BH1"] = "Armador"; db["BI1"] = "Calidad"; db["BJ1"] = "Zona"; db["BK1"] = "Cantidad"
    matarm_rows = [(j, cal, z, cnt)
                   for j, cals in data["armado_calidad_armador"].items()
                   for cal, zonas in cals.items()
                   for z, cnt in zonas.items()]
    for i, (j, cal, z, cnt) in enumerate(matarm_rows, start=2):
        db.cell(row=i, column=60, value=j)
        db.cell(row=i, column=61, value=cal)
        db.cell(row=i, column=62, value=z)
        db.cell(row=i, column=63, value=cnt)
    MATARM_LAST = 1 + max(len(matarm_rows), 1)

    db["BM1"] = "Clase"; db["BN1"] = "Fase"; db["BO1"] = "Puntos"
    db["BP1"] = "Ganados"; db["BQ1"] = "PorError"
    fases_rows = [(clase, fase, data["fases"][clase].get(fase, {}))
                  for clase in ("hechos", "recibidos") for fase in FASES_RALLY]
    for i, (clase, fase, d) in enumerate(fases_rows, start=2):
        db.cell(row=i, column=65, value=clase)
        db.cell(row=i, column=66, value=fase)
        db.cell(row=i, column=67, value=d.get("total", 0))
        db.cell(row=i, column=68, value=d.get("ganados", 0))
        db.cell(row=i, column=69, value=d.get("error", 0))
    FASES_LAST = 1 + max(len(fases_rows), 1)

    db["BS1"] = "Clase"; db["BT1"] = "Causa"; db["BU1"] = "Puntos"
    causas_rows = [(clase, causa, data["causas"][clase].get(causa, 0))
                   for clase in ("hechos", "recibidos") for causa in CAUSAS_PUNTO]
    for i, (clase, causa, cnt) in enumerate(causas_rows, start=2):
        db.cell(row=i, column=71, value=clase)
        db.cell(row=i, column=72, value=causa)
        db.cell(row=i, column=73, value=cnt)
    CAUSAS_LAST = 1 + max(len(causas_rows), 1)

    db["BW1"] = "ZonaArmador"; db["BX1"] = "Clase"; db["BY1"] = "Fase"; db["BZ1"] = "Puntos"
    zarm_rows = [(z, clase, fase, data["zona_armador"].get(z, {}).get(clase, {}).get(fase, 0))
                 for z in ZONAS_ARMADOR for clase in ("hechos", "recibidos")
                 for fase in COLUMNAS_ZARM]
    for i, (z, clase, fase, cnt) in enumerate(zarm_rows, start=2):
        db.cell(row=i, column=75, value=z)
        db.cell(row=i, column=76, value=clase)
        db.cell(row=i, column=77, value=fase)
        db.cell(row=i, column=78, value=cnt)
    ZARM_LAST = 1 + max(len(zarm_rows), 1)

    db["AR1"] = "Jugador"; db["AS1"] = "BloqueosPunto"
    bloq_items = sorted(data["bloqueos_jugador"].items(), key=lambda kv: (-kv[1], kv[0]))
    for i, (j, v) in enumerate(bloq_items, start=2):
        db.cell(row=i, column=44, value=j)
        db.cell(row=i, column=45, value=v)
    BLOQ_LAST = 1 + max(len(bloq_items), 1)

    db["CR1"] = "Jugador"; db["CS1"] = "ToquesBloqueo"
    toqbloq_items = sorted(data["toques_bloqueo_jugador"].items(), key=lambda kv: (-kv[1], kv[0]))
    for i, (j, v) in enumerate(toqbloq_items, start=2):
        db.cell(row=i, column=96, value=j)
        db.cell(row=i, column=97, value=v)
    TOQBLOQ_LAST = 1 + max(len(toqbloq_items), 1)

    db["CU1"] = "Jugador"; db["CV1"] = "Tipo"; db["CW1"] = "Total"; db["CX1"] = "Punto"
    db["CY1"] = "UsandoBloqueo"; db["CZ1"] = "Sigue"; db["DA1"] = "Malo"
    libre_rows = [(j, tipo, d) for j, tipos in data["libres_jugador"].items()
                  for tipo, d in tipos.items()]
    for i, (j, tipo, d) in enumerate(libre_rows, start=2):
        db.cell(row=i, column=99, value=j)
        db.cell(row=i, column=100, value=tipo)
        for columna, clave in ((101, "total"), (102, "punto"), (103, "usado"),
                               (104, "sigue"), (105, "malo")):
            db.cell(row=i, column=columna, value=d.get(clave, 0))
    LIBRE_LAST = 1 + max(len(libre_rows), 1)

    db["DC1"] = "Jugador"; db["DD1"] = "Tipo"; db["DE1"] = "Saques"; db["DF1"] = "As"; db["DG1"] = "Error"
    saq_rows = [(j, tipo, d) for j, tipos in data["saques_jugador"].items()
                for tipo, d in tipos.items()]
    for i, (j, tipo, d) in enumerate(saq_rows, start=2):
        db.cell(row=i, column=107, value=j)
        db.cell(row=i, column=108, value=tipo)
        db.cell(row=i, column=109, value=d.get("saques", 0))
        db.cell(row=i, column=110, value=d.get("as", 0))
        db.cell(row=i, column=111, value=d.get("error", 0))
    SAQ_LAST = 1 + max(len(saq_rows), 1)

    db["DI1"] = "Armador"; db["DJ1"] = "CalidadArmado"; db["DK1"] = "Cantidad"
    calarm_rows = [(j, cal, cnt) for j, cals in data["calidad_armado_jugador"].items()
                   for cal, cnt in cals.items()]
    for i, (j, cal, cnt) in enumerate(calarm_rows, start=2):
        db.cell(row=i, column=113, value=j)
        db.cell(row=i, column=114, value=cal)
        db.cell(row=i, column=115, value=cnt)
    CALARM_LAST = 1 + max(len(calarm_rows), 1)

    db["DM1"] = "Jugador"; db["DN1"] = "CalidadArmado"; db["DO1"] = "Puntos"
    db["DP1"] = "Defendidos"; db["DQ1"] = "Fuera"
    atkcal_rows = [(j, cal, pdf) for j, cals in data["ataque_calidad"].items()
                   for cal, pdf in cals.items()]
    for i, (j, cal, (p_, d_, f_)) in enumerate(atkcal_rows, start=2):
        db.cell(row=i, column=117, value=j)
        db.cell(row=i, column=118, value=cal)
        db.cell(row=i, column=119, value=p_)
        db.cell(row=i, column=120, value=d_)
        db.cell(row=i, column=121, value=f_)
    ATKCAL_LAST = 1 + max(len(atkcal_rows), 1)

    db["DS1"] = "Jugador"; db["DT1"] = "TipoResolucion"; db["DU1"] = "Direccion"
    db["DV1"] = "Puntos"; db["DW1"] = "Defendidos"; db["DX1"] = "Fuera"
    for i, (j, tipo, dr, p_, d_, f_) in enumerate(data["ataque_tipo"], start=2):
        for columna, valor in zip(range(123, 129), (j, tipo, dr, p_, d_, f_)):
            db.cell(row=i, column=columna, value=valor)
    ATKTIPO_LAST = 1 + max(len(data["ataque_tipo"]), 1)

    for col in ["A", "B", "C", "D", "E", "F", "H", "I", "K", "L", "M", "O", "P", "Q", "R", "S", "U", "V", "W", "X", "Y", "Z",
                "AB", "AC", "AD", "AE", "AF", "AG", "AH",
                "AJ", "AK", "AL", "AM", "AN", "AO", "AP", "AR", "AS",
                "AU", "AV", "AW", "AY", "AZ", "BA", "BC", "BD", "BE", "BF",
                "BH", "BI", "BJ", "BK", "BM", "BN", "BO", "BP", "BQ",
                "BS", "BT", "BU", "BW", "BX", "BY", "BZ",
                "CR", "CS", "CU", "CV", "CW", "CX", "CY", "CZ", "DA",
                "DC", "DD", "DE", "DF", "DG", "DI", "DJ", "DK",
                "DM", "DN", "DO", "DP", "DQ", "DS", "DT", "DU", "DV", "DW", "DX"]:
        db.column_dimensions[col].width = 13

    D = "Datos_Base!"

    def rng(col, last_row):
        return f"${col}$2:${col}${last_row}"

    def sumif(value_col, last_row, crit_col, crit):
        return f"SUMIF({D}{rng(crit_col, last_row)},\"{crit}\",{D}{rng(value_col, last_row)})"

    def sumifs_tres(value_col, last_row, col1, val1, col2, val2, col3, val3):
        """SUMIFS con tres criterios (el primero puede ser numerico)."""
        crit1 = val1 if isinstance(val1, int) else f'"{val1}"'
        return (f'SUMIFS({D}{rng(value_col, last_row)},'
                f'{D}{rng(col1, last_row)},{crit1},'
                f'{D}{rng(col2, last_row)},"{val2}",'
                f'{D}{rng(col3, last_row)},"{val3}")')

    def sumifs_dos(value_col, last_row, col1, val1, col2, val2):
        """SUMIFS con dos criterios de texto."""
        return (f'SUMIFS({D}{rng(value_col, last_row)},'
                f'{D}{rng(col1, last_row)},"{val1}",'
                f'{D}{rng(col2, last_row)},"{val2}")')

    def sumif_cellcrit(value_col, last_row, crit_col, crit_cell):
        return f"SUMIF({D}{rng(crit_col, last_row)},{crit_cell},{D}{rng(value_col, last_row)})"

    def sumifs_crit(value_col, last_row, criterios):
        """SUMIFS con criterios literales [(columna, valor), ...]."""
        args = ",".join(f'{D}{rng(c, last_row)},"{v}"' for c, v in criterios)
        return f"SUMIFS({D}{rng(value_col, last_row)},{args})"

    def tipo_count(criterios):
        return "+".join(sumifs_crit(c, ATKTIPO_LAST, criterios) for c in ("DV", "DW", "DX"))

    def atk_count_terms(zona=None, direccion=None, jugador_cell=None):
        """Suma Puntos+Defendidos+Fuera del detalle filtrando por zona y/o direccion
        (literal) y opcionalmente por jugador (referencia a celda)."""
        parts = []
        for col in ("X", "Y", "Z"):
            crit_cols, crits = [], []
            if jugador_cell is not None:
                crit_cols.append("U"); crits.append(jugador_cell)
            if zona is not None:
                crit_cols.append("V"); crits.append(f"\"{zona}\"")
            if direccion is not None:
                crit_cols.append("W"); crits.append(f"\"{direccion}\"")
            args = ",".join(f"{D}{rng(cc, ATKD_LAST)},{cv}" for cc, cv in zip(crit_cols, crits))
            parts.append(f"SUMIFS({D}{rng(col, ATKD_LAST)},{args})")
        return "+".join(parts)

    # ------------------------------------------------------------------
    # Hoja 1: Partido
    # ------------------------------------------------------------------
    ws = new_sheet(wb, "Partido")
    row = 1
    row = set_title(ws, row, 1, 3, f"PARTIDO — {equipo_name.upper()} vs {rival_name.upper()}")

    row = set_subtitle(ws, row, 1, 3, "Marcador por set")
    row = set_headers(ws, row, 1, ["Set", equipo_name, rival_name])
    set_first = row
    team1_is_equipo = parsed["team1_name"] and parsed["team1_name"].strip().lower() == equipo_name.strip().lower()
    for set_num, s1, s2 in sorted(parsed["sets_rows"]):
        eq_score, ri_score = (s1, s2) if team1_is_equipo else (s2, s1)
        row = set_data_row(ws, row, 1, [f"Set {set_num}", eq_score, ri_score])
    set_last = row - 1
    eq_rng = f"B{set_first}:B{set_last}"
    ri_rng = f"C{set_first}:C{set_last}"
    row = set_data_row(
        ws, row, 1,
        ["Sets ganados",
         f"=SUMPRODUCT(({eq_rng}>{ri_rng})*(({eq_rng}+{ri_rng})>0))",
         f"=SUMPRODUCT(({ri_rng}>{eq_rng})*(({eq_rng}+{ri_rng})>0))"],
        total=True,
    )
    row = set_data_row(ws, row, 1, ["Puntos totales anotados", f"=SUM({eq_rng})", f"=SUM({ri_rng})"], total=True)
    row += 1
    #row = set_footnote(
    #    ws, row, 1, 3,
    #    "Nota: revisar si algun set en 0-0 realmente no se disputo (partido finalizado antes) antes de "
    #    "interpretar el marcador.",
    #)
    # row += 1

    row = set_subtitle(ws, row, 1, 2, f"Totales registrados de {equipo_name}")
    row = set_headers(ws, row, 1, ["Concepto", "Valor"])
    row = set_data_row(ws, row, 1, ["Puntos jugados (total del partido)", f"=SUM({eq_rng})+SUM({ri_rng})"])
    row = set_data_row(ws, row, 1, ["Recepciones registradas",
                                     "=" + "+".join(f"SUM({D}{rng(c, REC_LAST)})" for c in "BCDEF")])
    row = set_data_row(ws, row, 1, ["Armados registrados", f"=SUM({D}{rng('I', ARMZ_LAST)})"])
    row = set_data_row(ws, row, 1, ["Ataques registrados", f"=SUM({D}{rng('P', ATKJ_LAST)})"])
    if parsed["total_puntos_cargados"] is not None:
        row += 1
        row = set_footnote(
            ws, row, 1, 2,
            f"Nota: el volcado original informa {parsed['total_puntos_cargados']} puntos cargados en total "
            "(ambos equipos); compara con \"Puntos jugados\" de arriba.",
        )
    autosize(ws, {"A": 34, "B": 16, "C": 16})
    ws.freeze_panes = "A4"

    # ------------------------------------------------------------------
    # Hoja 2: Fases y armador
    # ------------------------------------------------------------------
    ws = new_sheet(wb, "Fases y armador")
    row = 1
    row = set_title(ws, row, 1, 9, f"FASES DEL RALLY — {equipo_name.upper()}")

    # K1/K2/K3: en que fase del rally se definio cada punto. "Saque" son los
    # puntos que no llegaron a tener recepcion (as o error de saque).
    # K1/K2/K3: en que fase del rally se definio cada punto, y si lo gano el
    # que se lo llevo o llego porque el otro se equivoco. "Saque" son los
    # puntos que no llegaron a tener recepcion (as o error de saque).
    if data["fases"]["hechos"]:
        row = set_subtitle(ws, row, 1, 9, "Puntos por fase del rally")
        row = set_headers(ws, row, 1, [
            "Fase", "Hechos", "% de los hechos", "Ganados", "Por error del rival",
            "Recibidos", "% de los recibidos", "Ganados por el rival", "Por error propio",
        ])
        fases_first = row
        fila_total = fases_first + len(FASES_RALLY)
        for fase in FASES_RALLY:
            r = row
            row = set_data_row(ws, row, 1, [
                fase,
                "=" + sumifs_dos("BO", FASES_LAST, "BM", "hechos", "BN", fase),
                f'=IFERROR(B{r}/B${fila_total},"")',
                "=" + sumifs_dos("BP", FASES_LAST, "BM", "hechos", "BN", fase),
                "=" + sumifs_dos("BQ", FASES_LAST, "BM", "hechos", "BN", fase),
                "=" + sumifs_dos("BO", FASES_LAST, "BM", "recibidos", "BN", fase),
                f'=IFERROR(F{r}/F${fila_total},"")',
                "=" + sumifs_dos("BP", FASES_LAST, "BM", "recibidos", "BN", fase),
                "=" + sumifs_dos("BQ", FASES_LAST, "BM", "recibidos", "BN", fase),
            ], formats=[None, "0", PCT_FMT, "0", "0", "0", PCT_FMT, "0", "0"])
        tf = row
        row = set_data_row(ws, row, 1, ["TOTAL"] + [
            f'=IFERROR(B{tf}/B{tf},"")' if col == "C" else
            f'=IFERROR(F{tf}/F{tf},"")' if col == "G" else
            f"=SUM({col}{fases_first}:{col}{tf - 1})"
            for col in "BCDEFGHI"
        ], formats=[None, "0", PCT_FMT, "0", "0", "0", PCT_FMT, "0", "0"], total=True)
        row += 1
        row = set_footnote(
            ws, row, 1, 9,
            "K1: recepcion, armado y ataque. K2: primera defensa del rally, armado y ataque. "
            "K3: el resto del rally. \"Saque\": el punto se definio en el saque (as o error), "
            "sin llegar a la recepcion. \"Sin fase\": error en juego antes de cualquier jugada. "
            "Un punto es \"ganado\" si lo cerro una accion de quien se lo llevo (ataque punto, "
            "usar el bloqueo, bloqueo, as, o un libre o toque que fue punto) y \"por error\" "
            "si lo cerro una falla del que lo "
            "perdio. El mismo punto es error del rival en los hechos y error propio en los "
            "recibidos. Los hechos suman el marcador propio y los recibidos el del rival.",
        )
        row += 1

        row = set_subtitle(ws, row, 1, 4, "Puntos por causa")
        row = set_headers(ws, row, 1, ["Causa", "Tipo", "Hechos", "Recibidos"])
        causas_first = row
        for causa in CAUSAS_PUNTO:
            tipo = "Ganado" if causa in CAUSAS_GANADAS else "Error"
            row = set_data_row(ws, row, 1, [
                causa, tipo,
                "=" + sumifs_dos("BU", CAUSAS_LAST, "BS", "hechos", "BT", causa),
                "=" + sumifs_dos("BU", CAUSAS_LAST, "BS", "recibidos", "BT", causa),
            ], formats=[None, None, "0", "0"])
        tc = row
        row = set_data_row(ws, row, 1, [
            "TOTAL", "",
            f"=SUM(C{causas_first}:C{tc - 1})", f"=SUM(D{causas_first}:D{tc - 1})",
        ], formats=[None, None, "0", "0"], total=True)
        row += 1


    # La rotacion se nombra por donde esta parado el armador: de eso depende
    # si arma de adelante o de atras y con cuantos atacantes cuenta.
    if any(any(c.values()) for z in data["zona_armador"].values() for c in z.values()):
        ncols_z = 2 + len(COLUMNAS_ZARM) + 1
        for clase, titulo, tot_col in (
            ("hechos", "Puntos hechos con el armador en cada zona", "Hechos"),
            ("recibidos", "Puntos recibidos con el armador en cada zona", "Recibidos"),
        ):
            row = set_subtitle(ws, row, 1, ncols_z, titulo)
            row = set_headers(ws, row, 1, ["Zona del armador"] + COLUMNAS_ZARM +
                               [tot_col, "% del total"])
            z_first = row
            fila_tot = z_first + len(ZONAS_ARMADOR)
            col_total = col_letter(1 + len(COLUMNAS_ZARM) + 1)
            for z in ZONAS_ARMADOR:
                r = row
                vals = [f"Zona {z}"]
                for fase in COLUMNAS_ZARM:
                    vals.append("=" + sumifs_tres("BZ", ZARM_LAST, "BW", z,
                                                  "BX", clase, "BY", fase))
                vals.append(f"=SUM(B{r}:{col_letter(1 + len(COLUMNAS_ZARM))}{r})")
                vals.append(f'=IFERROR({col_total}{r}/{col_total}${fila_tot},"")')
                row = set_data_row(ws, row, 1, vals,
                                   formats=[None] + ["0"] * (len(COLUMNAS_ZARM) + 1) + [PCT_FMT])
            tz = row
            row = set_data_row(ws, row, 1, ["TOTAL"] + [
                f"=SUM({col_letter(1 + i)}{z_first}:{col_letter(1 + i)}{tz - 1})"
                for i in range(1, len(COLUMNAS_ZARM) + 2)
            ] + [f'=IFERROR({col_total}{tz}/{col_total}{tz},"")'],
                formats=[None] + ["0"] * (len(COLUMNAS_ZARM) + 1) + [PCT_FMT], total=True)
            row += 1

        row = set_footnote(
            ws, row, 1, ncols_z,
            "La zona es donde estaba parado el armador propio en cada punto, que es como se "
            "nombra la rotacion: de ahi depende si arma de adelante o de atras. \"As\" y "
            "\"Error de saque\" separan el saque porque no son la misma situacion: en el as "
            "sacaba el equipo de la tabla y en el error sacaba el rival. Los puntos cargados "
            "sin rotacion no tienen zona y no entran en estas dos tablas.",
        )
        row += 1

    if row <= 3:
        row = set_footnote(
            ws, row, 1, 9,
            "Este volcado es anterior al desglose por fase del rally: hay que volver a "
            "cargar el partido con la version actual para que aparezcan estas tablas.",
        )

    autosize(ws, {"A": 22})
    ws.freeze_panes = "A4"

    # ------------------------------------------------------------------
    # Hoja: Defensa
    #
    # Va aparte de Recepcion a proposito. Son la misma habilidad en dos
    # momentos distintos, pero no se entrenan igual y mezclarlas taparia a
    # alguien que recibe bien y defiende mal (o al reves).
    # ------------------------------------------------------------------
    CABEZA_DEF = ["Jugador", "Defensas", "% del total", "Calidad 3", "Calidad 2",
                  "Calidad 1", "Calidad 0", "Pase al otro lado",
                  "% Positiva (cal. 2+3)", "% Perfecta (cal. 3)"]
    FORMATOS_DEF = [None, "0", PCT_FMT, "0", "0", "0", "0", "0", PCT_FMT, PCT_FMT]

    ws = new_sheet(wb, "Defensa")
    row = 1
    row = set_title(ws, row, 1, 10, f"DEFENSA — {equipo_name.upper()}")
    row = set_nota(ws, row, 1, 10,
        "Defender es levantar un ATAQUE del rival. La CALIDAD 0 es la pelota que el "
        "defensor tocó pero no pudo jugar: el punto termina ahí y es del que atacó. "
        "No entran acá los balones que vienen de un libre, un toque, un overpass, "
        "un bloqueo rejugable ni un toque de bloqueo (el bloqueador tocó el ataque y "
        "la pelota siguió de su lado): en ninguno de esos casos hubo un ataque que "
        "defender, o ya lo frenó el bloqueo.")

    row = set_subtitle(ws, row, 1, 10, "Defensas por jugador")
    row = set_headers(ws, row, 1, CABEZA_DEF)
    def_first = row
    for p_ in def_players:
        r = row
        valores = [p_, f"=SUM(D{r}:H{r})",
                   f"=IFERROR(B{r}/B${def_first + len(def_players)},\"\")"]
        for col in ("CC", "CD", "CE", "CF", "CG"):
            valores.append("=" + sumif(col, DEF_LAST, "CB", p_))
        valores.append(f"=IFERROR((D{r}+E{r})/B{r},\"\")")
        valores.append(f"=IFERROR(D{r}/B{r},\"\")")
        row = set_data_row(ws, row, 1, valores, formats=FORMATOS_DEF)
    td = row
    row = set_data_row(
        ws, row, 1,
        ["TOTAL", f"=SUM(B{def_first}:B{td - 1})", f"=IFERROR(B{td}/B{td},\"\")"]
        + [f"=SUM({c}{def_first}:{c}{td - 1})" for c in "DEFGH"]
        + [f"=IFERROR((D{td}+E{td})/B{td},\"\")", f"=IFERROR(D{td}/B{td},\"\")"],
        formats=FORMATOS_DEF, total=True,
    )
    row += 1

    sets_def = sorted(data["defensas_por_set"])
    if len(sets_def) > 1:
        for numero in sets_def:
            jugadores_set = [p_ for p_ in def_players if p_ in data["defensas_por_set"][numero]]
            if not jugadores_set:
                continue
            row = set_subtitle(ws, row, 1, 10, f"Defensas por jugador — Set {numero}")
            row = set_headers(ws, row, 1, CABEZA_DEF)
            set_first = row
            for p_ in jugadores_set:
                r = row
                valores = [p_, f"=SUM(D{r}:H{r})",
                           f"=IFERROR(B{r}/B${set_first + len(jugadores_set)},\"\")"]
                for col in ("CL", "CM", "CN", "CO", "CP"):
                    valores.append(f"=SUMIFS({D}{rng(col, DEFSET_LAST)},"
                                   f"{D}{rng('CJ', DEFSET_LAST)},{numero},"
                                   f"{D}{rng('CK', DEFSET_LAST)},\"{p_}\")")
                valores.append(f"=IFERROR((D{r}+E{r})/B{r},\"\")")
                valores.append(f"=IFERROR(D{r}/B{r},\"\")")
                row = set_data_row(ws, row, 1, valores, formats=FORMATOS_DEF)
            ts = row
            row = set_data_row(
                ws, row, 1,
                ["TOTAL", f"=SUM(B{set_first}:B{ts - 1})", f"=IFERROR(B{ts}/B{ts},\"\")"]
                + [f"=SUM({c}{set_first}:{c}{ts - 1})" for c in "DEFGH"]
                + [f"=IFERROR((D{ts}+E{ts})/B{ts},\"\")", f"=IFERROR(D{ts}/B{ts},\"\")"],
                formats=FORMATOS_DEF, total=True,
            )
            row += 1

    autosize(ws, {"A": 22})
    ws.freeze_panes = "A4"

    # ------------------------------------------------------------------
    # Hoja 2: Recepcion
    # ------------------------------------------------------------------
    ws = new_sheet(wb, "Recepción")
    row = 1
    row = set_title(ws, row, 1, 10, f"RECEPCIÓN — {equipo_name.upper()}")
    row = set_nota(ws, row, 1, 10,
        "Recibir es levantar el SAQUE del rival. Acá la CALIDAD 0 NO termina el punto: "
        "es una recepción negativa, un pase malo que igual se juega y que le complica "
        "el armado al equipo. Es la diferencia con la hoja de Defensa, donde el 0 sí "
        "cierra el punto.")

    row = set_subtitle(ws, row, 1, 10, "Recepciones por jugador")
    row = set_headers(ws, row, 1, [
        "Jugador", "Recepciones", "% del total", "Calidad 3", "Calidad 2", "Calidad 1",
        "Calidad 0", "Pase al otro lado", "% Positiva (cal. 2+3)", "% Perfecta (cal. 3)",
    ])
    rec_first = row
    for p in rec_players:
        r = row
        d_ = sumif("B", REC_LAST, "A", p)
        e_ = sumif("C", REC_LAST, "A", p)
        f_ = sumif("D", REC_LAST, "A", p)
        g_ = sumif("E", REC_LAST, "A", p)
        h_ = sumif("F", REC_LAST, "A", p)
        b_ = f"SUM(D{r}:H{r})"
        c_ = f"=IFERROR(B{r}/B${rec_first + len(rec_players)},\"\")"
        i_ = f"=IFERROR((D{r}+E{r})/B{r},\"\")"
        j_ = f"=IFERROR(D{r}/B{r},\"\")"
        row = set_data_row(ws, row, 1, [p, "=" + b_, c_, "=" + d_, "=" + e_, "=" + f_, "=" + g_, "=" + h_, i_, j_],
                            formats=[None, "0", PCT_FMT, "0", "0", "0", "0", "0", PCT_FMT, PCT_FMT])
    rec_total = row
    tr = rec_total
    row = set_data_row(
        ws, row, 1,
        ["TOTAL", f"=SUM(B{rec_first}:B{tr - 1})", f"=IFERROR(B{tr}/B{tr},\"\")",
         f"=SUM(D{rec_first}:D{tr - 1})", f"=SUM(E{rec_first}:E{tr - 1})", f"=SUM(F{rec_first}:F{tr - 1})",
         f"=SUM(G{rec_first}:G{tr - 1})", f"=SUM(H{rec_first}:H{tr - 1})",
         f"=IFERROR((D{tr}+E{tr})/B{tr},\"\")", f"=IFERROR(D{tr}/B{tr},\"\")"],
        formats=[None, "0", PCT_FMT, "0", "0", "0", "0", "0", PCT_FMT, PCT_FMT], total=True,
    )
    row += 1

    # mismo desglose, pero set por set (solo si el partido tiene mas de un set)
    sets_rec = sorted(data["recepciones_por_set"])
    if len(sets_rec) > 1:
        for numero in sets_rec:
            jugadores_set = [p for p in rec_players if p in data["recepciones_por_set"][numero]]
            row = set_subtitle(ws, row, 1, 10, f"Recepciones por jugador — Set {numero}")
            row = set_headers(ws, row, 1, [
                "Jugador", "Recepciones", "% del set", "Calidad 3", "Calidad 2", "Calidad 1",
                "Calidad 0", "Pase al otro lado", "% Positiva (cal. 2+3)", "% Perfecta (cal. 3)",
            ])
            set_first = row
            for p in jugadores_set:
                r = row
                vals = [p, f"=SUM(D{r}:H{r})", f"=IFERROR(B{r}/B${set_first + len(jugadores_set)},\"\")"]
                for col in ("AL", "AM", "AN", "AO", "AP"):
                    vals.append(f"=SUMIFS({D}{rng(col, RECSET_LAST)},"
                                f"{D}{rng('AJ', RECSET_LAST)},{numero},"
                                f"{D}{rng('AK', RECSET_LAST)},\"{p}\")")
                vals.append(f"=IFERROR((D{r}+E{r})/B{r},\"\")")
                vals.append(f"=IFERROR(D{r}/B{r},\"\")")
                row = set_data_row(ws, row, 1, vals,
                                    formats=[None, "0", PCT_FMT, "0", "0", "0", "0", "0", PCT_FMT, PCT_FMT])
            ts = row
            row = set_data_row(
                ws, row, 1,
                ["TOTAL", f"=SUM(B{set_first}:B{ts - 1})", f"=IFERROR(B{ts}/B{ts},\"\")",
                 f"=SUM(D{set_first}:D{ts - 1})", f"=SUM(E{set_first}:E{ts - 1})", f"=SUM(F{set_first}:F{ts - 1})",
                 f"=SUM(G{set_first}:G{ts - 1})", f"=SUM(H{set_first}:H{ts - 1})",
                 f"=IFERROR((D{ts}+E{ts})/B{ts},\"\")", f"=IFERROR(D{ts}/B{ts},\"\")"],
                formats=[None, "0", PCT_FMT, "0", "0", "0", "0", "0", PCT_FMT, PCT_FMT], total=True,
            )
            row += 1

    row = set_subtitle(ws, row, 1, 3, "Distribución de calidad de recepción del equipo")
    row = set_headers(ws, row, 1, ["Calidad", "Cantidad", "% del total"])
    qual_first = row
    for label, col in [("Calidad 3", "B"), ("Calidad 2", "C"), ("Calidad 1", "D"), ("Calidad 0", "E"), ("Pase al otro lado", "F")]:
        r = row
        val = f"=SUM({D}{rng(col, REC_LAST)})"
        row = set_data_row(ws, row, 1, [label, val, f"=IFERROR(B{r}/B${qual_first + 5},\"\")"], formats=[None, "0", PCT_FMT])
    qt = row
    row = set_data_row(ws, row, 1, ["TOTAL", f"=SUM(B{qual_first}:B{qt - 1})", f"=IFERROR(B{qt}/B{qt},\"\")"],
                        formats=[None, "0", PCT_FMT], total=True)
    row += 1

    row = set_subtitle(ws, row, 1, 11, "Recepción según tipo de saque y par de zonas")
    row = set_headers(ws, row, 1, [
        "Tipo de saque", "Par de zonas", "Recibidos", "% del total", "Calidad 3", "Calidad 2",
        "Calidad 1", "Calidad 0", "Pase al otro lado", "% Positiva (cal. 2+3)", "% Perfecta (cal. 3)",
    ])
    pares_presentes = {
        tipo: [p for p in pares if p in data["recepcion_tipo_saque"]]
        for tipo, pares in PARES_POR_TIPO_SAQUE.items()
    }
    rectipo_first = row
    # la fila TOTAL va despues de todas las filas de par + una fila de subtotal por tipo
    rectipo_total_row = rectipo_first + sum(len(p) for p in pares_presentes.values()) + len(pares_presentes)
    subtotal_rows = []
    for tipo, pares in pares_presentes.items():
        for par in pares:
            r = row
            vals = [
                tipo, par, f"=SUM(E{r}:I{r})", f"=IFERROR(C{r}/C${rectipo_total_row},\"\")",
                "=" + sumif("AD", RECTIPO_LAST, "AC", par),
                "=" + sumif("AE", RECTIPO_LAST, "AC", par),
                "=" + sumif("AF", RECTIPO_LAST, "AC", par),
                "=" + sumif("AG", RECTIPO_LAST, "AC", par),
                "=" + sumif("AH", RECTIPO_LAST, "AC", par),
                f"=IFERROR((E{r}+F{r})/C{r},\"\")", f"=IFERROR(E{r}/C{r},\"\")",
            ]
            row = set_data_row(ws, row, 1, vals,
                                formats=[None, None, "0", PCT_FMT, "0", "0", "0", "0", "0", PCT_FMT, PCT_FMT])
        r = row
        subtotal_rows.append(r)
        vals = [
            f"Subtotal {tipo}", "", f"=SUM(E{r}:I{r})", f"=IFERROR(C{r}/C${rectipo_total_row},\"\")",
            "=" + sumif("AD", RECTIPO_LAST, "AB", tipo),
            "=" + sumif("AE", RECTIPO_LAST, "AB", tipo),
            "=" + sumif("AF", RECTIPO_LAST, "AB", tipo),
            "=" + sumif("AG", RECTIPO_LAST, "AB", tipo),
            "=" + sumif("AH", RECTIPO_LAST, "AB", tipo),
            f"=IFERROR((E{r}+F{r})/C{r},\"\")", f"=IFERROR(E{r}/C{r},\"\")",
        ]
        row = set_data_row(ws, row, 1, vals,
                            formats=[None, None, "0", PCT_FMT, "0", "0", "0", "0", "0", PCT_FMT, PCT_FMT], total=True)
    rt = row
    vals = ["TOTAL", "", f"=SUM(E{rt}:I{rt})", f"=IFERROR(C{rt}/C{rt},\"\")"]
    for col in ("E", "F", "G", "H", "I"):
        vals.append("=" + "+".join(f"{col}{sr}" for sr in subtotal_rows))
    vals.append(f"=IFERROR((E{rt}+F{rt})/C{rt},\"\")")
    vals.append(f"=IFERROR(E{rt}/C{rt},\"\")")
    row = set_data_row(ws, row, 1, vals,
                        formats=[None, None, "0", PCT_FMT, "0", "0", "0", "0", "0", PCT_FMT, PCT_FMT], total=True)
    row += 1
    row = set_footnote(
        ws, row, 1, 11,
        "Nota: las zonas se numeran desde cada lado, así que la zona 1 de un lado queda enfrentada a la "
        "zona 5 del otro. Saque paralelo (va derecho) = 1 a 5, 5 a 1, 6 a 6; saque cruzado (va en "
        "diagonal) = 1 a 1, 5 a 5, 6 a 1, 6 a 5. Los saques hacia el resto de las zonas no entran en "
        "esta tabla, y los pares sin recepciones registradas no se listan.",
    )

    autosize(ws, {"A": 14, "B": 13, "C": 11, "D": 11, "E": 11, "F": 11, "G": 11, "H": 11, "I": 14, "J": 15, "K": 15})
    ws.freeze_panes = "A4"

    # ------------------------------------------------------------------
    # Hoja 3: Armado
    # ------------------------------------------------------------------
    n_mz = len(matriz_arm_zonas)
    ws = new_sheet(wb, "Armado")
    row = 1
    row = set_title(ws, row, 1, max(3, 2 + n_mz), f"ARMADO — {equipo_name.upper()}")

    row = set_subtitle(ws, row, 1, 3, "Armado por zona")
    row = set_headers(ws, row, 1, ["Zona", "Armados", "% del total"])
    armz_first = row
    for z in armz_zonas:
        r = row
        val = sumif("I", ARMZ_LAST, "H", z)
        row = set_data_row(ws, row, 1, [f"Zona {z}", "=" + val, f"=IFERROR(B{r}/B${armz_first + len(armz_zonas)},\"\")"],
                            formats=[None, "0", PCT_FMT])
    at = row
    row = set_data_row(ws, row, 1, ["TOTAL", f"=SUM(B{armz_first}:B{at - 1})", f"=IFERROR(B{at}/B{at},\"\")"],
                        formats=[None, "0", PCT_FMT], total=True)
    row += 1

    n_az = len(armz_zonas)
    if len(arm_sets) > 1:
        row = set_subtitle(ws, row, 1, 2 + n_az, "Armado por zona y set")
        row = set_headers(ws, row, 1, ["Set"] + [f"Zona {z}" for z in armz_zonas] + ["Total"])
        azs_first = row
        for numero in arm_sets:
            r = row
            vals = [f"Set {numero}"]
            for z in armz_zonas:
                vals.append(f"=SUMIFS({D}{rng('AW', ARMZSET_LAST)},"
                            f"{D}{rng('AU', ARMZSET_LAST)},{numero},"
                            f"{D}{rng('AV', ARMZSET_LAST)},\"{z}\")")
            vals.append(f"=SUM(B{r}:{col_letter(1 + n_az)}{r})")
            row = set_data_row(ws, row, 1, vals, formats=[None] + ["0"] * (n_az + 1))
        tz = row
        row = set_data_row(
            ws, row, 1,
            ["TOTAL"] + [f"=SUM({col_letter(1 + i)}{azs_first}:{col_letter(1 + i)}{tz - 1})"
                         for i in range(1, n_az + 2)],
            formats=[None] + ["0"] * (n_az + 1), total=True,
        )
        row += 1

    # Los armados de emergencia (los hace cualquiera cuando el armador defiende)
    # van en "Otros jugadores", que se calcula como el total menos los armadores.
    row = set_subtitle(ws, row, 1, 3 + n_az, "Armado por armador")
    if not armadores:
        row = set_footnote(ws, row, 1, 3 + n_az, "El volcado no trae desglose por armador.")
    else:
        row = set_headers(ws, row, 1, ["Armador"] + [f"Zona {z}" for z in armz_zonas] +
                           ["Total", "% del total del equipo"])
        arm_first = row
        col_total = col_letter(2 + n_az)
        for j in armadores:
            r = row
            vals = [j]
            for z in armz_zonas:
                vals.append(f"=SUMIFS({D}{rng('BA', ARMADOR_LAST)},"
                            f"{D}{rng('AY', ARMADOR_LAST)},\"{j}\","
                            f"{D}{rng('AZ', ARMADOR_LAST)},\"{z}\")")
            vals.append(f"=SUM(B{r}:{col_letter(1 + n_az)}{r})")
            vals.append(f"=IFERROR({col_total}{r}/{col_total}${arm_first + len(armadores) + 1},\"\")")
            row = set_data_row(ws, row, 1, vals,
                               formats=[None] + ["0"] * (n_az + 1) + [PCT_FMT])
        # fila "Otros jugadores": total del equipo menos lo de los armadores
        r_otros = row
        vals = ["Otros jugadores"]
        for i, z in enumerate(armz_zonas):
            cl = col_letter(2 + i)
            vals.append(f"={sumif('I', ARMZ_LAST, 'H', z)}-SUM({cl}{arm_first}:{cl}{r_otros - 1})")
        vals.append(f"=SUM(B{r_otros}:{col_letter(1 + n_az)}{r_otros})")
        vals.append(f"=IFERROR({col_total}{r_otros}/{col_total}${arm_first + len(armadores) + 1},\"\")")
        row = set_data_row(ws, row, 1, vals, formats=[None] + ["0"] * (n_az + 1) + [PCT_FMT])
        ta = row
        row = set_data_row(
            ws, row, 1,
            ["TOTAL"] + [f"=SUM({col_letter(1 + i)}{arm_first}:{col_letter(1 + i)}{ta - 1})"
                         for i in range(1, n_az + 2)] +
            [f"=IFERROR({col_total}{ta}/{col_total}{ta},\"\")"],
            formats=[None] + ["0"] * (n_az + 1) + [PCT_FMT], total=True,
        )
        row += 1

        if len(data["armado_armador_por_set"]) > 1:
            row = set_subtitle(ws, row, 1, 3 + n_az, "Armado por armador y set")
            row = set_headers(ws, row, 1, ["Set", "Armador"] + [f"Zona {z}" for z in armz_zonas] + ["Total"])
            for numero in sorted(data["armado_armador_por_set"]):
                for j in armadores:
                    r = row
                    vals = [f"Set {numero}", j]
                    for z in armz_zonas:
                        vals.append(f"=SUMIFS({D}{rng('BF', ARMADORSET_LAST)},"
                                    f"{D}{rng('BC', ARMADORSET_LAST)},{numero},"
                                    f"{D}{rng('BD', ARMADORSET_LAST)},\"{j}\","
                                    f"{D}{rng('BE', ARMADORSET_LAST)},\"{z}\")")
                    vals.append(f"=SUM(C{r}:{col_letter(2 + n_az)}{r})")
                    row = set_data_row(ws, row, 1, vals, formats=[None, None] + ["0"] * (n_az + 1))
            row += 1

    row = set_subtitle(ws, row, 1, 2 + n_mz, "Matriz calidad de recepción × zona armada — frecuencia")
    row = set_headers(ws, row, 1, ["Calidad"] + [f"Zona {z}" for z in matriz_arm_zonas] + ["Total"])
    qualities = [3, 2, 1, 0]
    mat_first = row
    for q in qualities:
        r = row
        vals = [f"Calidad {q}"]
        for z in matriz_arm_zonas:
            vals.append(f"=SUMIFS({D}{rng('M', ARMQ_LAST)},{D}{rng('K', ARMQ_LAST)},{q},{D}{rng('L', ARMQ_LAST)},\"{z}\")")
        last_col = col_letter(1 + n_mz)
        vals.append(f"=SUM(B{r}:{last_col}{r})")
        row = set_data_row(ws, row, 1, vals, formats=[None] + ["0"] * (n_mz + 1))
    mt = row
    tot_vals = ["TOTAL"]
    for i in range(1, n_mz + 2):
        cl = col_letter(1 + i)
        tot_vals.append(f"=SUM({cl}{mat_first}:{cl}{mt - 1})")
    row = set_data_row(ws, row, 1, tot_vals, formats=[None] + ["0"] * (n_mz + 1), total=True)
    row += 1

    row = set_subtitle(ws, row, 1, 2 + n_mz, "Matriz calidad de recepción × zona armada — % por fila")
    row = set_headers(ws, row, 1, ["Calidad"] + [f"Zona {z}" for z in matriz_arm_zonas] + ["Total"])
    for i, q in enumerate(qualities):
        src_row = mat_first + i
        r = row
        vals = [f"Calidad {q}"]
        total_col_letter = col_letter(1 + n_mz + 1)
        for k in range(n_mz):
            cl = col_letter(2 + k)
            vals.append(f"=IFERROR({cl}{src_row}/${total_col_letter}{src_row},\"\")")
        last_col = col_letter(1 + n_mz)
        vals.append(f"=IFERROR(SUM(B{r}:{last_col}{r}),\"\")")
        row = set_data_row(ws, row, 1, vals, formats=[None] + [PCT_FMT] * (n_mz + 1))
    row += 1

    # La misma matriz abierta por armador: una fila por (armador, calidad),
    # para poder comparar a donde distribuye cada uno con la misma recepcion.
    mat_armadores = [j for j in armadores if j in data["armado_calidad_armador"]]
    if mat_armadores:
        ncols_ma = 3 + n_mz
        row = set_subtitle(ws, row, 1, ncols_ma,
                           "Matriz calidad de recepción × zona armada por armador — frecuencia")
        row = set_headers(ws, row, 1, ["Armador", "Calidad"] +
                           [f"Zona {z}" for z in matriz_arm_zonas] + ["Total"])
        matarm_first = row
        for j in mat_armadores:
            for q in qualities:
                r = row
                vals = [j, f"Calidad {q}"]
                for z in matriz_arm_zonas:
                    vals.append(f"=SUMIFS({D}{rng('BK', MATARM_LAST)},"
                                f"{D}{rng('BH', MATARM_LAST)},\"{j}\","
                                f"{D}{rng('BI', MATARM_LAST)},{q},"
                                f"{D}{rng('BJ', MATARM_LAST)},\"{z}\")")
                vals.append(f"=SUM(C{r}:{col_letter(2 + n_mz)}{r})")
                row = set_data_row(ws, row, 1, vals, formats=[None, None] + ["0"] * (n_mz + 1))
        row += 1

        row = set_subtitle(ws, row, 1, ncols_ma,
                           "Matriz calidad de recepción × zona armada por armador — % por fila")
        row = set_headers(ws, row, 1, ["Armador", "Calidad"] +
                           [f"Zona {z}" for z in matriz_arm_zonas] + ["Total"])
        col_total_ma = col_letter(3 + n_mz)
        for i in range(len(mat_armadores) * len(qualities)):
            src = matarm_first + i
            r = row
            vals = [ws.cell(row=src, column=1).value, ws.cell(row=src, column=2).value]
            for k in range(n_mz):
                cl = col_letter(3 + k)
                vals.append(f"=IFERROR({cl}{src}/${col_total_ma}{src},\"\")")
            vals.append(f"=IFERROR(SUM(C{r}:{col_letter(2 + n_mz)}{r}),\"\")")
            row = set_data_row(ws, row, 1, vals, formats=[None, None] + [PCT_FMT] * (n_mz + 1))
        row += 1

    row = set_footnote(
        ws, row, 1, max(3, 2 + n_mz),
        "Nota: la matriz de calidad de recepción × zona armada solo incluye los armados con calidad de "
        "recepción conocida en el volcado original; puede no coincidir con el total de \"Armado por zona\" "
        "si existen armados en jugadas de transición (tras defensa) no asociados a una recepción.",
    )

    row += 1
    # La calidad del armado es opcional al cargar: lo que no se califico va
    # aparte y los porcentajes se calculan solo sobre lo calificado.
    row = set_subtitle(ws, row, 1, 11, "Calidad del armado por armador")
    if not any(sum(v.values()) - v.get("Sin calificar", 0)
               for v in data["calidad_armado_jugador"].values()):
        row = set_footnote(ws, row, 1, 11,
                           "Sin armados calificados en el volcado (A+ / A0 / A- / AX).")
    else:
        row = set_headers(ws, row, 1, ["Armador", "A+", "A0", "A-", "AX", "Calificados",
                                       "% A+", "% A0", "% A-", "% AX", "Sin calificar"])
        ca_first = row
        for p in calarm_players:
            r = row
            vals = [p] + ["=" + sumifs_dos("DK", CALARM_LAST, "DI", p, "DJ", cal)
                          for cal in ("A+", "A0", "A-", "AX")]
            vals.append(f"=SUM(B{r}:E{r})")
            vals += [f'=IFERROR({c}{r}/F{r},"")' for c in "BCDE"]
            vals.append("=" + sumifs_dos("DK", CALARM_LAST, "DI", p, "DJ", "Sin calificar"))
            row = set_data_row(ws, row, 1, vals,
                               formats=[None] + ["0"] * 5 + [PCT_FMT] * 4 + ["0"])
        tc = row
        row = set_data_row(
            ws, row, 1,
            ["TOTAL"] + [f"=SUM({c}{ca_first}:{c}{tc - 1})" for c in "BCDEF"]
            + [f'=IFERROR({c}{tc}/F{tc},"")' for c in "BCDE"]
            + [f"=SUM(K{ca_first}:K{tc - 1})"],
            formats=[None] + ["0"] * 5 + [PCT_FMT] * 4 + ["0"], total=True)
        row = set_footnote(
            ws, row, 1, 11,
            "A+: el atacante queda en situación favorable. A0: condiciones normales. "
            "A-: pelota difícil, previsible o fuera de sistema. AX: error de armado "
            "(armada mala, punto del rival). Los % son sobre los armados calificados.",
        )

    widths = {"A": 22 if calarm_players else 12}
    for i, z in enumerate(matriz_arm_zonas):
        widths[col_letter(2 + i)] = 10
    widths[col_letter(2 + n_mz)] = 10
    autosize(ws, widths)
    ws.freeze_panes = "A4"

    # ------------------------------------------------------------------
    # Hoja 4: Ataque jugador
    # ------------------------------------------------------------------
    n_az = len(atk_zonas)
    ws = new_sheet(wb, "Ataque jugador")
    row = 1
    row = set_title(ws, row, 1, 9, f"ATAQUE POR JUGADOR — {equipo_name.upper()}")

    row = set_subtitle(ws, row, 1, 9, "Ataques por jugador")
    row = set_headers(ws, row, 1, [
        "Jugador", "Ataques", "% del total de ataques", "Puntos", "Defendidos", "Fuera",
        "% Punto", "% Defendido", "% Fuera",
    ])
    atk1_first = row
    for p in atk_players:
        r = row
        b_ = sumif("P", ATKJ_LAST, "O", p)
        d_ = sumif("Q", ATKJ_LAST, "O", p)
        e_ = sumif("R", ATKJ_LAST, "O", p)
        f_ = sumif("S", ATKJ_LAST, "O", p)
        c_ = f"=IFERROR(B{r}/B${atk1_first + len(atk_players)},\"\")"
        g_ = f"=IFERROR(D{r}/B{r},\"\")"
        h_ = f"=IFERROR(E{r}/B{r},\"\")"
        i_ = f"=IFERROR(F{r}/B{r},\"\")"
        row = set_data_row(ws, row, 1, [p, "=" + b_, c_, "=" + d_, "=" + e_, "=" + f_, g_, h_, i_],
                            formats=[None, "0", PCT_FMT, "0", "0", "0", PCT_FMT, PCT_FMT, PCT_FMT])
    t1 = row
    row = set_data_row(
        ws, row, 1,
        ["TOTAL", f"=SUM(B{atk1_first}:B{t1 - 1})", f"=IFERROR(B{t1}/B{t1},\"\")",
         f"=SUM(D{atk1_first}:D{t1 - 1})", f"=SUM(E{atk1_first}:E{t1 - 1})", f"=SUM(F{atk1_first}:F{t1 - 1})",
         f"=IFERROR(D{t1}/B{t1},\"\")", f"=IFERROR(E{t1}/B{t1},\"\")", f"=IFERROR(F{t1}/B{t1},\"\")"],
        formats=[None, "0", PCT_FMT, "0", "0", "0", PCT_FMT, PCT_FMT, PCT_FMT], total=True,
    )
    row += 1

    # Bloqueos punto: van aparte de la tabla de ataques porque bloquear no es
    # atacar y hay jugadores que bloquean sin haber atacado nunca.
    row = set_subtitle(ws, row, 1, 3, "Bloqueos punto por jugador")
    if not bloq_players:
        row = set_footnote(ws, row, 1, 3, "Sin bloqueos punto registrados en el volcado.")
    else:
        row = set_headers(ws, row, 1, ["Jugador", "Bloqueos punto", "% del total del equipo"])
        bloq_first = row
        for p in bloq_players:
            r = row
            b_ = sumif("AS", BLOQ_LAST, "AR", p)
            c_ = f"=IFERROR(B{r}/B${bloq_first + len(bloq_players)},\"\")"
            row = set_data_row(ws, row, 1, [p, "=" + b_, c_],
                               formats=[None, "0", PCT_FMT])
        tb = row
        row = set_data_row(
            ws, row, 1,
            ["TOTAL", f"=SUM(B{bloq_first}:B{tb - 1})", f"=IFERROR(B{tb}/B{tb},\"\")"],
            formats=[None, "0", PCT_FMT], total=True,
        )
    row += 1

    # El bloqueador toca el ataque y la pelota sigue de su lado. No es punto,
    # pero frena el ataque: por eso la pelota siguiente no cuenta como defensa.
    row = set_subtitle(ws, row, 1, 3, "Toques de bloqueo por jugador (sigue el punto)")
    if not toqbloq_players:
        row = set_footnote(ws, row, 1, 3, "Sin toques de bloqueo registrados en el volcado.")
    else:
        row = set_headers(ws, row, 1, ["Jugador", "Toques de bloqueo", "% del total del equipo"])
        tq_first = row
        for p in toqbloq_players:
            r = row
            b_ = sumif("CS", TOQBLOQ_LAST, "CR", p)
            c_ = f"=IFERROR(B{r}/B${tq_first + len(toqbloq_players)},\"\")"
            row = set_data_row(ws, row, 1, [p, "=" + b_, c_], formats=[None, "0", PCT_FMT])
        tt = row
        row = set_data_row(
            ws, row, 1,
            ["TOTAL", f"=SUM(B{tq_first}:B{tt - 1})", f"=IFERROR(B{tt}/B{tt},\"\")"],
            formats=[None, "0", PCT_FMT], total=True,
        )
    row += 1

    # Libres y toques: no son ataques (el que los hace no remata), pero pueden
    # ser punto, usar el bloqueo, seguir o salir mal.
    row = set_subtitle(ws, row, 1, 8, "Libres y toques por jugador")
    if not libre_filas:
        row = set_footnote(ws, row, 1, 8, "Sin libres ni toques registrados en el volcado.")
    else:
        row = set_headers(ws, row, 1, ["Jugador", "Tipo", "Total", "Punto", "Usando el bloqueo",
                                       "Sigue", "Malo", "% Punto"])
        lt_first = row
        for p, tipo in libre_filas:
            r = row
            vals = [p, tipo]
            for col in ("CW", "CX", "CY", "CZ", "DA"):
                vals.append("=" + sumifs_dos(col, LIBRE_LAST, "CU", p, "CV", tipo))
            vals.append(f"=IFERROR((D{r}+E{r})/C{r},\"\")")
            row = set_data_row(ws, row, 1, vals,
                               formats=[None, None, "0", "0", "0", "0", "0", PCT_FMT])
        tl = row
        row = set_data_row(
            ws, row, 1,
            ["TOTAL", ""] + [f"=SUM({c}{lt_first}:{c}{tl - 1})" for c in "CDEFG"]
            + [f"=IFERROR((D{tl}+E{tl})/C{tl},\"\")"],
            formats=[None, None, "0", "0", "0", "0", "0", PCT_FMT], total=True,
        )
        row = set_footnote(
            ws, row, 1, 8,
            "\"% Punto\" cuenta los que fueron punto directo y los que usaron el bloqueo. "
            "\"Sigue\": la pelota paso y el punto continuo. \"Malo\": se erro, punto del rival.",
        )
    row += 1

    ncols2 = 1 + n_az + 3
    row = set_subtitle(ws, row, 1, ncols2, "Ataques por jugador y zona de origen")
    row = set_headers(ws, row, 1, ["Jugador"] + [f"Zona {z}" for z in atk_zonas] +
                       ["Total con zona", "Sin zona registrada", "Ataques totales"])
    atk2_first = row
    for p in atk_players:
        r = row
        vals = [p]
        for z in atk_zonas:
            vals.append("=" + atk_count_terms(zona=z, jugador_cell=f"$A{r}"))
        zone_last_col = col_letter(1 + n_az)
        vals.append(f"=SUM(B{r}:{zone_last_col}{r})")  # Total con zona
        vals.append(0)  # Sin zona registrada: se completa abajo con formula (necesita el total ya escrito)
        vals.append("=" + sumif_cellcrit("P", ATKJ_LAST, "O", f"$A{r}"))  # Ataques totales
        row = set_data_row(ws, row, 1, vals, formats=[None] + ["0"] * (n_az + 3))
    # Sin zona registrada = Ataques totales - Total con zona
    total_con_zona_col = col_letter(2 + n_az)
    ataques_tot_col = col_letter(4 + n_az)
    for rr in range(atk2_first, row):
        ws.cell(row=rr, column=3 + n_az, value=f"={ataques_tot_col}{rr}-{total_con_zona_col}{rr}")
    t2 = row
    tot_vals = ["TOTAL"]
    for i in range(1, n_az + 4):
        cl = col_letter(1 + i)
        tot_vals.append(f"=SUM({cl}{atk2_first}:{cl}{t2 - 1})")
    row = set_data_row(ws, row, 1, tot_vals, formats=[None] + ["0"] * (n_az + 3), total=True)
    row += 1

    row = set_footnote(
        ws, row, 1, ncols2,
        "Nota: \"Sin zona registrada\" son ataques cuyo total declarado por jugador no tiene zona/dirección "
        "asociada en el detalle del volcado original (ver advertencias del script en consola).",
    )

    row += 1
    # Separar por calidad del armado evita castigar al atacante por una pelota
    # mala, o premiarlo por una que le dejaron servida.
    row = set_subtitle(ws, row, 1, 9, "Ataque según calidad del armado")
    if not atkcal_filas:
        row = set_footnote(ws, row, 1, 9, "Sin ataques con armado registrados en el volcado.")
    else:
        row = set_headers(ws, row, 1, ["Calidad"] + ["Ataques", "Puntos", "Defendidos", "Fuera", "% Punto", "% Fuera", "Eficacia"])
        eq_first = row
        for cal in CALIDADES_ARMADO_ATAQUE:
            r = row
            vals = [cal] + [f"=C{r}+D{r}+E{r}"] + [
                "=" + sumif(col, ATKCAL_LAST, "DN", cal) for col in ("DO", "DP", "DQ")]
            vals += [f'=IFERROR(C{r}/B{r},"")', f'=IFERROR(E{r}/B{r},"")',
                     f'=IFERROR((C{r}-E{r})/B{r},"")']
            row = set_data_row(ws, row, 1, vals, formats=[None] + ["0"] * 4 + [PCT_FMT] * 3)
        te = row
        row = set_data_row(
            ws, row, 1,
            ["TOTAL"] + [f"=SUM({c}{eq_first}:{c}{te - 1})" for c in "BCDE"]
            + [f'=IFERROR(C{te}/B{te},"")', f'=IFERROR(E{te}/B{te},"")',
               f'=IFERROR((C{te}-E{te})/B{te},"")'],
            formats=[None] + ["0"] * 4 + [PCT_FMT] * 3, total=True)
        row += 1

        row = set_subtitle(ws, row, 1, 9, "Ataque según calidad del armado, por jugador")
        row = set_headers(ws, row, 1, ["Jugador", "Calidad"] + ["Ataques", "Puntos", "Defendidos", "Fuera", "% Punto", "% Fuera", "Eficacia"])
        for p, cal in atkcal_filas:
            r = row
            vals = [p, cal, f"=D{r}+E{r}+F{r}"] + [
                "=" + sumifs_dos(col, ATKCAL_LAST, "DM", p, "DN", cal) for col in ("DO", "DP", "DQ")]
            vals += [f'=IFERROR(D{r}/C{r},"")', f'=IFERROR(F{r}/C{r},"")',
                     f'=IFERROR((D{r}-F{r})/C{r},"")']
            row = set_data_row(ws, row, 1, vals,
                               formats=[None, None] + ["0"] * 4 + [PCT_FMT] * 3)
        row = set_footnote(
            ws, row, 1, 9,
            "Solo ataques que vienen de un armado (los de primera no). Eficacia = "
            "(puntos − fuera) / ataques; \"fuera\" incluye afuera, malla y bloqueado.",
        )

    widths = {"A": 13}
    for i in range(n_az):
        widths[col_letter(2 + i)] = 10
    widths[col_letter(2 + n_az)] = 14
    widths[col_letter(3 + n_az)] = 16
    widths[col_letter(4 + n_az)] = 14
    autosize(ws, widths)
    ws.freeze_panes = "A4"

    # ------------------------------------------------------------------
    # Hoja 5: Zona y direccion
    # ------------------------------------------------------------------
    n_dz = len(atk_dirs)
    ws = new_sheet(wb, "Zona y dirección")
    row = 1
    row = set_title(ws, row, 1, 8, f"ZONA Y DIRECCIÓN DE ATAQUE — {equipo_name.upper()}")

    row = set_subtitle(ws, row, 1, 8, "Resultado por zona de origen")
    row = set_headers(ws, row, 1, ["Zona", "Ataques", "% del total", "Puntos", "Defendidos", "Fuera", "% Punto", "% Fuera"])
    z1_first = row
    for z in atk_zonas:
        r = row
        d_ = sumif("X", ATKD_LAST, "V", z)
        e_ = sumif("Y", ATKD_LAST, "V", z)
        f_ = sumif("Z", ATKD_LAST, "V", z)
        b_ = f"=D{r}+E{r}+F{r}"
        c_ = f"=IFERROR(B{r}/B${z1_first + len(atk_zonas)},\"\")"
        g_ = f"=IFERROR(D{r}/B{r},\"\")"
        h_ = f"=IFERROR(F{r}/B{r},\"\")"
        row = set_data_row(ws, row, 1, [f"Zona {z}", b_, c_, "=" + d_, "=" + e_, "=" + f_, g_, h_],
                            formats=[None, "0", PCT_FMT, "0", "0", "0", PCT_FMT, PCT_FMT])
    t = row
    row = set_data_row(
        ws, row, 1,
        ["TOTAL", f"=SUM(B{z1_first}:B{t - 1})", f"=IFERROR(B{t}/B{t},\"\")",
         f"=SUM(D{z1_first}:D{t - 1})", f"=SUM(E{z1_first}:E{t - 1})", f"=SUM(F{z1_first}:F{t - 1})",
         f"=IFERROR(D{t}/B{t},\"\")", f"=IFERROR(F{t}/B{t},\"\")"],
        formats=[None, "0", PCT_FMT, "0", "0", "0", PCT_FMT, PCT_FMT], total=True,
    )
    row += 1

    row = set_subtitle(ws, row, 1, 8, "Resultado por dirección del ataque")
    row = set_headers(ws, row, 1, ["Dirección", "Ataques", "% del total", "Puntos", "Defendidos", "Fuera", "% Punto", "% Fuera"])
    z2_first = row
    for dd in atk_dirs:
        r = row
        d_ = sumif("X", ATKD_LAST, "W", dd)
        e_ = sumif("Y", ATKD_LAST, "W", dd)
        f_ = sumif("Z", ATKD_LAST, "W", dd)
        b_ = f"=D{r}+E{r}+F{r}"
        c_ = f"=IFERROR(B{r}/B${z2_first + len(atk_dirs)},\"\")"
        g_ = f"=IFERROR(D{r}/B{r},\"\")"
        h_ = f"=IFERROR(F{r}/B{r},\"\")"
        row = set_data_row(ws, row, 1, [f"Zona {dd}", b_, c_, "=" + d_, "=" + e_, "=" + f_, g_, h_],
                            formats=[None, "0", PCT_FMT, "0", "0", "0", PCT_FMT, PCT_FMT])
    t = row
    row = set_data_row(
        ws, row, 1,
        ["TOTAL", f"=SUM(B{z2_first}:B{t - 1})", f"=IFERROR(B{t}/B{t},\"\")",
         f"=SUM(D{z2_first}:D{t - 1})", f"=SUM(E{z2_first}:E{t - 1})", f"=SUM(F{z2_first}:F{t - 1})",
         f"=IFERROR(D{t}/B{t},\"\")", f"=IFERROR(F{t}/B{t},\"\")"],
        formats=[None, "0", PCT_FMT, "0", "0", "0", PCT_FMT, PCT_FMT], total=True,
    )
    row += 1

    ncols3 = 1 + n_dz + 1
    row = set_subtitle(ws, row, 1, ncols3, "Matriz zona de origen × dirección — ataques totales")
    row = set_headers(ws, row, 1, ["Zona origen"] + [f"Zona {dd}" for dd in atk_dirs] + ["Total"])
    mat3_first = row
    for z in atk_zonas:
        r = row
        vals = [f"Zona {z}"]
        for dd in atk_dirs:
            vals.append("=" + atk_count_terms(zona=z, direccion=dd))
        last_col = col_letter(1 + n_dz)
        vals.append(f"=SUM(B{r}:{last_col}{r})")
        row = set_data_row(ws, row, 1, vals, formats=[None] + ["0"] * (n_dz + 1))
    t3 = row
    tot_vals = ["TOTAL"]
    for i in range(1, n_dz + 2):
        cl = col_letter(1 + i)
        tot_vals.append(f"=SUM({cl}{mat3_first}:{cl}{t3 - 1})")
    row = set_data_row(ws, row, 1, tot_vals, formats=[None] + ["0"] * (n_dz + 1), total=True)
    row += 1

    row = set_footnote(
        ws, row, 1, 8,
        "Nota: estas tablas consideran solo los ataques con zona de origen y dirección registradas en el "
        "volcado; ver Hoja \"Ataque jugador\" para los ataques sin zona/dirección y advertencias del script.",
    )

    row += 1
    # Tipo de resolucion (potente / colocado / block-out) cruzado con la
    # direccion final: es donde se ve si un atacante es demasiado predecible.
    row = set_subtitle(ws, row, 1, 8, "Resultado por tipo de resolución")
    if not atktipo_filas:
        row = set_footnote(ws, row, 1, 8, "Sin ataques con dirección registrados en el volcado.")
    else:
        row = set_headers(ws, row, 1, ["Tipo"] + ["Ataques", "Puntos", "Defendidos", "Fuera", "% Punto", "% Fuera", "Eficacia"])
        tr_first = row
        for tipo in TIPOS_RESOLUCION:
            r = row
            vals = [tipo, f"=C{r}+D{r}+E{r}"] + [
                "=" + sumif(col, ATKTIPO_LAST, "DT", tipo) for col in ("DV", "DW", "DX")]
            vals += [f'=IFERROR(C{r}/B{r},"")', f'=IFERROR(E{r}/B{r},"")',
                     f'=IFERROR((C{r}-E{r})/B{r},"")']
            row = set_data_row(ws, row, 1, vals, formats=[None] + ["0"] * 4 + [PCT_FMT] * 3)
        tt = row
        row = set_data_row(
            ws, row, 1,
            ["TOTAL"] + [f"=SUM({c}{tr_first}:{c}{tt - 1})" for c in "BCDE"]
            + [f'=IFERROR(C{tt}/B{tt},"")', f'=IFERROR(E{tt}/B{tt},"")',
               f'=IFERROR((C{tt}-E{tt})/B{tt},"")'],
            formats=[None] + ["0"] * 4 + [PCT_FMT] * 3, total=True)
        row += 1

        cab_dir = [f"Zona {d}" for d in DIRECCIONES_ATAQUE]
        cab_pct = [f"% Zona {d}" for d in DIRECCIONES_ATAQUE]
        row = set_subtitle(ws, row, 1, 8, "Tipo de resolución × dirección (equipo)")
        row = set_headers(ws, row, 1, ["Tipo"] + cab_dir + ["Total"] + cab_pct)
        for tipo in TIPOS_RESOLUCION:
            r = row
            vals = [tipo] + ["=" + tipo_count([("DT", tipo), ("DU", d)]) for d in DIRECCIONES_ATAQUE]
            vals.append(f"=SUM(B{r}:D{r})")
            vals += [f'=IFERROR({c}{r}/E{r},"")' for c in "BCD"]
            row = set_data_row(ws, row, 1, vals, formats=[None] + ["0"] * 4 + [PCT_FMT] * 3)
        row += 1

        row = set_subtitle(ws, row, 1, 10, "Dirección por jugador y tipo de resolución")
        row = set_headers(ws, row, 1, ["Jugador", "Tipo"] + cab_dir + ["Total"] + cab_pct
                          + ["% dirección más usada"])
        for p, tipo in atktipo_filas:
            r = row
            vals = [p, tipo] + ["=" + tipo_count([("DS", p), ("DT", tipo), ("DU", d)])
                                for d in DIRECCIONES_ATAQUE]
            vals.append(f"=SUM(C{r}:E{r})")
            vals += [f'=IFERROR({c}{r}/F{r},"")' for c in "CDE"]
            vals.append(f'=IFERROR(MAX(C{r}:E{r})/F{r},"")')
            row = set_data_row(ws, row, 1, vals,
                               formats=[None, None] + ["0"] * 4 + [PCT_FMT] * 4)
        row = set_footnote(
            ws, row, 1, 10,
            "\"% dirección más usada\" alto con varios ataques = patrón previsible. "
            "El block-out se toma del resultado; \"Sin tipo\" son los ataques que se "
            "cargaron sin marcar potente o colocado.",
        )

    widths = {"A": 22, "B": 10, "C": 11, "D": 10, "E": 11, "F": 10, "G": 10, "H": 10}
    autosize(ws, widths)
    ws.freeze_panes = "A4"

    # ------------------------------------------------------------------
    # Hoja: Saque (normal y de potencia)
    # ------------------------------------------------------------------
    ws = new_sheet(wb, "Saque")
    row = 1
    row = set_title(ws, row, 1, 9, f"SAQUE — {equipo_name.upper()}")
    row = set_nota(ws, row, 1, 9,
        "Los saques de POTENCIA son los que se cargaron con el \"_P\" (ej. 5_1_6_P_A). "
        "\"En juego\": el saque paso y el rival recibio. El error en juego del que "
        "saca (\"f\") no deja saque cargado y no entra.")

    row = set_subtitle(ws, row, 1, 9, "Saques por jugador")
    if not saq_players:
        row = set_footnote(ws, row, 1, 9, "Sin saques registrados en el volcado.")
    else:
        row = set_headers(ws, row, 1, ["Jugador", "Saques", "As", "Errores", "En juego",
                                       "% As", "% Error", "Potencia", "% Potencia"])
        sq_first = row
        for p in saq_players:
            r = row
            row = set_data_row(ws, row, 1, [
                p,
                "=" + sumif("DE", SAQ_LAST, "DC", p),
                "=" + sumif("DF", SAQ_LAST, "DC", p),
                "=" + sumif("DG", SAQ_LAST, "DC", p),
                f"=B{r}-C{r}-D{r}",
                f"=IFERROR(C{r}/B{r},\"\")",
                f"=IFERROR(D{r}/B{r},\"\")",
                "=" + sumifs_dos("DE", SAQ_LAST, "DC", p, "DD", "Potencia"),
                f"=IFERROR(H{r}/B{r},\"\")",
            ], formats=[None, "0", "0", "0", "0", PCT_FMT, PCT_FMT, "0", PCT_FMT])
        ts = row
        row = set_data_row(ws, row, 1, [
            "TOTAL",
            f"=SUM(B{sq_first}:B{ts - 1})", f"=SUM(C{sq_first}:C{ts - 1})",
            f"=SUM(D{sq_first}:D{ts - 1})", f"=SUM(E{sq_first}:E{ts - 1})",
            f"=IFERROR(C{ts}/B{ts},\"\")", f"=IFERROR(D{ts}/B{ts},\"\")",
            f"=SUM(H{sq_first}:H{ts - 1})", f"=IFERROR(H{ts}/B{ts},\"\")",
        ], formats=[None, "0", "0", "0", "0", PCT_FMT, PCT_FMT, "0", PCT_FMT], total=True)
        row += 1

        row = set_subtitle(ws, row, 1, 8, "Saque normal vs. potencia (equipo)")
        row = set_headers(ws, row, 1, ["Tipo", "Saques", "% de los saques", "As", "Errores",
                                       "En juego", "% As", "% Error"])
        tipo_first = row
        fila_total = tipo_first + len(TIPOS_SAQUE_FUERZA)
        for tipo in TIPOS_SAQUE_FUERZA:
            r = row
            row = set_data_row(ws, row, 1, [
                tipo,
                "=" + sumif("DE", SAQ_LAST, "DD", tipo),
                f"=IFERROR(B{r}/B${fila_total},\"\")",
                "=" + sumif("DF", SAQ_LAST, "DD", tipo),
                "=" + sumif("DG", SAQ_LAST, "DD", tipo),
                f"=B{r}-D{r}-E{r}",
                f"=IFERROR(D{r}/B{r},\"\")",
                f"=IFERROR(E{r}/B{r},\"\")",
            ], formats=[None, "0", PCT_FMT, "0", "0", "0", PCT_FMT, PCT_FMT])
        tt = row
        row = set_data_row(ws, row, 1, [
            "TOTAL", f"=SUM(B{tipo_first}:B{tt - 1})", f"=IFERROR(B{tt}/B{tt},\"\")",
            f"=SUM(D{tipo_first}:D{tt - 1})", f"=SUM(E{tipo_first}:E{tt - 1})",
            f"=SUM(F{tipo_first}:F{tt - 1})",
            f"=IFERROR(D{tt}/B{tt},\"\")", f"=IFERROR(E{tt}/B{tt},\"\")",
        ], formats=[None, "0", PCT_FMT, "0", "0", "0", PCT_FMT, PCT_FMT], total=True)
        row += 1

        row = set_subtitle(ws, row, 1, 9, "Normal vs. potencia por jugador")
        row = set_headers(ws, row, 1, ["Jugador", "Normal", "As normal", "Error normal",
                                       "Potencia", "As potencia", "Error potencia",
                                       "% As potencia", "% Error potencia"])
        for p in saq_players:
            r = row
            vals = [p]
            for tipo in TIPOS_SAQUE_FUERZA:
                for col in ("DE", "DF", "DG"):
                    vals.append("=" + sumifs_dos(col, SAQ_LAST, "DC", p, "DD", tipo))
            vals += [f"=IFERROR(F{r}/E{r},\"\")", f"=IFERROR(G{r}/E{r},\"\")"]
            row = set_data_row(ws, row, 1, vals,
                               formats=[None] + ["0"] * 6 + [PCT_FMT, PCT_FMT])
    autosize(ws, {"A": 22, "B": 11, "C": 12, "D": 12, "E": 11, "F": 12, "G": 13, "H": 13, "I": 15})
    ws.freeze_panes = "A4"

    # ------------------------------------------------------------------
    # Orden de hojas y hoja oculta
    # ------------------------------------------------------------------
    order = ["Partido", "Fases y armador", "Saque", "Recepción", "Defensa", "Armado",
             "Ataque jugador", "Zona y dirección", "Datos_Base"]
    wb._sheets = [wb[name] for name in order]
    wb["Datos_Base"].sheet_state = "hidden"
    wb.active = 0

    return wb, warnings


# ======================================================================
# 4) MAIN / CLI
# ======================================================================

RE_FECHA_EN_NOMBRE = re.compile(r"(20\d{2})(\d{2})(\d{2})")


def guess_fecha_from_filename(path):
    """Detecta AAAA-MM-DD en nombres tipo partido_20260903_200737.txt."""
    m = RE_FECHA_EN_NOMBRE.search(path)
    if not m:
        return None
    anio, mes, dia = m.groups()
    try:
        return datetime.date(int(anio), int(mes), int(dia)).isoformat()
    except ValueError:
        return None


def guardar_informe(libro, ruta) -> tuple[str, list[str]]:
    """Guarda el informe con los numeros ya calculados, sin formulas.

    Las tablas se arman internamente con formulas sobre la hoja Datos_Base
    porque es la forma de que todos los totales salgan del mismo lugar y
    cuadren entre si, pero el archivo que se entrega lleva los resultados
    escritos: openpyxl no calcula nada y los visores del celular leen el valor
    guardado, asi que con formulas sueltas las tablas se ven vacias.

    Devuelve (ruta, avisos)."""
    import valores_excel

    ruta = pathlib.Path(ruta)
    convertidas, fallidas = valores_excel.convertir_a_valores(libro)
    avisos = []
    if fallidas:
        avisos.append(f"{len(fallidas)} formula(s) no se pudieron calcular y quedaron sin "
                      f"resolver en el archivo: {fallidas[0]}")
    alm.carpeta_lista(ruta.parent)
    libro.save(ruta)
    # Si esto corre en un serverless, `ruta` esta en /tmp y dura lo que dure la
    # instancia: el informe se sube al blob para que siga apareciendo despues.
    alm.publicar(ruta)
    return str(ruta), avisos


def main():
    ap = argparse.ArgumentParser(description="Genera el Informe de partido en Excel a partir de un volcado de estadisticas de volleyball.")
    ap.add_argument("volcado", nargs="?", default="-", help="Ruta al archivo .txt con el volcado (usa '-' o se omite para leer desde stdin).")
    ap.add_argument("--equipo", help="Nombre de 'mi equipo' tal como aparece en el volcado. Si el volcado solo trae un equipo, se detecta solo.")
    ap.add_argument("--rival", help="Nombre del rival (por defecto se toma del marcador de sets).")
    ap.add_argument("--fecha", help="Fecha del partido AAAA-MM-DD (por defecto: hoy).")
    ap.add_argument("-o", "--output", help="Ruta del .xlsx de salida (por defecto: Informe_<Equipo>_vs_<Rival>_<Fecha>.xlsx).")
    args = ap.parse_args()

    if args.volcado == "-":
        text = sys.stdin.read()
    else:
        with open(args.volcado, "r", encoding="utf-8") as fh:
            text = fh.read()

    parsed = parse_volcado(text)

    equipos_disponibles = list(parsed["teams"].keys())
    if args.equipo:
        equipo_name = args.equipo
        if equipo_name not in parsed["teams"]:
            sys.exit(f"Error: el equipo '{equipo_name}' no aparece en el volcado. Equipos encontrados: {equipos_disponibles}")
    elif len(equipos_disponibles) == 1:
        equipo_name = equipos_disponibles[0]
    else:
        sys.exit(f"Error: el volcado trae mas de un equipo ({equipos_disponibles}). Especifica --equipo <nombre>.")

    t1, t2 = parsed["team1_name"], parsed["team2_name"]
    if args.rival:
        rival_name = args.rival
    elif t1 and t1.strip().lower() != equipo_name.strip().lower():
        rival_name = t1
    elif t2 and t2.strip().lower() != equipo_name.strip().lower():
        rival_name = t2
    else:
        rival_name = "Rival"

    fecha = args.fecha or guess_fecha_from_filename(args.volcado) or datetime.date.today().isoformat()

    wb, warnings = build_workbook(equipo_name, rival_name, parsed)

    if args.output:
        out_path = args.output
    else:
        # sin -o el informe va a la carpeta de informes que corresponda: la
        # del proyecto en una maquina propia, /tmp si corre alojado
        carpeta = alm.carpeta_lista(alm.carpeta_de_escritura(alm.INFORMES))
        out_path = str(carpeta / f"Informe_{equipo_name}_vs_{rival_name}_{fecha}.xlsx")
    salida, avisos_guardado = guardar_informe(wb, out_path)

    print(f"Archivo generado: {salida}")
    for aviso in avisos_guardado:
        print(f"  {aviso}")
    if warnings:
        print("\nInconsistencias detectadas en el volcado original:")
        for w in warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
