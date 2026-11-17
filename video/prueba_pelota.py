"""Etapa 2: ¿se ve la pelota en mis videos? Es una prueba, no producto.

    python -m video probar-pelota partido1 [--desde 1:08:46] [--minutos 5]
                                           [--detectores movimiento,v4c,fastv1]

Toma el tramo con mas armadas marcadas (o el que se le pida), corre cada
detector sobre el ORIGINAL y deja en Videos/<nombre>/prueba_pelota/:

    candidatos_<detector>.csv   t, x, y, puntaje (lo mismo que pelota.csv de la etapa 4)
    armadas.mp4                 cada armada del tramo con lo que vio cada detector
    hoja_<detector>.png         recortes cuadro a cuadro de lo que tomo por pelota
    informe.md                  la tabla y lo que sale de ella

Que se mide. No hay "la pelota esta en tal pixel" anotado a mano: lo unico
anotado son los instantes de las armadas. Se mira el vuelo alrededor de cada
marca (desde VUELO_ANTES antes hasta VUELO_DESPUES despues: la M se aprieta
con el video andando y suele caer tarde) y se cuenta, por detector:

  - con algo: cuadros del vuelo con al menos un candidato. Es un techo: un
    candidato puede ser una mano.
  - en un arco: cuadros del vuelo con un candidato sobre un arco de caida
    libre (trayectorias.py). Una mano o una cabeza no dibujan una parabola:
    es lo que mas se parece a "se ve la pelota". Las hojas de recortes son
    para confirmarlo a ojo.
  - ruido: candidatos por cuadro fuera de los vuelos.
  - velocidad: cuadros por segundo de punta a punta (leer + detectar).
"""
from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import fusion, lectura, modelos, proyecto, trayectorias

VUELO_ANTES = 0.5
VUELO_DESPUES = 0.8
TOLERANCIA = 0.012           # del ancho: a cuanto de un arco un candidato es de el
MINIMO_EN_ARCO = 6           # cuadros para que un arco valga
META = 0.70                  # la del plan: menos que esto, no alcanza
COLORES = {"movimiento": (255, 200, 0), "v4c": (255, 0, 255), "fastv1": (0, 200, 255)}  # BGR


@dataclass
class Medida:
    """Lo que vio un detector en el vuelo de una armada."""
    t_armado: float
    cuadros: int
    con_algo: int
    en_arco: int
    arcos: list = field(default_factory=list)


# ----------------------------------------------------------------------
# Lo que no toca video: elegir el tramo y medir. Se prueba sin cv2.

def tramo_con_mas_armadas(tiempos: list[float], minutos: float) -> tuple[float, float]:
    """(desde, hasta) del tramo de esa duracion con mas armadas adentro."""
    largo = minutos * 60
    tiempos = sorted(tiempos)
    if not tiempos:
        raise ValueError("No hay armadas marcadas: marca algunas en la revision primero.")
    mejor, mejor_cuenta = tiempos[0], -1
    for inicio in tiempos:
        desde = inicio - VUELO_ANTES - 1.0
        cuenta = sum(1 for t in tiempos if desde + VUELO_ANTES <= t <= desde + largo - VUELO_DESPUES)
        if cuenta > mejor_cuenta:
            mejor, mejor_cuenta = desde, cuenta
    desde = max(0.0, mejor)
    return desde, desde + largo


def medir_vuelo(t_armado: float, tiempos_de_cuadro: list[float], por_cuadro: dict,
                ancho: int, alto: int, umbral: float) -> Medida:
    """Cuantos cuadros del vuelo de esa armada tienen algo, y cuantos algo
    sobre un arco. por_cuadro: {t: [Candidato]} (x, y de 0 a 1)."""
    desde, hasta = t_armado - VUELO_ANTES, t_armado + VUELO_DESPUES
    cuadros = [t for t in tiempos_de_cuadro if desde <= t <= hasta]
    puntos = [(c.t, c.x * ancho, c.y * alto, c.puntaje)
              for t in cuadros for c in por_cuadro.get(t, []) if c.puntaje >= umbral]
    con_algo = len({p[0] for p in puntos})
    arcos = trayectorias.buscar_arcos(puntos, tolerancia=TOLERANCIA * ancho,
                                      minimo=MINIMO_EN_ARCO)
    en_arco = len({p[0] for arco in arcos for p in arco.puntos})
    return Medida(t_armado, len(cuadros), con_algo, en_arco, arcos)


