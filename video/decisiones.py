"""De lo que hago en la pantalla a revision.json.

Las pantallas no escriben decisiones: mandan operaciones ("marcar aca",
"aceptar esta", "zona 4") y la decision se arma aca. Asi la forma de
revision.json esta escrita en un solo lugar, y lo que llega del navegador se
valida antes de tocar el archivo.

    marcar      {t, campos?}          una armada que vi yo, sin propuesta atras
    aceptar     {clave}
    descartar   {clave}               una marca mia descartada se borra
    cambiar     {clave, campos}       corregir; tocar una pendiente la acepta
    set         {desde, set, lado}    desde aca es el set N y mi equipo esta de ese lado
    quitar_set  {desde}

"deshacer" no esta aca: necesita la historia, y la historia la tiene el
servidor (ver servidor_video).

Una operacion recibe la revision y las propuestas, y devuelve una revision
NUEVA (la que recibe no se toca), la clave de la armada que quedo afectada
(la que la pantalla deja elegida) y las armadas ya fusionadas.
"""
from __future__ import annotations

import copy
import re

from . import fusion
from .proyecto import LADOS, TIPOS, es_numero

MAXIMO_DE_ETIQUETAS = 20
LARGO_DE_ETIQUETA = 40
LARGO_DE_NOTA = 500
SETS_POSIBLES = range(1, 6)
# Volver a marcar un set casi en el mismo lugar es corregir el que estaba.
VENTANA_DE_SET = 1.0
ID_DE_DECISION = re.compile(r"^d(\d+)$")


class OperacionInvalida(ValueError):
    """La operacion no se puede hacer. El mensaje es para la persona."""


def aplicar(revision: dict, propuestas: dict | None, op: dict,
            duracion: float | None = None) -> tuple[dict, str | None, list[dict]]:
    if not isinstance(op, dict):
        raise OperacionInvalida("La operacion tiene que ser un objeto.")
    hacer = OPERACIONES.get(op.get("tipo"))
    if hacer is None:
        raise OperacionInvalida(f"Operacion desconocida: {op.get('tipo')!r}.")

    armadas = fusion.fusionar(propuestas, revision, duracion)
    nueva = copy.deepcopy(revision)
    nueva.setdefault("sets", [])
    nueva.setdefault("decisiones", [])
    clave = hacer(nueva, armadas, op, duracion)

    # Se valida sobre el resultado ya fusionado: es la unica forma de saber
    # como queda la armada cuando se mezcla lo corregido con lo propuesto.
    nuevas = fusion.fusionar(propuestas, nueva, duracion)
    afectada = next((a for a in nuevas if a["clave"] == clave), None)
    if afectada is not None:
        _revisar_coherencia(afectada)
    return nueva, clave, nuevas


# ----------------------------------------------------------------------
# Las operaciones. Cada una modifica la revision nueva y devuelve la clave de
# la armada afectada (o None si no queda ninguna elegida).

def _marcar(revision, armadas, op, duracion):
    t = _tiempo(op.get("t"), "El instante", duracion)
    cambios, mios = _campos(op.get("campos") or {}, duracion)
    decision = _decision_nueva(revision, t_armado=t, lado=None, origen="manual",
                               propuesta=None)
    decision["cambios"] = cambios
    decision.update(mios)
    revision["decisiones"].append(decision)
    return "d:" + decision["id"]


def _aceptar(revision, armadas, op, duracion):
    decision = _decision_de(revision, _buscar(armadas, op.get("clave")))
    decision["estado"] = "aceptada"
    return "d:" + decision["id"]


def _descartar(revision, armadas, op, duracion):
    armada = _buscar(armadas, op.get("clave"))
    if armada["origen"] == "manual":
        # una marca mia no tiene una propuesta que recordar como descartada
        revision["decisiones"] = [d for d in revision["decisiones"]
                                  if d["id"] != armada["decision"]]
        return None
    decision = _decision_de(revision, armada)
    decision["estado"] = "descartada"
    return "d:" + decision["id"]


