"""
Interfaz web para cargar partidos.

    python servidor_voley.py

Levanta un servidor local y abre el navegador. Como escucha en toda la red,
desde el celular o la tablet se entra con la IP que imprime al arrancar,
siempre que esten en la misma WiFi.

El mismo manejador atiende el sitio alojado en Vercel: ahi no corre este main()
sino api/index.py, que importa la clase Manejador y deja que Vercel la
instancie por cada pedido (ver DESPLIEGUE.md). Lo que cambia alojado no es la
API sino donde estan los archivos y donde vive el estado:

  - la carpeta del proyecto es de solo lectura, asi que Datos/ e Informes/ se
    escriben en otro lado y se publican en Vercel Blob (ver almacenamiento.py);
  - dos pedidos seguidos pueden caer en dos procesos distintos, asi que ni el
    partido en curso ni los tokens pueden vivir en una variable de modulo.

Usa solo la biblioteca estandar; el motor es el mismo analisis_voley.py que la
consola. openpyxl hace falta unicamente para el Excel: generarlo o mirarlo
desde la pestana Partidos.

La pagina (public/index.html + .css + .js) sale de una lista blanca; nunca se
sirve la carpeta del proyecto. Alojado la sirve Vercel directamente desde
public/, que es la unica carpeta que publica: por eso los .py del proyecto,
que estan afuera, no se pueden bajar.

Cargar pide la contraseña de analisis_voley (la misma de la consola). Se
escribe una vez por pestana: el servidor devuelve un token que el navegador
manda despues en la cabecera X-Clave. Mirar partidos, informes y jugadores no
pide nada; lo unico que se protege es escribir sobre el partido en curso.
    POST /api/clave                 valida la contraseña y da el token
    GET  /api/sesion                dice si el token que mando sigue valiendo

Endpoints del partido en curso, que si toman el candado de la sesion. Los
POST piden el token de /api/clave:
    GET  /api/estado /api/estadisticas
    POST /api/enviar /api/deshacer /api/reiniciar /api/cargar
         /api/guardar /api/excel

Endpoints de los partidos archivados. Son de solo lectura y no tocan la
sesion, para que mirar un informe no interrumpa la carga en la cancha:
    GET  /api/partidos              listado de Datos/*.txt e Informes/*.xlsx
    GET  /api/partido?archivo=      un volcado entero, ya parseado
    GET  /api/informe?archivo=      un .xlsx como hojas y filas de texto
    GET  /api/descargar?archivo=&tipo=txt|xlsx
    POST /api/abrir                 lo abre con Excel en esta maquina (solo
                                    tiene sentido corriendo en una PC propia)
"""
import argparse
import hashlib
import hmac
import json
import os
import socket
import threading
import time
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote, parse_qs, urlsplit

import almacenamiento as alm
import analisis_voley as av
import archivo_partidos as arch
from sesion_web import SesionPartido

CARPETA = Path(__file__).resolve().parent

# La pagina vive en public/ y no en la raiz. Es la carpeta que Vercel publica
# como sitio estatico, y que ahi sea la unica publicada es lo que evita que los
# .py del proyecto (con la clave adentro) se puedan bajar como si fueran
# archivos mas. Corriendo en casa las sirve este servidor y las URL son las
# mismas, asi que la pagina no se entera de en cual de los dos esta.
PUBLICO = CARPETA / "public"
PAGINA = PUBLICO / "index.html"

# Lista blanca de lo que se sirve. La pagina se partio en tres archivos para
# poder mantenerla, pero eso no significa publicar un directorio: cualquier
# otra ruta es un 404.
ESTATICOS = {
    "/": (PAGINA, "text/html"),
    "/index.html": (PAGINA, "text/html"),
    "/interfaz.css": (PUBLICO / "interfaz.css", "text/css"),
    "/interfaz.js": (PUBLICO / "interfaz.js", "application/javascript"),
}

# Una sola partida a la vez: es una herramienta de escritorio, no un servicio.
# El lock alcanza porque cada pedido rehace el partido entero y es cortito.
sesion = SesionPartido()
candado = threading.Lock()

