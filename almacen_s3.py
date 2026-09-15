"""Habla con S3, para que el proyecto pueda vivir en Lambda.

Es el reemplazo del Vercel Blob: mismas cinco operaciones (listar, subir,
bajar, cabeza y borrar) y devuelve los mismos diccionarios, asi que
`almacenamiento.py` no distingue con cual de los dos esta hablando.

Se firma a mano en vez de usar boto3 por dos razones. La primera es que el
proyecto no tiene dependencias fuera de openpyxl y no hay motivo para sumar
una de 50 MB por cinco llamadas HTTP. La segunda es que boto3 viene
preinstalado en Lambda pero no en una PC, asi que habria que instalarlo igual
para poder correr los tests en casa.

Firmar es un algoritmo cerrado y documentado (AWS Signature Version 4): se
arma un texto con el pedido, se lo hashea, y se lo firma con una clave
derivada de la fecha y la region. Nada de esto depende de la red, asi que se
puede probar entero sin tocar AWS -- y de hecho se prueba contra los vectores
que publica AWS.

Las credenciales salen del entorno. En Lambda las pone el rol de la funcion y
rotan solas; en casa salen de `aws configure` o de las variables de siempre.
Nunca se escriben en ningun lado.
"""
import hashlib
import hmac
import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ALGORITMO = "AWS4-HMAC-SHA256"
SERVICIO = "s3"

# El listado de S3 contesta XML con este espacio de nombres delante de cada
# etiqueta. ElementTree no lo saca solo, asi que se pega a mano al buscar.
ESPACIO = "{http://s3.amazonaws.com/doc/2006-03-01/}"

# S3 exige la cabecera x-amz-content-sha256 en todos los pedidos, tambien en
# los que no llevan cuerpo. Este es el sha256 de cero bytes.
CUERPO_VACIO = hashlib.sha256(b"").hexdigest()

COMILLAS = "\"' "      # lo que puede venir pegado al copiar de un .env


def _limpio(valor) -> str:
    return str(valor or "").strip().strip(COMILLAS)


# ----------------------------------------------------------------------
# La configuracion
# ----------------------------------------------------------------------

def bucket() -> str:
    """El bucket donde vive todo. Es lo que prende o apaga este modulo."""
    return _limpio(os.environ.get("VOLEY_S3_BUCKET"))


def region() -> str:
    """La region del bucket.

    En Lambda AWS_REGION ya viene puesta y es la de la funcion, que conviene
    que sea la misma del bucket: cruzar regiones se paga y tarda mas."""
    return (_limpio(os.environ.get("VOLEY_S3_REGION"))
            or _limpio(os.environ.get("AWS_REGION"))
            or _limpio(os.environ.get("AWS_DEFAULT_REGION"))
            or "us-east-1")


def credenciales() -> tuple[str, str, str]:
    """(clave, secreto, token de sesion). El token esta solo en Lambda.

    Las credenciales de un rol son temporales y vienen con un token que hay
    que mandar aparte; las de un usuario comun no lo tienen y va vacio."""
    return (_limpio(os.environ.get("AWS_ACCESS_KEY_ID")),
            _limpio(os.environ.get("AWS_SECRET_ACCESS_KEY")),
            _limpio(os.environ.get("AWS_SESSION_TOKEN")))


def hay_s3() -> bool:
    """Si esta todo lo que hace falta para hablar con S3."""
    clave, secreto, _ = credenciales()
    return bool(bucket() and clave and secreto)


def anfitrion() -> str:
    """El host del bucket, en estilo virtual-hosted.

    Es el que AWS recomienda y el unico que no necesita saber la region en la
    URL. Con un punto en el nombre del bucket el certificado comodin no valida
    y habria que usar el estilo viejo, asi que el bucket no lleva puntos."""
    return f"{bucket()}.s3.{region()}.amazonaws.com"


class ErrorDeS3(RuntimeError):
    """S3 contesto algo que no esperabamos.

    Guarda el codigo HTTP porque un 404 puede ser normal (preguntar por un
    archivo que todavia no existe) y todo lo demas no."""

    def __init__(self, mensaje: str, codigo: int | None = None):
        super().__init__(mensaje)
        self.codigo = codigo


# ----------------------------------------------------------------------
# La firma (AWS Signature Version 4)
# ----------------------------------------------------------------------

