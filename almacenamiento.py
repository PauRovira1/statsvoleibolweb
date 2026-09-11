"""
Donde viven los archivos, que no es lo mismo en la notebook que en Vercel.

Hasta ahora los volcados y los informes se escribian al lado del .py y con eso
alcanzaba: el programa corria en una maquina propia. Alojado en Vercel eso no
funciona, por dos motivos que no se arreglan solos:

1) La carpeta del proyecto es de SOLO LECTURA. Lo unico que se puede escribir
   es /tmp, asi que un `open(..., "w")` sobre Datos/ revienta con OSError 30.

2) /tmp no es persistente ni compartido. Cada invocacion puede caer en una
   instancia distinta, y la que la atendio hace un rato se apaga. Lo que se
   escribe ahi sobrevive minutos y solo para el que lo escribio.

Por eso este modulo separa tres lugares distintos, que antes eran uno:

    escritura   la carpeta donde SE PUEDE escribir. En casa es la del
                proyecto; en Vercel es /tmp/voley, que ademas hace de cache
                de lo que esta en el blob.

    semilla     la carpeta del proyecto cuando no se puede escribir en ella:
                los partidos e informes que viajan en el deploy. Solo lectura,
                pero se siguen viendo en la pestana Partidos.

    blob        Vercel Blob, el unico que persiste de verdad. Cada archivo que
                se guarda se sube ahi, y antes de listar o de leer se baja a la
                carpeta de escritura lo que falte.

El resto del proyecto no se entera: sigue trabajando con Paths. La diferencia
es que ahora pregunta por las carpetas en vez de calcularlas con __file__, y
que despues de escribir un archivo llama a publicar().

Sin BLOB_READ_WRITE_TOKEN todo esto se apaga solo y queda el comportamiento de
siempre (leer y escribir en la carpeta del proyecto), que es justo lo que se
quiere cuando se corre `python servidor_voley.py` en casa.
"""
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CARPETA_PROYECTO = Path(__file__).resolve().parent

# Nombres logicos de las dos carpetas. Son tambien el prefijo con el que cada
# archivo se guarda en el blob, asi que el blob queda igual de legible que la
# carpeta: Datos/partido_....txt, Informes/Informe_....xlsx
DATOS = "Datos"
INFORMES = "Informes"
CARPETAS = (DATOS, INFORMES)

# Vercel define VERCEL=1 en todas sus ejecuciones. AWS_LAMBDA_FUNCTION_NAME
# cubre el caso de correr el mismo codigo en otro serverless.
EN_SERVERLESS = bool(os.environ.get("VERCEL") or
                     os.environ.get("AWS_LAMBDA_FUNCTION_NAME"))

MENSAJE_SIN_BLOB = (
    "No hay Blob configurado: lo que guardes vive en /tmp y se pierde en un "
    "rato. Crea un Blob store en Vercel y agrega BLOB_READ_WRITE_TOKEN."
)


def _carpeta_de_escritura() -> Path:
    """La carpeta donde si se puede escribir.

    VOLEY_CARPETA gana siempre: es la forma de apuntar a un disco de verdad si
    algun dia esto se muda a un servidor comun. Si no, en serverless /tmp y en
    casa la del proyecto."""
    forzada = os.environ.get("VOLEY_CARPETA", "").strip()
    if forzada:
        return Path(forzada).expanduser().resolve()
    if EN_SERVERLESS:
        return Path("/tmp/voley")
    return CARPETA_PROYECTO


CARPETA_ESCRITURA = _carpeta_de_escritura()

# Las del proyecto son semilla solo cuando no son la de escritura: en casa las
# dos son la misma y no hay que listarla dos veces.
_ES_LOCAL = CARPETA_ESCRITURA == CARPETA_PROYECTO


def carpeta_de_escritura(logica: str) -> Path:
    """Donde se guarda un archivo nuevo de esa carpeta logica."""
    return CARPETA_ESCRITURA / logica


def carpeta_semilla(logica: str) -> Path:
    """La copia de solo lectura que viaja en el deploy."""
    return CARPETA_PROYECTO / logica


def carpetas_de_lectura(logica: str) -> list[Path]:
    """Todas las carpetas donde puede estar un archivo, la de escritura
    primero: si un partido esta en las dos, manda el que se guardo."""
    if _ES_LOCAL:
        return [carpeta_de_escritura(logica)]
    return [carpeta_de_escritura(logica), carpeta_semilla(logica)]


def carpeta_lista(carpeta: Path) -> Path:
    """La carpeta, creandola la primera vez que hace falta.

    En la carpeta de solo lectura de Vercel el mkdir falla; no es un error que
    tenga que cortar nada, porque ahi no se iba a escribir igual."""
    try:
        Path(carpeta).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return Path(carpeta)


