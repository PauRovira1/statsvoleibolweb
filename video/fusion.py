"""Lo que propone la maquina + lo que decidi yo = las armadas que se muestran.

Es lo unico que leen la revision, la galeria y (despues) la exportacion. No
escribe nada: recibe las propuestas y la revision y devuelve la lista.

Como se reconoce que una decision es sobre una propuesta: por el TIEMPO y no
por el id, porque los ids cambian cada vez que se rehacen las propuestas. Es
la misma armada si el toque del armador difiere en menos de VENTANA segundos
y no estan en lados distintos de la red. Cada decision tiene dos tiempos, el
que tenia cuando se decidio y el corregido si se lo movio, y vale el mas
cercano: asi la decision encuentra a su propuesta tanto si el detector nuevo
repite el error que se corrigio como si ahora acierta. Las parejas se arman
de a una (una propuesta para una decision), empezando por las mas cercanas.

Cuando se juntan, manda la persona: lo que acepte o corregi queda como
estaba, y la propuesta solo completa lo que yo no dije (la trayectoria, una
zona que no marque). Una decision cuya propuesta desaparecio no se pierde:
sigue con los datos que tenia cuando la decidi.
"""
from __future__ import annotations

VENTANA = 0.5

# Lo que se copia de la propuesta a la decision cuando se la decide: es lo que
# la persona vio y acepto. La trayectoria no, porque pesa y no es una opinion.
CAMPOS_DE_LA_PROPUESTA = ("t_armado", "t_ataque", "t_toque_previo", "lado", "tipo",
                          "zona_destino")

# El recorte por defecto: desde un poco antes del toque previo (para ver de
# que recepcion salio) hasta un rato despues del ataque (para ver como
# termino). Sin esos toques se los estima a la distancia tipica.
ANTES_DEL_TOQUE_PREVIO = 1.0
DESPUES_DEL_ATAQUE = 2.0
TOQUE_PREVIO_TIPICO = 1.5    # segundos antes del armado
ATAQUE_TIPICO = 1.0          # segundos despues del armado

# Rapida / media / alta segun el vuelo del armado al ataque. Una primera
# tiempo vuela unas tres decimas; una pelota alta a punta, mas de un segundo.
# Son los cortes de la galeria: si no convencen, se cambian aca.
CORTES_DE_TEMPO = (0.5, 1.0)


def tramo_en(sets: list[dict], t: float) -> dict | None:
    """El set vigente en el instante t (y de que lado esta mi equipo), o None
    si es antes del primero que se marco."""
    vigente = None
    for tramo in sorted(sets or [], key=lambda s: s["desde"]):
        if tramo["desde"] > t + 1e-9:
            break
        vigente = tramo
    return vigente


def tempo_de(vuelo: float | None) -> str | None:
    if vuelo is None:
        return None
    rapida, alta = CORTES_DE_TEMPO
    if vuelo < rapida:
        return "rapida"
    return "media" if vuelo < alta else "alta"


def _t_efectivo(decision: dict) -> float:
    cambiado = (decision.get("cambios") or {}).get("t_armado")
    return decision["t_armado"] if cambiado is None else cambiado


def _tiempos_de(decision: dict) -> list[float]:
    tiempos = [decision["t_armado"]]
    cambiado = (decision.get("cambios") or {}).get("t_armado")
    if cambiado is not None:
        tiempos.append(cambiado)
    return tiempos


def _lado_de(decision: dict, sets: list[dict]) -> str | None:
    """Donde fue la armada de esta decision. Una marca a mano no lo dice: es
    de mi equipo, asi que es el lado de mi equipo en ese momento."""
    lado = (decision.get("cambios") or {}).get("lado") or decision.get("lado")
    if lado is None:
        tramo = tramo_en(sets, _t_efectivo(decision))
        lado = tramo["lado"] if tramo else None
    return lado


def emparejar(propuestas: list[dict], decisiones: list[dict],
              sets: list[dict]) -> dict[int, int]:
    """{indice de la decision: indice de su propuesta}."""
    candidatos = []
    for j, decision in enumerate(decisiones):
        tiempos = _tiempos_de(decision)
        lado = _lado_de(decision, sets)
        for i, propuesta in enumerate(propuestas):
            otro_lado = propuesta.get("lado")
            # un lado desconocido no descarta: no se sabe, no es "otro"
            if lado and otro_lado and lado != otro_lado:
                continue
            distancia = min(abs(propuesta["t_armado"] - t) for t in tiempos)
            if distancia < VENTANA:
                candidatos.append((distancia, j, i))
    candidatos.sort()
    pares, tomadas = {}, set()
    for _, j, i in candidatos:
        if j in pares or i in tomadas:
            continue
        pares[j] = i
        tomadas.add(i)
    return pares


