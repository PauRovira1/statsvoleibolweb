"""
Ficha de cada jugador, juntando todos los partidos guardados.

No guarda nada: cada pedido relee los volcados de Datos/ y suma. Son unos
pocos milisegundos por partido, y a cambio no hay un segundo juego de numeros
que pueda quedar desactualizado cuando se borra o se recarga un partido.

Lo unico delicado es no contar dos veces el mismo partido: en Datos/ conviven
recargas del mismo encuentro (a veces completas, a veces a medias) y sumarlas
duplicaria en silencio las cifras de todos. Por eso partidos_unicos() ademas
devuelve lo que descarto, para poder mostrarlo en pantalla.
"""
import re
from pathlib import Path

import almacenamiento as alm
import analisis_voley as av
import archivo_partidos

CARPETA_DATOS = av.CARPETA_DATOS

# Solo se arman fichas de los equipos propios. Los del rival se cargan para
# poder llevar el partido, pero no son jugadores nuestros y sus datos son
# bastante menos confiables: al no llevar rotacion no se sabe quien es el
# armador, y los dorsales se anotan de memoria.
#
# Se compara como prefijo y sin distinguir mayusculas, asi que "Palestino" y
# "Palestino B" entran solos. Para sumar otro equipo, agregarlo a esta tupla.
EQUIPOS_PROPIOS = ("palestino",)
ZONAS_ATAQUE = ("1", "2", "3", "4", "6-5")
DIRECCIONES = ("1", "5", "6")
CALIDADES = (3, 2, 1, 0)
RE_FECHA = re.compile(r"(20\d{2})(\d{2})(\d{2})")


def es_equipo_propio(nombre: str) -> bool:
    limpio = " ".join(str(nombre or "").split()).lower()
    return any(limpio.startswith(prefijo) for prefijo in EQUIPOS_PROPIOS)


def _parser():
    import generar_informe_volley
    return generar_informe_volley


def _cero_recepcion():
    return {"cal3": 0, "cal2": 0, "cal1": 0, "cal0": 0, "pase": 0}


def _cero_ataque():
    return {"totales": 0, "puntos": 0, "defendidos": 0, "fuera": 0}


def _sumar(destino: dict, origen: dict) -> None:
    for clave, valor in (origen or {}).items():
        destino[clave] = destino.get(clave, 0) + valor


def _sumar_hondo(destino: dict, origen: dict) -> None:
    """Suma diccionarios anidados: {"hechos": {"K1": {"total": 3}}}.

    Las secciones de equipo del volcado tienen dos y tres niveles, y cada
    partido trae solo las claves que ocurrieron. Sumar a mano nivel por nivel
    seria repetir el mismo bucle cinco veces."""
    for clave, valor in (origen or {}).items():
        if isinstance(valor, dict):
            _sumar_hondo(destino.setdefault(clave, {}), valor)
        elif isinstance(valor, bool):
            destino[clave] = destino.get(clave) or valor
        elif isinstance(valor, (int, float)):
            destino[clave] = destino.get(clave, 0) + valor
        else:
            # etiquetas, no numeros: "tipo": "Paralelo" dice de que saque
            # vino esa recepcion y es la misma en todos los partidos. Sin
            # esto la columna llegaba vacia a la pantalla.
            destino.setdefault(clave, valor)


def _dorsal(clave: str) -> str:
    return str(clave).replace("Jugador ", "").strip()


def _fecha_de(nombre: str) -> str:
    m = RE_FECHA.search(nombre)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


# ----------------------------------------------------------------------
def _parciales(volcado: dict) -> tuple:
    """Los parciales jugados, en el orden de los dos equipos ya ordenado por
    nombre, para poder comparar dos volcados del mismo partido."""
    equipos = [volcado.get("team1_name") or "", volcado.get("team2_name") or ""]
    invertir = equipos[0].strip().lower() > equipos[1].strip().lower()
    parciales = []
    for _, uno, otro in sorted(volcado.get("sets_rows") or []):
        if uno + otro == 0:
            continue                      # set abierto que no se jugo
        parciales.append((otro, uno) if invertir else (uno, otro))
    return tuple(parciales)