def _cambiar(revision, armadas, op, duracion):
    armada = _buscar(armadas, op.get("clave"))
    cambios, mios = _campos(op.get("campos") or {}, duracion)
    if not cambios and not mios:
        raise OperacionInvalida("No hay nada para cambiar.")
    decision = _decision_de(revision, armada)
    propios = decision.setdefault("cambios", {})
    nuevo_t = cambios.get("t_armado")
    if nuevo_t is not None and not armada["t_inicio"] <= nuevo_t <= armada["t_fin"]:
        # El recorte estaba armado alrededor del tiempo viejo. Con el armado
        # afuera vuelve al de por defecto, en vez de quedar un clip que no
        # muestra la armada.
        propios.pop("t_inicio", None)
        propios.pop("t_fin", None)
    propios.update(cambios)
    decision.update(mios)
    return "d:" + decision["id"]


def _poner_set(revision, armadas, op, duracion):
    desde = _tiempo(op.get("desde"), "El comienzo del set", duracion)
    numero = op.get("set")
    if not _es_entero(numero) or numero not in SETS_POSIBLES:
        raise OperacionInvalida("El set va del 1 al 5.")
    lado = op.get("lado")
    if lado not in LADOS:
        raise OperacionInvalida("Mi equipo esta 'cerca' o 'lejos' de la camara.")
    sets = [s for s in revision["sets"] if abs(s["desde"] - desde) >= VENTANA_DE_SET]
    sets.append({"desde": desde, "set": numero, "lado": lado})
    revision["sets"] = sorted(sets, key=lambda s: s["desde"])
    return None


def _quitar_set(revision, armadas, op, duracion):
    desde = op.get("desde")
    if not es_numero(desde):
        raise OperacionInvalida("Falta desde cuando es el set a quitar.")
    quedan = [s for s in revision["sets"] if abs(s["desde"] - desde) > 1e-3]
    if len(quedan) == len(revision["sets"]):
        raise OperacionInvalida("No hay un set que empiece ahi.")
    revision["sets"] = quedan
    return None


OPERACIONES = {
    "marcar": _marcar,
    "aceptar": _aceptar,
    "descartar": _descartar,
    "cambiar": _cambiar,
    "set": _poner_set,
    "quitar_set": _quitar_set,
}


# ----------------------------------------------------------------------
def _buscar(armadas: list[dict], clave) -> dict:
    for armada in armadas:
        if armada["clave"] == clave:
            return armada
    # Una pendiente deja de serlo al decidirla y cambia de clave ("p:..." pasa
    # a "d:..."). Si la pantalla manda dos toques seguidos, el segundo puede
    # salir con la clave vieja: se la reconoce por la propuesta.
    if isinstance(clave, str) and clave.startswith("p:"):
        for armada in armadas:
            if armada["propuesta"] is not None and str(armada["propuesta"]) == clave[2:]:
                return armada
    raise OperacionInvalida("No encuentro esa armada: recarga la pagina.")


def _decision_nueva(revision, t_armado, lado, origen, propuesta) -> dict:
    numeros = [int(m.group(1)) for d in revision["decisiones"]
               if (m := ID_DE_DECISION.match(d["id"]))]
    return {"id": f"d{max(numeros, default=0) + 1}", "t_armado": t_armado, "lado": lado,
            "estado": "aceptada", "origen": origen, "propuesta": propuesta,
            "cambios": {}, "armador": None, "etiquetas": [], "nota": ""}


def _decision_de(revision: dict, armada: dict) -> dict:
    """La decision de esa armada. Una pendiente no tiene: se la crea copiando
    lo que propuso la maquina, que es lo que la persona tuvo a la vista.
    Tocar una pendiente para corregirla tambien es aceptarla."""
    if armada["decision"] is not None:
        for decision in revision["decisiones"]:
            if decision["id"] == armada["decision"]:
                return decision
        raise OperacionInvalida("Esa armada cambio mientras tanto: recarga la pagina.")
    vista = {campo: armada[campo] for campo in fusion.CAMPOS_DE_LA_PROPUESTA}
    decision = _decision_nueva(revision, t_armado=armada["t_armado"], lado=armada["lado"],
                               origen="auto", propuesta=vista)
    revision["decisiones"].append(decision)
    return decision


def _revisar_coherencia(armada: dict) -> None:
    t = armada["t_armado"]
    if not armada["t_inicio"] <= t <= armada["t_fin"]:
        raise OperacionInvalida(
            f"El recorte ({_reloj(armada['t_inicio'])} a {_reloj(armada['t_fin'])}) "
            f"tiene que incluir el armado ({_reloj(t)}).")
    if armada["t_ataque"] is not None and armada["t_ataque"] <= t:
        raise OperacionInvalida(
            f"El ataque ({_reloj(armada['t_ataque'])}) tiene que ser despues "
            f"del armado ({_reloj(t)}).")
    if armada["t_toque_previo"] is not None and armada["t_toque_previo"] >= t:
        raise OperacionInvalida(
            f"El toque previo ({_reloj(armada['t_toque_previo'])}) tiene que ser "
            f"antes del armado ({_reloj(t)}).")


