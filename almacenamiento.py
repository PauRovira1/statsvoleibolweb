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


# Lo que Windows no acepta en el nombre de un archivo. La barra ademas es
# separador de carpetas, asi que un equipo llamado "Palestino/B" no fallaba:
# escribia el informe adentro de una carpeta inventada, donde no lo encuentra
# nadie.
PROHIBIDOS_EN_NOMBRE = '<>:"/\\|?*'


def nombre_para_archivo(texto: str) -> str:
    """El nombre de un equipo, servible como parte de un nombre de archivo.

    El volcado se llama partido_<fecha>.txt y el informe
    Informe_<equipo>_vs_<rival>_<fecha>.xlsx: por eso un nombre con un "|" o
    un "?" hacia que el .txt se guardara bien y el Excel no, con un OSError
    que en pantalla se veia como que el boton no hacia nada."""
    limpio = "".join("-" if c in PROHIBIDOS_EN_NOMBRE or ord(c) < 32 else c
                     for c in str(texto or ""))
    # Windows tampoco quiere puntos ni espacios al final de un nombre
    return limpio.strip().rstrip(". ") or "equipo"


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

# Un store de Blob se crea publico o privado, y hay que decirle a cada subida
# cual es: el servicio rechaza con 400 la subida que no coincide con como esta
# configurado el store. Privado es lo que corresponde aca -- los partidos y los
# informes salen siempre por /api/descargar, que es del servidor, y no hay
# ninguna razon para que ademas se puedan bajar de una URL suelta -- pero si el
# store es publico se cambia con VOLEY_BLOB_ACCESO=public.
ACCESO_BLOB = os.environ.get("VOLEY_BLOB_ACCESO", "private").strip() or "private"

# Lo que devuelve el listado se guarda un ratito: un pedido de la pantalla
# dispara varias lecturas seguidas (listado, partido, jugadores) y no tiene
# sentido preguntarle al blob tres veces por lo mismo.
SEGUNDOS_DE_CACHE = float(os.environ.get("VOLEY_CACHE_BLOB", "5"))


COMILLAS = "\"' "      # lo que puede venir pegado al copiar de un .env


def _limpio(valor) -> str:
    return str(valor or "").strip().strip(COMILLAS)


def token_blob() -> str:
    """El token del Blob, sin lo que suele venir pegado al copiarlo.

    El panel de Vercel lo muestra dentro de un snippet de .env.local, o sea
    entre comillas, y es facil que terminen formando parte del valor. Un token
    con comillas no da un error de formato: da un 403 "Token mismatch", que
    parece un problema de permisos y no lo es."""
    return _limpio(os.environ.get("BLOB_READ_WRITE_TOKEN"))


def hay_blob() -> bool:
    return bool(token_blob())


_candado_blob = threading.Lock()
_ultimo_listado: dict[str, tuple[float, list[dict]]] = {}


class ErrorDeBlob(RuntimeError):
    """El blob contesto algo que no esperabamos.

    Existe para no perder el cuerpo de la respuesta: urllib deja el detalle
    del error adentro del HTTPError y hay que leerlo antes de que se cierre.
    Ese detalle es lo unico que dice si fallo la credencial, la version de la
    API o el nombre del archivo, y es lo que se termina mostrando en pantalla.

    "codigo" es el HTTP que contesto, cuando hubo uno: sirve para distinguir
    un 404 ("no esta ese archivo", que puede ser normal) de todo lo demas."""

    def __init__(self, mensaje: str, codigo: int | None = None):
        super().__init__(mensaje)
        self.codigo = codigo


# Por que fallo la ultima llamada al blob. Se guarda para poder decirlo en el
# mensaje del guardado: el que esta en la cancha no va a ir a mirar los logs
# del proyecto, y sin el motivo "no se pudo subir" no se puede arreglar.
_ultimo_error = ""


def ultimo_error() -> str:
    with _candado_blob:
        return _ultimo_error


def _anotar_error(texto: str) -> None:
    global _ultimo_error
    with _candado_blob:
        _ultimo_error = texto
    print(f"[almacenamiento] {texto}")      # ademas queda en los logs de Vercel