def _es_prefijo(corto: tuple, largo: tuple) -> bool:
    return len(corto) <= len(largo) and largo[:len(corto)] == corto


def _jugadas_cargadas(texto: str) -> tuple:
    """Las lineas tal como se tipearon, del encabezado a la primera seccion.

    Comparar esto es lo unico exacto para saber si dos volcados son el mismo
    partido: los parciales no alcanzan porque un guardado hecho a mitad de un
    set dice 15-14 donde el completo dice 20-25, y asi el parcial se contaba
    como un partido aparte y sus jugadas se sumaban dos veces."""
    lineas = []
    for linea in texto.splitlines():
        if linea.startswith("==="):
            if lineas:
                break
            continue
        lineas.append(linea)
    while lineas and not lineas[-1].strip():
        lineas.pop()
    return tuple(lineas)


# Secciones que se fueron agregando con el tiempo: un volcado viejo del mismo
# partido no las trae. Sirven para elegir, entre dos recargas iguales, la que
# tiene mas datos en vez de la primera que aparezca.
SECCIONES_OPCIONALES = (
    "recepciones_por_set", "bloqueos_jugador", "armado_armador",
    "armado_armador_por_set", "armado_calidad_armador", "zona_armador",
)


def _riqueza(volcado: dict) -> int:
    """Cuantas de las secciones nuevas trae el volcado."""
    return sum(
        1
        for datos in volcado.get("teams", {}).values()
        for seccion in SECCIONES_OPCIONALES
        if datos.get(seccion)
    ) + sum(1 for c in ("hechos", "recibidos")
            for datos in volcado.get("teams", {}).values()
            if datos.get("fases", {}).get(c))


def partidos_unicos(carpeta=None) -> tuple[list[dict], list[dict]]:
    """Lee los volcados y descarta las recargas del mismo partido.

    Dos volcados son el mismo partido si enfrentan a los mismos equipos y los
    parciales de uno son el principio de los del otro; se queda el mas largo.
    Devuelve (elegidos, descartados)."""
    if carpeta is None:
        # los volcados pueden estar repartidos entre la carpeta de escritura
        # (lo guardado, mas lo que se bajo del blob) y la del deploy
        alm.sincronizar(alm.DATOS)
        carpetas = archivo_partidos.carpetas_de_tipo("txt")
    else:
        carpetas = [Path(carpeta)]
    gi = _parser()

    leidos = []
    for ruta in archivo_partidos.archivos_de(carpetas, "*.txt",
                                             alm.DATOS if carpeta is None else None):
        if ruta.name.startswith("~$"):
            continue
        try:
            texto = ruta.read_text(encoding="utf-8")
            volcado = gi.parse_volcado(texto)
        except (OSError, ValueError):
            continue
        if not volcado.get("teams"):
            continue
        # quienes llevaban el flag _S: sin rotacion cargada el volcado lista
        # como "armador" a cualquiera que haya armado una pelota de emergencia
        marcados: dict = {}
        for rot in archivo_partidos.secciones_de_cancha(texto)["rotaciones"]:
            for eq in rot["equipos"]:
                if eq["armador"]:
                    marcados.setdefault(eq["equipo"], set()).add(str(eq["armador"]))

        leidos.append({
            "archivo": ruta.name,
            "jugadas": _jugadas_cargadas(texto),
            "armadores": marcados,
            "fecha": _fecha_de(ruta.name),
            "equipos": tuple(sorted(volcado["teams"])),
            "parciales": _parciales(volcado),
            "puntos": volcado.get("total_puntos_cargados") or 0,
            "riqueza": _riqueza(volcado),
            "volcado": volcado,
        })

    elegidos, descartados = [], []
    # a igualdad de partido se queda el volcado con mas secciones: los viejos
    # no traen las que se agregaron despues y perderiamos esos datos
    for partido in sorted(leidos,
                          key=lambda p: (-len(p["parciales"]), -len(p["jugadas"]),
                                         -p["puntos"], -p["riqueza"])):
        gemelo = next(
            (e for e in elegidos
             if e["equipos"] == partido["equipos"]
             and (_es_prefijo(partido["parciales"], e["parciales"])
                  # o directamente lo mismo tipeado: un guardado a mitad de
                  # set tiene otro parcial pero las mismas jugadas
                  or (partido["jugadas"]
                      and _es_prefijo(partido["jugadas"], e["jugadas"])))),
            None,
        )
        if gemelo is None:
            elegidos.append(partido)
            continue
        descartados.append({
            "archivo": partido["archivo"],
            "motivo": (f"mismo partido que {gemelo['archivo']}"
                       + ("" if partido["parciales"] == gemelo["parciales"] else ", con menos sets")
                       + ("" if partido["riqueza"] >= gemelo["riqueza"] else ", y con menos datos")),
        })

    elegidos.sort(key=lambda p: (p["fecha"], p["archivo"]))
    return elegidos, descartados