def codificar(texto: str, *, barras: bool = False) -> str:
    """Codifica para la URL como lo quiere AWS.

    Se diferencia de quote() por defecto en dos cosas: la virgulilla NO se
    codifica (si se codifica, la firma no coincide) y en la ruta las barras se
    dejan pasar, porque separan carpetas y no son parte del nombre."""
    seguro = "-_.~" + ("/" if barras else "")
    return urllib.parse.quote(texto, safe=seguro)


def _hmac(clave: bytes, mensaje: str) -> bytes:
    return hmac.new(clave, mensaje.encode("utf-8"), hashlib.sha256).digest()


def clave_de_firma(secreto: str, dia: str, donde: str) -> bytes:
    """La clave con la que se firma, derivada en cuatro pasos.

    Cada paso agrega un dato (dia, region, servicio), asi que la clave que
    sale sirve solo para ese dia, esa region y ese servicio. Es lo que hace
    que una firma robada no sirva para nada manana."""
    clave = _hmac(f"AWS4{secreto}".encode("utf-8"), dia)
    clave = _hmac(clave, donde)
    clave = _hmac(clave, SERVICIO)
    return _hmac(clave, "aws4_request")


def pedido_canonico(metodo: str, ruta: str, consulta: dict,
                    cabeceras: dict, hash_cuerpo: str) -> tuple[str, str]:
    """El pedido escrito en la forma exacta que AWS va a hashear.

    Todo el algoritmo se apoya en que las dos partes armen este texto igual
    caracter por caracter: los parametros ordenados por nombre, las cabeceras
    en minuscula y ordenadas, los espacios de mas sacados. Devuelve el texto y
    la lista de cabeceras firmadas, que hay que repetir en la autorizacion."""
    partes_consulta = "&".join(
        f"{codificar(nombre)}={codificar(str(valor))}"
        for nombre, valor in sorted((consulta or {}).items())
    )
    nombres = sorted(nombre.lower() for nombre in cabeceras)
    firmadas = ";".join(nombres)
    lineas_cabeceras = "".join(
        f"{nombre}:{' '.join(str(cabeceras[nombre]).split())}\n" for nombre in nombres
    )
    canonico = "\n".join([
        metodo,
        codificar(ruta, barras=True),
        partes_consulta,
        lineas_cabeceras,
        firmadas,
        hash_cuerpo,
    ])
    return canonico, firmadas


def autorizacion(metodo: str, ruta: str, consulta: dict, cabeceras: dict,
                 hash_cuerpo: str, momento: str) -> str:
    """El valor de la cabecera Authorization para ese pedido."""
    clave, secreto, _ = credenciales()
    dia = momento[:8]
    alcance = f"{dia}/{region()}/{SERVICIO}/aws4_request"

    canonico, firmadas = pedido_canonico(metodo, ruta, consulta, cabeceras, hash_cuerpo)
    a_firmar = "\n".join([
        ALGORITMO,
        momento,
        alcance,
        hashlib.sha256(canonico.encode("utf-8")).hexdigest(),
    ])
    firma = hmac.new(clave_de_firma(secreto, dia, region()),
                     a_firmar.encode("utf-8"), hashlib.sha256).hexdigest()
    return (f"{ALGORITMO} Credential={clave}/{alcance}, "
            f"SignedHeaders={firmadas}, Signature={firma}")


# ----------------------------------------------------------------------
# El pedido
# ----------------------------------------------------------------------

def _ahora() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def pedir(metodo: str, ruta: str = "/", *, consulta=None, cuerpo=None,
          tipo=None, timeout=20) -> tuple[bytes, dict]:
    """Un pedido firmado a S3. Devuelve (cuerpo, cabeceras de la respuesta).

    Levanta ErrorDeS3 con el codigo HTTP si algo sale mal. El cuerpo del error
    de S3 es XML y trae el motivo real (credencial vencida, permiso que falta,
    bucket que no existe), asi que se lee antes de que se cierre: sin eso
    todos los errores parecen el mismo."""
    ruta = "/" + ruta.lstrip("/")
    momento = _ahora()
    _, _, sesion = credenciales()
    hash_cuerpo = hashlib.sha256(cuerpo).hexdigest() if cuerpo else CUERPO_VACIO

    cabeceras = {
        "host": anfitrion(),
        "x-amz-content-sha256": hash_cuerpo,
        "x-amz-date": momento,
    }
    if sesion:
        cabeceras["x-amz-security-token"] = sesion
    if tipo:
        cabeceras["content-type"] = tipo

    cabeceras["authorization"] = autorizacion(
        metodo, ruta, consulta or {}, cabeceras, hash_cuerpo, momento)

    url = f"https://{anfitrion()}{codificar(ruta, barras=True)}"
    if consulta:
        url += "?" + "&".join(f"{codificar(n)}={codificar(str(v))}"
                              for n, v in sorted(consulta.items()))

    pedido = urllib.request.Request(url, data=cuerpo, method=metodo)
    for nombre, valor in cabeceras.items():
        pedido.add_header(nombre, valor)

    donde = f"{metodo} s3://{bucket()}{ruta}"
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as respuesta:
            return respuesta.read(), dict(respuesta.headers)
    except urllib.error.HTTPError as error:
        try:
            detalle = error.read().decode("utf-8", "replace").strip()[:300]
        except OSError:
            detalle = ""
        raise ErrorDeS3(f"{donde} -> HTTP {error.code} {detalle}", error.code) from None
    except urllib.error.URLError as error:
        raise ErrorDeS3(f"{donde} -> no se pudo contactar a S3: {error.reason}") from None