# ======================================================================
# VERCEL BLOB
# ======================================================================
#
# Se habla con la API REST y no con @vercel/blob, que es un paquete de Node.
# Son tres llamadas (listar, subir, bajar) y con urllib alcanza: asi el
# proyecto sigue sin dependencias fuera de openpyxl.

API_BLOB = "https://blob.vercel-storage.com"
VERSION_API_BLOB = "7"          # va en x-api-version; la fija el servicio

# Lo que devuelve el listado se guarda un ratito: un pedido de la pantalla
# dispara varias lecturas seguidas (listado, partido, jugadores) y no tiene
# sentido preguntarle al blob tres veces por lo mismo.
SEGUNDOS_DE_CACHE = float(os.environ.get("VOLEY_CACHE_BLOB", "5"))


def token_blob() -> str:
    return os.environ.get("BLOB_READ_WRITE_TOKEN", "").strip()


def hay_blob() -> bool:
    return bool(token_blob())


_candado_blob = threading.Lock()
_ultimo_listado: dict[str, tuple[float, list[dict]]] = {}


def _pedir(url: str, *, metodo="GET", cuerpo=None, cabeceras=None, timeout=10):
    pedido = urllib.request.Request(url, data=cuerpo, method=metodo)
    pedido.add_header("authorization", f"Bearer {token_blob()}")
    pedido.add_header("x-api-version", VERSION_API_BLOB)
    for clave, valor in (cabeceras or {}).items():
        pedido.add_header(clave, valor)
    with urllib.request.urlopen(pedido, timeout=timeout) as respuesta:
        return respuesta.read()


def listar_blobs(prefijo: str, *, refrescar=False) -> list[dict]:
    """Los archivos que hay en el blob bajo ese prefijo.

    Devuelve [] si no hay blob o si la llamada falla: que se caiga el listado
    remoto no puede dejar la pantalla sin los partidos que ya estan bajados."""
    if not hay_blob():
        return []

    ahora = time.monotonic()
    with _candado_blob:
        guardado = _ultimo_listado.get(prefijo)
        if not refrescar and guardado and ahora - guardado[0] < SEGUNDOS_DE_CACHE:
            return guardado[1]

    blobs, cursor = [], None
    try:
        while True:
            consulta = {"prefix": prefijo, "limit": "1000"}
            if cursor:
                consulta["cursor"] = cursor
            crudo = _pedir(f"{API_BLOB}?{urllib.parse.urlencode(consulta)}")
            pagina = json.loads(crudo.decode("utf-8"))
            blobs.extend(pagina.get("blobs") or [])
            cursor = pagina.get("cursor") if pagina.get("hasMore") else None
            if not cursor:
                break
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        with _candado_blob:
            guardado = _ultimo_listado.get(prefijo)
        return guardado[1] if guardado else []

    with _candado_blob:
        _ultimo_listado[prefijo] = (ahora, blobs)
    return blobs


def _url_sin_cache(blob: dict) -> str:
    """La URL del blob con la fecha de subida pegada atras.

    Los blobs publicos se sirven por CDN con un max-age larguisimo, asi que
    pedir dos veces la misma URL puede devolver la version vieja. Cambiando la
    query cambia la entrada del CDN, y como la fecha viene del listado siempre
    apunta a la ultima version subida."""
    url = blob.get("downloadUrl") or blob.get("url") or ""
    marca = str(blob.get("uploadedAt") or "")
    if not url or not marca:
        return url
    separador = "&" if "?" in url else "?"
    return f"{url}{separador}v={urllib.parse.quote(marca)}"


def bajar_blob(blob: dict, destino: Path) -> bool:
    try:
        with urllib.request.urlopen(_url_sin_cache(blob), timeout=20) as respuesta:
            contenido = respuesta.read()
    except (urllib.error.URLError, OSError):
        return False
    carpeta_lista(destino.parent)
    temporal = destino.with_name(destino.name + ".bajando")
    temporal.write_bytes(contenido)
    temporal.replace(destino)      # el archivo aparece entero o no aparece
    return True


def subir_blob(pathname: str, contenido: bytes, tipo: str) -> str:
    """Sube (o pisa) un archivo del blob. Devuelve su URL publica."""
    crudo = _pedir(
        f"{API_BLOB}/{urllib.parse.quote(pathname)}",
        metodo="PUT",
        cuerpo=contenido,
        cabeceras={
            "x-content-type": tipo,
            # el nombre del archivo ya es unico (lleva fecha y hora) y ademas
            # tiene que poder pisarse: regenerar un informe es reemplazarlo
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
            "content-type": "application/octet-stream",
        },
        timeout=30,
    )
    return (json.loads(crudo.decode("utf-8")) or {}).get("url", "")


