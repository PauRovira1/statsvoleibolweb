"""
Probar el Vercel Blob sin desplegar nada.

    python probar_blob.py              prueba que el Blob funcione
    python probar_blob.py --listar     muestra que hay guardado

El token sale del archivo .env de la carpeta, que es donde lo deja el boton
"Copy Snippet" del panel. Tambien se acepta en el entorno o como argumento,
pero conviene el .env: un token pegado a mano es un token que paso por los
ojos de alguien, y `1` y `l`, `0` y `O` son indistinguibles en casi cualquier
fuente. Un solo caracter cambiado da 403 "Token mismatch", que parece un
problema de permisos y no lo es.

Hace, una por una, las tres cosas que el proyecto le pide al Blob: listar,
subir y volver a bajar. Cada paso dice si salio bien y, si no, el codigo HTTP
y el cuerpo del error tal como los devolvio el servicio.

Usa las funciones de almacenamiento.py, no una copia: si esto anda, el sitio
anda, y si esto falla, falla por lo mismo. Sirve para separar "el token no
vale" de "las llamadas estan mal armadas", que desde la pantalla se ven igual.

Lo que sube es un archivo de prueba en prueba/, no toca Datos/ ni Informes/,
y lo borra al terminar.
"""
import json
import os
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request

import almacenamiento as alm

PRUEBA = "prueba/hola.txt"
CONTENIDO = b"probando el blob\n"


ARCHIVO_ENV = ".env"


def leer_del_env(clave: str, ruta=ARCHIVO_ENV) -> str:
    """Busca una variable en el .env de la carpeta.

    No es un parser de .env completo: alcanza con `CLAVE=valor`, con o sin
    comillas, que es lo que copia el panel de Vercel."""
    try:
        lineas = pathlib.Path(ruta).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for linea in lineas:
        nombre, sep, valor = linea.partition("=")
        if sep and nombre.strip() == clave:
            return valor.strip().strip(alm.COMILLAS)
    return ""


def titulo(texto: str) -> None:
    print(f"\n{texto}\n" + "-" * len(texto))


def borrar(url: str) -> None:
    """Saca el archivo de prueba. Si no se puede, no es grave: son 17 bytes."""
    cuerpo = json.dumps({"urls": [url]}).encode("utf-8")
    try:
        alm._pedir(f"{alm.API_BLOB}/delete", metodo="POST", cuerpo=cuerpo,
                   cabeceras={"content-type": "application/json"})
        print("  se borro el archivo de prueba")
    except Exception as error:      # noqa: BLE001  (es un script de diagnostico)
        print(f"  no se pudo borrar (borralo a mano si molesta): {error}")


def tamaño(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} B"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.0f} KB"
    return f"{bytes_ / 1024 / 1024:.1f} MB"


def listar() -> int:
    """Que hay guardado, por carpeta. Lo mismo que el Browse del panel."""
    try:
        blobs = alm._listar_blobs_crudo("")
    except alm.FALLAS_DE_RED as error:
        print(f"No se pudo leer el Blob: {error}")
        return 1

    if not blobs:
        print("\nEl store esta vacio.")
        return 0

    por_carpeta: dict[str, list[dict]] = {}
    for blob in blobs:
        por_carpeta.setdefault(blob["pathname"].split("/")[0], []).append(blob)

    # Datos e Informes primero, que son los partidos; lo demas (la sesion en
    # curso, la lista de borrados) es maquinaria y va al final
    orden = [c for c in (alm.DATOS, alm.INFORMES) if c in por_carpeta]
    orden += sorted(c for c in por_carpeta if c not in orden)

    total = 0
    for carpeta in orden:
        archivos = sorted(por_carpeta[carpeta], key=lambda b: b["pathname"])
        print(f"\n{carpeta}/  ({len(archivos)})")
        for blob in archivos:
            nombre = blob["pathname"].split("/", 1)[1]
            subido = str(blob.get("uploadedAt", ""))[:16].replace("T", " ")
            print(f"  {nombre:<50} {tamaño(blob['size']):>8}   {subido}")
            total += blob["size"]
    print(f"\n{len(blobs)} archivo(s), {tamaño(total)} en total.")

    ocultos = alm._cargar_borrados(refrescar=True)
    if ocultos:
        print(f"\nOcultos ({len(ocultos)}): partidos borrados que igual siguen en el")
        print("repositorio, asi que no se pueden borrar, solo dejar de mostrar.")
        for nombre in sorted(ocultos):
            print(f"  {nombre}")
    return 0


