"""Servidor local de las pantallas de video: inicio, revision y galeria.

    python -m video servir            ->  http://127.0.0.1:8001

Escucha solo en 127.0.0.1: es para esta maquina, y por eso no pide
contrasena, a diferencia de la carga de partidos. Igual hay dos defensas,
porque cualquier pagina abierta en el navegador puede mandarle pedidos a
localhost:
  - el encabezado Host tiene que ser 127.0.0.1 o localhost. Corta el "DNS
    rebinding": un dominio ajeno que resuelve a 127.0.0.1 para leer de aca;
  - lo que escribe pide Content-Type application/json, que una pagina de otro
    sitio no puede mandar sin preguntar antes por CORS, y aca CORS no se
    contesta.

Que se sirve, igual que en servidor_voley: una lista blanca. Las paginas de
video/web/ por nombre, y de cada video solo su proxy, buscando el proyecto
por su nombre validado. Nunca se arma una ruta con lo que trae el pedido.

El video se sirve por rangos (Range -> 206 Partial Content): sin eso el
navegador no puede saltar a la mitad del partido y la revision no sirve.

Deshacer vive aca y no en decisiones.py: es la lista de revisiones
anteriores, en memoria, de esta sesion del servidor. Cerrar el servidor la
borra; lo guardado queda.
"""
from __future__ import annotations

import json
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from . import decisiones, fusion, proyecto

PUERTO = 8001
WEB = Path(__file__).resolve().parent / "web"
HTML = "text/html; charset=utf-8"
JS = "application/javascript; charset=utf-8"

PAGINAS = {
    "/": ("inicio.html", HTML),
    "/inicio.html": ("inicio.html", HTML),
    "/revision.html": ("revision.html", HTML),
    "/galeria.html": ("galeria.html", HTML),
    "/video.css": ("video.css", "text/css; charset=utf-8"),
    "/comun.js": ("comun.js", JS),
    "/inicio.js": ("inicio.js", JS),
    "/revision.js": ("revision.js", JS),
    "/galeria.js": ("galeria.js", JS),
}

RUTA_DEL_PROXY = re.compile(r"^/videos/([a-z0-9-]+)/proxy\.mp4$")
RUTA_DEL_VIDEO = re.compile(r"^/api/videos/([a-z0-9-]+)$")
RUTA_DE_OPERAR = re.compile(r"^/api/videos/([a-z0-9-]+)/operar$")

HOSTS_PERMITIDOS = {"127.0.0.1", "localhost"}
MAXIMO_DEL_PEDIDO = 1024 * 1024
BLOQUE = 256 * 1024
HISTORIAL_MAXIMO = 200

# Lo que devuelve leer_rango cuando el pedido cae afuera del archivo.
FUERA = "fuera"


def leer_rango(encabezado: str | None, tamano: int):
    """'bytes=100-199' -> (100, 199). None si no se entiende (el estandar dice
    ignorarlo y mandar todo); FUERA si empieza despues del final."""
    coincide = re.fullmatch(r"\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*", encabezado or "")
    if not coincide or not (coincide.group(1) or coincide.group(2)):
        return None
    desde, hasta = coincide.group(1), coincide.group(2)
    if desde:
        inicio = int(desde)
        fin = int(hasta) if hasta else tamano - 1
        if inicio >= tamano:
            return FUERA
        if fin < inicio:
            return None
        return inicio, min(fin, tamano - 1)
    # "bytes=-500": los ultimos 500
    ultimos = int(hasta)
    if ultimos == 0 or tamano == 0:
        return FUERA
    return max(0, tamano - ultimos), tamano - 1


class Servidor(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, direccion, carpeta: Path = proyecto.CARPETA_VIDEOS):
        super().__init__(direccion, Manejador)
        self.carpeta = Path(carpeta)
        # una sola escritura a la vez: leer, aplicar y guardar tienen que ir
        # juntos o dos pedidos seguidos se pisan
        self.candado = threading.Lock()
        self.historial: dict[str, list[dict]] = {}