TIPO_POR_EXTENSION = {
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


# ======================================================================
# LO QUE USA EL RESTO DEL PROYECTO
# ======================================================================

def sincronizar(logica: str, *, refrescar=False) -> Path:
    """Baja del blob lo que no este en la carpeta de escritura.

    Se llama antes de listar o de leer. Compara por tamaño y no por fecha
    porque el mtime local es el de la bajada, no el de la subida; con nombres
    que ya llevan fecha y hora, tamaño distinto significa archivo distinto."""
    destino_base = carpeta_de_escritura(logica)
    if not hay_blob():
        return destino_base

    for blob in listar_blobs(f"{logica}/", refrescar=refrescar):
        nombre = Path(blob.get("pathname", "")).name
        if not nombre:
            continue
        destino = destino_base / nombre
        try:
            if destino.exists() and destino.stat().st_size == int(blob.get("size") or -1):
                continue
        except OSError:
            pass
        bajar_blob(blob, destino)
    return destino_base


def sincronizar_todo(*, refrescar=False) -> None:
    for logica in CARPETAS:
        sincronizar(logica, refrescar=refrescar)


def publicar(ruta) -> str:
    """Sube al blob un archivo recien escrito. Sin blob no hace nada.

    Devuelve la URL publica, o "" si no se subio. No levanta: el archivo ya
    esta guardado en disco y la pantalla tiene que poder descargarlo igual
    aunque el blob este caido; lo que se pierde es la persistencia, y de eso
    avisa estado()."""
    ruta = Path(ruta)
    if not hay_blob() or not ruta.exists():
        return ""
    logica = ruta.parent.name
    if logica not in CARPETAS:
        return ""
    tipo = TIPO_POR_EXTENSION.get(ruta.suffix.lower(), "application/octet-stream")
    try:
        url = subir_blob(f"{logica}/{ruta.name}", ruta.read_bytes(), tipo)
    except (urllib.error.URLError, OSError, ValueError):
        return ""
    with _candado_blob:
        _ultimo_listado.pop(f"{logica}/", None)   # que el proximo listado lo vea
    return url


# ----------------------------------------------------------------------
# El partido en curso.
#
# No es un archivo del usuario, pero tiene el mismo problema y peor: en
# serverless cada pedido puede caer en una instancia distinta, asi que la
# sesion no puede vivir en una variable de modulo. Se guarda la lista de
# lineas (que es todo lo que hace falta: el motor rehace el partido entero a
# partir de ellas) y cada instancia la relee antes de contestar.
# ----------------------------------------------------------------------

RUTA_SESION = "sesion/actual.json"


def guardar_sesion(lineas: list[str]) -> bool:
    datos = json.dumps({"lineas": lineas, "guardado": time.time()},
                       ensure_ascii=False).encode("utf-8")
    local = CARPETA_ESCRITURA / "sesion" / "actual.json"
    carpeta_lista(local.parent)
    try:
        local.write_bytes(datos)
    except OSError:
        pass
    if not hay_blob():
        return False
    try:
        subir_blob(RUTA_SESION, datos, TIPO_POR_EXTENSION[".json"])
    except (urllib.error.URLError, OSError, ValueError):
        return False
    with _candado_blob:
        _ultimo_listado.pop("sesion/", None)
    return True


def leer_sesion() -> tuple[list[str], str] | None:
    """(lineas, version) de la sesion guardada, o None si no hay ninguna.

    La version es la fecha de subida: con eso la instancia que atiende el
    pedido sabe si lo que tiene en memoria sigue siendo lo ultimo, sin
    bajarse el archivo en cada pedido."""
    if not hay_blob():
        local = CARPETA_ESCRITURA / "sesion" / "actual.json"
        try:
            datos = json.loads(local.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return list(datos.get("lineas") or []), str(local.stat().st_mtime)

    blobs = [b for b in listar_blobs("sesion/", refrescar=True)
             if b.get("pathname") == RUTA_SESION]
    if not blobs:
        return None
    blob = blobs[0]
    try:
        with urllib.request.urlopen(_url_sin_cache(blob), timeout=10) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return list(datos.get("lineas") or []), str(blob.get("uploadedAt") or "")


def version_de_sesion() -> str:
    """La fecha de subida de la sesion guardada, sin bajar el contenido."""
    if not hay_blob():
        local = CARPETA_ESCRITURA / "sesion" / "actual.json"
        try:
            return str(local.stat().st_mtime)
        except OSError:
            return ""
    for blob in listar_blobs("sesion/", refrescar=True):
        if blob.get("pathname") == RUTA_SESION:
            return str(blob.get("uploadedAt") or "")
    return ""


# ----------------------------------------------------------------------

def estado() -> dict:
    """Como quedo configurado el almacenamiento. Va en /api/estado para que la
    pantalla pueda avisar que lo que se guarde no va a durar."""
    avisos = []
    if EN_SERVERLESS and not hay_blob():
        avisos.append(MENSAJE_SIN_BLOB)
    return {
        "serverless": EN_SERVERLESS,
        "persistente": hay_blob() or not EN_SERVERLESS,
        "blob": hay_blob(),
        "escritura": str(CARPETA_ESCRITURA),
        "avisos": avisos,
    }