def fusionar(propuestas: dict | None, revision: dict,
             duracion: float | None = None) -> list[dict]:
    """Todas las armadas, ordenadas por tiempo: las decididas (aceptadas o
    descartadas) y las propuestas que nadie decidio todavia (pendientes)."""
    lista = list((propuestas or {}).get("armadas") or [])
    decisiones = list(revision.get("decisiones") or [])
    sets = list(revision.get("sets") or [])

    pares = emparejar(lista, decisiones, sets)
    usadas = set(pares.values())
    armadas = [_armar(lista[pares[j]] if j in pares else None, decision, sets, duracion)
               for j, decision in enumerate(decisiones)]
    armadas += [_armar(propuesta, None, sets, duracion)
                for i, propuesta in enumerate(lista) if i not in usadas]
    armadas.sort(key=lambda a: (a["t_armado"], a["clave"]))
    return armadas


def _armar(propuesta: dict | None, decision: dict | None, sets: list[dict],
           duracion: float | None) -> dict:
    # De abajo hacia arriba: la propuesta, lo que acepte de ella (o mi marca)
    # y lo que corregi. Lo de arriba tapa lo de abajo.
    datos = {}
    if propuesta is not None:
        datos.update({campo: propuesta[campo] for campo in CAMPOS_DE_LA_PROPUESTA
                      if campo in propuesta})
    cambios = {}
    if decision is not None:
        if decision["origen"] == "manual":
            # la marca es mia: el tiempo en que la puse tambien
            datos["t_armado"] = decision["t_armado"]
        else:
            datos.update(decision.get("propuesta") or {})
            datos.setdefault("t_armado", decision["t_armado"])
        if decision.get("lado"):
            datos["lado"] = decision["lado"]
        cambios = decision.get("cambios") or {}
        datos.update(cambios)

    t_armado = datos["t_armado"]
    tramo = tramo_en(sets, t_armado)
    t_ataque = datos.get("t_ataque")
    t_previo = datos.get("t_toque_previo")
    # Una marca a mano se pone con el video andando y llega tarde: puede caer
    # despues del ataque que vio el detector. Ese ataque no es de esta marca
    # (vuelo negativo); si lo hubiera puesto la persona, decisiones.py no lo
    # habria dejado pasar.
    if t_ataque is not None and t_ataque <= t_armado and "t_ataque" not in cambios:
        t_ataque = None
    if t_previo is not None and t_previo >= t_armado and "t_toque_previo" not in cambios:
        t_previo = None
    vuelo = round(t_ataque - t_armado, 3) if t_ataque is not None else None

    t_inicio = datos.get("t_inicio")
    if t_inicio is None:
        previo = t_previo if t_previo is not None else t_armado - TOQUE_PREVIO_TIPICO
        t_inicio = round(max(0.0, previo - ANTES_DEL_TOQUE_PREVIO), 3)
    t_fin = datos.get("t_fin")
    if t_fin is None:
        ataque = t_ataque if t_ataque is not None else t_armado + ATAQUE_TIPICO
        t_fin = ataque + DESPUES_DEL_ATAQUE
        if duracion:
            t_fin = min(t_fin, duracion)
        t_fin = round(t_fin, 3)

    if decision is not None:
        clave, estado, origen = "d:" + decision["id"], decision["estado"], decision["origen"]
    else:
        clave, estado, origen = "p:" + str(propuesta["id"]), "pendiente", "auto"

    return {
        "clave": clave,
        "estado": estado,
        "origen": origen,
        "decision": decision["id"] if decision is not None else None,
        "propuesta": propuesta.get("id") if propuesta is not None else None,
        # decidida sobre una propuesta que ya no esta: quedo con lo que tenia
        "huerfana": decision is not None and origen == "auto" and propuesta is None,
        "t_armado": t_armado,
        "t_ataque": t_ataque,
        "t_toque_previo": t_previo,
        "tiempo_vuelo": vuelo,
        "tempo": tempo_de(vuelo),
        "t_inicio": t_inicio,
        "t_fin": t_fin,
        "lado": datos.get("lado") or (tramo["lado"] if tramo else None),
        "tipo": datos.get("tipo") or "armada",
        "zona_destino": datos.get("zona_destino"),
        "set": tramo["set"] if tramo else None,
        "lado_mi_equipo": tramo["lado"] if tramo else None,
        "confianza": propuesta.get("confianza") if propuesta is not None else None,
        "motivos": list(propuesta.get("motivos") or []) if propuesta is not None else [],
        "trayectoria": propuesta.get("trayectoria") if propuesta is not None else None,
        "medidas": propuesta.get("medidas") if propuesta is not None else None,
        "armador": decision.get("armador") if decision is not None else None,
        "etiquetas": list(decision.get("etiquetas") or []) if decision is not None else [],
        "nota": (decision.get("nota") or "") if decision is not None else "",
        # que campos toco la persona, para marcarlos en la pantalla
        "corregido": sorted(cambios),
    }
