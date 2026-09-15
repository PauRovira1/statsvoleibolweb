"""Comprueba que S3 esta bien configurado, desde tu PC y antes de tocar Lambda.

    python probar_s3.py --bucket voley-pau-2026
    python probar_s3.py --bucket voley-pau-2026 --solo-leer   (no escribe nada)

Sirve para separar dos problemas que desde afuera se ven iguales: que S3 este
mal (bucket, region, permisos) y que Lambda este mal (paquete, handler,
variables). Si esto pasa entero, lo que falle despues es de Lambda.

Cada paso dice que permiso esta probando, asi que cuando uno falla ya sabes
que linea le falta a la policy.

Necesita:
    --bucket NOMBRE     o la variable VOLEY_S3_BUCKET
    las credenciales     de `aws configure`, o AWS_ACCESS_KEY_ID y compania
"""
import argparse
import os
import sys
from pathlib import Path

import almacen_s3 as s3

PRUEBA = "prueba/desde-mi-pc.txt"
CONTENIDO = "Si lees esto, S3 anda.\n".encode("utf-8")


def _credenciales_del_cli() -> bool:
    """Lee ~/.aws/credentials si no hay variables de entorno.

    `aws configure` guarda las claves en ese archivo y no en el entorno, asi
    que sin esto el script no encuentra nada aunque el CLI funcione. Es un
    INI de dos claves; no vale la pena importar configparser para otra cosa,
    pero tampoco inventar un parser."""
    import configparser
    archivo = Path.home() / ".aws" / "credentials"
    if not archivo.exists():
        return False
    datos = configparser.ConfigParser()
    datos.read(archivo)
    perfil = os.environ.get("AWS_PROFILE", "default")
    if not datos.has_section(perfil):
        return False
    for variable, clave in (("AWS_ACCESS_KEY_ID", "aws_access_key_id"),
                            ("AWS_SECRET_ACCESS_KEY", "aws_secret_access_key"),
                            ("AWS_SESSION_TOKEN", "aws_session_token")):
        if datos.has_option(perfil, clave) and not os.environ.get(variable):
            os.environ[variable] = datos.get(perfil, clave)
    return True


def _region_del_cli() -> None:
    import configparser
    archivo = Path.home() / ".aws" / "config"
    if os.environ.get("VOLEY_S3_REGION") or os.environ.get("AWS_REGION") or not archivo.exists():
        return
    datos = configparser.ConfigParser()
    datos.read(archivo)
    perfil = os.environ.get("AWS_PROFILE", "default")
    seccion = perfil if datos.has_section(perfil) else f"profile {perfil}"
    if datos.has_option(seccion, "region"):
        os.environ["AWS_REGION"] = datos.get(seccion, "region")


def revisar_forma(clave: str, secreto: str) -> list[str]:
    """Avisa si lo que hay en ~/.aws/credentials no es una clave de acceso.

    `aws configure` pide "Access Key ID" y "Secret Access Key", y es facil
    pegarle otra cosa: el link de ingreso a la consola y la clave de la
    cuenta son lo que uno tiene a mano cuando recien empieza. Con eso adentro
    AWS contesta InvalidClientTokenId, que no se parece en nada a la causa.

    Una clave de acceso son 20 caracteres y arranca con AKIA (las de un
    usuario) o ASIA (las temporales). El secreto son 40."""
    problemas = []
    if clave.startswith("http"):
        problemas.append("la clave es una URL: pegaste el link de la consola "
                         "en vez de la Access Key ID")
    elif not clave.startswith(("AKIA", "ASIA")):
        problemas.append("la clave no empieza con AKIA ni con ASIA")
    elif len(clave) != 20:
        problemas.append(f"la clave tiene {len(clave)} caracteres y son 20")
    if secreto and len(secreto) != 40:
        # sin acentos a proposito: la consola de Windows los rompe
        problemas.append(f"el secreto tiene {len(secreto)} caracteres y son 40 "
                         f"(si pusiste la clave de tu cuenta, no es eso)")
    return problemas