# ----------------------------------------------------------------------
def _acumular(destino: dict, datos: dict, etiqueta: str, numero_set_base: int) -> None:
    """Suma a "destino" (una ficha por dorsal) lo que aporta un partido."""
    gi = _parser()
    gi.reconcile_sin_registrar(datos, [], "")      # completa "Sin registrar"

    def ficha(clave):
        return destino.setdefault(_dorsal(clave), {
            "recepcion": _cero_recepcion(),
            "recepcion_set": {},
            "ataque": _cero_ataque(),
            "detalle": {},
            "bloqueos": 0,
            "armado": {},
            "armado_calidad": {c: {} for c in CALIDADES},
            "partidos": [],
        })

    vistos = set()
    for clave, valores in datos["recepciones"].items():
        j = ficha(clave); vistos.add(_dorsal(clave))
        _sumar(j["recepcion"], valores)
    for numero, jugadores in datos["recepciones_por_set"].items():
        for clave, valores in jugadores.items():
            j = ficha(clave); vistos.add(_dorsal(clave))
            _sumar(j["recepcion_set"].setdefault(numero_set_base + numero, _cero_recepcion()), valores)
    for clave, valores in datos["ataques_jugador"].items():
        j = ficha(clave); vistos.add(_dorsal(clave))
        j["ataque"]["totales"] += valores["totales"]
        j["ataque"]["puntos"] += valores["puntos"]
        j["ataque"]["defendidos"] += valores["defendidos"]
        j["ataque"]["fuera"] += valores["fuera"]
    for clave, zona, direccion, punto, defendido, fuera in datos["ataques_detalle"]:
        j = ficha(clave); vistos.add(_dorsal(clave))
        celda = j["detalle"].setdefault((zona, direccion), _cero_ataque())
        celda["totales"] += punto + defendido + fuera
        celda["puntos"] += punto
        celda["defendidos"] += defendido
        celda["fuera"] += fuera
    for clave, cantidad in datos["bloqueos_jugador"].items():
        j = ficha(clave); vistos.add(_dorsal(clave))
        j["bloqueos"] += cantidad
    for clave, zonas in datos["armado_armador"].items():
        j = ficha(clave); vistos.add(_dorsal(clave))
        _sumar(j["armado"], zonas)
    for clave, calidades in datos["armado_calidad_armador"].items():
        j = ficha(clave); vistos.add(_dorsal(clave))
        for calidad, zonas in calidades.items():
            _sumar(j["armado_calidad"].setdefault(calidad, {}), zonas)

    # una linea por partido, para el resumen y el grafico
    for dorsal in vistos:
        j = destino[dorsal]
        rec = _cero_recepcion()
        _sumar(rec, datos["recepciones"].get(f"Jugador {dorsal}", {}))
        atk = dict(_cero_ataque())
        de_ataque = datos["ataques_jugador"].get(f"Jugador {dorsal}")
        if de_ataque:
            atk = {"totales": de_ataque["totales"], "puntos": de_ataque["puntos"],
                   "defendidos": de_ataque["defendidos"], "fuera": de_ataque["fuera"]}
        j["partidos"].append({
            "etiqueta": etiqueta,
            "recepcion": rec,
            "ataque": atk,
            "bloqueos": datos["bloqueos_jugador"].get(f"Jugador {dorsal}", 0),
            "armados": sum(datos["armado_armador"].get(f"Jugador {dorsal}", {}).values()),
            "armados_equipo": sum(datos["armado_zona"].values()),
        })