def _pedir(url: str, *, metodo="GET", cuerpo=None, cabeceras=None, timeout=10):
    pedido = urllib.request.Request(url, data=cuerpo, method=metodo)
    pedido.add_header("authorization", f"Bearer {token_blob()}")
    pedido.add_header("x-api-version", VERSION_API_BLOB)
    for clave, valor in (cabeceras or {}).items():
        pedido.add_header(clave, valor)
    # el token va en la cabecera, asi que la URL se puede mostrar entera
    donde = f"{metodo} {url.split('?')[0]}"
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as respuesta:
            return respuesta.read()
    except urllib.error.HTTPError as error:
        try:
            detalle = error.read().decode("utf-8", "replace").strip()[:300]
        except OSError:
            detalle = ""
        raise ErrorDeBlob(f"{donde} -> HTTP {error.code} {detalle}", error.code) from None
    except urllib.error.URLError as error:
        raise ErrorDeBlob(f"{donde} -> no se pudo contactar al blob: {error.reason}") from None


FALLAS_DE_RED = (ErrorDeBlob, urllib.error.URLError, OSError,
                 ValueError, json.JSONDecodeError)


def _listar_blobs_crudo(prefijo: str) -> list[dict]:
    """Le pregunta al blob que hay bajo ese prefijo. Levanta si no se puede."""
    blobs, cursor = [], None
    while True:
        consulta = {"prefix": prefijo, "limit": "1000"}
        if cursor:
            consulta["cursor"] = cursor
        crudo = _pedir(f"{API_BLOB}?{urllib.parse.urlencode(consulta)}")
        pagina = json.loads(crudo.decode("utf-8"))
        blobs.extend(pagina.get("blobs") or [])
        cursor = pagina.get("cursor") if pagina.get("hasMore") else None
        if not cursor:
            return blobs


def _guardar_listado(prefijo: str, blobs: list[dict]) -> None:
    with _candado_blob:
        _ultimo_listado[prefijo] = (time.monotonic(), blobs)


def listar_blobs(prefijo: str, *, refrescar=False) -> list[dict]:
    """Los archivos que hay en el blob bajo ese prefijo.

    Si la llamada falla se devuelve lo ultimo que se supo, o [] si nunca se
    supo nada: que se caiga el listado remoto no puede dejar la pantalla sin
    los partidos que ya estan bajados. Para preguntas donde una respuesta
    vieja seria peor que ninguna esta publicado(), que no usa el cache."""
    if not hay_blob():
        return []

    ahora = time.monotonic()
    with _candado_blob:
        guardado = _ultimo_listado.get(prefijo)
        if not refrescar and guardado and ahora - guardado[0] < SEGUNDOS_DE_CACHE:
            return guardado[1]

    try:
        blobs = _listar_blobs_crudo(prefijo)
    except FALLAS_DE_RED as error:
        _anotar_error(f"no se pudo listar {prefijo!r}: {error}")
        with _candado_blob:
            guardado = _ultimo_listado.get(prefijo)
        return guardado[1] if guardado else []

    _guardar_listado(prefijo, blobs)
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
    """Trae un archivo del blob a la carpeta de escritura.

    Va con el token igual que el resto: en un store privado la URL sola
    devuelve 403, y en uno publico la cabecera de mas no molesta."""
    try:
        contenido = _pedir(_url_sin_cache(blob), timeout=20)
    except FALLAS_DE_RED as error:
        _anotar_error(f"no se pudo bajar {blob.get('pathname')}: {error}")
        return False
    carpeta_lista(destino.parent)
    temporal = destino.with_name(destino.name + ".bajando")
    temporal.write_bytes(contenido)
    temporal.replace(destino)      # el archivo aparece entero o no aparece
    return True


def _version_de(blob: dict) -> str:
    """Con que se decide si lo guardado cambio.

    El etag es lo unico que devuelven las TRES operaciones (subir, cabeza y
    listar), y por eso se prefiere: permite enterarse de la version en la
    misma subida, sin una segunda llamada. Si la API no lo manda se cae a la
    fecha de subida, que es lo que se usaba antes."""
    return str(blob.get("etag") or blob.get("uploadedAt") or "")


def cabeza_blob(pathname: str) -> dict | None:
    """Los datos de un archivo del blob sin listar el store ni bajarlo.

    Es la diferencia entre entrar o no en el plan gratis: listar cuenta como
    operacion ADVANCED y pedir la cabeza como SIMPLE, y en el plan Hobby son
    2.000 contra 10.000 por mes. Esto se pregunta en CADA pedido (para saber
    si la sesion que hay en memoria sigue siendo la ultima), asi que es la
    llamada que mas se repite de todo el proyecto.

    Devuelve None si el archivo no esta. Si el servicio contesta cualquier
    otra cosa levanta, y el que llama se cae al listado de siempre."""
    crudo = _pedir(f"{API_BLOB}?{urllib.parse.urlencode({'url': pathname})}")
    datos = json.loads(crudo.decode("utf-8"))
    return datos or None