def main() -> int:
    solo_listar = len(sys.argv) > 1 and sys.argv[1] in ("--listar", "-l")
    if solo_listar:
        sys.argv.pop(1)

    # argumento > entorno > .env
    if len(sys.argv) > 1:
        os.environ["BLOB_READ_WRITE_TOKEN"] = sys.argv[1]
        origen = "el argumento"
    elif alm.token_blob():
        origen = "el entorno"
    else:
        os.environ["BLOB_READ_WRITE_TOKEN"] = leer_del_env("BLOB_READ_WRITE_TOKEN")
        origen = f"el archivo {ARCHIVO_ENV}"

    titulo("1) El token")
    forma = alm.forma_del_token()
    if not forma["presente"]:
        print(f"  No hay BLOB_READ_WRITE_TOKEN (lo busque en {origen}).")
        print(f"  Ponelo en un archivo {ARCHIVO_ENV} al lado de este .py:")
        print("      BLOB_READ_WRITE_TOKEN=vercel_blob_rw_...")
        print("  Copialo con el boton Copy Snippet del panel, no lo escribas a mano.")
        return 1
    print(f"  sale de      : {origen}")
    print(f"  bien formado : {forma['bien_formado']}   (vercel_blob_rw_<store>_<secreto>)")
    print(f"  largo        : {forma['largo']}")
    print(f"  store        : {forma['store'] or '(no se pudo leer)'}")
    if not forma["bien_formado"]:
        print("\n  El token no tiene la forma esperada: quedo cortado, o se copio")
        print("  la linea entera del .env en vez del valor. No sigo probando.")
        return 1

    if solo_listar:
        return listar()

    titulo("2) Listar lo que hay (GET /)")
    try:
        blobs = alm._listar_blobs_crudo("")
    except alm.FALLAS_DE_RED as error:
        print(f"  FALLO: {error}")
        print("\n  Si dice 403 Token mismatch, el token no es el que emitio ese")
        print("  store: se regenero, o es de otro store. Copia el actual desde")
        print("  Storage -> el store -> pestaña .env.local.")
        return 1
    print(f"  OK: {len(blobs)} archivo(s) en el store")
    for blob in blobs[:10]:
        print(f"    {blob.get('pathname')}  ({blob.get('size')} bytes)")

    titulo("3) Subir un archivo (PUT)")
    try:
        url = alm.subir_blob(PRUEBA, CONTENIDO, "text/plain; charset=utf-8")
    except alm.FALLAS_DE_RED as error:
        print(f"  FALLO: {error}")
        print("\n  Listar anduvo pero subir no: el token puede ser de solo")
        print("  lectura. Tiene que ser uno read-write (vercel_blob_rw_...).")
        return 1
    print(f"  OK: {url}")

    titulo("4) Confirmar que quedo")
    if alm.publicado("prueba", "hola.txt"):
        print("  OK: aparece en el listado")
    else:
        print("  RARO: subio pero no aparece al listar de nuevo")

    titulo("5) Bajarlo y comparar")
    try:
        # con el token, igual que bajar_blob: en un store privado la URL sola
        # devuelve 403 aunque el archivo exista
        bajado = alm._pedir(url, timeout=20)
    except alm.FALLAS_DE_RED as error:
        print(f"  FALLO: {error}")
        print("\n  Si dice 403 y el store es privado, la descarga esta yendo")
        print("  sin autorizacion. Es un bug, no un problema de configuracion.")
        return 1
    print("  OK: el contenido coincide" if bajado == CONTENIDO
          else f"  FALLO: bajo otra cosa ({bajado!r})")

    titulo("6) Limpiar")
    borrar(url)

    print("\nTodo bien. El Blob funciona y el proyecto lo esta usando como debe.")
    print("Si el sitio igual falla, lo que esta mal es la variable en Vercel,")
    print("no el token que acabas de probar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