SECCIONES_DE_EQUIPO = ("fases", "causas", "zona_armador", "armado_zona",
                       "armado_calidad", "recepcion_tipo_saque")


def _cero_equipo() -> dict:
    return {seccion: {} for seccion in SECCIONES_DE_EQUIPO} | {
        "recepcion": _cero_recepcion(),
        "ataque": _cero_ataque(),
        # (zona de origen, direccion) -> ataques, para la matriz de tendencia
        "direccion": {},
        "bloqueos": 0,
        "sets": 0,
        "partidos": [],
    }


def _acumular_equipo(destino: dict, datos: dict, etiqueta: str, sets: int) -> None:
    """Suma un partido al acumulado del equipo, sin abrir por jugador.

    Casi todo ya viene a nivel equipo en el volcado y solo hay que sumarlo. Lo
    que no -- recepcion, ataque, bloqueos y la matriz de direcciones -- se arma
    sumando a todos los jugadores, que es lo mismo que mirar al equipo."""
    for seccion in SECCIONES_DE_EQUIPO:
        _sumar_hondo(destino[seccion], datos.get(seccion) or {})

    recepcion, ataque = _cero_recepcion(), _cero_ataque()
    for valores in (datos.get("recepciones") or {}).values():
        _sumar(recepcion, valores)
    for valores in (datos.get("ataques_jugador") or {}).values():
        _sumar(ataque, valores)
    _sumar(destino["recepcion"], recepcion)
    _sumar(destino["ataque"], ataque)

    bloqueos = sum((datos.get("bloqueos_jugador") or {}).values())
    destino["bloqueos"] += bloqueos
    destino["sets"] += sets

    for _, zona, direccion, puntos, defendidos, fuera in (datos.get("ataques_detalle") or []):
        celda = destino["direccion"].setdefault((str(zona), str(direccion)), _cero_ataque())
        celda["puntos"] += puntos
        celda["defendidos"] += defendidos
        celda["fuera"] += fuera
        celda["totales"] += puntos + defendidos + fuera

    # una fila por partido: un acumulado de varios encuentros esconde si el
    # equipo viene mejorando o empeorando, que es media pregunta del entrenador
    fases = datos.get("fases") or {}
    destino["partidos"].append({
        "etiqueta": etiqueta,
        "hechos": sum(f.get("total", 0) for f in (fases.get("hechos") or {}).values()),
        "recibidos": sum(f.get("total", 0) for f in (fases.get("recibidos") or {}).values()),
        "recepciones": sum(recepcion.values()),
        "positiva": _porcentaje(recepcion["cal3"] + recepcion["cal2"], sum(recepcion.values())),
        "ataques": ataque["totales"],
        "punto": _porcentaje(ataque["puntos"], ataque["totales"]),
        "eficacia": _porcentaje(ataque["puntos"] - ataque["fuera"], ataque["totales"]),
        "bloqueos": bloqueos,
    })