class Manejador(BaseHTTPRequestHandler):
    server_version = "VideoVoley/1"

    def log_message(self, formato, *args):
        pass

    # ------------------------------------------------------------------
    def _host_valido(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        return host.rsplit(":", 1)[0] in HOSTS_PERMITIDOS

    def _json(self, datos: dict, codigo: int = 200) -> None:
        cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _error(self, mensaje: str, codigo: int) -> None:
        self._json({"ok": False, "mensaje": mensaje}, codigo)

    def _proyecto(self, nombre: str) -> proyecto.Proyecto:
        return proyecto.abrir(nombre, self.server.carpeta)

    # ------------------------------------------------------------------
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if not self._host_valido():
            return self._error("Host no permitido.", 403)
        ruta = urlsplit(self.path).path
        try:
            if ruta in PAGINAS:
                return self._pagina(*PAGINAS[ruta])
            coincide = RUTA_DEL_PROXY.match(ruta)
            if coincide:
                return self._archivo(self._proyecto(coincide.group(1)).ruta_proxy, "video/mp4")
            if ruta == "/api/videos":
                return self._json({"ok": True, "videos": [
                    self._resumen(p) for p in proyecto.listar(self.server.carpeta)]})
            if ruta == "/api/armadas":
                return self._json(self._aceptadas_de_todos())
            coincide = RUTA_DEL_VIDEO.match(ruta)
            if coincide:
                return self._json(self._estado(self._proyecto(coincide.group(1))))
        except proyecto.NoExiste as error:
            return self._error(str(error), 404)
        except proyecto.ErrorDeProyecto as error:
            return self._error(str(error), 500)
        return self._error("No existe.", 404)

    def do_POST(self):
        if not self._host_valido():
            return self._error("Host no permitido.", 403)
        tipo = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if tipo != "application/json":
            return self._error("Se espera un pedido en JSON.", 415)
        coincide = RUTA_DE_OPERAR.match(urlsplit(self.path).path)
        if not coincide:
            return self._error("No existe.", 404)
        nombre = coincide.group(1)
        try:
            return self._json(self._operar(nombre, self._leer_json()))
        except proyecto.Desactualizado as error:
            # se manda la revision de ahora para que la pantalla se ponga al dia
            return self._json({**self._estado(self._proyecto(nombre)),
                               "ok": False, "conflicto": True, "mensaje": str(error)}, 409)
        except decisiones.OperacionInvalida as error:
            return self._error(str(error), 400)
        except proyecto.NoExiste as error:
            return self._error(str(error), 404)
        except proyecto.ErrorDeProyecto as error:
            return self._error(str(error), 500)

    # ------------------------------------------------------------------
    def _leer_json(self) -> dict:
        try:
            largo = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            largo = -1
        if largo <= 0 or largo > MAXIMO_DEL_PEDIDO:
            raise decisiones.OperacionInvalida("Pedido vacio o demasiado grande.")
        try:
            datos = json.loads(self.rfile.read(largo).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise decisiones.OperacionInvalida("El pedido no es JSON valido.") from None
        if not isinstance(datos, dict):
            raise decisiones.OperacionInvalida("El pedido tiene que ser un objeto.")
        return datos

    def _pagina(self, archivo: str, tipo: str) -> None:
        try:
            cuerpo = (WEB / archivo).read_bytes()
        except FileNotFoundError:
            return self._error(f"Falta {archivo}.", 500)
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        # que un cambio en el codigo se vea con solo recargar
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(cuerpo)

    def _archivo(self, ruta: Path, tipo: str) -> None:
        try:
            tamano = ruta.stat().st_size
        except FileNotFoundError:
            return self._error("Este video todavia no tiene proxy: "
                               "corre python -m video nuevo.", 404)
        inicio, fin, codigo = 0, tamano - 1, 200
        if self.headers.get("Range"):
            rango = leer_rango(self.headers.get("Range"), tamano)
            if rango == FUERA:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{tamano}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if rango is not None:
                (inicio, fin), codigo = rango, 206
        largo = max(0, fin - inicio + 1)

        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(largo))
        if codigo == 206:
            self.send_header("Content-Range", f"bytes {inicio}-{fin}/{tamano}")
        self.end_headers()
        if self.command == "HEAD":
            return
        try:
            with open(ruta, "rb") as archivo:
                archivo.seek(inicio)
                quedan = largo
                while quedan > 0:
                    trozo = archivo.read(min(BLOQUE, quedan))
                    if not trozo:
                        break
                    self.wfile.write(trozo)
                    quedan -= len(trozo)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # el navegador corta el pedido cada vez que se salta a otro lado
            # del video: no es un error
            pass

    # ------------------------------------------------------------------
    def _datos_del_video(self, p: proyecto.Proyecto, fuente: dict) -> dict:
        return {"nombre": p.nombre, "titulo": fuente.get("titulo") or p.nombre,
                "duracion": fuente.get("duracion"), "fps": fuente.get("fps"),
                "ancho": fuente.get("ancho"), "alto": fuente.get("alto"),
                "hay_proxy": p.hay_proxy()}

    def _estado(self, p: proyecto.Proyecto, revision: dict | None = None) -> dict:
        fuente = p.fuente()
        revision = revision if revision is not None else p.revision()
        armadas = fusion.fusionar(p.propuestas(), revision, fuente.get("duracion"))
        return {"ok": True, "video": self._datos_del_video(p, fuente),
                "edicion": revision.get("edicion", 0), "sets": revision.get("sets", []),
                "armadas": armadas,
                "se_puede_deshacer": bool(self.server.historial.get(p.nombre))}

    def _resumen(self, p: proyecto.Proyecto) -> dict:
        try:
            estado = self._estado(p)
        except proyecto.ErrorDeProyecto as error:
            # un video roto no tapa a los demas
            return {"nombre": p.nombre, "titulo": p.nombre, "error": str(error)}
        cuentas = {"aceptada": 0, "pendiente": 0, "descartada": 0}
        for armada in estado["armadas"]:
            cuentas[armada["estado"]] += 1
        return {**estado["video"], "cuentas": cuentas, "sets": len(estado["sets"])}

    def _aceptadas_de_todos(self) -> dict:
        videos, armadas, errores = {}, [], []
        for p in proyecto.listar(self.server.carpeta):
            try:
                estado = self._estado(p)
            except proyecto.ErrorDeProyecto as error:
                errores.append(f"{p.nombre}: {error}")
                continue
            videos[p.nombre] = estado["video"]
            armadas += [{**a, "video": p.nombre} for a in estado["armadas"]
                        if a["estado"] == "aceptada"]
        return {"ok": True, "videos": videos, "armadas": armadas, "errores": errores}

    def _operar(self, nombre: str, cuerpo: dict) -> dict:
        op, edicion = cuerpo.get("op"), cuerpo.get("edicion")
        if not isinstance(edicion, int) or isinstance(edicion, bool):
            raise decisiones.OperacionInvalida("Falta la edicion que tenia la pantalla.")
        with self.server.candado:
            p = self._proyecto(nombre)
            revision = p.revision()
            if revision.get("edicion", 0) != edicion:
                raise proyecto.Desactualizado(
                    "La revision cambio desde otra pestana: recargue la ultima version.")
            historial = self.server.historial.setdefault(nombre, [])
            if isinstance(op, dict) and op.get("tipo") == "deshacer":
                if not historial:
                    raise decisiones.OperacionInvalida("No hay nada para deshacer.")
                guardada = p.guardar_revision(historial.pop(), edicion)
                clave = None
            else:
                duracion = p.fuente().get("duracion")
                nueva, clave, _ = decisiones.aplicar(revision, p.propuestas(), op, duracion)
                guardada = p.guardar_revision(nueva, edicion)
                historial.append(revision)
                del historial[:-HISTORIAL_MAXIMO]
            return {**self._estado(p, guardada), "clave": clave}


def servir(puerto: int = PUERTO, abrir_navegador: bool = True,
           carpeta: Path = proyecto.CARPETA_VIDEOS) -> int:
    try:
        servidor = Servidor(("127.0.0.1", puerto), carpeta)
    except OSError as error:
        print(f"No pude abrir el puerto {puerto} ({error}). Ya hay otro servidor "
              f"abierto? Proba con --puerto {puerto + 1}.")
        return 1
    url = f"http://127.0.0.1:{puerto}"
    print("=== Analisis de video ===")
    print(f"  Abrilo en:  {url}")
    print(f"  Videos en:  {Path(carpeta)}")
    print("\n  Ctrl+C para cerrar.\n")
    if abrir_navegador:
        threading.Timer(0.6, webbrowser.open, [url]).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")
    finally:
        servidor.server_close()
    return 0
