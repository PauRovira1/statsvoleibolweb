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
  - dos pedidos seguidos pueden caer en dos procesos distintos, asi que los
    tokens no pueden vivir en una variable de modulo (se firman, ver abajo).
    El partido en curso ya no vive aca en absoluto: lo manda la pantalla en
    cada pedido, asi que le da igual en que instancia cae.

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
pide nada; lo que se protege es escribir: el partido en curso y borrar uno
guardado.
    POST /api/clave                 valida la contraseña y da el token
    GET  /api/sesion                dice si el token que mando sigue valiendo

Endpoints del partido en curso. El partido no vive aca: vive en la pantalla
que lo esta cargando, que manda en cada pedido la lista entera de lineas
("lineas" en el cuerpo). El servidor las corre por el motor, contesta como
quedo y no se guarda nada, que es lo que deja que dos personas carguen dos
partidos al mismo tiempo sin pisarse. Un pedido sin "lineas" cae en la sesion
compartida de siempre, que sigue ahi para las pantallas viejas y los tests.
Los POST piden el token de /api/clave:
    GET  /api/estado /api/estadisticas      la sesion compartida
    POST /api/estado /api/estadisticas      el partido que trae la pantalla
    POST /api/enviar /api/deshacer /api/reiniciar /api/cargar
         /api/guardar /api/excel