def agregar(carpeta=None) -> dict:


    """Junta todos los partidos. Devuelve {equipo: {dorsal: ficha cruda}}."""
    elegidos, descartados = partidos_unicos(carpeta)
    equipos: dict = {}
    partidos_por_equipo: dict = {}
    marcados_como_armador: dict = {}
    # lo mismo que lo de arriba pero sin abrir por jugador: son las secciones
    # que el volcado ya trae a nivel equipo (fases del rally, causas, armado
    # por zona, recepcion por tipo de saque) mas las que se arman sumando a
    # todos. Se acumula en la misma pasada porque releer los volcados es lo
    # unico caro de todo esto.
    por_equipo: dict = {}
    otros: set = set()

    for partido in elegidos:
        volcado = partido["volcado"]
        nombres = list(volcado["teams"])
        for nombre, datos in volcado["teams"].items():
            if not es_equipo_propio(nombre):
                otros.add(nombre)
                continue
            rival = next((n for n in nombres if n != nombre), "?")
            etiqueta = f"vs {rival}"
            if partido["fecha"]:
                etiqueta += f" ({partido['fecha']})"
            _acumular(equipos.setdefault(nombre, {}), datos, etiqueta, 0)
            _acumular_equipo(por_equipo.setdefault(nombre, _cero_equipo()),
                             datos, etiqueta, len(partido["parciales"]))
            for dorsal in partido["armadores"].get(nombre, ()):
                marcados_como_armador.setdefault(nombre, set()).add(dorsal)
            partidos_por_equipo.setdefault(nombre, []).append({
                "archivo": partido["archivo"], "rival": rival,
                "fecha": partido["fecha"], "sets": len(partido["parciales"]),
            })

    return {"equipos": equipos, "partidos": partidos_por_equipo,
            "por_equipo": por_equipo,
            "armadores": marcados_como_armador, "otros_equipos": sorted(otros),
            "descartados": descartados, "elegidos": elegidos}


# ----------------------------------------------------------------------
def _porcentaje(parte, total):
    return (parte / total) if total else 0.0


def _resumen_recepcion(r: dict) -> dict:
    total = sum(r.values())
    return {"recepciones": total, "cal3": r["cal3"], "cal2": r["cal2"],
            "cal1": r["cal1"], "cal0": r["cal0"], "pase": r["pase"],
            "positiva": _porcentaje(r["cal3"] + r["cal2"], total),
            "perfecta": _porcentaje(r["cal3"], total)}