# ----------------------------------------------------------------------
# Las operaciones, con la forma que espera almacenamiento.py
# ----------------------------------------------------------------------

def _sin_comillas(etag) -> str:
    """S3 devuelve el etag entre comillas y el resto del codigo no las espera."""
    return str(etag or "").strip().strip('"')


def _como_blob(clave: str, etag, fecha, tamano) -> dict:
    """Un archivo descrito igual que lo describia el Blob de Vercel.

    "url" es la clave y no una URL de verdad: el unico que la usa es este
    mismo modulo (para bajar y para borrar), porque los archivos se sirven
    siempre por /api/descargar y nunca por un link suelto. Guardar la clave
    ahi evita tener que firmar URLs temporales para nada."""
    return {
        "pathname": clave,
        "url": clave,
        "etag": _sin_comillas(etag),
        "uploadedAt": str(fecha or ""),
        "size": int(tamano or 0),
    }


def listar(prefijo: str) -> list[dict]:
    """Todo lo que hay bajo ese prefijo, paginando si hace falta."""
    encontrados, cursor = [], None
    while True:
        consulta = {"list-type": "2", "prefix": prefijo, "max-keys": "1000"}
        if cursor:
            consulta["continuation-token"] = cursor
        crudo, _ = pedir("GET", "/", consulta=consulta)
        arbol = ET.fromstring(crudo)

        for item in arbol.findall(f"{ESPACIO}Contents"):
            def texto(etiqueta):
                nodo = item.find(f"{ESPACIO}{etiqueta}")
                return nodo.text if nodo is not None else ""
            encontrados.append(_como_blob(texto("Key"), texto("ETag"),
                                          texto("LastModified"), texto("Size")))

        truncado = arbol.find(f"{ESPACIO}IsTruncated")
        siguiente = arbol.find(f"{ESPACIO}NextContinuationToken")
        if truncado is None or truncado.text != "true" or siguiente is None:
            return encontrados
        cursor = siguiente.text


def cabeza(clave: str) -> dict | None:
    """Los datos de un archivo sin bajarlo ni listar el bucket.

    Es la llamada que mas se repite del proyecto (en cada pedido se pregunta
    si la sesion en memoria sigue siendo la ultima). En S3 un HEAD cuesta lo
    mismo que un GET y una decima parte de un LIST.

    Devuelve None si el archivo no esta, que es normal al empezar."""
    try:
        _, cabeceras = pedir("HEAD", clave)
    except ErrorDeS3 as error:
        if error.codigo in (403, 404):
            # 403 y no 404 cuando el rol no tiene s3:ListBucket: S3 esconde la
            # diferencia entre "no existe" y "no te lo puedo decir"
            return None
        raise
    return _como_blob(clave, cabeceras.get("ETag"),
                      cabeceras.get("Last-Modified"), cabeceras.get("Content-Length"))


def subir(clave: str, contenido: bytes, tipo: str) -> dict:
    """Sube o pisa un archivo. Devuelve sus datos, con el etag de la subida.

    Que el etag venga en la respuesta es lo que evita una segunda llamada para
    saber con que version quedo, que es justo lo que hacia cara la carga."""
    _, cabeceras = pedir("PUT", clave, cuerpo=contenido, tipo=tipo, timeout=30)
    return _como_blob(clave, cabeceras.get("ETag"), _ahora(), len(contenido))


def bajar(clave: str) -> bytes:
    """El contenido de un archivo."""
    contenido, _ = pedir("GET", clave, timeout=30)
    return contenido


def borrar(clave: str) -> None:
    """Saca un archivo. S3 contesta 204 tambien si no estaba."""
    pedir("DELETE", clave)