# Alojado, "el servidor" no es un proceso sino muchos que van y vienen, y dos
# pedidos seguidos pueden caer en dos instancias distintas. La sesion se
# guarda entonces afuera (ver almacenamiento) y cada instancia se pone al dia
# antes de contestar. En una maquina propia esto sobra y queda apagado.
PERSISTIR_SESION = alm.EN_SERVERLESS or alm.hay_blob()
version_de_la_sesion = ""

# Escribir sobre el partido en curso pide el token; leer no. Asi se puede
# seguir el marcador o mirar un informe desde cualquier celular de la tribuna,
# pero cargar la jugada solo desde el que sabe la clave.
RUTAS_CON_CLAVE = {
    "/api/enviar", "/api/deshacer", "/api/reiniciar",
    "/api/cargar", "/api/guardar", "/api/excel",
}


# El token no se guarda en ningun lado: se firma con una clave que sale del
# entorno y se verifica con la misma cuenta. Antes era un secreto random en un
# set en memoria, que alojado no sirve (la instancia que lo emitio no es la que
# recibe el pedido siguiente) y ademas obligaria a compartir ese set.
HORAS_DE_TOKEN = 12


def _secreto() -> bytes:
    """Con que se firman los tokens.

    VOLEY_SECRETO si esta; si no, la contraseña de carga, que ya es un secreto
    del servidor. Poner VOLEY_SECRETO en Vercel hace que cambiar la clave no
    invalide los tokens, y al reves."""
    return (os.environ.get("VOLEY_SECRETO") or av.CONTRASENA_CARGA).encode("utf-8")


def _firma(vence: str) -> str:
    return hmac.new(_secreto(), vence.encode("utf-8"), hashlib.sha256).hexdigest()


def abrir_sesion(clave) -> dict:
    """Valida la contraseña y entrega el token de la pantalla que acerto."""
    if not av.contraseña_valida(clave):
        time.sleep(1)      # un intento por segundo: no se prueban claves a mano
        return {"ok": False, "mensaje": "Contraseña incorrecta."}
    vence = str(int(time.time()) + HORAS_DE_TOKEN * 3600)
    return {"ok": True, "token": f"{vence}.{_firma(vence)}",
            "mensaje": "Listo, ya podes cargar."}


def token_valido(token) -> bool:
    vence, _, firma = str(token or "").partition(".")
    if not firma or not vence.isdigit():
        return False
    # compare_digest y no ==: la firma la manda el cliente
    if not hmac.compare_digest(firma, _firma(vence)):
        return False
    return time.time() < int(vence)


def sesion_al_dia() -> SesionPartido:
    """La sesion con las ultimas lineas, vengan de donde vengan.

    Sin persistencia devuelve la de siempre. Con persistencia se compara la
    version guardada contra la que tiene esta instancia y solo se rehace el
    partido si cambio, que es lo caro."""
    global version_de_la_sesion
    if not PERSISTIR_SESION:
        return sesion
    version = alm.version_de_sesion()
    if version and version != version_de_la_sesion:
        guardada = alm.leer_sesion()
        if guardada is not None:
            lineas, version_de_la_sesion = guardada
            sesion.reemplazar(lineas)
    return sesion


def anotar_sesion() -> None:
    """Guarda las lineas despues de un cambio, para la proxima instancia."""
    global version_de_la_sesion
    if not PERSISTIR_SESION:
        return
    alm.guardar_sesion(sesion.lineas)
    version_de_la_sesion = alm.version_de_sesion()


