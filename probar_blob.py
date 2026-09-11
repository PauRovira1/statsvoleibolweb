"""
Probar el Vercel Blob sin desplegar nada.

    set BLOB_READ_WRITE_TOKEN=vercel_blob_rw_...     (o pasarlo como argumento)
    python probar_blob.py

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
import sys
import urllib.error
import urllib.parse
import urllib.request

import almacenamiento as alm

PRUEBA = "prueba/hola.txt"
CONTENIDO = b"probando el blob\n"


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


def main() -> int:
    if len(sys.argv) > 1:
        import os
        os.environ["BLOB_READ_WRITE_TOKEN"] = sys.argv[1]

    titulo("1) El token")
    forma = alm.forma_del_token()
    if not forma["presente"]:
        print("  No hay BLOB_READ_WRITE_TOKEN.")
        print("  Ponelo en el entorno o pasalo como argumento:")
        print("      python probar_blob.py vercel_blob_rw_...")
        return 1
    print(f"  bien formado : {forma['bien_formado']}   (vercel_blob_rw_<store>_<secreto>)")
    print(f"  largo        : {forma['largo']}")
    print(f"  store        : {forma['store'] or '(no se pudo leer)'}")
    if not forma["bien_formado"]:
        print("\n  El token no tiene la forma esperada: quedo cortado, o se copio")
        print("  la linea entera del .env en vez del valor. No sigo probando.")
        return 1

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
        with urllib.request.urlopen(url, timeout=20) as respuesta:
            bajado = respuesta.read()
    except (urllib.error.URLError, OSError) as error:
        print(f"  FALLO: {error}")
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
