"""La carpeta de trabajo de cada video, lo que hay adentro y su forma.

    Videos/<nombre>/
        fuente.json       de donde salio: ruta del original, duracion, fps...
        proxy.mp4         la copia liviana que reproducen las pantallas
        propuestas.json   lo que propone la maquina        (se regenera entero)
        revision.json     lo que decidi yo                 (nunca se pisa)

La regla que ordena todo: lo que decide una persona y lo que calcula la
maquina viven en archivos distintos. Rehacer las propuestas (otro detector,
otros umbrales) escribe propuestas.json y nada mas. revision.json lo escriben
solo las pantallas, a traves de decisiones.py, y antes de cada guardado queda
una copia de lo anterior en revision.anterior.json.

Los sets (desde cuando y de que lado de la red esta mi equipo) van en
revision.json y no en la calibracion: los marca la persona, igual que las
armadas, y se deshacen con el mismo Z.

Este modulo no sabe de video ni de voley: lee y escribe JSON, valida nombres
y cuida que dos pestanas no se pisen (ver "edicion" en guardar_revision).
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import time
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETA_VIDEOS = RAIZ / "Videos"

# Version del formato de los .json. Un archivo con una version mayor lo
# escribio un codigo mas nuevo: no se toca, porque reescribirlo con este
# codigo perderia lo que este codigo no conoce.
VERSION = 1

FUENTE = "fuente.json"
PROXY = "proxy.mp4"
PROPUESTAS = "propuestas.json"
REVISION = "revision.json"
REVISION_ANTERIOR = "revision.anterior.json"

EXTENSIONES_DE_VIDEO = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".webm"}

# Los valores que puede tener cada cosa. Estan aca porque son la forma de los
# archivos; fusion.py y decisiones.py los toman de aca.
LADOS = ("cerca", "lejos")              # respecto de la camara
ESTADOS = ("aceptada", "descartada")    # "pendiente" no se guarda: es no haber decidido
ORIGENES = ("auto", "manual")
TIPOS = ("armada", "segunda")

# El nombre de la carpeta va en las URL y en rutas de Windows: solo
# minusculas, numeros y guiones. El titulo con acentos queda en fuente.json.
NOMBRE_VALIDO = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")

# Para reconocer un video sin leerlo entero (un partido pesa gigas).
BLOQUE_DE_HUELLA = 4 * 1024 * 1024


class ErrorDeProyecto(Exception):
    """Algo que la persona puede entender y arreglar: el mensaje se muestra tal cual."""


class NoExiste(ErrorDeProyecto):
    """No hay un video con ese nombre."""


class Desactualizado(ErrorDeProyecto):
    """Se quiso guardar sobre una revision que ya cambio (otra pestana guardo antes)."""


# ----------------------------------------------------------------------
# Nombres y archivos

def nombre_para(texto: str) -> str:
    """'Palestino vs Español (set 1)' -> 'palestino-vs-espanol-set-1'."""
    sin_acentos = (unicodedata.normalize("NFKD", texto)
                   .encode("ascii", "ignore").decode("ascii"))
    nombre = re.sub(r"[^a-z0-9]+", "-", sin_acentos.lower()).strip("-")
    return nombre[:80].rstrip("-") or "video"


def es_numero(valor) -> bool:
    return (isinstance(valor, (int, float)) and not isinstance(valor, bool)
            and math.isfinite(valor))


def leer_json(ruta: Path, por_defecto=None):
    try:
        texto = Path(ruta).read_text(encoding="utf-8")
    except FileNotFoundError:
        return copy.deepcopy(por_defecto)
    try:
        return json.loads(texto)
    except json.JSONDecodeError as error:
        raise ErrorDeProyecto(
            f"{Path(ruta).name} esta roto ({error}). Arreglalo a mano o "
            f"recuperalo de {REVISION_ANTERIOR} si es la revision.") from None


def escribir_json(ruta: Path, datos) -> None:
    """Escribe entero o no escribe: primero a un .tmp y despues se reemplaza.
    Un corte a mitad de camino deja el archivo viejo, no uno a medias."""
    ruta = Path(ruta)
    temporal = ruta.with_name(ruta.name + ".tmp")
    temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    for intento in range(5):
        try:
            os.replace(temporal, ruta)
            return
        except PermissionError:
            # En Windows el antivirus o el indexador pueden tener el archivo
            # abierto un instante, y reemplazarlo justo ahi falla.
            if intento == 4:
                raise
            time.sleep(0.1)


def hash_parcial(ruta: Path) -> str:
    """El tamano, los primeros y los ultimos 4 MB. Alcanza para saber si es el
    mismo video aunque se haya movido o renombrado."""
    ruta = Path(ruta)
    tamano = ruta.stat().st_size
    huella = hashlib.sha256(str(tamano).encode("ascii"))
    with open(ruta, "rb") as archivo:
        huella.update(archivo.read(BLOQUE_DE_HUELLA))
        if tamano > BLOQUE_DE_HUELLA:
            archivo.seek(max(BLOQUE_DE_HUELLA, tamano - BLOQUE_DE_HUELLA))
            huella.update(archivo.read(BLOQUE_DE_HUELLA))
    return huella.hexdigest()[:32]


def _revisar_version(datos, nombre_archivo: str) -> None:
    if not isinstance(datos, dict):
        raise ErrorDeProyecto(f"{nombre_archivo} no tiene la forma esperada.")
    version = datos.get("version", VERSION)
    if not isinstance(version, int) or version > VERSION:
        raise ErrorDeProyecto(
            f"{nombre_archivo} lo escribio una version mas nueva del programa "
            f"(formato {version}). Actualiza el codigo antes de abrirlo.")


def revision_vacia() -> dict:
    return {"version": VERSION, "edicion": 0, "sets": [], "decisiones": []}


def revisar_revision(datos: dict) -> None:
    """La revision puede venir editada a mano: si algo no tiene la forma
    esperada se avisa ahora, con el dato a la vista, y no mas adelante con
    un error que no se entiende."""
    _revisar_version(datos, REVISION)
    sets, decisiones = datos.get("sets", []), datos.get("decisiones", [])
    if not isinstance(sets, list) or not isinstance(decisiones, list):
        raise ErrorDeProyecto(f"{REVISION}: 'sets' y 'decisiones' tienen que ser listas.")
    for tramo in sets:
        if not (isinstance(tramo, dict) and es_numero(tramo.get("desde"))
                and isinstance(tramo.get("set"), int) and tramo.get("lado") in LADOS):
            raise ErrorDeProyecto(f"{REVISION}: set mal formado: {tramo!r:.120}")
    ids = set()
    for decision in decisiones:
        bien = (isinstance(decision, dict) and isinstance(decision.get("id"), str)
                and es_numero(decision.get("t_armado"))
                and decision.get("estado") in ESTADOS
                and decision.get("origen") in ORIGENES
                and isinstance(decision.get("cambios", {}), dict)
                and isinstance(decision.get("etiquetas", []), list))
        if not bien:
            raise ErrorDeProyecto(f"{REVISION}: decision mal formada: {decision!r:.160}")
        if decision["id"] in ids:
            raise ErrorDeProyecto(f"{REVISION}: hay dos decisiones con el id {decision['id']}.")
        ids.add(decision["id"])


# ----------------------------------------------------------------------
class Proyecto:
    """Un video dado de alta: su carpeta y lo que hay adentro."""

    def __init__(self, carpeta: Path):
        self.carpeta = Path(carpeta)
        self.nombre = self.carpeta.name

    def __repr__(self):
        return f"Proyecto({self.nombre!r})"

    @property
    def ruta_proxy(self) -> Path:
        return self.carpeta / PROXY

    def hay_proxy(self) -> bool:
        return self.ruta_proxy.is_file()

    def fuente(self) -> dict:
        datos = leer_json(self.carpeta / FUENTE)
        if datos is None:
            raise NoExiste(f"No hay un video llamado {self.nombre}.")
        _revisar_version(datos, FUENTE)
        return datos

    def guardar_fuente(self, datos: dict) -> None:
        escribir_json(self.carpeta / FUENTE, {**datos, "version": VERSION})

    def propuestas(self) -> dict:
        datos = leer_json(self.carpeta / PROPUESTAS, {"version": VERSION, "armadas": []})
        _revisar_version(datos, PROPUESTAS)
        if not isinstance(datos.get("armadas", []), list):
            raise ErrorDeProyecto(f"{PROPUESTAS}: 'armadas' tiene que ser una lista.")
        return datos

    def revision(self) -> dict:
        datos = leer_json(self.carpeta / REVISION, revision_vacia())
        revisar_revision(datos)
        return datos

    def guardar_revision(self, nueva: dict, edicion_vista: int) -> dict:
        """Guarda solo si la revision en disco es la que la pantalla tenia a
        la vista. Si otra pestana guardo en el medio, guardar esta pisaria lo
        que hizo la otra: se rechaza y la pantalla recarga."""
        actual = self.revision()
        if actual.get("edicion", 0) != edicion_vista:
            raise Desactualizado(
                "La revision cambio desde otra pestana: recargue la ultima version.")
        guardada = {**nueva, "version": VERSION, "edicion": actual.get("edicion", 0) + 1}
        revisar_revision(guardada)
        ruta = self.carpeta / REVISION
        if ruta.exists():
            escribir_json(self.carpeta / REVISION_ANTERIOR, actual)
        escribir_json(ruta, guardada)
        return guardada


# ----------------------------------------------------------------------
def abrir(nombre: str, base: Path = CARPETA_VIDEOS) -> Proyecto:
    """El proyecto de ese nombre. El nombre llega de una URL: se valida antes
    de armar ninguna ruta con el."""
    if not isinstance(nombre, str) or not NOMBRE_VALIDO.match(nombre):
        raise NoExiste(f"No hay un video llamado {nombre!r}.")
    carpeta = Path(base) / nombre
    if not (carpeta / FUENTE).is_file():
        raise NoExiste(f"No hay un video llamado {nombre}.")
    return Proyecto(carpeta)


def listar(base: Path = CARPETA_VIDEOS) -> list[Proyecto]:
    base = Path(base)
    if not base.is_dir():
        return []
    return [Proyecto(carpeta) for carpeta in sorted(base.iterdir())
            if carpeta.is_dir() and NOMBRE_VALIDO.match(carpeta.name)
            and (carpeta / FUENTE).is_file()]


def crear(original: Path, metadatos: dict, nombre: str | None = None,
          base: Path = CARPETA_VIDEOS) -> Proyecto:
    """Da de alta un video. Si ya estaba (mismo nombre, mismo archivo) lo
    devuelve tal cual, para retomar un proxy que quedo a medias."""
    original = Path(original).resolve()
    nombre = nombre or nombre_para(original.stem)
    if not NOMBRE_VALIDO.match(nombre):
        raise ErrorDeProyecto(
            f"Nombre invalido: {nombre!r}. Usa minusculas, numeros y guiones.")
    carpeta = Path(base) / nombre
    huella = hash_parcial(original)

    existente = leer_json(carpeta / FUENTE)
    if existente is not None:
        if existente.get("hash_parcial") != huella:
            raise ErrorDeProyecto(
                f"Ya hay un video llamado {nombre} y es otro archivo. "
                f"Elegi otro nombre con --nombre.")
        proyecto = Proyecto(carpeta)
        if existente.get("original") != str(original):
            # el mismo video, movido de lugar: se anota donde esta ahora
            proyecto.guardar_fuente({**existente, "original": str(original)})
        return proyecto

    carpeta.mkdir(parents=True, exist_ok=True)
    proyecto = Proyecto(carpeta)
    proyecto.guardar_fuente({
        "titulo": original.stem,
        "original": str(original),
        "tamano": original.stat().st_size,
        "hash_parcial": huella,
        "alta": datetime.now().isoformat(timespec="seconds"),
        **metadatos,
    })
    return proyecto


def videos_sin_alta(base: Path = CARPETA_VIDEOS) -> list[Path]:
    """Los videos sueltos en la carpeta (no en una subcarpeta) que ningun
    proyecto tiene como original: los que se copiaron y falta dar de alta."""
    base = Path(base)
    if not base.is_dir():
        return []
    conocidos = set()
    for proyecto in listar(base):
        try:
            conocidos.add(os.path.normcase(str(Path(proyecto.fuente()["original"]))))
        except (ErrorDeProyecto, KeyError):
            continue
    return [ruta for ruta in sorted(base.iterdir())
            if ruta.is_file() and ruta.suffix.lower() in EXTENSIONES_DE_VIDEO
            and os.path.normcase(str(ruta.resolve())) not in conocidos]
