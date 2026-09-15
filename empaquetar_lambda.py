"""Arma el .zip que se sube a Lambda.

    python empaquetar_lambda.py              solo arma el zip
    python empaquetar_lambda.py --subir      lo arma y lo sube a la funcion

Deja `lambda_voley.zip` en la carpeta del proyecto. Adentro va el codigo, la
pantalla, openpyxl, y los partidos e informes que estan comiteados -- esos
viajan como semilla de solo lectura, igual que en Vercel: se siguen viendo
aunque no esten en S3.

No se incluyen los tests ni nada que escriba en disco. Lambda descomprime el
paquete en una carpeta de solo lectura, asi que todo lo que se genere tiene
que ir a /tmp, que es lo que ya hace `almacenamiento.py` cuando detecta que
esta en serverless.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DESTINO = RAIZ / "lambda_voley.zip"

MODULOS = [
    "lambda_handler.py",
    "servidor_voley.py",
    "analisis_voley.py",
    "almacenamiento.py",
    "almacen_s3.py",
    "sesion_web.py",
    "notacion.py",
    "archivo_partidos.py",
    "estadisticas_jugadores.py",
    "generar_informe_volley.py",
    "valores_excel.py",
]

CARPETAS = ["public", "Datos", "Informes"]

# Lo que no tiene por que viajar: ocupa lugar y no lo usa nadie alojado.
BASURA = {"__pycache__", ".pytest_cache", ".DS_Store"}


def _sin_basura(carpeta: Path):
    """Los archivos de una carpeta, salteando cache y ocultos."""
    for ruta in sorted(carpeta.rglob("*")):
        if ruta.is_dir() or any(parte in BASURA for parte in ruta.parts):
            continue
        if ruta.name.startswith("."):
            continue
        yield ruta


def subir(funcion: str) -> int:
    """Manda el zip a Lambda. Devuelve 0 si salio bien.

    La cuenta necesita permiso `lambda:UpdateFunctionCode` sobre esa funcion.
    El usuario del CLI arranca solo con acceso a S3, asi que la primera vez
    esto falla con AccessDenied y hay que agregarselo (esta en DESPLIEGUE_AWS.md)."""
    print(f"\nSubiendo a la funcion {funcion}...")
    hecho = subprocess.run(
        ["aws", "lambda", "update-function-code",
         "--function-name", funcion,
         "--zip-file", f"fileb://{DESTINO}",
         "--output", "json"],
        capture_output=True, text=True, shell=(os.name == "nt"),
    )
    if hecho.returncode != 0:
        print(hecho.stderr.strip()[:600])
        return 1

    # el partido que este cargado no se pierde: vive en S3, y el primer pedido
    # despues de la actualizacion lo vuelve a leer de ahi
    print("Listo. La app ya esta corriendo el codigo nuevo.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subir", metavar="FUNCION", nargs="?", const="voley",
                        default="", help="subirlo a esa funcion (por defecto, voley)")
    args = parser.parse_args()

    faltan = [nombre for nombre in MODULOS if not (RAIZ / nombre).exists()]
    if faltan:
        print(f"Faltan modulos: {', '.join(faltan)}")
        return 1

    with tempfile.TemporaryDirectory() as temporal:
        armado = Path(temporal)

        # Las dependencias primero. Lambda ya trae boto3, pero no openpyxl.
        print("Instalando dependencias...")
        instalado = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(RAIZ / "requirements.txt"),
             "--target", str(armado), "--quiet", "--no-compile"],
            capture_output=True, text=True,
        )
        if instalado.returncode != 0:
            print(instalado.stderr.strip()[:500])
            return 1

        for nombre in MODULOS:
            shutil.copy2(RAIZ / nombre, armado / nombre)
        for nombre in CARPETAS:
            origen = RAIZ / nombre
            if origen.is_dir():
                shutil.copytree(origen, armado / nombre,
                                ignore=shutil.ignore_patterns(*BASURA, ".*"))

        print("Comprimiendo...")
        if DESTINO.exists():
            DESTINO.unlink()
        with zipfile.ZipFile(DESTINO, "w", zipfile.ZIP_DEFLATED) as zip_:
            for ruta in _sin_basura(armado):
                zip_.write(ruta, ruta.relative_to(armado).as_posix())

    tamano = DESTINO.stat().st_size / 1024 / 1024
    print(f"\nListo: {DESTINO.name}  ({tamano:.1f} MB)")
    if tamano > 50:
        # el limite de subida directa; mas grande hay que pasar por S3
        print("  Pasa de 50 MB: subilo a un bucket y cargalo desde ahi.")
    return subir(args.subir) if args.subir else 0


if __name__ == "__main__":
    raise SystemExit(main())
