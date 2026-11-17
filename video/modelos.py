"""Los modelos de pelota ya entrenados: de donde salen, su huella y donde quedan.

Los pesos no entran al repo (no son nuestros y no hace falta versionarlos): se
bajan con

    python -m video modelos

y antes de usarlos se verifica la huella SHA-256. La direccion apunta a un
commit fijo y no a "master": si el autor sube otra version con el mismo
nombre, la huella no coincide y se avisa, en vez de medir otra cosa sin
saberlo.

Origen: asigatchov/fast-volleyball-tracking-inference, licencia MIT (que
segun su README cubre tambien los pesos de models/). Entrenados con voley de
playa: lo que valen con nuestros videos lo mide la etapa 2, no su tabla.
"""
from __future__ import annotations

import hashlib
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

CARPETA = Path(__file__).resolve().parent / "modelos"
COMMIT = "c3864156a4dfbd5af3f00f427ab0fc4bfe7af5b5"
ORIGEN = ("https://raw.githubusercontent.com/asigatchov/fast-volleyball-tracking-inference/"
          f"{COMMIT}/models/")


@dataclass(frozen=True)
class Modelo:
    nombre: str          # el corto, el que se escribe en la consola
    archivo: str
    sha256: str
    tamano: int
    cuadros: int         # cuantos cuadros seguidos entran juntos
    ancho: int           # a que tamano se achica cada cuadro
    alto: int
    descripcion: str


CATALOGO = {
    "v4c": Modelo(
        nombre="v4c", archivo="VballNetV4c_seq9_grayscale_20260908_213829.onnx",
        sha256="8eea11cc5c881fa008ec55b0f5732ab79f2e0e1833d7f586e680f3aaa98e4b8c",
        tamano=987155, cuadros=9, ancho=512, alto=288,
        descripcion="el mas preciso de su tabla (F1 0,90 en playa)"),
    "fastv1": Modelo(
        nombre="fastv1", archivo="VballNetFastV1_seq9_grayscale_233_h288_w512.onnx",
        sha256="a37d2f082c1821c31da10b4d3356788ed8ec0e1ba1c7d4fcbaf69f76925b0ff8",
        tamano=50199, cuadros=9, ancho=512, alto=288,
        descripcion="el mas liviano y rapido (F1 0,80 en playa)"),
}


class ErrorDeModelo(RuntimeError):
    pass


def ruta(modelo: Modelo, carpeta: Path = CARPETA) -> Path:
    return Path(carpeta) / modelo.archivo


def huella(ruta_archivo: Path) -> str:
    calculo = hashlib.sha256()
    with open(ruta_archivo, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            calculo.update(bloque)
    return calculo.hexdigest()


def esta_bien(modelo: Modelo, carpeta: Path = CARPETA) -> bool:
    archivo = ruta(modelo, carpeta)
    return archivo.is_file() and huella(archivo) == modelo.sha256


def asegurar(modelo: Modelo, carpeta: Path = CARPETA) -> Path:
    """La ruta del modelo, si esta y es el que tiene que ser."""
    archivo = ruta(modelo, carpeta)
    if not archivo.is_file():
        raise ErrorDeModelo(f"Falta el modelo {modelo.nombre}. Bajalo con: python -m video modelos")
    if huella(archivo) != modelo.sha256:
        raise ErrorDeModelo(f"{archivo.name} no es el que tiene que ser (la huella no coincide). "
                            f"Borralo y volve a correr: python -m video modelos")
    return archivo


def bajar(modelo: Modelo, carpeta: Path = CARPETA, abrir=urllib.request.urlopen) -> Path:
    """Baja el modelo y lo deja solo si la huella coincide. Se escribe a un
    .parcial y se renombra al final: uno cortado o cambiado nunca queda con
    el nombre del bueno."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = ruta(modelo, carpeta)
    if esta_bien(modelo, carpeta):
        return destino
    parcial = destino.with_name(destino.name + ".parcial")
    pedido = urllib.request.Request(ORIGEN + modelo.archivo,
                                    headers={"User-Agent": "statsvoleibolweb-video"})
    try:
        with abrir(pedido, timeout=60) as respuesta, open(parcial, "wb") as archivo:
            while True:
                bloque = respuesta.read(1 << 16)
                if not bloque:
                    break
                archivo.write(bloque)
        obtenida = huella(parcial)
        if obtenida != modelo.sha256:
            raise ErrorDeModelo(
                f"{modelo.archivo}: la huella no coincide (llego {obtenida[:12]}..., se esperaba "
                f"{modelo.sha256[:12]}...). No se usa.")
        os.replace(parcial, destino)
    finally:
        parcial.unlink(missing_ok=True)
    return destino