def subir_blob_detalle(pathname: str, contenido: bytes, tipo: str) -> dict:
    """Sube (o pisa) un archivo del blob. Devuelve lo que contesto el servicio
    (url, pathname y etag), que es de donde sale la version sin preguntarla."""
    crudo = _pedir(
        f"{API_BLOB}/{urllib.parse.quote(pathname)}",
        metodo="PUT",
        cuerpo=contenido,
        cabeceras={
            "x-content-type": tipo,
            "x-vercel-blob-access": ACCESO_BLOB,
            # el nombre del archivo ya es unico (lleva fecha y hora) y ademas
            # tiene que poder pisarse: regenerar un informe es reemplazarlo
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "1",
            "content-type": "application/octet-stream",
        },
        timeout=30,
    )
    return json.loads(crudo.decode("utf-8")) or {}


def subir_blob(pathname: str, contenido: bytes, tipo: str) -> str:
    """Sube (o pisa) un archivo del blob. Devuelve su URL publica."""
    return subir_blob_detalle(pathname, contenido, tipo).get("url", "")


def borrar_blob(url: str) -> None:
    """Saca un archivo del blob. Levanta si no se pudo."""
    _pedir(f"{API_BLOB}/delete", metodo="POST",
           cuerpo=json.dumps({"urls": [url]}).encode("utf-8"),
           cabeceras={"content-type": "application/json"}, timeout=20)