def ruido(tiempos_de_cuadro: list[float], por_cuadro: dict, vuelos: list[float],
          umbral: float) -> float:
    """Candidatos por cuadro fuera de los vuelos."""
    afuera = [t for t in tiempos_de_cuadro
              if not any(v - VUELO_ANTES <= t <= v + VUELO_DESPUES for v in vuelos)]
    if not afuera:
        return 0.0
    total = sum(1 for t in afuera for c in por_cuadro.get(t, []) if c.puntaje >= umbral)
    return total / len(afuera)


def porcentaje(parte: int, total: int) -> str:
    return f"{100 * parte / total:.0f} %" if total else "—"


def reloj(t: float) -> str:
    horas, resto = divmod(int(t), 3600)
    return (f"{horas}:{resto // 60:02d}:{resto % 60:02d}" if horas
            else f"{resto // 60}:{resto % 60:02d}")


def leer_reloj(texto: str) -> float:
    """'1:08:46' -> 4126; '4126.5' -> 4126.5."""
    partes = [float(p) for p in str(texto).split(":")]
    segundos = 0.0
    for parte in partes:
        segundos = segundos * 60 + parte
    return segundos


# ----------------------------------------------------------------------
# Lo que toca video

def crear_detector(nombre: str):
    from . import pelota
    if nombre == "movimiento":
        return pelota.DetectorMovimiento()
    modelo = modelos.CATALOGO.get(nombre)
    if modelo is None:
        raise ValueError(f"No conozco el detector {nombre!r}: "
                         f"movimiento o {', '.join(modelos.CATALOGO)}.")
    return pelota.DetectorModelo(modelo, modelos.asegurar(modelo))


def pasar(detector, original: Path, desde: float, hasta: float, avisar=None):
    """Corre el detector por el tramo. Devuelve ({t: [Candidato]}, tiempos de
    cuadro, cuadros por segundo de punta a punta)."""
    por_cuadro, tiempos = {}, []

    def contando():
        for t, cuadro in lectura.cuadros(original, desde, hasta):
            tiempos.append(t)
            if avisar and len(tiempos) % 500 == 0:
                avisar(t)
            yield t, cuadro

    inicio = time.perf_counter()
    for t, hallados in detector.detectar(contando()):
        por_cuadro[t] = hallados
    segundos = time.perf_counter() - inicio
    return por_cuadro, tiempos, len(tiempos) / segundos if segundos else 0.0


def guardar_candidatos(ruta: Path, nombre: str, por_cuadro: dict) -> None:
    with open(ruta, "w", newline="", encoding="utf-8") as archivo:
        escritor = csv.writer(archivo)
        escritor.writerow(["t", "x", "y", "puntaje", "detector"])
        for t in sorted(por_cuadro):
            for c in por_cuadro[t]:
                escritor.writerow([f"{c.t:.3f}", f"{c.x:.4f}", f"{c.y:.4f}", c.puntaje, nombre])


def desfase_con_el_proxy(original: Path, proxy: Path, t: float) -> int | None:
    """En cuantos cuadros difieren el original y el proxy en el instante t
    (deberia ser 0: los tiempos de las marcas salen del proxy y la deteccion
    corre sobre el original). None si no se pudo comparar."""
    import cv2
    import numpy as np
    originales = list(lectura.cuadros(original, t - 0.25, t + 0.25))
    # la primera copia desde t: una ventana mas angosta que un cuadro puede
    # quedar vacia
    copias = list(lectura.cuadros(proxy, t, t + 0.1))[:1]
    if not originales or not copias:
        return None
    _, copia = copias[0]
    alto, ancho = copia.shape[:2]
    errores = [float(np.mean((cv2.resize(o, (ancho, alto)).astype(np.float32)
                              - copia.astype(np.float32)) ** 2)) for _, o in originales]
    t_original = [tt for tt, _ in originales]
    t_copia = copias[0][0]
    mejor = t_original[errores.index(min(errores))]
    medio = sorted(t_original, key=lambda tt: abs(tt - t_copia))[0]
    return t_original.index(mejor) - t_original.index(medio)


