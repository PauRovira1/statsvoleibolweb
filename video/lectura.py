"""Del archivo de video a lo que necesitan las pantallas: metadatos y proxy.

Usa el ffmpeg que trae imageio-ffmpeg (python -m pip install -r
requirements-video.txt). No usa cv2: el cv2 de pip en Windows no escribe
H.264, que es lo unico que reproducen todos los navegadores, y para leer los
metadatos alcanza con ffmpeg. cv2 entra recien con la deteccion (etapa 2).

El proxy es la copia que reproducen las pantallas:
  - H.264 a 720p, porque el original puede venir en HEVC (no todos los
    navegadores lo abren) y en 4K (pesado para ir y venir);
  - un cuadro clave por segundo, porque saltar a un instante obliga a
    decodificar desde el cuadro clave anterior, y un celular pone uno cada
    varios segundos;
  - las marcas de tiempo del original, sin re-muestrear a un ritmo fijo: un
    instante del proxy es el mismo instante del original, que es en lo que
    estan todos los tiempos de este paquete.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

ALTO_DEL_PROXY = 720


class FaltaFfmpeg(RuntimeError):
    pass


class ErrorDeLectura(RuntimeError):
    pass


def ffmpeg() -> str:
    try:
        import imageio_ffmpeg
    except ImportError:
        raise FaltaFfmpeg("Falta ffmpeg. Instalalo con: "
                          "python -m pip install -r requirements-video.txt") from None
    try:
        return imageio_ffmpeg.get_ffmpeg_exe()
    except RuntimeError as error:
        raise FaltaFfmpeg(f"imageio-ffmpeg no encuentra su ffmpeg: {error}") from None


def hay_ffmpeg() -> bool:
    try:
        ffmpeg()
    except FaltaFfmpeg:
        return False
    return True


def metadatos(ruta: Path) -> dict:
    """Duracion, cuadros por segundo, tamano en pantalla y rotacion."""
    ffmpeg()
    import imageio_ffmpeg
    # read_frames devuelve primero los metadatos y despues los cuadros; se
    # cierra apenas da los metadatos, sin decodificar nada.
    lector = imageio_ffmpeg.read_frames(str(ruta))
    try:
        meta = next(lector)
    except (OSError, RuntimeError, StopIteration) as error:
        raise ErrorDeLectura(f"ffmpeg no pudo abrir {Path(ruta).name}: {error}") from None
    finally:
        lector.close()

    duracion, fps, tamano = meta.get("duration"), meta.get("fps"), meta.get("size")
    if not duracion or duracion <= 0 or not fps or fps <= 0 or not tamano:
        raise ErrorDeLectura(
            f"{Path(ruta).name}: ffmpeg no informa duracion o cuadros por segundo. "
            f"Es un video?")
    return {
        "duracion": round(float(duracion), 3),
        "fps": round(float(fps), 3),
        # el tamano ya girado: es como se ve, y como lo ve el navegador
        "ancho": int(tamano[0]),
        "alto": int(tamano[1]),
        "rotacion": int(meta.get("rotate") or 0),
        "codec": meta.get("codec"),
    }


def comando_del_proxy(original: Path, destino: Path) -> list[str]:
    return [
        ffmpeg(), "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
        "-i", str(original),
        # el primer video y, si hay, el primer audio (el silbato sirve)
        "-map", "0:v:0", "-map", "0:a:0?",
        # a 720 de alto, o menos si el original es mas chico; alto par, que
        # es lo que pide H.264
        "-vf", f"scale=-2:'min({ALTO_DEL_PROXY},trunc(ih/2)*2)'",
        "-fps_mode", "vfr",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
        "-force_key_frames", "expr:gte(t,n_forced*1)",
        "-c:a", "aac", "-b:a", "96k",
        # el indice al principio: el navegador puede empezar sin bajar todo
        "-movflags", "+faststart",
        "-progress", "pipe:1", "-nostats",
        str(destino),
    ]


def _segundos(texto: str) -> float | None:
    """'00:01:02.500000' -> 62.5. Al arrancar ffmpeg informa 'N/A'."""
    try:
        horas, minutos, segundos = texto.strip().split(":")
        return int(horas) * 3600 + int(minutos) * 60 + float(segundos)
    except ValueError:
        return None


def hacer_proxy(original: Path, destino: Path, duracion: float, avisar=None) -> None:
    """Arma el proxy. Escribe a un .parcial y lo renombra solo si termino
    bien: un proxy cortado a la mitad nunca queda con el nombre del bueno.
    avisar(hecho, total, velocidad) se llama a medida que avanza."""
    destino = Path(destino)
    parcial = destino.with_name(destino.stem + ".parcial" + destino.suffix)
    with tempfile.TemporaryFile() as errores, \
            subprocess.Popen(comando_del_proxy(original, parcial),
                             stdout=subprocess.PIPE, stderr=errores,
                             text=True, encoding="utf-8", errors="replace") as proceso:
        try:
            velocidad = None
            for linea in proceso.stdout:
                clave, _, valor = linea.strip().partition("=")
                if clave == "speed":
                    velocidad = valor
                elif clave == "out_time" and avisar is not None:
                    hecho = _segundos(valor)
                    if hecho is not None:
                        avisar(hecho, duracion, velocidad)
            proceso.wait()
        except BaseException:
            # Ctrl+C o cualquier otra cosa: que no quede ffmpeg andando ni
            # un archivo a medias
            proceso.kill()
            proceso.wait()
            _borrar(parcial)
            raise
        if proceso.returncode != 0:
            errores.seek(0)
            detalle = errores.read().decode("utf-8", "replace").strip()[-800:]
            _borrar(parcial)
            raise ErrorDeLectura(f"ffmpeg fallo armando el proxy ({proceso.returncode}): {detalle}")

    # Que no haya quedado corto: un disco lleno puede terminar "bien" con
    # medio video.
    obtenida = metadatos(parcial)["duracion"]
    if abs(obtenida - duracion) > max(1.0, duracion * 0.01):
        _borrar(parcial)
        raise ErrorDeLectura(
            f"El proxy salio de {obtenida:.1f} s y el original dura {duracion:.1f} s.")
    os.replace(parcial, destino)


def _borrar(ruta: Path) -> None:
    try:
        Path(ruta).unlink(missing_ok=True)
    except PermissionError:
        pass    # si Windows lo tiene tomado, se pisa la proxima vez