Endpoints de los partidos archivados. No tocan la sesion, para que mirar un
informe (o borrar un partido viejo) no interrumpa la carga en la cancha:
    GET  /api/partidos              listado de Datos/*.txt e Informes/*.xlsx
    GET  /api/partido?archivo=      un volcado entero, ya parseado
    GET  /api/informe?archivo=      un .xlsx como hojas y filas de texto
    GET  /api/descargar?archivo=&tipo=txt|xlsx
    GET  /api/equipo                resumen del equipo entero
    POST /api/borrar                borra el volcado y/o el informe (pide clave)
    POST /api/abrir                 lo abre con Excel en esta maquina (solo
                                    tiene sentido corriendo en una PC propia)
"""
import argparse
import base64
import binascii
import hashlib
import hmac
import json
import os
import socket
import threading
import time
import webbrowser
import zlib
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import quote, parse_qs, urlsplit

import almacenamiento as alm
import analisis_voley as av
import archivo_partidos as arch
import notacion
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
    "/armador.js": (PUBLICO / "armador.js", "application/javascript"),
    # la guia de como cargar un partido, enlazada desde la pantalla de carga
    "/guia.html": (PUBLICO / "guia.html", "text/html"),
}

# La sesion compartida: la de antes, cuando el partido en curso era uno solo y
# vivia aca. Hoy cada pantalla trae el suyo en el pedido y esta no se toca;
# queda para el pedido que no manda sus lineas (una pantalla con el .js viejo
# en cache, los tests) y para no perder un partido a medio cargar justo en el
# momento del cambio. El lock es de ella sola.
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
    "/api/cargar", "/api/guardar", "/api/excel", "/api/borrar",
    "/api/corregir", "/api/plantel",
    # los partidos guardados en privado piden la clave TAMBIEN para leerlos,
    # que es lo unico que los hace privados: no estan en Datos, no salen en la
    # pestana Partidos y no se pueden listar sin la contraseña
    "/api/privados", "/api/privado/guardar", "/api/privado/abrir",
    "/api/privado/borrar",
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


def sesion_al_dia(*, escribiendo: bool = True) -> SesionPartido:
    """La sesion con las ultimas lineas, vengan de donde vengan.

    Sin persistencia devuelve la de siempre. Con persistencia se compara la
    version guardada contra la que tiene esta instancia y solo se rehace el
    partido si cambio, que es lo caro.

    Las rutas que solo leen (el marcador, las estadisticas) se conforman con
    una respuesta de hace unos segundos: mirar el partido desde la tribuna no
    tiene por que costar una consulta al blob cada vez. Las que escriben
    preguntan siempre, porque cargar una jugada sobre una sesion vieja
    perderia las que entraron en el medio."""
    global version_de_la_sesion
    if not PERSISTIR_SESION:
        return sesion
    version = alm.version_de_sesion(refrescar=escribiendo)
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
    # la version la trae la propia subida; solo se pregunta si no vino, que es
    # lo que hacia siempre y costaba una operacion advanced por jugada
    version_de_la_sesion = alm.guardar_sesion(sesion.lineas) or alm.version_de_sesion()


def sesion_del_pedido(datos) -> SesionPartido | None:
    """El partido que trae el navegador en el pedido, si lo trae.

    Cargar una jugada siempre costo rehacer el partido entero desde la primera
    linea (ver sesion_web), asi que guardarlo aca entre pedidos no ahorraba
    nada y en cambio obligaba a que hubiera uno solo: dos personas cargando a
    la vez escribian sobre el mismo partido. Ahora las lineas son de la
    pantalla y viajan con cada pedido; el servidor arma una sesion con ellas,
    contesta y la tira. Sin nada compartido que tocar, tampoco hacen falta el
    candado ni la copia en el blob.

    Devolver None es decir "este pedido no trae partido": ahi contesta la
    sesion compartida, como antes."""
    lineas = (datos or {}).get("lineas")
    if lineas is None:
        return None
    if not isinstance(lineas, list):
        raise ValueError("Las lineas del partido tienen que ser una lista.")
    return SesionPartido(lineas)


def guardar_nombres(equipo, nombres, volcado=None, posiciones=None) -> dict:
    """Anota como se llama cada dorsal de un equipo.

    El volcado guarda numeros porque es lo que se grita en la cancha, pero el
    numero solo no dice quien es: dos equipos pueden tener un 13, y el 13 de
    este año puede no ser el del anterior. Esto no toca el volcado ni el
    Excel; es para poder mirar las estadisticas y saber de quien son.

    Sin "volcado" son los nombres del equipo, que valen para todos sus
    partidos. Con "volcado" son los de ESE partido, que pisan a los del equipo
    y sirven justo para cuando el plantel cambio de un año al otro."""
    equipo = str(equipo or "").strip()
    if not equipo:
        raise arch.RutaInvalida("Falta decir de que equipo son los nombres.")
    limpios = {str(d).strip(): str(n or "").strip()
               for d, n in (nombres or {}).items() if str(d or "").strip()}
    puestos = sum(1 for n in limpios.values() if n)

    # Las posiciones son del equipo, no de un partido: de que juega alguien no
    # cambia de un encuentro al otro. Van en el mismo pedido que los nombres
    # porque se editan en la misma pantalla y de a un jugador por fila.
    marcadas = 0
    if posiciones is not None:
        alm.guardar_posiciones(equipo, posiciones)
        marcadas = len(alm.posiciones_del_equipo(equipo))
    if nombres is None:
        return {"ok": True, "posiciones": alm.posiciones_del_equipo(equipo),
                "mensaje": f"{equipo}: {marcadas} posicion(es) anotada(s)."}

    if volcado:
        # solo el nombre: es una clave, nunca una ruta
        partido = Path(str(volcado)).name
        if not partido.lower().endswith(".txt"):
            raise arch.RutaInvalida("Ese no es un volcado.")
        guardado = alm.guardar_nombres_de_partido(partido, equipo, limpios)
        donde = f"{equipo} en {partido}"
        propios = alm.leer_nombres_de_partido().get(partido, {}).get(equipo, {})
    else:
        guardado = alm.guardar_plantel(equipo, limpios)
        donde = equipo
        propios = alm.leer_plantel().get(equipo, {})

    aviso = "" if guardado else "  [OJO: no se pudo guardar afuera, se pierde al reiniciar]"
    detalle = (f"{puestos} nombre(s) anotado(s)" if puestos
               else "vuelve a usar los nombres del equipo")
    if posiciones is not None:
        # sin ningun nombre puesto, "vuelve a usar los nombres del equipo y 7
        # posiciones" se lee como si hubiera borrado algo
        detalle = (f"{detalle} y {marcadas} posicion(es)" if puestos
                   else f"{marcadas} posicion(es) anotada(s)")
    return {"ok": True, "plantel": propios,
            "posiciones": alm.posiciones_del_equipo(equipo),
            "mensaje": f"{donde}: {detalle}.{aviso}"}


def corregir_partido(volcado, campos) -> dict:
    """Guarda (o saca) el arreglo a mano del resumen de un partido.

    El resumen sale leido del .txt y casi siempre eso alcanza. Lo que el
    archivo no puede saber es cual de varios informes del mismo dia le
    corresponde: el nombre del informe no lleva la hora, asi que dos guardados
    del mismo partido comparten archivo y el emparejado automatico se lo
    cuelga al primero."""
    # solo el nombre: es la clave con la que se guarda la correccion, nunca
    # una ruta, y .name deja afuera cualquier intento de salir de la carpeta
    nombre = Path(str(volcado or "")).name
    if not nombre.lower().endswith(".txt"):
        raise arch.RutaInvalida("Hay que decir de que volcado es la correccion.")

    limpios = {}
    for campo in arch.CAMPOS_CORREGIBLES:
        valor = (campos or {}).get(campo)
        if valor in (None, ""):
            continue
        if campo == "parciales":
            limpios[campo] = [str(p).strip() for p in valor if str(p).strip()]
        elif campo == "puntos":
            limpios[campo] = int(valor)
        else:
            limpios[campo] = str(valor).strip()

    guardado = alm.guardar_correccion(nombre, limpios)
    if not limpios:
        return {"ok": True, "mensaje": f"{nombre}: vuelve a mostrar lo que dice el .txt.",
                "corregido": []}
    aviso = "" if guardado else "  [OJO: no se pudo guardar afuera, se pierde al reiniciar]"
    return {"ok": True, "corregido": sorted(limpios),
            "mensaje": f"{nombre}: corregido {', '.join(sorted(limpios))}.{aviso}"}


def aviso_de_blob(logica: str, nombre: str) -> str:
    """Lo que hay que agregarle al mensaje si el archivo no llego al Blob.

    Guardar contesta "Guardado: ..." apenas se escribe el archivo, pero
    alojado eso todavia no quiere decir nada: lo escrito esta en /tmp y se
    borra solo. Recien cuando esta en el Blob esta guardado de verdad, asi que
    se verifica y, si no llego, se dice en el mismo mensaje.

    Sin Blob configurado no se agrega nada: de eso ya avisa la franja de
    arriba, y repetirlo en cada guardado seria ruido."""
    if not alm.hay_blob() or alm.publicado(logica, nombre):
        return ""
    # el motivo lo sabe esta misma instancia, que es la que acaba de fallar:
    # va en el mensaje para no tener que ir a buscarlo a los logs
    motivo = alm.ultimo_error()
    return (f"  [OJO: {nombre} no se pudo subir al Blob y por ahora solo esta "
            f"en {alm.CARPETA_ESCRITURA}, que se borra solo. Descargalo ahora "
            f"o volve a guardar."
            + (f" Motivo: {motivo}]" if motivo else "]"))


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
    # los nombres de ESE partido: los del equipo y, encima, los propios si
    # los tiene. El .txt sigue guardando numeros; el nombre se agrega aca
    nombres = alm.nombres_de(Path(nombre_txt).name, equipo)
    libro, avisos = gi.build_workbook(equipo, rival, volcado, nombres)
    fecha = gi.guess_fecha_from_filename(nombre_txt) or f"{datetime.now():%Y-%m-%d}"
    salida = (av.carpeta_lista(av.CARPETA_INFORMES) /
          f"Informe_{alm.nombre_para_archivo(equipo)}_vs_"
          f"{alm.nombre_para_archivo(rival)}_{fecha}.xlsx")
    archivo, _ = gi.guardar_informe(libro, salida)
    return archivo


# ----------------------------------------------------------------------
# Lecturas de disco. Van aca afuera y devuelven datos, sin tocar la sesion ni
# el candado: navegar por los partidos guardados no puede frenar la carga en
# vivo, que es lo unico que tiene que ser rapido.
# ----------------------------------------------------------------------

def responder_jugadores(campeonato: str = "") -> dict:
    """Los equipos con su plantel. Se recalcula en cada pedido a partir de los
    volcados: son milisegundos, y asi no hay numeros guardados que se puedan
    desactualizar cuando se borra o se recarga un partido.

    Con "campeonato" se cuentan solo los partidos de ese campeonato."""
    import estadisticas_jugadores as ej
    datos = ej.listado(campeonato=campeonato)
    # Los nombres no salen de los volcados (ahi solo hay numeros): se anotan
    # aparte y se pegan aca. El modulo de estadisticas sigue leyendo archivos
    # y nada mas; ponerle los nombres adentro lo ataria a donde se guardan.
    plantel = alm.leer_plantel()
    for equipo in datos.get("equipos", []):
        # aca se suman varios partidos, asi que vale el nombre del equipo y,
        # si no lo tiene, el ultimo que se le haya puesto en algun partido
        nombres = alm.nombres_del_equipo(equipo["nombre"])
        for jugador in equipo["jugadores"]:
            jugador["nombre"] = nombres.get(str(jugador["dorsal"]), "")
    # igual que el listado de partidos: si el Blob esta fallando, esto es lo
    # que se ve incompleto, asi que el aviso tiene que viajar con los datos
    return {"ok": True, **datos, "plantel": plantel, "almacenamiento": alm.estado()}


def responder_jugador(equipo: str, dorsal: str, campeonato: str = "") -> dict:
    import estadisticas_jugadores as ej
    # el agregado se arma aca y no adentro de ficha() para que el campeonato
    # entre por un solo lugar: ficha() ya recibia el agregado hecho
    ficha = ej.ficha(equipo, dorsal, ej.agregar(campeonato=campeonato))
    if ficha is None:
        return {"ok": False, "mensaje": f"No hay datos del {dorsal} en {equipo}."}
    ficha["nombre"] = alm.nombres_del_equipo(equipo).get(str(dorsal), "")
    return {"ok": True, "jugador": ficha}


def responder_equipo(equipo: str, campeonato: str = "") -> dict:
    """El resumen del equipo entero: las mismas metricas que una ficha, pero
    del juego y no de una persona."""
    import estadisticas_jugadores as ej
    resumen = ej.resumen_equipo(equipo, ej.agregar(campeonato=campeonato))
    if resumen is None:
        falta = f" en {campeonato}" if campeonato else ""
        return {"ok": False, "mensaje": f"No hay partidos cargados de {equipo}{falta}."}
    return {"ok": True, "equipo": resumen}


def responder_partidos() -> dict:
    # el estado del almacenamiento viaja tambien aca: si el Blob esta fallando,
    # esta lista es justo la que se ve incompleta
    return {"ok": True, "partidos": arch.listar_partidos(),
            "almacenamiento": alm.estado()}


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


def donde_quedo(ruta) -> str:
    """Como nombrar un archivo recien guardado, para el mensaje de pantalla.

    Alojado la ruta real es /tmp/voley/..., que no le dice nada a nadie y
    encima asusta: parece que el partido quedo en un lugar que se borra solo.
    Ahi lo unico que importa es el nombre, porque el archivo ademas se publico
    en el almacen -- y si NO se pudo publicar, eso ya lo dice aviso_de_blob().

    En casa la ruta si sirve, que es para ir a buscar el archivo."""
    ruta = Path(ruta)
    return ruta.name if alm.hay_blob() else str(ruta)


# ----------------------------------------------------------------------
# Partidos guardados en privado (ver almacenamiento.RUTA_PRIVADOS).
#
# Guardar el .txt publica el partido. Esto no: sube las mismas lineas a un
# lugar aparte, para poder apagar la maquina en el entretiempo y seguir
# manana (o desde otra maquina) sin que el partido a medias le aparezca a
# nadie ni cuente en las estadisticas.
# ----------------------------------------------------------------------

def resumen_del_privado(estado: dict) -> dict:
    """Con que se reconoce un partido en la lista de guardados.

    Se guarda armado y no se recalcula al listar: recalcularlo obligaria a
    bajar las lineas de todos los partidos y correr el motor sobre cada uno
    solo para pintar un renglon."""
    nombres = estado["nombres"]
    sets, marcador = estado["sets_ganados"], estado["marcador"]
    return {
        "A": nombres["A"], "B": nombres["B"],
        "sets": f"{sets['A']} - {sets['B']}",
        "marcador": f"{marcador['A']} - {marcador['B']}",
        "set": estado["set"],
        "puntos": estado["puntos_cargados"],
    }


def aviso_de_privado() -> str:
    """Lo que hay que agregarle al mensaje si esto no se guardo de verdad.

    Alojado y sin almacenamiento remoto, el archivo queda en /tmp y se borra
    solo: decir "guardado" ahi seria mentir justo en lo unico que este boton
    promete."""
    if not alm.EN_SERVERLESS or alm.hay_blob():
        return ""
    return ("  [OJO: este servidor no tiene almacenamiento configurado, asi que "
            "el partido quedo en una carpeta que se borra sola. No cierres esta "
            "pantalla.]")


def guardar_en_privado(sesion, id_, nombre) -> dict:
    """Sube el partido a medio cargar sin publicarlo."""
    estado = sesion.instantanea()
    if not sesion.lineas:
        return {"ok": False, "mensaje": "No hay nada cargado para guardar.",
                "estado": estado}
    resumen = resumen_del_privado(estado)
    nombre = str(nombre or "").strip() or f"{resumen['A']} vs {resumen['B']}"
    try:
        pudo = alm.guardar_privado(id_, nombre, sesion.lineas, resumen)
    except ValueError as error:
        return {"ok": False, "mensaje": str(error), "estado": estado}
    except alm.FALLAS_DE_RED as error:
        # no se pudo leer lo que ya habia: guardar igual pisaria los partidos
        # guardados de los demas, asi que no se guarda nada
        return {"ok": False, "estado": estado,
                "mensaje": f"No se pudo guardar en privado: {error}. "
                           f"El partido sigue cargado aca, proba de nuevo."}
    if not pudo:
        motivo = alm.ultimo_error()
        return {"ok": False, "estado": estado,
                "mensaje": ("No se pudo guardar en privado. El partido sigue "
                            "cargado aca, proba de nuevo."
                            + (f" Motivo: {motivo}" if motivo else ""))}
    return {"ok": True, "estado": estado, "privados": alm.listar_privados(),
            "mensaje": (f"Guardado en privado: {nombre} ({len(sesion.lineas)} lineas). "
                        f"No aparece en Partidos ni en las estadisticas; se vuelve "
                        f"a abrir desde aca." + aviso_de_privado())}


def abrir_privado(sesion, id_) -> dict:
    """Deja la pantalla cargando ese partido, donde habia quedado."""
    try:
        guardado = alm.leer_privado(id_)
    except alm.FALLAS_DE_RED as error:
        return {"ok": False, "mensaje": f"No se pudo leer el partido guardado: {error}.",
                "estado": sesion.instantanea()}
    if guardado is None:
        return {"ok": False, "mensaje": "Ese partido ya no esta guardado en privado.",
                "estado": sesion.instantanea()}
    sesion.reemplazar([str(linea) for linea in (guardado.get("lineas") or [])])
    return {"ok": True, "estado": sesion.instantanea(),
            "mensaje": (f"Seguis cargando {guardado.get('nombre') or id_}: "
                        f"{len(sesion.lineas)} lineas. Sigue guardado en privado "
                        f"hasta que lo borres.")}


def olvidar_privado(id_) -> dict:
    """Saca un partido de los guardados en privado."""
    if not alm.borrar_privado(id_):
        return {"ok": False, "mensaje": "Ese partido ya no estaba guardado.",
                "privados": alm.listar_privados()}
    return {"ok": True, "mensaje": "Se borro de los guardados en privado.",
            "privados": alm.listar_privados()}


def borrar_partido(volcado, informe) -> dict:
    """Borra el volcado y/o el informe de un partido.

    Los dos son opcionales porque una fila del listado puede tener uno solo.
    Se borra lo que se pueda y se informa de cada uno: que el .xlsx este
    abierto en Excel no tiene por que impedir que se borre el .txt."""
    pedidos = [(alm.DATOS, "txt", volcado), (alm.INFORMES, "xlsx", informe)]
    pedidos = [(logica, tipo, str(n).strip()) for logica, tipo, n in pedidos
               if n and str(n).strip()]
    if not pedidos:
        return {"ok": False, "mensaje": "No se dijo que borrar."}

    mensajes, fallo = [], False
    for logica, tipo, nombre in pedidos:
        try:
            # por ruta_de_tipo aunque solo haga falta el nombre: es donde se
            # valida que lo pedido caiga en Datos/ o Informes/ y no en
            # cualquier otro lado del disco
            ruta, _ = arch.ruta_de_tipo(nombre, tipo)
        except arch.RutaInvalida as error:
            mensajes.append(str(error))
            fallo = True
            continue
        except FileNotFoundError:
            mensajes.append(f"{nombre} ya no estaba.")
            continue
        pudo, mensaje = alm.borrar(logica, ruta.name)
        mensajes.append(mensaje)
        fallo = fallo or not pudo

    return {"ok": not fallo, "mensaje": " ".join(mensajes)}


# El navegador manda el pedido comprimido: {"z": gzip en base64 del JSON de
# siempre}. Es por el WAF de CloudFront, no por ahorrar datos. Cada pedido
# lleva el partido entero, asi que el cuerpo crece con cada punto; pasados los
# 8 KB la regla SizeRestrictions_BODY lo corta con un 403, y antes de eso las
# reglas que buscan ataques pueden confundir una jugada con uno. Comprimido el
# cuerpo es chico y opaco. El pedido sin comprimir se sigue aceptando: es el
# de un navegador sin CompressionStream, o el de la consola y los tests.
MAXIMO_DESCOMPRIMIDO = 5 * 1024 * 1024   # un partido son decenas de KB


def desempaquetar(datos):
    if not (isinstance(datos, dict) and set(datos) == {"z"} and isinstance(datos["z"], str)):
        return datos
    try:
        comprimido = base64.b64decode(datos["z"], validate=True)
        descompresor = zlib.decompressobj(wbits=31)          # 31 = formato gzip
        crudo = descompresor.decompress(comprimido, MAXIMO_DESCOMPRIMIDO)
        if descompresor.unconsumed_tail:
            raise ValueError("El pedido descomprimido es demasiado grande.")
        return json.loads(crudo.decode("utf-8"))
    except (binascii.Error, zlib.error, UnicodeDecodeError) as error:
        raise ValueError(f"No se pudo leer el pedido comprimido: {error}") from None


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
        return desempaquetar(json.loads(self.rfile.read(largo).decode("utf-8")))

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

        if ruta == "/api/notacion":
            # la tabla de la notacion: fija, de solo lectura y sin sesion
            # atras, asi que ni toma el candado ni se pone al dia
            return self._responder({"ok": True, **notacion.tabla()})

        if ruta == "/api/estado":
            with candado:
                return self._responder({"ok": True,
                                        "estado": sesion_al_dia(escribiendo=False).instantanea(),
                                        "almacenamiento": alm.estado()})

        if ruta == "/api/estadisticas":
            with candado:
                return self._responder({"ok": True, "texto": sesion_al_dia(escribiendo=False).estadisticas()})

        if ruta == "/api/descargar":
            return self._descargar(consulta)

        lecturas = {
            "/api/partidos": lambda: responder_partidos(),
            "/api/partido": lambda: responder_partido(consulta.get("archivo", "")),
            "/api/informe": lambda: responder_informe(consulta.get("archivo", "")),
            "/api/jugadores": lambda: responder_jugadores(consulta.get("campeonato", "")),
            # solo lectura y sin clave: los nombres se muestran en las tablas
            # de cualquier partido, no solo en la pestana Jugadores
            "/api/plantel": lambda: {"ok": True, "plantel": alm.leer_plantel(),
                                     "partidos": alm.leer_nombres_de_partido(),
                                     "posiciones": alm.leer_posiciones(),
                                     "opciones_posicion": list(alm.POSICIONES)},
            "/api/jugador": lambda: responder_jugador(consulta.get("equipo", ""),
                                                      consulta.get("dorsal", ""),
                                                      consulta.get("campeonato", "")),
            "/api/equipo": lambda: responder_equipo(consulta.get("equipo", ""),
                                                    consulta.get("campeonato", "")),
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
        except ValueError as error:   # el comprimido no se pudo abrir
            return self._responder({"ok": False, "mensaje": str(error)}, 400)

        ruta = urlsplit(self.path).path
        if ruta == "/api/clave":
            # fuera del candado de la sesion: el segundo de castigo por clave
            # errada no puede frenar al que esta cargando el partido
            return self._responder(abrir_sesion(datos.get("clave", "")))

        if ruta in RUTAS_CON_CLAVE and not token_valido(self.headers.get("X-Clave")):
            # "clave": True es la senal para que la pantalla vuelva a pedirla
            return self._responder({"ok": False, "clave": True,
                                    "mensaje": "Hace falta la contraseña."}, 401)

        if ruta == "/api/borrar":
            # como /api/abrir: toca el disco pero no la sesion, asi que no
            # toma el candado y no frena al que esta cargando un punto
            respuesta, codigo = self._leer_de_disco(
                lambda: borrar_partido(datos.get("volcado"), datos.get("informe")))
            return self._responder(respuesta, codigo)

        if ruta == "/api/privados":
            # la lista de partidos guardados en privado. No toca la sesion:
            # mirarla mientras se carga un punto no puede frenar la carga
            respuesta, codigo = self._leer_de_disco(
                lambda: {"ok": True, "privados": alm.listar_privados()})
            return self._responder(respuesta, codigo)

        if ruta == "/api/privado/borrar":
            respuesta, codigo = self._leer_de_disco(
                lambda: olvidar_privado(datos.get("id", "")))
            return self._responder(respuesta, codigo)

        if ruta == "/api/plantel":
            # los nombres de un equipo. Como /api/corregir: toca archivos pero
            # no la sesion, asi que no toma el candado
            respuesta, codigo = self._leer_de_disco(
                lambda: guardar_nombres(datos.get("equipo"), datos.get("nombres"),
                                        datos.get("volcado"),
                                        datos.get("posiciones")))
            return self._responder(respuesta, codigo)

        if ruta == "/api/corregir":
            # arregla a mano el resumen de un partido. Como /api/borrar: toca
            # los archivos pero no la sesion, asi que no toma el candado y no
            # frena al que esta cargando un punto
            respuesta, codigo = self._leer_de_disco(
                lambda: corregir_partido(datos.get("volcado"), datos.get("campos")))
            return self._responder(respuesta, codigo)

        if ruta == "/api/abrir":
            # no toca la sesion, asi que tampoco toma el candado: si alguien
            # esta cargando un punto no tiene por que esperar a que abra Excel
            respuesta, codigo = self._leer_de_disco(
                lambda: abrir_en_el_escritorio(datos.get("archivo", ""), datos.get("tipo")))
            return self._responder(respuesta, codigo)

        # El caso normal: el partido lo trae la pantalla. No hay nada
        # compartido que tocar, asi que no se toma el candado (el que carga no
        # espera al que guarda un Excel) ni se escribe la sesion afuera.
        try:
            propia = sesion_del_pedido(datos)
        except ValueError as error:
            return self._responder({"ok": False, "mensaje": str(error)}, 400)
        if propia is not None:
            try:
                respuesta = self._despachar(ruta, datos, propia)
            except Exception as error:      # que un error no tumbe el servidor
                respuesta = {"ok": False, "mensaje": f"{type(error).__name__}: {error}",
                             "estado": propia.instantanea()}
            if respuesta is None:
                return self._responder({"ok": False, "mensaje": "No existe"}, 404)
            return self._responder(respuesta)

        with candado:
            try:
                antes = list(sesion_al_dia().lineas)
                respuesta = self._despachar(ruta, datos, sesion)
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

    def _despachar(self, ruta: str, datos: dict, sesion: SesionPartido):
        """Atiende una ruta del partido en curso contra la sesion que toque:
        la que trajo la pantalla, o la compartida si el pedido no trajo
        ninguna. Las dos son una SesionPartido, asi que el codigo es uno."""
        # estado y estadisticas son de solo lectura y por eso tambien atienden
        # por GET (ver do_GET). Por POST es como se pregunta por un partido que
        # el servidor no conoce: el de la pantalla, que viene en el cuerpo.
        if ruta == "/api/estado":
            return {"ok": True, "estado": sesion.instantanea(),
                    "almacenamiento": alm.estado()}
        if ruta == "/api/estadisticas":
            return {"ok": True, "texto": sesion.estadisticas()}
        if ruta == "/api/enviar":
            return sesion.enviar(datos.get("linea", ""))
        if ruta == "/api/deshacer":
            return sesion.deshacer_linea()
        if ruta == "/api/reiniciar":
            return sesion.reiniciar()
        if ruta == "/api/cargar":
            return sesion.cargar_lineas(datos.get("texto", ""))
        if ruta == "/api/privado/guardar":
            return guardar_en_privado(sesion, datos.get("id", ""), datos.get("nombre"))
        if ruta == "/api/privado/abrir":
            return abrir_privado(sesion, datos.get("id", ""))
        if ruta == "/api/guardar":
            nombre = sesion.guardar()
            return {"ok": True,
                    "mensaje": f"Guardado: {donde_quedo(nombre)}"
                               + aviso_de_blob(alm.DATOS, Path(nombre).name),
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
            except Exception as error:      # noqa: BLE001
                # El volcado se guarda ANTES de armar el Excel, asi que si esto
                # falla el partido igual quedo a salvo. Hay que decirlo: desde
                # la pantalla se veia como que el boton no hacia nada y solo
                # aparecia un .txt, sin ninguna pista de por que.
                return {"ok": False,
                        "mensaje": (f"No se pudo generar el Excel "
                                    f"({type(error).__name__}: {error}). El partido "
                                    f"igual quedo guardado como {Path(nombre_txt).name}; "
                                    f"se puede generar el informe despues desde Partidos."),
                        "archivo": Path(nombre_txt).name, "tipo": "txt",
                        "estado": sesion.instantanea()}
            # el nombre suelto ademas del mensaje: con eso la pantalla arma el
            # enlace para abrir o descargar el informe sin copiar la ruta
            aviso = (aviso_de_blob(alm.INFORMES, Path(excel).name)
                     or aviso_de_blob(alm.DATOS, Path(nombre_txt).name))
            return {"ok": True,
                    "mensaje": (f"Generado: {donde_quedo(excel)} "
                                f"(volcado: {donde_quedo(nombre_txt)}){aviso}"),
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