def _marcar(cuadro, candidatos, arcos, color, ancho, alto, escala):
    import cv2
    en_arco = {(round(p[0], 4), round(p[1], 1), round(p[2], 1)) for a in arcos for p in a.puntos}
    for c in candidatos:
        x, y = int(c.x * ancho * escala), int(c.y * alto * escala)
        clave = (round(c.t, 4), round(c.x * ancho, 1), round(c.y * alto, 1))
        if clave in en_arco:
            cv2.circle(cuadro, (x, y), 7, color, 2)
            cv2.circle(cuadro, (x, y), 2, color, -1)
        else:
            cv2.circle(cuadro, (x, y), 4, color, 1)


def video_de_armadas(destino: Path, original: Path, medidas: dict, por_detector: dict,
                     ancho: int, alto: int, fps: float) -> None:
    """Las armadas del tramo seguidas, con lo de cada detector dibujado: un
    circulo grueso es un candidato sobre un arco, uno finito uno suelto."""
    import cv2
    import imageio_ffmpeg
    escala = 2
    tamano = (ancho * escala, alto * escala)
    escritor = imageio_ffmpeg.write_frames(str(destino), tamano, pix_fmt_in="bgr24", fps=fps,
                                           codec="libx264", quality=7, macro_block_size=8,
                                           ffmpeg_log_level="error")
    escritor.send(None)
    try:
        nombres = list(por_detector)
        primeras = medidas[nombres[0]]
        for n, medida in enumerate(primeras, start=1):
            t = medida.t_armado
            for tt, cuadro in lectura.cuadros(original, t - 1.5, t + 2.0):
                grande = cv2.resize(cuadro, tamano, interpolation=cv2.INTER_LINEAR)
                for nombre in nombres:
                    arcos = next(m.arcos for m in medidas[nombre] if m.t_armado == t)
                    _marcar(grande, por_detector[nombre].get(tt, []), arcos,
                            COLORES.get(nombre, (255, 255, 255)), ancho, alto, escala)
                en_vuelo = t - VUELO_ANTES <= tt <= t + VUELO_DESPUES
                texto = f"armada {n}/{len(primeras)}  {reloj(t)}  {'VUELO' if en_vuelo else ''}"
                cv2.putText(grande, texto, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
                cv2.putText(grande, texto, (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
                for i, nombre in enumerate(nombres):
                    cv2.putText(grande, nombre, (12, 58 + 26 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                                COLORES.get(nombre, (255, 255, 255)), 2)
                escritor.send(grande.tobytes())
    finally:
        escritor.close()


def hoja_de_recortes(destino: Path, original: Path, medidas: list[Medida], por_cuadro: dict,
                     ancho: int, alto: int) -> None:
    """Una fila por armada, un recorte cada dos cuadros del vuelo, centrado en
    lo que el detector tomo por pelota. Borde verde: sobre un arco. Naranja:
    candidato suelto (el de mas puntaje). Gris: nada (centrado donde el arco
    dice que estaria, si hay arco)."""
    import cv2
    import numpy as np
    lado, zoom, rotulo = 40, 2, 110
    filas = []
    for medida in medidas:
        cuadros = dict(lectura.cuadros(original, medida.t_armado - VUELO_ANTES,
                                       medida.t_armado + VUELO_DESPUES))
        celdas = []
        for tt in sorted(cuadros)[::2]:
            cuadro = cuadros[tt]
            sobre_arco = [p for a in medida.arcos for p in a.puntos if p[0] == tt]
            sueltos = por_cuadro.get(tt, [])
            if sobre_arco:
                cx, cy, borde = sobre_arco[0][1], sobre_arco[0][2], (0, 200, 0)
            elif sueltos:
                cx, cy, borde = sueltos[0].x * ancho, sueltos[0].y * alto, (0, 140, 255)
            else:
                cerca = [a for a in medida.arcos if a.desde - 0.3 <= tt <= a.hasta + 0.3]
                cx, cy = cerca[0].en(tt) if cerca else (ancho / 2, alto / 2)
                borde = (128, 128, 128)
            x0 = int(min(max(0, cx - lado / 2), ancho - lado))
            y0 = int(min(max(0, cy - lado / 2), alto - lado))
            recorte = cv2.resize(cuadro[y0:y0 + lado, x0:x0 + lado], (lado * zoom, lado * zoom),
                                 interpolation=cv2.INTER_NEAREST)
            cv2.rectangle(recorte, (0, 0), (lado * zoom - 1, lado * zoom - 1), borde, 3)
            celdas.append(recorte)
        fila = np.hstack(celdas) if celdas else np.zeros((lado * zoom, lado * zoom, 3), np.uint8)
        cabeza = np.zeros((lado * zoom, rotulo, 3), np.uint8)
        cv2.putText(cabeza, reloj(medida.t_armado), (6, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (255, 255, 255), 1)
        cv2.putText(cabeza, f"{medida.en_arco}/{medida.cuadros}", (6, 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 0), 1)
        filas.append(np.hstack([cabeza, fila]))
    ancho_hoja = max(f.shape[1] for f in filas)
    filas = [np.pad(f, ((0, 0), (0, ancho_hoja - f.shape[1]), (0, 0))) for f in filas]
    cv2.imwrite(str(destino), np.vstack(filas))


# ----------------------------------------------------------------------
def probar(nombre: str, base: Path = proyecto.CARPETA_VIDEOS, desde: float | None = None,
           minutos: float = 5.0, detectores: list[str] | None = None, avisar=print) -> Path:
    p = proyecto.abrir(nombre, base)
    fuente = p.fuente()
    original = Path(fuente["original"])
    if not original.is_file():
        raise proyecto.ErrorDeProyecto(f"No encuentro el original en {original}.")
    ancho, alto, fps = fuente["ancho"], fuente["alto"], fuente["fps"]
    detectores = detectores or ["movimiento", *modelos.CATALOGO]

    armadas = [a for a in fusion.fusionar(p.propuestas(), p.revision(), fuente["duracion"])
               if a["estado"] == "aceptada"]
    if desde is None:
        desde, hasta = tramo_con_mas_armadas([a["t_armado"] for a in armadas], minutos)
    else:
        hasta = desde + minutos * 60
    hasta = min(hasta, fuente["duracion"])
    vuelos = [a for a in armadas if desde + VUELO_ANTES <= a["t_armado"] <= hasta - VUELO_DESPUES]
    if not vuelos:
        raise proyecto.ErrorDeProyecto(f"No hay armadas marcadas entre {reloj(desde)} y {reloj(hasta)}.")
    avisar(f"Tramo {reloj(desde)} a {reloj(hasta)}: {len(vuelos)} armadas marcadas.")

    # una carpeta por tramo, para comparar corridas sin pisarlas
    salida = p.carpeta / "prueba_pelota" / f"{reloj(desde).replace(':', '-')}_{minutos:g}min"
    salida.mkdir(parents=True, exist_ok=True)
    desfase = desfase_con_el_proxy(original, p.ruta_proxy, vuelos[0]["t_armado"]) \
        if p.hay_proxy() else None

    # solo leer, para saber cuanto de la velocidad es del detector
    inicio = time.perf_counter()
    leidos = sum(1 for _ in lectura.cuadros(original, desde, hasta))
    lectura_fps = leidos / (time.perf_counter() - inicio)

    resultados, por_detector, medidas = {}, {}, {}
    for nombre_detector in detectores:
        detector = crear_detector(nombre_detector)
        avisar(f"{nombre_detector}: corriendo...")
        por_cuadro, tiempos, velocidad = pasar(
            detector, original, desde, hasta,
            avisar=lambda t: avisar(f"  {nombre_detector}: {reloj(t)}"))
        guardar_candidatos(salida / f"candidatos_{nombre_detector}.csv", nombre_detector, por_cuadro)
        umbral = 0.0 if nombre_detector == "movimiento" else detector.UMBRAL_BAJO
        lista = [medir_vuelo(a["t_armado"], tiempos, por_cuadro, ancho, alto, umbral)
                 for a in vuelos]
        estricto = None
        if nombre_detector != "movimiento":
            estricto = [medir_vuelo(a["t_armado"], tiempos, por_cuadro, ancho, alto, 0.5)
                        for a in vuelos]
        por_detector[nombre_detector], medidas[nombre_detector] = por_cuadro, lista
        resultados[nombre_detector] = {
            "velocidad": velocidad,
            "cuadros": sum(m.cuadros for m in lista),
            "con_algo": sum(m.con_algo for m in lista),
            "en_arco": sum(m.en_arco for m in lista),
            "en_arco_05": sum(m.en_arco for m in estricto) if estricto else None,
            "con_algo_05": sum(m.con_algo for m in estricto) if estricto else None,
            "ruido": ruido(tiempos, por_cuadro, [a["t_armado"] for a in vuelos], umbral),
        }
        hoja_de_recortes(salida / f"hoja_{nombre_detector}.png", original, lista, por_cuadro,
                         ancho, alto)

    avisar("Armando armadas.mp4...")
    video_de_armadas(salida / "armadas.mp4", original, medidas, por_detector, ancho, alto, fps)
    informe = escribir_informe(salida / "informe.md", fuente, desde, hasta, vuelos, resultados,
                               medidas, desfase, lectura_fps)
    return informe


def escribir_informe(destino: Path, fuente: dict, desde: float, hasta: float, vuelos: list,
                     resultados: dict, medidas: dict, desfase, lectura_fps: float) -> Path:
    lineas = [
        f"# ¿Se ve la pelota? — {fuente.get('titulo')}",
        "",
        f"Tramo {reloj(desde)} a {reloj(hasta)} del original "
        f"({fuente['ancho']}x{fuente['alto']}, {fuente['fps']:g} cuadros/s): "
        f"{len(vuelos)} armadas marcadas. El vuelo de cada una se mira desde "
        f"{VUELO_ANTES} s antes de la marca hasta {VUELO_DESPUES} s despues.",
        "",
        "| Detector | En un arco | En un arco (corte 0,5) | Con algo | Con algo (corte 0,5) "
        "| Ruido (cand./cuadro) | Velocidad |",
        "|---|---|---|---|---|---|---|",
    ]
    for nombre, r in resultados.items():
        def estricto(clave):
            return porcentaje(r[clave], r["cuadros"]) if r[clave] is not None else "—"
        lineas.append(f"| {nombre} | **{porcentaje(r['en_arco'], r['cuadros'])}** | "
                      f"{estricto('en_arco_05')} | {porcentaje(r['con_algo'], r['cuadros'])} | "
                      f"{estricto('con_algo_05')} | {r['ruido']:.1f} | "
                      f"{r['velocidad']:.0f} cuadros/s |")
    lineas += [
        "",
        f"Leer el video solo, sin detectar: {lectura_fps:.0f} cuadros/s.",
        "",
        "- **En un arco**: cuadros del vuelo con un candidato sobre un arco de caida libre. "
        "Es lo que mas se parece a \"se ve la pelota\". La meta del plan es "
        f"{100 * META:.0f} %.",
        "- **Con algo**: cuadros del vuelo con al menos un candidato (techo: puede ser una mano).",
        "- **Corte 0,5**: lo mismo, con el umbral que usa el autor de los modelos.",
        "",
        "## Por armada (cuadros en un arco / cuadros del vuelo)",
        "",
        "| Armada | " + " | ".join(medidas) + " |",
        "|---|" + "---|" * len(medidas),
    ]
    for i, a in enumerate(vuelos):
        celdas = [f"{medidas[n][i].en_arco}/{medidas[n][i].cuadros}" for n in medidas]
        lineas.append(f"| {reloj(a['t_armado'])} | " + " | ".join(celdas) + " |")
    lineas += ["", f"Desfase entre el original y el proxy: "
               + ("no se pudo medir" if desfase is None else f"{desfase} cuadros"), ""]
    destino.write_text("\n".join(lineas), encoding="utf-8")
    return destino