def ficha(equipo: str, dorsal: str, agregado: dict | None = None) -> dict | None:
    """La ficha de un jugador con la forma que espera la pantalla."""
    agregado = agregado or agregar()
    if not es_equipo_propio(equipo):
        return None
    crudo = agregado["equipos"].get(equipo, {}).get(str(dorsal))
    if crudo is None:
        return None

    rec, atk = crudo["recepcion"], crudo["ataque"]
    armados = sum(crudo["armado"].values())
    es_armador = str(dorsal) in agregado.get("armadores", {}).get(equipo, set())
    partidos_equipo = agregado["partidos"].get(equipo, [])

    zonas_atacadas = sorted(
        {z for z, _ in crudo["detalle"]},
        key=lambda z: -sum(v["totales"] for (zz, _), v in crudo["detalle"].items() if zz == z),
    )
    por_zona = []
    for zona in zonas_atacadas:
        celdas = [v for (z, _), v in crudo["detalle"].items() if z == zona]
        por_zona.append({
            "zona": zona,
            "ataques": sum(c["totales"] for c in celdas),
            "punto": sum(c["puntos"] for c in celdas),
            "defendido": sum(c["defendidos"] for c in celdas),
            "fuera": sum(c["fuera"] for c in celdas),
        })

    zonas_armadas = sorted(crudo["armado"], key=lambda z: -crudo["armado"][z])

    return {
        "equipo": equipo,
        "dorsal": dorsal,
        "armador": es_armador,
        # De que juega, si se anoto. "Armador" no vive aca: sale del _S de las
        # rotaciones, o sea del partido, y por eso va en su propio campo.
        "posicion": alm.posiciones_del_equipo(equipo).get(str(dorsal), ""),
        "partidos": len(crudo["partidos"]),
        "sets": sum(p["sets"] for p in partidos_equipo),
        "indicadores": {
            "recepciones": sum(rec.values()),
            "positiva": _porcentaje(rec["cal3"] + rec["cal2"], sum(rec.values())),
            "perfecta": _porcentaje(rec["cal3"], sum(rec.values())),
            "ataques": atk["totales"],
            "punto": _porcentaje(atk["puntos"], atk["totales"]),
            "bloqueos_punto": crudo["bloqueos"],
            "armados": armados,
        },
        "por_partido": [{
            "etiqueta": p["etiqueta"],
            "recepciones": sum(p["recepcion"].values()),
            "positiva": _porcentaje(p["recepcion"]["cal3"] + p["recepcion"]["cal2"],
                                    sum(p["recepcion"].values())),
            "ataques": p["ataque"]["totales"],
            "punto": _porcentaje(p["ataque"]["puntos"], p["ataque"]["totales"]),
            "eficacia": _porcentaje(p["ataque"]["puntos"] - p["ataque"]["fuera"],
                                    p["ataque"]["totales"]),
            "bloqueos": p["bloqueos"],
            "armados": p["armados"],
            "armados_equipo": p["armados_equipo"],
        } for p in crudo["partidos"]],
        "recepcion": {
            "total": _resumen_recepcion(rec),
            "por_set": [dict(_resumen_recepcion(crudo["recepcion_set"][n]), set=n)
                        for n in sorted(crudo["recepcion_set"])],
        },
        "ataque": {
            "total": {"ataques": atk["totales"], "punto": atk["puntos"],
                      "defendido": atk["defendidos"], "fuera": atk["fuera"],
                      "eficacia": _porcentaje(atk["puntos"] - atk["fuera"], atk["totales"])},
            "por_zona": por_zona,
            "direcciones": list(DIRECCIONES),
            # "valores" son los ataques hacia cada direccion y "puntos" cuantos
            # de esos fueron punto: van juntos porque 27 ataques hacia la 6 no
            # dicen nada hasta saber cuantos entraron
            "matriz_direccion": [
                {"zona": zona,
                 "valores": [crudo["detalle"].get((zona, d), _cero_ataque())["totales"]
                             for d in DIRECCIONES],
                 "puntos": [crudo["detalle"].get((zona, d), _cero_ataque())["puntos"]
                            for d in DIRECCIONES]}
                for zona in zonas_atacadas
            ],
        },
        "armado": None if not armados else {
            "total": armados,
            "zonas": zonas_armadas,
            "por_zona": [{"zona": z, "armados": crudo["armado"][z]} for z in zonas_armadas],
            "matriz_calidad": [
                {"calidad": c,
                 "valores": [crudo["armado_calidad"].get(c, {}).get(z, 0) for z in zonas_armadas]}
                for c in CALIDADES
            ],
            "con_recepcion": sum(sum(v.values()) for v in crudo["armado_calidad"].values()),
        },
        "evolucion": [{
            "etiqueta": p["etiqueta"],
            "recepcion_positiva": _porcentaje(p["recepcion"]["cal3"] + p["recepcion"]["cal2"],
                                              sum(p["recepcion"].values())),
            "ataque_punto": _porcentaje(p["ataque"]["puntos"], p["ataque"]["totales"]),
        } for p in crudo["partidos"]],
        "promedio_equipo": _promedio_equipo(agregado, equipo),
    }


def _promedio_equipo(agregado: dict, equipo: str) -> dict:
    jugadores = agregado["equipos"].get(equipo, {})
    if not jugadores:
        return {}
    def media(f):
        valores = [f(j) for j in jugadores.values()]
        return sum(valores) / len(valores) if valores else 0
    return {
        "recepciones": round(media(lambda j: sum(j["recepcion"].values())), 1),
        "positiva": media(lambda j: _porcentaje(j["recepcion"]["cal3"] + j["recepcion"]["cal2"],
                                                sum(j["recepcion"].values()))),
        "perfecta": media(lambda j: _porcentaje(j["recepcion"]["cal3"], sum(j["recepcion"].values()))),
        "ataques": round(media(lambda j: j["ataque"]["totales"]), 1),
        "punto": media(lambda j: _porcentaje(j["ataque"]["puntos"], j["ataque"]["totales"])),
        "bloqueos_punto": round(media(lambda j: j["bloqueos"]), 1),
    }


FASES = ("K1", "K2", "K3", "Saque", "Sin fase")
GANADOS = ("Ataque punto", "Ataque usando el bloqueo", "Bloqueo punto", "As de saque")
ERRORES = ("Ataque afuera", "Ataque a la malla", "Error de saque", "Armado malo",
           "Defensa perdida", "Error en juego")


def _orden_zonas(presentes) -> list:
    """Las zonas en el orden de la cancha, con las raras al final."""
    conocidas = [z for z in ZONAS_ATAQUE if z in presentes]
    return conocidas + sorted(z for z in presentes if z not in ZONAS_ATAQUE)


