"""
Interfaz web para cargar partidos.

    python servidor_voley.py

Levanta un servidor local y abre el navegador. Como escucha en toda la red,
desde el celular o la tablet se entra con la IP que imprime al arrancar,
siempre que esten en la misma WiFi.

Usa solo la biblioteca estandar; el motor es el mismo analisis_voley.py que la
consola. openpyxl hace falta unicamente para el Excel: generarlo o mirarlo
desde la pestana Partidos.

La pagina (interfaz.html + .css + .js) sale de una lista blanca; nunca se
sirve la carpeta del proyecto.

Endpoints del partido en curso, que si toman el candado de la sesion:
    GET  /api/estado /api/estadisticas
    POST /api/enviar /api/deshacer /api/reiniciar /api/cargar
         /api/guardar /api/excel

Endpoints de los partidos archivados. Son de solo lectura y no tocan la
sesion, para que mirar un informe no interrumpa la carga en la cancha:
    GET  /api/partidos              listado de Datos/*.txt e Informes/*.xlsx
    GET  /api/partido?archivo=      un volcado entero, ya parseado
    GET  /api/informe?archivo=      un .xlsx como hojas y filas de texto
    GET  /api/descargar?archivo=&tipo=txt|xlsx
    POST /api/abrir                 lo abre con Excel en esta maquina
"""
import argparse
import json
import os
import socket
import threading
import webbrowser
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote, parse_qs, urlsplit

import analisis_voley as av
import archivo_partidos as arch
from sesion_web import SesionPartido

CARPETA = Path(__file__).resolve().parent
PAGINA = CARPETA / "interfaz.html"

# Lista blanca de lo que se sirve de la carpeta del proyecto. La pagina se
# partio en tres archivos para poder mantenerla, pero eso no significa
# publicar el directorio: cualquier otra ruta es un 404.
ESTATICOS = {
    "/": (PAGINA, "text/html"),
    "/index.html": (PAGINA, "text/html"),
    "/interfaz.css": (CARPETA / "interfaz.css", "text/css"),
    "/interfaz.js": (CARPETA / "interfaz.js", "application/javascript"),
}

# Una sola partida a la vez: es una herramienta de escritorio, no un servicio.
# El lock alcanza porque cada pedido rehace el partido entero y es cortito.
sesion = SesionPartido()
candado = threading.Lock()


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

        if ruta == "/api/estado":
            with candado:
                return self._responder({"ok": True, "estado": sesion.instantanea()})

        if ruta == "/api/estadisticas":
            with candado:
                return self._responder({"ok": True, "texto": sesion.estadisticas()})

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
        if ruta == "/api/abrir":
            # no toca la sesion, asi que tampoco toma el candado: si alguien
            # esta cargando un punto no tiene por que esperar a que abra Excel
            respuesta, codigo = self._leer_de_disco(
                lambda: abrir_en_el_escritorio(datos.get("archivo", ""), datos.get("tipo")))
            return self._responder(respuesta, codigo)

        with candado:
            try:
                respuesta = self._despachar(self.path, datos)
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
