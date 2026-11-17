"""La consola del analisis de video. Se corre desde la carpeta del proyecto:

    python -m video nuevo [videos...]   da de alta y arma la copia liviana (proxy)
    python -m video lista               los videos dados de alta
    python -m video servir              abre las pantallas (revision y galeria)

"nuevo" sin nada da de alta los videos sueltos en Videos/ y retoma los que
quedaron sin proxy (por ejemplo, porque se corto con Ctrl+C).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import proyecto


def _reloj(segundos: float) -> str:
    segundos = int(segundos)
    horas, resto = divmod(segundos, 3600)
    return (f"{horas}:{resto // 60:02d}:{resto % 60:02d}" if horas
            else f"{resto // 60}:{resto % 60:02d}")


def _armar_proxy(lectura, p: proyecto.Proyecto) -> None:
    fuente = p.fuente()
    original = Path(fuente["original"])
    if not original.is_file():
        raise proyecto.ErrorDeProyecto(
            f"{p.nombre}: no encuentro el original en {original}. Si lo moviste, "
            f"volve a correr: python -m video nuevo <ruta nueva> --nombre {p.nombre}")

    def avisar(hecho, total, velocidad):
        porcentaje = min(100, int(100 * hecho / total)) if total else 0
        rapidez = f"  ({velocidad})" if velocidad and velocidad != "N/A" else ""
        print(f"\r  proxy {porcentaje:3d}%  {_reloj(hecho)} de {_reloj(total)}{rapidez}   ",
              end="", flush=True)

    print(f"  armando el proxy de {_reloj(fuente['duracion'])} de video...")
    lectura.hacer_proxy(original, p.ruta_proxy, fuente["duracion"], avisar)
    print(f"\r  proxy listo: {p.ruta_proxy}".ljust(60))


def _nuevo(args) -> int:
    from . import lectura   # pide imageio-ffmpeg: solo lo necesita "nuevo"

    if args.nombre and len(args.videos) != 1:
        print("--nombre va con un solo video.")
        return 2
    if args.videos:
        altas = [(Path(v), args.nombre) for v in args.videos]
        retomar = []
    else:
        altas = [(v, None) for v in proyecto.videos_sin_alta(args.carpeta)]
        retomar = [p for p in proyecto.listar(args.carpeta) if not p.hay_proxy()]
        if not altas and not retomar:
            print(f"No hay videos nuevos en {args.carpeta}. Copia el video ahi, "
                  f"o pasale la ruta: python -m video nuevo <video>")
            return 0

    fallas = 0
    try:
        for original, nombre in altas:
            print(f"{original.name}")
            try:
                if not original.is_file():
                    raise proyecto.ErrorDeProyecto(f"No existe el archivo {original}.")
                p = proyecto.crear(original, lectura.metadatos(original), nombre, args.carpeta)
                fuente = p.fuente()
                print(f"  {fuente['ancho']}x{fuente['alto']}, {fuente['fps']:g} cuadros/s, "
                      f"{_reloj(fuente['duracion'])}  ->  {p.nombre}")
                if p.hay_proxy():
                    print("  ya estaba dado de alta y con proxy.")
                else:
                    _armar_proxy(lectura, p)
            except (proyecto.ErrorDeProyecto, lectura.ErrorDeLectura) as error:
                print(f"  {error}")
                fallas += 1
        for p in retomar:
            print(f"{p.nombre} (sin proxy)")
            try:
                _armar_proxy(lectura, p)
            except (proyecto.ErrorDeProyecto, lectura.ErrorDeLectura) as error:
                print(f"  {error}")
                fallas += 1
    except lectura.FaltaFfmpeg as error:
        print(error)
        return 2
    except KeyboardInterrupt:
        print("\nCortado. Lo que quedo sin proxy se retoma con: python -m video nuevo")
        return 130
    return 1 if fallas else 0


def _lista(args) -> int:
    proyectos = proyecto.listar(args.carpeta)
    if not proyectos:
        print(f"No hay videos dados de alta en {args.carpeta}.")
        return 0
    from . import fusion
    for p in proyectos:
        try:
            fuente, revision = p.fuente(), p.revision()
            armadas = fusion.fusionar(p.propuestas(), revision, fuente.get("duracion"))
        except proyecto.ErrorDeProyecto as error:
            print(f"{p.nombre:30}  {error}")
            continue
        aceptadas = sum(a["estado"] == "aceptada" for a in armadas)
        pendientes = sum(a["estado"] == "pendiente" for a in armadas)
        proxy = "" if p.hay_proxy() else "  SIN PROXY"
        print(f"{p.nombre:30}  {_reloj(fuente.get('duracion') or 0):>8}  "
              f"{aceptadas:4d} aceptadas  {pendientes:4d} pendientes  "
              f"{len(revision.get('sets', []))} sets{proxy}")
    return 0


def _servir(args) -> int:
    from . import servidor_video
    return servidor_video.servir(args.puerto, not args.sin_navegador, args.carpeta)


def main(argv=None) -> int:
    # En Windows, con la salida redirigida, un nombre de archivo raro no
    # puede tumbar el programa por no poder imprimirse.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    parser = argparse.ArgumentParser(prog="python -m video",
                                     description="Analisis de video de las armadas.")
    parser.add_argument("--carpeta", type=Path, default=proyecto.CARPETA_VIDEOS,
                        help="donde viven los videos (por defecto: Videos/ del proyecto)")
    ordenes = parser.add_subparsers(dest="orden", required=True)

    nuevo = ordenes.add_parser("nuevo", help="dar de alta videos y armar su proxy")
    nuevo.add_argument("videos", nargs="*", type=Path,
                       help="sin nada: los sueltos en Videos/ y los que quedaron sin proxy")
    nuevo.add_argument("--nombre", help="nombre de la carpeta (con un solo video)")
    nuevo.set_defaults(hacer=_nuevo)

    ordenes.add_parser("lista", help="los videos dados de alta").set_defaults(hacer=_lista)

    servir = ordenes.add_parser("servir", help="abrir las pantallas de revision y galeria")
    servir.add_argument("--puerto", type=int, default=8001)
    servir.add_argument("--sin-navegador", action="store_true")
    servir.set_defaults(hacer=_servir)

    args = parser.parse_args(argv)
    return args.hacer(args)


if __name__ == "__main__":
    sys.exit(main())
