"""Punto de entrada en AWS Lambda.

Lambda no arranca `python servidor_voley.py`: importa este archivo y por cada
pedido llama a `handler(evento, contexto)` con el pedido convertido en un
diccionario. Hay que traducirlo a algo que entienda el manejador del proyecto,
que es un BaseHTTPRequestHandler de la biblioteca estandar.

La traduccion es mas facil de lo que parece porque un BaseHTTPRequestHandler
no necesita un socket: necesita dos archivos, uno para leer el pedido y otro
para escribir la respuesta. Se le pasan dos BytesIO con el pedido armado como
HTTP crudo, se lo deja contestar, y se lee lo que escribio. Es el mismo truco
que usa Vercel en `api/index.py`, solo que alla lo hace la plataforma.

Asi no hay una segunda implementacion de la API: el mismo `Manejador` atiende
en casa, en Vercel y aca.

En Lambda la configuracion va toda por variables de entorno:

    VOLEY_S3_BUCKET     el bucket donde vive todo (lo que prende S3)
    VOLEY_CLAVE         la contraseña para cargar
    VOLEY_SECRETO       opcional, firma los tokens de la pantalla

Las credenciales de AWS las pone sola la plataforma desde el rol de la
funcion, y rotan cada pocas horas. No hay que escribir ninguna.
"""
import base64
import io

from servidor_voley import Manejador

# Lo que se puede mandar como texto. Todo lo demas (los .xlsx) viaja en base64,
# porque la respuesta de Lambda es JSON y ahi no entran bytes crudos.
TEXTO = ("application/json", "text/", "application/javascript", "image/svg")


class _UnPedido(Manejador):
    """El manejador de siempre, atendiendo un pedido que vino de Lambda.

    Se saltea el __init__ de BaseHTTPRequestHandler a proposito: ese espera un
    socket y se encarga de abrirlo y cerrarlo. Aca los dos extremos ya estan
    listos, asi que se llama derecho a handle_one_request(), que es la parte
    que lee el pedido y llama a do_GET o do_POST."""

    def __init__(self, crudo: bytes):
        self.rfile = io.BytesIO(crudo)
        self.wfile = io.BytesIO()
        self.connection = None
        self.server = None
        self.client_address = ("lambda", 0)
        self.handle_one_request()

    @property
    def respuesta(self) -> bytes:
        return self.wfile.getvalue()


def _pedido_crudo(evento: dict) -> bytes:
    """El evento de Lambda escrito como un pedido HTTP de verdad."""
    http = (evento.get("requestContext") or {}).get("http") or {}
    metodo = http.get("method", "GET")
    ruta = evento.get("rawPath") or http.get("path") or "/"
    consulta = evento.get("rawQueryString") or ""
    if consulta:
        ruta = f"{ruta}?{consulta}"

    cuerpo = evento.get("body") or ""
    cuerpo = (base64.b64decode(cuerpo) if evento.get("isBase64Encoded")
              else cuerpo.encode("utf-8"))

    # el content-length se recalcula: el que venga en el evento puede no
    # coincidir si el cuerpo viajo en base64, y el manejador lee de ahi
    # cuantos bytes tiene que consumir
    cabeceras = {clave: valor for clave, valor in (evento.get("headers") or {}).items()
                 if clave.lower() not in ("content-length", "connection")}
    cabeceras["content-length"] = str(len(cuerpo))
    cabeceras["connection"] = "close"

    lineas = [f"{metodo} {ruta} HTTP/1.1"]
    lineas += [f"{clave}: {valor}" for clave, valor in cabeceras.items()]
    return ("\r\n".join(lineas) + "\r\n\r\n").encode("utf-8") + cuerpo


def _partir(crudo: bytes) -> tuple[int, dict, bytes]:
    """Parte la respuesta HTTP en (codigo, cabeceras, cuerpo)."""
    cabeza, _, cuerpo = crudo.partition(b"\r\n\r\n")
    lineas = cabeza.split(b"\r\n")
    partes = lineas[0].split(None, 2) if lineas and lineas[0] else []
    codigo = int(partes[1]) if len(partes) > 1 else 500

    cabeceras = {}
    for linea in lineas[1:]:
        nombre, separador, valor = linea.partition(b":")
        if separador:
            cabeceras[nombre.decode("latin-1").strip()] = valor.decode("latin-1").strip()
    return codigo, cabeceras, cuerpo


def handler(evento: dict, contexto=None) -> dict:
    """Lo que llama Lambda. Devuelve la respuesta con el formato que espera."""
    atendido = _UnPedido(_pedido_crudo(evento))
    codigo, cabeceras, cuerpo = _partir(atendido.respuesta)

    tipo = cabeceras.get("Content-Type", cabeceras.get("content-type", ""))
    es_texto = any(tipo.startswith(bueno) for bueno in TEXTO)

    return {
        "statusCode": codigo,
        "headers": cabeceras,
        "body": (cuerpo.decode("utf-8", "replace") if es_texto
                 else base64.b64encode(cuerpo).decode("ascii")),
        "isBase64Encoded": not es_texto,
    }