def ip_en_la_red() -> str:
    """IP de esta maquina en la LAN, para entrar desde el celular."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))     # no manda nada, solo elige la placa
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def generar_excel(nombre_txt: str, equipo: str) -> str:
    """Arma el Excel del volcado recien guardado."""
    import generar_informe_volley as gi

    with open(nombre_txt, encoding="utf-8") as archivo:
        volcado = gi.parse_volcado(archivo.read())
    if equipo not in volcado["teams"]:
        raise ValueError(f"El equipo {equipo} no aparece en el volcado.")

    rival = next((n for n in volcado["teams"] if n != equipo), "Rival")
    libro, avisos = gi.build_workbook(equipo, rival, volcado)
    fecha = gi.guess_fecha_from_filename(nombre_txt) or f"{datetime.now():%Y-%m-%d}"
    salida = av.carpeta_lista(av.CARPETA_INFORMES) / f"Informe_{equipo}_vs_{rival}_{fecha}.xlsx"
    archivo, _ = gi.guardar_informe(libro, salida)
    return archivo


# ----------------------------------------------------------------------
# Lecturas de disco. Van aca afuera y devuelven datos, sin tocar la sesion ni
# el candado: navegar por los partidos guardados no puede frenar la carga en
# vivo, que es lo unico que tiene que ser rapido.
# ----------------------------------------------------------------------

def responder_jugadores() -> dict:
    """Los equipos con su plantel. Se recalcula en cada pedido a partir de los
    volcados: son milisegundos, y asi no hay numeros guardados que se puedan
    desactualizar cuando se borra o se recarga un partido."""
    import estadisticas_jugadores as ej
    return {"ok": True, **ej.listado()}


def responder_jugador(equipo: str, dorsal: str) -> dict:
    import estadisticas_jugadores as ej
    ficha = ej.ficha(equipo, dorsal)
    if ficha is None:
        return {"ok": False, "mensaje": f"No hay datos del {dorsal} en {equipo}."}
    return {"ok": True, "jugador": ficha}


def responder_partidos() -> dict:
    return {"ok": True, "partidos": arch.listar_partidos()}


def responder_partido(nombre: str) -> dict:
    ruta, _ = arch.ruta_de_tipo(nombre, "txt")
    return {"ok": True, "partido": arch.leer_partido(ruta)}


def responder_informe(nombre: str) -> dict:
    ruta, _ = arch.ruta_de_tipo(nombre, "xlsx")
    return {"ok": True, "informe": arch.leer_informe(ruta)}


def abrir_en_el_escritorio(nombre: str, tipo: str | None = None) -> dict:
    """Abre el archivo con la aplicacion del sistema, en la maquina donde
    corre el servidor. Sirve para pasar del informe en la web al Excel de
    verdad sin buscarlo en la carpeta."""
    if alm.EN_SERVERLESS:
        # Aca "esta PC" es un contenedor en un datacenter: no hay Excel ni
        # pantalla. Descargar el archivo es lo que corresponde.
        return {"ok": False, "descargar": True,
                "mensaje": "El sitio no corre en una PC: descarga el archivo."}
    ruta, _ = arch.ruta_de_tipo(nombre, tipo)
    if not ruta.exists():
        return {"ok": False, "mensaje": f"No existe {ruta.name}."}
    if not hasattr(os, "startfile"):      # startfile es solo de Windows
        return {"ok": False, "mensaje": "Abrir el archivo en el escritorio "
                                        "solo funciona en Windows."}
    os.startfile(ruta)                    # noqa: S606  (ruta ya validada)
    return {"ok": True, "mensaje": f"Se abrio {ruta.name} en esta PC."}


class Manejador(BaseHTTPRequestHandler):

    def log_message(self, formato, *args):
        pass      # sin ruido en la consola

    # ------------------------------------------------------------------
    def _responder(self, datos, codigo=200, tipo="application/json"):
        cuerpo = (json.dumps(datos, ensure_ascii=False) if tipo == "application/json"
                  else datos).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", f"{tipo}; charset=utf-8")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _responder_bytes(self, cuerpo: bytes, tipo: str, nombre_descarga=None):
        self.send_response(200)
        self.send_header("Content-Type", tipo)
        if nombre_descarga:
            # filename* con la version codificada porque hay informes con
            # apostrofos y acentos en el nombre (Informe_..._vs_O'sommer_...)
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''" + quote(nombre_descarga))
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _leer_json(self) -> dict:
        largo = int(self.headers.get("Content-Length") or 0)
        if not largo:
            return {}
        return json.loads(self.rfile.read(largo).decode("utf-8"))

    # ------------------------------------------------------------------
    def do_GET(self):
        partes = urlsplit(self.path)
        ruta = partes.path
        consulta = {clave: valores[0]
                    for clave, valores in parse_qs(partes.query).items()}

        estatico = ESTATICOS.get(ruta)
        if estatico is not None:
            archivo, tipo = estatico
            if not archivo.exists():
                return self._responder(f"Falta {archivo.name}", 500, "text/plain")
            return self._responder(archivo.read_text(encoding="utf-8"), tipo=tipo)

        if ruta == "/api/sesion":
            return self._responder({"ok": True,
                                    "autorizado": token_valido(self.headers.get("X-Clave"))})

        if ruta == "/api/estado":
            with candado:
                return self._responder({"ok": True,
                                        "estado": sesion_al_dia().instantanea(),
                                        "almacenamiento": alm.estado()})

        if ruta == "/api/estadisticas":
            with candado:
                return self._responder({"ok": True, "texto": sesion_al_dia().estadisticas()})

        if ruta == "/api/descargar":
            return self._descargar(consulta)

        lecturas = {
            "/api/partidos": lambda: responder_partidos(),
            "/api/partido": lambda: responder_partido(consulta.get("archivo", "")),
            "/api/informe": lambda: responder_informe(consulta.get("archivo", "")),
            "/api/jugadores": lambda: responder_jugadores(),
            "/api/jugador": lambda: responder_jugador(consulta.get("equipo", ""),
                                                      consulta.get("dorsal", "")),
        }
        if ruta in lecturas:
            datos, codigo = self._leer_de_disco(lecturas[ruta])
            return self._responder(datos, codigo)

        self._responder({"ok": False, "mensaje": "No existe"}, 404)

    def _leer_de_disco(self, tarea):
        """Corre una lectura de disco traduciendo cada falla al mensaje que
        corresponde. Se agrupan aca porque las cuatro fallan igual: nombre
        invalido, archivo que no esta, o el .xlsx abierto en Excel."""
        try:
            return tarea(), 200
        except arch.RutaInvalida as error:
            return {"ok": False, "mensaje": str(error)}, 400
        except FileNotFoundError as error:
            return {"ok": False, "mensaje": f"No existe: {Path(str(error.filename or '')).name}"}, 404
        except arch.FaltaOpenpyxl:
            return {"ok": False, "mensaje": arch.MENSAJE_SIN_OPENPYXL}, 200
        except PermissionError:
            return {"ok": False, "mensaje": arch.MENSAJE_ARCHIVO_ABIERTO}, 200
        except Exception as error:      # que un archivo raro no tumbe el servidor
            return {"ok": False, "mensaje": f"{type(error).__name__}: {error}"}, 500

    def _descargar(self, consulta: dict):
        try:
            ruta, tipo = arch.ruta_de_tipo(consulta.get("archivo", ""),
                                           consulta.get("tipo"))
            cuerpo = ruta.read_bytes()
        except arch.RutaInvalida as error:
            return self._responder({"ok": False, "mensaje": str(error)}, 400)
        except FileNotFoundError:
            return self._responder({"ok": False, "mensaje": "No existe ese archivo"}, 404)
        except PermissionError:
            return self._responder({"ok": False, "mensaje": arch.MENSAJE_ARCHIVO_ABIERTO}, 200)
        self._responder_bytes(cuerpo, arch.MIME_POR_TIPO[tipo], ruta.name)

    def do_POST(self):
        try:
            datos = self._leer_json()
        except json.JSONDecodeError:
            return self._responder({"ok": False, "mensaje": "JSON invalido"}, 400)

        ruta = urlsplit(self.path).path
        if ruta == "/api/clave":
            # fuera del candado de la sesion: el segundo de castigo por clave
            # errada no puede frenar al que esta cargando el partido
            return self._responder(abrir_sesion(datos.get("clave", "")))

        if ruta in RUTAS_CON_CLAVE and not token_valido(self.headers.get("X-Clave")):
            # "clave": True es la senal para que la pantalla vuelva a pedirla
            return self._responder({"ok": False, "clave": True,
                                    "mensaje": "Hace falta la contraseña para cargar."}, 401)

        if ruta == "/api/abrir":
            # no toca la sesion, asi que tampoco toma el candado: si alguien
            # esta cargando un punto no tiene por que esperar a que abra Excel
            respuesta, codigo = self._leer_de_disco(
                lambda: abrir_en_el_escritorio(datos.get("archivo", ""), datos.get("tipo")))
            return self._responder(respuesta, codigo)

        with candado:
            try:
                antes = list(sesion_al_dia().lineas)
                respuesta = self._despachar(ruta, datos)
                # se compara contra las lineas de antes y no contra el "ok" de
                # la respuesta: una carga que se corta a la mitad deja la
                # sesion cambiada aunque conteste que no, y una linea que el
                # motor rechaza no la cambia aunque la ruta sea de escritura
                if sesion.lineas != antes:
                    anotar_sesion()
            except Exception as error:      # que un error no tumbe el servidor
                respuesta = {"ok": False, "mensaje": f"{type(error).__name__}: {error}",
                             "estado": sesion.instantanea()}
        if respuesta is None:
            return self._responder({"ok": False, "mensaje": "No existe"}, 404)
        self._responder(respuesta)

    def _despachar(self, ruta: str, datos: dict):
        if ruta == "/api/enviar":
            return sesion.enviar(datos.get("linea", ""))
        if ruta == "/api/deshacer":
            return sesion.deshacer_linea()
        if ruta == "/api/reiniciar":
            return sesion.reiniciar()
        if ruta == "/api/cargar":
            return sesion.cargar_lineas(datos.get("texto", ""))
        if ruta == "/api/guardar":
            nombre = sesion.guardar()
            return {"ok": True, "mensaje": f"Guardado: {nombre}",
                    "archivo": Path(nombre).name, "tipo": "txt",
                    "estado": sesion.instantanea()}
        if ruta == "/api/excel":
            nombre_txt = sesion.guardar()
            equipo = datos.get("equipo") or sesion.estado["nombres"]["A"]
            try:
                excel = generar_excel(nombre_txt, equipo)
            except ImportError:
                return {"ok": False, "mensaje": arch.MENSAJE_SIN_OPENPYXL,
                        "estado": sesion.instantanea()}
            except PermissionError:
                return {"ok": False, "mensaje": arch.MENSAJE_ARCHIVO_ABIERTO,
                        "estado": sesion.instantanea()}
            # el nombre suelto ademas del mensaje: con eso la pantalla arma el
            # enlace para abrir o descargar el informe sin copiar la ruta
            return {"ok": True, "mensaje": f"Generado: {excel} (volcado: {nombre_txt})",
                    "archivo": Path(excel).name, "tipo": "xlsx",
                    "volcado": Path(nombre_txt).name, "estado": sesion.instantanea()}
        return None


def main():
    parser = argparse.ArgumentParser(description="Interfaz web para cargar partidos de voley.")
    parser.add_argument("--puerto", type=int, default=8000)
    parser.add_argument("--solo-local", action="store_true",
                        help="escuchar unicamente en esta maquina (no se ve desde el celular)")
    parser.add_argument("--sin-navegador", action="store_true")
    args = parser.parse_args()

    host = "127.0.0.1" if args.solo_local else "0.0.0.0"
    servidor = ThreadingHTTPServer((host, args.puerto), Manejador)

    print("=== Estadisticas de voley ===")
    print(f"  En esta PC:   http://localhost:{args.puerto}")
    if not args.solo_local:
        print(f"  En la WiFi:   http://{ip_en_la_red()}:{args.puerto}   (celular / tablet)")
    print("\n  Ctrl+C para cerrar.\n")

    if not args.sin_navegador:
        threading.Timer(0.6, webbrowser.open, [f"http://localhost:{args.puerto}"]).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nCerrado.")
    finally:
        servidor.server_close()


if __name__ == "__main__":
    main()