def resumen_equipo(equipo: str, agregado: dict | None = None) -> dict | None:
    """Las mismas metricas que la ficha de un jugador, pero del equipo entero.

    No es la suma de las fichas: las preguntas que se responden aca -- en que
    fase se ganan los puntos, hacia donde se ataca desde cada zona de armado,
    que arma el armador segun como vino la recepcion -- no son de nadie en
    particular, son del juego."""
    agregado = agregado or agregar()
    if not es_equipo_propio(equipo):
        return None
    crudo = agregado.get("por_equipo", {}).get(equipo)
    if not crudo:
        return None

    rec, atk = crudo["recepcion"], crudo["ataque"]
    recibidas = sum(rec.values())
    fases, causas = crudo["fases"], crudo["causas"]
    hechos = sum(f.get("total", 0) for f in (fases.get("hechos") or {}).values())
    recibidos = sum(f.get("total", 0) for f in (fases.get("recibidos") or {}).values())

    def lado(donde, fase):
        return (fases.get(donde) or {}).get(fase) or {"total": 0, "ganados": 0, "error": 0}

    armado_total = sum(crudo["armado_zona"].values())
    zonas_armado = _orden_zonas(crudo["armado_zona"])

    # armado segun como vino la recepcion: con pase perfecto el armador puede
    # ir a cualquier lado, y con recepcion mala casi siempre termina en el
    # mismo. La fila por calidad es lo que muestra cuanto se achica el juego.
    zonas_calidad = _orden_zonas(
        {str(z) for por_zona in crudo["armado_calidad"].values() for z in por_zona})
    # parse_volcado devuelve la calidad como entero y la zona como texto; se
    # normaliza aca y no alla para no tocar el formato que lee el Excel
    por_calidad = {str(c): {str(z): n for z, n in v.items()}
                   for c, v in crudo["armado_calidad"].items()}
    distribucion = []
    for calidad in ("3", "2", "1", "0"):
        por_zona = por_calidad.get(calidad) or {}
        total = sum(por_zona.values())
        distribucion.append({
            "calidad": calidad,
            "total": total,
            "valores": [por_zona.get(z, 0) for z in zonas_calidad],
            "reparto": [_porcentaje(por_zona.get(z, 0), total) for z in zonas_calidad],
        })

    # hacia donde ataca el equipo desde cada zona de origen
    zonas_ataque = _orden_zonas({z for z, _ in crudo["direccion"]})
    direcciones = []
    for zona in zonas_ataque:
        celdas = [crudo["direccion"].get((zona, d), _cero_ataque()) for d in DIRECCIONES]
        desde = sum(c["totales"] for c in celdas)
        if not desde:
            continue          # el volcado lista zonas que nadie ataco nunca
        direcciones.append({
            "zona": zona,
            "ataques": desde,
            "del_total": _porcentaje(desde, atk["totales"]),
            "hacia": [{"direccion": d, "ataques": c["totales"],
                       "puntos": c["puntos"],
                       "reparto": _porcentaje(c["totales"], desde),
                       "punto": _porcentaje(c["puntos"], c["totales"])}
                      for d, c in zip(DIRECCIONES, celdas)],
        })

    def sin_tipo(v):
        return sum(x for k, x in v.items() if k != "tipo")

    return {
        "equipo": equipo,
        "partidos": len(crudo["partidos"]),
        "sets": crudo["sets"],
        "indicadores": {
            "hechos": hechos,
            "recibidos": recibidos,
            "recepciones": recibidas,
            "positiva": _porcentaje(rec["cal3"] + rec["cal2"], recibidas),
            "perfecta": _porcentaje(rec["cal3"], recibidas),
            "ataques": atk["totales"],
            "punto": _porcentaje(atk["puntos"], atk["totales"]),
            "eficacia": _porcentaje(atk["puntos"] - atk["fuera"], atk["totales"]),
            "bloqueos_punto": crudo["bloqueos"],
        },
        "fases": [{
            "fase": fase,
            "hechos": lado("hechos", fase)["total"],
            "hechos_reparto": _porcentaje(lado("hechos", fase)["total"], hechos),
            "hechos_ganados": lado("hechos", fase)["ganados"],
            "hechos_error": lado("hechos", fase)["error"],
            "recibidos": lado("recibidos", fase)["total"],
            "recibidos_reparto": _porcentaje(lado("recibidos", fase)["total"], recibidos),
            # el saldo es lo que dice si esa fase da o quita puntos
            "saldo": lado("hechos", fase)["total"] - lado("recibidos", fase)["total"],
        } for fase in FASES],
        "causas": {
            "ganados": [{"causa": c, "hechos": (causas.get("hechos") or {}).get(c, 0),
                         "recibidos": (causas.get("recibidos") or {}).get(c, 0)}
                        for c in GANADOS],
            "errores": [{"causa": c, "hechos": (causas.get("hechos") or {}).get(c, 0),
                         "recibidos": (causas.get("recibidos") or {}).get(c, 0)}
                        for c in ERRORES],
        },
        "armado_zona": [{"zona": z, "armados": crudo["armado_zona"][z],
                         "reparto": _porcentaje(crudo["armado_zona"][z], armado_total)}
                        for z in zonas_armado],
        "armado_total": armado_total,
        "distribucion": {"zonas": zonas_calidad, "filas": distribucion},
        "direccion": {"direcciones": list(DIRECCIONES), "filas": direcciones},
        "recepcion": {
            "total": dict(rec, recepciones=recibidas),
            "por_tipo": sorted(
                ({"ruta": ruta, "tipo": v.get("tipo", ""),
                  "recepciones": sin_tipo(v),
                  "cal3": v.get("cal3", 0), "cal2": v.get("cal2", 0),
                  "cal1": v.get("cal1", 0), "cal0": v.get("cal0", 0),
                  "pase": v.get("pase", 0),
                  "positiva": _porcentaje(v.get("cal3", 0) + v.get("cal2", 0), sin_tipo(v))}
                 for ruta, v in crudo["recepcion_tipo_saque"].items()),
                key=lambda f: (f["tipo"], f["ruta"])),
        },
        "zona_armador": [{
            "zona": z,
            "hechos": (crudo["zona_armador"].get(z) or {}).get("hechos", 0),
            "recibidos": (crudo["zona_armador"].get(z) or {}).get("recibidos", 0),
        } for z in sorted(crudo["zona_armador"], key=str)],
        "por_partido": crudo["partidos"],
    }