# ----------------------------------------------------------------------
def _es_entero(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _reloj(t: float) -> str:
    minutos, segundos = divmod(round(t, 2), 60)
    return f"{int(minutos)}:{segundos:05.2f}"


def _tiempo(valor, que: str, duracion, nulo=False):
    if valor is None and nulo:
        return None
    if not es_numero(valor) or valor < 0:
        raise OperacionInvalida(f"{que} tiene que ser un tiempo en segundos.")
    if duracion and valor > duracion + 0.5:
        raise OperacionInvalida(f"{que} ({_reloj(valor)}) cae despues del final del video.")
    return round(float(valor), 3)


def _campos(campos, duracion) -> tuple[dict, dict]:
    """Separa y valida lo que llega: (cambios sobre lo propuesto, datos mios).
    Los cambios tapan a la propuesta; armador, etiquetas y nota no existen en
    una propuesta y van sueltos en la decision."""
    if not isinstance(campos, dict):
        raise OperacionInvalida("Los campos tienen que ser un objeto.")
    cambios, mios = {}, {}
    for campo, valor in campos.items():
        if campo == "t_armado":
            cambios[campo] = _tiempo(valor, "El armado", duracion)
        elif campo == "t_inicio":
            cambios[campo] = _tiempo(valor, "El inicio del recorte", duracion)
        elif campo == "t_fin":
            cambios[campo] = _tiempo(valor, "El fin del recorte", duracion)
        elif campo == "t_ataque":
            cambios[campo] = _tiempo(valor, "El ataque", duracion, nulo=True)
        elif campo == "t_toque_previo":
            cambios[campo] = _tiempo(valor, "El toque previo", duracion, nulo=True)
        elif campo == "zona_destino":
            if valor is not None and not (_es_entero(valor) and 1 <= valor <= 6):
                raise OperacionInvalida("La zona va del 1 al 6.")
            cambios[campo] = valor
        elif campo == "lado":
            if valor is not None and valor not in LADOS:
                raise OperacionInvalida("El lado es 'cerca' o 'lejos' de la camara.")
            cambios[campo] = valor
        elif campo == "tipo":
            if valor not in TIPOS:
                raise OperacionInvalida("El tipo es 'armada' o 'segunda'.")
            cambios[campo] = valor
        elif campo == "armador":
            if valor is not None and not (_es_entero(valor) and 0 <= valor <= 999):
                raise OperacionInvalida("El armador es un numero de camiseta.")
            mios[campo] = valor
        elif campo == "etiquetas":
            mios[campo] = _etiquetas(valor)
        elif campo == "nota":
            if not isinstance(valor, str):
                raise OperacionInvalida("La nota es un texto.")
            if len(valor.strip()) > LARGO_DE_NOTA:
                raise OperacionInvalida(f"La nota es muy larga (hasta {LARGO_DE_NOTA} letras).")
            mios[campo] = valor.strip()
        else:
            raise OperacionInvalida(f"No se puede cambiar {campo!r}.")
    return cambios, mios


def _etiquetas(valor) -> list[str]:
    if not isinstance(valor, list) or not all(isinstance(e, str) for e in valor):
        raise OperacionInvalida("Las etiquetas son una lista de textos.")
    limpias, vistas = [], set()
    for etiqueta in valor:
        etiqueta = " ".join(etiqueta.split())
        if not etiqueta or etiqueta.lower() in vistas:
            continue
        if len(etiqueta) > LARGO_DE_ETIQUETA:
            raise OperacionInvalida(
                f"La etiqueta {etiqueta[:20]!r}... es muy larga (hasta {LARGO_DE_ETIQUETA}).")
        vistas.add(etiqueta.lower())
        limpias.append(etiqueta)
    if len(limpias) > MAXIMO_DE_ETIQUETAS:
        raise OperacionInvalida(f"Hasta {MAXIMO_DE_ETIQUETAS} etiquetas por armada.")
    return limpias