def paso(numero: int, titulo: str) -> None:
    print(f"\n{numero}. {titulo}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bucket", default="",
                        help="el bucket; si no, se usa VOLEY_S3_BUCKET")
    parser.add_argument("--solo-leer", action="store_true",
                        help="no subir ni borrar nada")
    args = parser.parse_args()

    # pasarlo por argumento evita la variable de entorno, que en PowerShell se
    # escribe $env:NOMBRE y sin el peso adelante no falla: no hace nada
    if args.bucket:
        os.environ["VOLEY_S3_BUCKET"] = args.bucket

    _credenciales_del_cli()
    _region_del_cli()

    print("=== Probando S3 ===")

    paso(1, "La configuracion")
    clave, secreto, sesion = s3.credenciales()
    print(f"   bucket : {s3.bucket() or '(sin VOLEY_S3_BUCKET)'}")
    print(f"   region : {s3.region()}")
    print(f"   clave  : {clave[:4] + '...' + clave[-4:] if clave else '(no hay)'}")
    print(f"   host   : {s3.anfitrion()}")
    if sesion:
        print("   credenciales temporales (token de sesion presente)")
    problemas = revisar_forma(clave, secreto) if clave else []
    if problemas:
        print("\n   LAS CREDENCIALES NO TIENEN FORMA DE CREDENCIALES:")
        for detalle in problemas:
            print(f"     - {detalle}")
        print("\n   Sacalas de IAM -> Users -> tu usuario -> Security credentials")
        print("   -> Create access key -> Command Line Interface, y despues")
        print("   corre `aws configure` de nuevo.")
        return 1
    if not s3.hay_s3():
        print("\n   FALTA configuracion. Pone VOLEY_S3_BUCKET y corre `aws configure`.")
        return 1

    paso(2, "Listar el bucket  [s3:ListBucket]")
    try:
        todo = s3.listar("")
    except s3.ErrorDeS3 as error:
        print(f"   FALLO: {error}")
        print("   Si dice AccessDenied, a la policy le falta el ARN del bucket")
        print("   sin la barra: arn:aws:s3:::TU-BUCKET")
        return 1
    print(f"   ok, {len(todo)} archivos")

    paso(3, "Los partidos que hay")
    for carpeta in ("Datos/", "Informes/"):
        cuantos = len([x for x in todo if x["pathname"].startswith(carpeta)])
        print(f"   {carpeta:12} {cuantos}")
    if not any(x["pathname"].startswith("Datos/") for x in todo):
        print("   (todavia no subiste nada: aws s3 sync Datos s3://<bucket>/Datos)")

    if args.solo_leer:
        print("\n--solo-leer: no se prueba escribir.")
        print("Sin eso no se sabe si la app va a poder guardar un partido.")
        return 0

    paso(4, "Subir un archivo  [s3:PutObject]")
    try:
        subido = s3.subir(PRUEBA, CONTENIDO, "text/plain; charset=utf-8")
    except s3.ErrorDeS3 as error:
        print(f"   FALLO: {error}")
        print("   A la policy le falta s3:PutObject sobre arn:aws:s3:::TU-BUCKET/*")
        return 1
    print(f"   ok, etag {subido['etag']}")

    paso(5, "Pedir la cabeza  [s3:GetObject]")
    # es la llamada que mas se repite en la app: en cada pedido pregunta si la
    # sesion que tiene en memoria sigue siendo la ultima
    datos = s3.cabeza(PRUEBA)
    if datos is None:
        print("   FALLO: el archivo que acabo de subir no aparece.")
        return 1
    print(f"   ok, {datos['size']} bytes, etag {datos['etag']}")
    if datos["etag"] != subido["etag"]:
        print("   OJO: el etag no coincide con el de la subida.")

    paso(6, "Bajarlo y comparar  [s3:GetObject]")
    vuelta = s3.bajar(PRUEBA)
    if vuelta != CONTENIDO:
        print(f"   FALLO: volvio distinto ({len(vuelta)} bytes)")
        return 1
    print("   ok, identico byte por byte")

    paso(7, "Borrarlo  [s3:DeleteObject]")
    try:
        s3.borrar(PRUEBA)
    except s3.ErrorDeS3 as error:
        print(f"   FALLO: {error}")
        print("   (no es grave: borra prueba/ a mano desde la consola)")
        return 1
    print("   ok" + ("" if s3.cabeza(PRUEBA) is None else "  (pero sigue apareciendo)"))

    print("\n=== S3 esta bien. Lo que falle de aca en mas es de Lambda. ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