def listado(carpeta=None) -> dict:


    """Los equipos con sus jugadores, para armar los selectores.

    Los equipos van ordenados por cantidad de partidos: el propio queda
    primero sin necesidad de configurarlo, y "Palestino B" aparece solo el dia
    que se cargue un partido suyo."""
    agregado = agregar(carpeta)
    equipos = []
    for nombre, jugadores in agregado["equipos"].items():
        filas = []
        marcados = agregado.get("armadores", {}).get(nombre, set())
        posiciones = alm.posiciones_del_equipo(nombre)
        for dorsal, j in jugadores.items():
            armados = sum(j["armado"].values())
            filas.append({
                "dorsal": dorsal,
                "armador": dorsal in marcados,
                "posicion": posiciones.get(str(dorsal), ""),
                "partidos": len(j["partidos"]),
                "recepciones": sum(j["recepcion"].values()),
                "ataques": j["ataque"]["totales"],
                "armados": armados,
                "bloqueos": j["bloqueos"],
            })
        filas.sort(key=lambda f: (-(f["ataques"] + f["recepciones"] + f["armados"]),
                                  int(f["dorsal"]) if f["dorsal"].isdigit() else 999))
        equipos.append({
            "nombre": nombre,
            "partidos": len(agregado["partidos"].get(nombre, [])),
            "jugadores": filas,
        })
    equipos.sort(key=lambda e: (-e["partidos"], e["nombre"]))
    return {"equipos": equipos, "descartados": agregado["descartados"],
            "otros_equipos": agregado["otros_equipos"]}