TIPO_POR_EXTENSION = {
    ".txt": "text/plain; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


# ----------------------------------------------------------------------
# Los borrados.
#
# Borrar un partido es borrar su archivo, salvo cuando el archivo viene en el
# deploy: esos estan en la carpeta del proyecto, que alojado es de solo
# lectura, y ahi no hay nada que borrar porque volverian en el deploy
# siguiente igual. Para esos se anota el nombre en una lista, y el que lista
# los saltea. Es la unica forma de que "borrar" quiera decir lo mismo para
# todos los partidos y no la mitad de las veces.
#
# La lista vive en el blob junto con lo demas, asi que la ve cualquier
# instancia. Sin blob no hace falta: ahi la carpeta del proyecto es la de
# escritura y el archivo se borra de verdad.
# ----------------------------------------------------------------------

RUTA_BORRADOS = "borrados/lista.json"

_borrados: set[str] | None = None      # cache por instancia
_momento_borrados = 0.0


def _cargar_borrados(*, refrescar=False) -> set[str]:
    """Los "<carpeta>/<nombre>" que se borraron y hay que seguir ocultando."""
    global _borrados, _momento_borrados
    if not hay_blob():
        return set()

    ahora = time.monotonic()
    if not refrescar and _borrados is not None and ahora - _momento_borrados < SEGUNDOS_DE_CACHE:
        return _borrados

    lista: set[str] = set()
    try:
        blobs = [b for b in _listar_blobs_crudo("borrados/")
                 if b.get("pathname") == RUTA_BORRADOS]
        if blobs:
            datos = json.loads(_pedir(_url_sin_cache(blobs[0])).decode("utf-8"))
            lista = {str(x) for x in (datos.get("borrados") or [])}
    except FALLAS_DE_RED as error:
        _anotar_error(f"no se pudo leer la lista de borrados: {error}")
        # lo ultimo que se supo es mejor que nada: si la lista no se puede
        # leer, un partido borrado reapareceria en pantalla
        return _borrados if _borrados is not None else set()

    _borrados, _momento_borrados = lista, ahora
    return lista


def esta_borrado(logica: str, nombre: str) -> bool:
    return f"{logica}/{nombre}" in _cargar_borrados()


# ----------------------------------------------------------------------
# Correcciones a mano del resumen de un partido.
#
# La fila que se ve en Partidos se lee del propio .txt, que es lo correcto
# mientras el .txt diga la verdad. Pero hay cosas que el archivo no puede
# saber: cual de varios guardados del mismo partido es el bueno, o que
# informe le corresponde cuando hay mas de uno del mismo dia. Para eso esta
# esto: un arreglo escrito a mano que gana sobre lo que dice el archivo, y
# que se puede sacar para volver a lo que dice el archivo.
#
# Se guarda igual que la sesion: siempre local, y ademas en el blob si hay.
# Asi funciona lo mismo corriendo en casa que alojado.
RUTA_CORRECCIONES = "correcciones/lista.json"

_correcciones: dict | None = None
_momento_correcciones = 0.0


def _archivo_correcciones() -> Path:
    return CARPETA_ESCRITURA / "correcciones" / "lista.json"


def _correcciones_locales() -> dict:
    try:
        datos = json.loads(_archivo_correcciones().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(datos.get("correcciones") or {})


def leer_correcciones(*, refrescar: bool = False) -> dict:
    """Los arreglos a mano, por nombre de volcado."""
    global _correcciones, _momento_correcciones
    ahora = time.monotonic()
    if (not refrescar and _correcciones is not None
            and ahora - _momento_correcciones < SEGUNDOS_DE_CACHE):
        return _correcciones

    if not hay_blob():
        _correcciones, _momento_correcciones = _correcciones_locales(), ahora
        return _correcciones

    try:
        blob = _blob_puntual(RUTA_CORRECCIONES)
        datos = (json.loads(_pedir(_url_sin_cache(blob), timeout=10).decode("utf-8"))
                 if blob else {})
        lista = dict(datos.get("correcciones") or {})
    except FALLAS_DE_RED as error:
        _anotar_error(f"no se pudo leer las correcciones: {error}")
        # lo ultimo que se supo es mejor que nada: sin esto, un partido
        # corregido volveria a verse mal en cuanto falle una lectura
        if _correcciones is not None:
            return _correcciones
        return _correcciones_locales()

    _correcciones, _momento_correcciones = lista, ahora
    return lista


def guardar_correccion(nombre: str, campos: dict | None) -> bool:
    """Guarda el arreglo de un volcado, o lo saca si campos viene vacio."""
    global _correcciones
    lista = dict(leer_correcciones(refrescar=True))
    if campos:
        lista[nombre] = campos
    else:
        lista.pop(nombre, None)

    datos = json.dumps({"correcciones": lista}, ensure_ascii=False).encode("utf-8")
    local = _archivo_correcciones()
    carpeta_lista(local.parent)
    try:
        local.write_bytes(datos)
    except OSError:
        pass

    _correcciones = lista
    if not hay_blob():
        return True
    try:
        subir_blob(RUTA_CORRECCIONES, datos, TIPO_POR_EXTENSION[".json"])
    except FALLAS_DE_RED as error:
        _anotar_error(f"no se pudo guardar la correccion de {nombre}: {error}")
        return False
    with _candado_blob:
        _ultimo_listado.pop("correcciones/", None)
    return True


# ----------------------------------------------------------------------
# Los nombres de los jugadores.
#
# El volcado guarda numeros, no nombres: en la cancha se grita "el 13" y eso
# es lo que se tipea. Pero el numero solo no alcanza para saber de quien se
# esta hablando -- dos equipos pueden tener un 13, y el 13 de este año puede
# no ser el mismo del anterior -- asi que los nombres se anotan aparte, por
# equipo y dorsal. No entran al volcado ni al Excel: son para mirar.
RUTA_PLANTEL = "plantel/lista.json"

_plantel: dict | None = None
_momento_plantel = 0.0


def _archivo_plantel() -> Path:
    return CARPETA_ESCRITURA / "plantel" / "lista.json"


def _plantel_local() -> dict:
    try:
        return json.loads(_archivo_plantel().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _leer_todo_el_plantel(*, refrescar: bool = False) -> dict:
    """El archivo entero: los nombres del equipo y los de cada partido."""
    global _plantel, _momento_plantel
    ahora = time.monotonic()
    if (not refrescar and _plantel is not None
            and ahora - _momento_plantel < SEGUNDOS_DE_CACHE):
        return _plantel

    if not hay_blob():
        _plantel, _momento_plantel = _plantel_local(), ahora
        return _plantel

    try:
        blob = _blob_puntual(RUTA_PLANTEL)
        datos = (json.loads(_pedir(_url_sin_cache(blob), timeout=10).decode("utf-8"))
                 if blob else {})
    except FALLAS_DE_RED as error:
        _anotar_error(f"no se pudo leer el plantel: {error}")
        if _plantel is not None:
            return _plantel
        return _plantel_local()

    _plantel, _momento_plantel = datos, ahora
    return datos


def leer_plantel(*, refrescar: bool = False) -> dict:
    """Los nombres del equipo, como {equipo: {dorsal: nombre}}.

    Son el valor por defecto: valen para todos los partidos de ese equipo
    salvo que alguno tenga los suyos (ver leer_nombres_de_partido)."""
    return dict(_leer_todo_el_plantel(refrescar=refrescar).get("plantel") or {})


def leer_nombres_de_partido(*, refrescar: bool = False) -> dict:
    """Los nombres propios de cada partido, {volcado: {equipo: {dorsal: nombre}}}.

    Hacen falta porque el numero no es de nadie para siempre: el 13 del año
    pasado puede no ser el 13 de este, y un partido viejo tiene que poder
    decir quien era el 13 ESE dia."""
    return dict(_leer_todo_el_plantel(refrescar=refrescar).get("partidos") or {})


def nombres_de(volcado: str, equipo: str) -> dict:
    """Los nombres que valen para ese equipo en ese partido.

    Los del equipo primero y encima los propios del partido, si los hay."""
    nombres = dict(leer_plantel().get(equipo) or {})
    nombres.update(leer_nombres_de_partido().get(volcado, {}).get(equipo) or {})
    return nombres


def _limpiar_nombres(nombres: dict) -> dict:
    return {str(d): str(n).strip() for d, n in (nombres or {}).items()
            if str(n or "").strip()}


def _guardar_todo_el_plantel(datos: dict) -> bool:
    global _plantel
    crudo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
    local = _archivo_plantel()
    carpeta_lista(local.parent)
    try:
        local.write_bytes(crudo)
    except OSError:
        pass

    _plantel = datos
    if not hay_blob():
        return True
    try:
        subir_blob(RUTA_PLANTEL, crudo, TIPO_POR_EXTENSION[".json"])
    except FALLAS_DE_RED as error:
        _anotar_error(f"no se pudo guardar el plantel: {error}")
        return False
    with _candado_blob:
        _ultimo_listado.pop("plantel/", None)
    return True


def guardar_plantel(equipo: str, nombres: dict) -> bool:
    """Deja los nombres por defecto de un equipo. Un dorsal sin nombre se saca."""
    datos = _leer_todo_el_plantel(refrescar=True)
    plantel = {e: dict(n) for e, n in (datos.get("plantel") or {}).items()}
    limpios = _limpiar_nombres(nombres)
    if limpios:
        plantel[equipo] = limpios
    else:
        plantel.pop(equipo, None)
    return _guardar_todo_el_plantel({**datos, "plantel": plantel})


def guardar_nombres_de_partido(volcado: str, equipo: str, nombres: dict) -> bool:
    """Deja los nombres propios de un partido. Sin nombres vuelve a los del
    equipo, que es lo que corresponde cuando no cambio nadie."""
    datos = _leer_todo_el_plantel(refrescar=True)
    partidos = {v: {e: dict(n) for e, n in equipos.items()}
                for v, equipos in (datos.get("partidos") or {}).items()}
    limpios = _limpiar_nombres(nombres)
    delpartido = partidos.setdefault(volcado, {})
    if limpios:
        delpartido[equipo] = limpios
    else:
        delpartido.pop(equipo, None)
    if not delpartido:
        partidos.pop(volcado, None)
    return _guardar_todo_el_plantel({**datos, "partidos": partidos})


def _anotar_borrado(logica: str, nombre: str) -> bool:
    """Agrega el archivo a la lista de los que hay que ocultar."""
    global _borrados
    if not hay_blob():
        return False
    lista = set(_cargar_borrados(refrescar=True)) | {f"{logica}/{nombre}"}
    try:
        subir_blob(RUTA_BORRADOS,
                   json.dumps({"borrados": sorted(lista)}, ensure_ascii=False).encode("utf-8"),
                   TIPO_POR_EXTENSION[".json"])
    except FALLAS_DE_RED as error:
        _anotar_error(f"no se pudo anotar el borrado de {logica}/{nombre}: {error}")
        return False
    _borrados = lista
    with _candado_blob:
        _ultimo_listado.pop("borrados/", None)
    return True


def borrar(logica: str, nombre: str) -> tuple[bool, str]:
    """Borra un archivo de donde este. Devuelve (se pudo, que paso).

    Son hasta tres lugares y hay que pasar por los tres: la carpeta de
    escritura, el blob, y la del deploy, que no se puede tocar y se resuelve
    anotando el nombre para que deje de aparecer."""
    hechos = []

    # El Blob primero, que es el que manda: la copia local es un cache que se
    # vuelve a bajar sola. Borrando al reves, un fallo al borrar afuera dejaba
    # el archivo "borrado" hasta la proxima sincronizacion, y despues volvia a
    # aparecer sin que nadie entendiera por que.
    if hay_blob():
        objetivo = f"{logica}/{nombre}"
        try:
            blob = _blob_puntual(objetivo, estricto=True)
        except FALLAS_DE_RED as error:
            _anotar_error(f"no se pudo preguntar por {objetivo}: {error}")
            return False, (f"No se pudo saber si {nombre} esta en el Blob ({error}). "
                           f"No se borro nada: borrar solo la copia local lo haria "
                           f"reaparecer en cuanto se vuelva a sincronizar.")
        if blob is not None:
            try:
                borrar_blob(blob.get("url", ""))
                hechos.append("del Blob")
            except FALLAS_DE_RED as error:
                _anotar_error(f"no se pudo borrar {objetivo} del Blob: {error}")
                return False, f"No se pudo borrar {nombre} del Blob: {error}"
            with _candado_blob:
                _ultimo_listado.pop(f"{logica}/", None)

    local = carpeta_de_escritura(logica) / nombre
    if local.exists():
        try:
            local.unlink()
            hechos.append("del disco")
        except OSError as error:
            return False, f"No se pudo borrar {nombre}: {error}"

    # si despues de todo eso sigue existiendo, es de los que vienen en el
    # deploy: no se puede borrar, pero si dejar de mostrar
    if (carpeta_semilla(logica) / nombre).exists():
        if not _anotar_borrado(logica, nombre):
            return False, (f"{nombre} viene en el repositorio y no se puede borrar "
                           f"desde aca. Hace falta el Blob para poder ocultarlo.")
        hechos.append("oculto (viene en el repositorio)")

    if not hechos:
        return False, f"No existe {nombre}."
    return True, f"Se borro {nombre} ({', '.join(hechos)})."


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
        if not nombre or esta_borrado(logica, nombre):
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
    aunque el blob este caido. Lo que se pierde cuando falla es la
    persistencia, y de eso no alcanza con no enterarse: el que llama pregunta
    despues con publicado() y lo dice en pantalla."""
    ruta = Path(ruta)
    if not hay_blob() or not ruta.exists():
        return ""
    logica = ruta.parent.name
    if logica not in CARPETAS:
        return ""
    tipo = TIPO_POR_EXTENSION.get(ruta.suffix.lower(), "application/octet-stream")
    try:
        url = subir_blob(f"{logica}/{ruta.name}", ruta.read_bytes(), tipo)
    except FALLAS_DE_RED as error:
        _anotar_error(f"no se pudo subir {logica}/{ruta.name}: {error}")
        return ""
    with _candado_blob:
        _ultimo_listado.pop(f"{logica}/", None)   # que el proximo listado lo vea
    return url


def publicado(logica: str, nombre: str) -> bool:
    """Si ese archivo esta hoy en el blob.

    Se le pregunta al blob en vez de confiar en lo que contesto la subida: lo
    que importa no es que el PUT haya salido bien sino que el archivo este, que
    es lo que va a hacer que siga estando la semana que viene.

    Sin cache a proposito, ni siquiera como respaldo: esto se usa para decidir
    si avisarle al usuario que su partido puede perderse, y un listado viejo
    (donde figura un informe del mismo nombre que se regenero) contestaria que
    si cuando la subida acaba de fallar. Si no se puede confirmar, se avisa."""
    global _hay_cabeza
    if not hay_blob():
        return False
    ruta = f"{logica}/{nombre}"

    # Preguntar por un archivo puntual es justo para lo que sirve la cabeza, y
    # cuesta una operacion simple en vez de una advanced. Listar el store
    # entero para ver si uno esta era lo caro.
    if _hay_cabeza:
        try:
            return bool(cabeza_blob(ruta))
        except ErrorDeBlob as error:
            if error.codigo == 404:
                return False
            _hay_cabeza = False
            _anotar_error(f"no se pudo confirmar {ruta}: {error}")
        except FALLAS_DE_RED as error:
            _hay_cabeza = False
            _anotar_error(f"no se pudo confirmar {ruta}: {error}")

    prefijo = f"{logica}/"
    try:
        blobs = _listar_blobs_crudo(prefijo)
    except FALLAS_DE_RED as error:
        _anotar_error(f"no se pudo confirmar {ruta}: {error}")
        return False
    _guardar_listado(prefijo, blobs)
    return any(b.get("pathname") == ruta for b in blobs)


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


def guardar_sesion(lineas: list[str]) -> str:
    """Guarda la sesion y devuelve con que version quedo.

    Devolverla es lo que evita una segunda llamada: antes, el que guardaba
    tenia que volver a preguntarle al blob que version le habia tocado, y esa
    pregunta costaba una operacion advanced por cada jugada cargada. La subida
    ya trae el etag. Si no lo trajera, se devuelve "" y el que llama pregunta
    como siempre."""
    datos = json.dumps({"lineas": lineas, "guardado": time.time()},
                       ensure_ascii=False).encode("utf-8")
    local = CARPETA_ESCRITURA / "sesion" / "actual.json"
    carpeta_lista(local.parent)
    try:
        local.write_bytes(datos)
    except OSError:
        pass
    if not hay_blob():
        try:
            return str(local.stat().st_mtime)
        except OSError:
            return ""
    try:
        subido = subir_blob_detalle(RUTA_SESION, datos, TIPO_POR_EXTENSION[".json"])
    except FALLAS_DE_RED as error:
        # que no se pueda guardar la sesion afuera no puede voltear la jugada
        # que se acaba de cargar: ya esta en memoria y contestada
        _anotar_error(f"no se pudo guardar la sesion: {error}")
        return ""
    version = _version_de(subido)
    with _candado_blob:
        _ultimo_listado.pop("sesion/", None)
        _ultima_version[RUTA_SESION] = (time.monotonic(), version)
    return version


# Si pedir la cabeza no funciona contra este store, se apaga para el resto del
# proceso y se vuelve al listado de siempre.
_hay_cabeza = True

# La ultima version que se supo de la sesion, con cuando se supo. Es para las
# rutas que solo leen: varias personas mirando el marcador no tienen por que
# preguntarle al blob una vez cada una.
_ultima_version: dict[str, tuple[float, str]] = {}


def _blob_puntual(ruta: str, *, refrescar: bool = True, estricto: bool = False) -> dict | None:
    """Los datos de UN archivo del blob, sin bajarlo.

    Por la cabeza si el servicio la contesta, y si no listando el store como
    se hacia antes. La diferencia importa: listar cuenta como operacion
    ADVANCED (2.000 al mes en el plan Hobby) y la cabeza como SIMPLE (10.000).
    La de la sesion se pregunta una vez por pedido, asi que es la llamada mas
    repetida de todo el proyecto.

    Si la cabeza falla por algo que no sea "no esta", se apaga para el resto
    del proceso: mejor gastar de mas que quedarse sin saber si algo cambio.

    Con estricto=True, no poder preguntar levanta en vez de devolver None. Lo
    usa el borrado, donde "no esta" y "no pude averiguar si esta" llevan a
    cosas muy distintas: dar por borrado algo que sigue en el Blob hace que
    reaparezca en cuanto se vuelva a sincronizar."""
    global _hay_cabeza
    if _hay_cabeza:
        try:
            return cabeza_blob(ruta)
        except ErrorDeBlob as error:
            if error.codigo == 404:
                return None            # no esta, y eso es una respuesta
            _hay_cabeza = False
            _anotar_error(f"no se pudo pedir la cabeza de {ruta}: {error}")
        except FALLAS_DE_RED as error:
            _hay_cabeza = False
            _anotar_error(f"no se pudo pedir la cabeza de {ruta}: {error}")

    prefijo = ruta.rsplit("/", 1)[0] + "/" if "/" in ruta else ""
    if estricto:
        # sin red de contencion: si el listado falla, se propaga
        for blob in _listar_blobs_crudo(prefijo):
            if blob.get("pathname") == ruta:
                return blob
        return None
    for blob in listar_blobs(prefijo, refrescar=refrescar):
        if blob.get("pathname") == ruta:
            return blob
    return None


def _blob_de_la_sesion(*, refrescar: bool = True) -> dict | None:
    return _blob_puntual(RUTA_SESION, refrescar=refrescar)


def leer_sesion() -> tuple[list[str], str] | None:
    """(lineas, version) de la sesion guardada, o None si no hay ninguna.

    La version identifica la subida: con eso la instancia que atiende el
    pedido sabe si lo que tiene en memoria sigue siendo lo ultimo, sin
    bajarse el archivo en cada pedido."""
    if not hay_blob():
        local = CARPETA_ESCRITURA / "sesion" / "actual.json"
        try:
            datos = json.loads(local.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return list(datos.get("lineas") or []), str(local.stat().st_mtime)

    blob = _blob_de_la_sesion()
    if blob is None:
        return None
    try:
        datos = json.loads(_pedir(_url_sin_cache(blob), timeout=10).decode("utf-8"))
    except FALLAS_DE_RED as error:
        _anotar_error(f"no se pudo leer la sesion guardada: {error}")
        return None
    return list(datos.get("lineas") or []), _version_de(blob)


def version_de_sesion(*, refrescar: bool = True) -> str:
    """Con que version esta guardada la sesion, sin bajar el contenido.

    Con refrescar=False vale la respuesta de hace unos segundos. Solo lo pueden
    usar las rutas de lectura: si una escritura trabajara sobre una sesion
    vieja, la jugada se cargaria sobre el partido equivocado."""
    if not hay_blob():
        local = CARPETA_ESCRITURA / "sesion" / "actual.json"
        try:
            return str(local.stat().st_mtime)
        except OSError:
            return ""

    if not refrescar:
        with _candado_blob:
            guardado = _ultima_version.get(RUTA_SESION)
        if guardado and time.monotonic() - guardado[0] < SEGUNDOS_DE_CACHE:
            return guardado[1]

    blob = _blob_de_la_sesion(refrescar=refrescar)
    version = _version_de(blob) if blob else ""
    with _candado_blob:
        _ultima_version[RUTA_SESION] = (time.monotonic(), version)
    return version


# ----------------------------------------------------------------------

# Las variables de entorno que el proyecto mira. En /api/estado se informa
# cuales llegaron y cuales no (solo eso: el nombre y un si/no, nunca el valor).
# Es para poder distinguir "falta configurarla" de "esta configurada pero el
# deploy es anterior y todavia no la ve", que desde afuera se ven igual.
#
# BLOB_STORE_ID no se usa para nada, pero se informa igual porque la pone
# Vercel sola al conectar el Blob store: si esa llega y el token no, el
# problema es esa variable; si no llega ninguna, no esta llegando NINGUNA
# variable del proyecto y hay que mirar en que entorno corre el deploy.
VARIABLES = ("BLOB_READ_WRITE_TOKEN", "BLOB_STORE_ID", "VOLEY_CLAVE", "VOLEY_SECRETO")


def forma_del_token() -> dict:
    """Como viene el token, sin mostrarlo.

    Un token bueno es `vercel_blob_rw_<store>_<secreto>`. Se informa si tiene
    esa forma, cuanto mide y si el pedazo del store coincide con el
    BLOB_STORE_ID que puso Vercel. El secreto no sale nunca de aca: con esto
    alcanza para distinguir "esta mal copiado" de "es de otro store" de "esta
    bien y el problema es otro"."""
    token = token_blob()
    if not token:
        return {"presente": False}
    partes = token.split("_")
    bien_formado = token.startswith("vercel_blob_rw_") and len(partes) >= 5
    store = f"store_{partes[3]}" if bien_formado else ""
    declarado = _limpio(os.environ.get("BLOB_STORE_ID"))
    return {
        "presente": True,
        "bien_formado": bien_formado,
        "largo": len(token),
        "store": store,
        "coincide_con_BLOB_STORE_ID": bool(store and declarado and store == declarado),
    }


def variables_presentes() -> dict:
    return {nombre: bool(os.environ.get(nombre, "").strip()) for nombre in VARIABLES}


def estado() -> dict:
    """Como quedo configurado el almacenamiento. Va en /api/estado para que la
    pantalla pueda avisar que lo que se guarde no va a durar."""
    avisos = []
    if EN_SERVERLESS and not hay_blob():
        avisos.append(MENSAJE_SIN_BLOB)
    # Un Blob que falla no se nota: los partidos que ya se bajaron se siguen
    # viendo, los nuevos no aparecen, y lo que se borra vuelve. Se avisa aca
    # para que se vea, en vez de quedar solo en los logs del proyecto.
    fallo = ultimo_error()
    if fallo:
        avisos.append(f"Ultimo problema con el Blob: {fallo}. Mientras no se "
                      f"arregle, los partidos nuevos pueden no aparecer y lo "
                      f"que borres puede volver.")
    return {
        "serverless": EN_SERVERLESS,
        "persistente": hay_blob() or not EN_SERVERLESS,
        "blob": hay_blob(),
        "escritura": str(CARPETA_ESCRITURA),
        # production / preview / development: si las variables se cargaron solo
        # para Production y el deploy que contesta es un preview, no las ve
        "entorno": os.environ.get("VERCEL_ENV", ""),
        "variables": variables_presentes(),
        "token": forma_del_token(),
        # solo lo sabe la instancia que fallo, asi que puede venir vacio
        # aunque algo haya fallado recien; el mensaje del guardado es el que
        # siempre lo trae, porque lo contesta esa misma instancia
        "ultimo_error": ultimo_error(),
        "avisos": avisos,
    }
