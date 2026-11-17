"""De candidatos sueltos a arcos: la pelota, entre toque y toque, cae libre.

En la imagen, un tramo corto de esa caida se ajusta bien con x(t) lineal e
y(t) cuadratica: la perspectiva lo deforma, pero en un segundo y medio poco.
Se busca con RANSAC: se prueban arcos que pasan por tres candidatos de
cuadros distintos y gana el que explica mas cuadros. Ese arco se queda con
sus cuadros (la pelota esta en un solo lugar a la vez) y se busca el
siguiente entre lo que queda.

Dos cosas que una curva perfecta no garantiza:
  - algo quieto (una lampara, un logo) tambien "ajusta": se pide que se mueva;
  - una curva que dobla para arriba no es caida libre: la aceleracion vertical
    tiene que ser hacia abajo (en la imagen, y crece para abajo) y de un
    tamano posible. Sin la calibracion de la etapa 3 el rango es ancho a
    proposito: solo descarta lo que seguro no es la pelota.

Lo que esto no puede: un pedazo corto (un tercio de segundo) de cualquier
movimiento suave se parece a una recta y entra como arco con poca gravedad.
Una curva entera que no cae no pasa, pero sus pedazos si. Con la gravedad de
la cancha calibrada (etapa 3) el rango se puede cerrar; mientras tanto, lo que
diga un arco se confirma a ojo.

Python puro, sin numpy: se prueba en cualquier maquina. Unidades: segundos y
pixeles del cuadro original.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

# Lo que cae en el rango es "puede ser la pelota". Una camara de celular a
# 640 de ancho ve la gravedad como unos 200 px/s^2 en la otra punta de la
# cancha y 500 o mas cerca; con 1080 de ancho, un 70 % mas.
GRAVEDAD = (50.0, 4000.0)       # px/s^2, hacia abajo
VELOCIDAD_MINIMA = 40.0          # px/s: menos que esto es algo quieto
DENSIDAD_MINIMA = 0.5            # cuadros explicados / cuadros que dura el arco


@dataclass
class Arco:
    t0: float                         # los tiempos se miden desde aca (estabilidad)
    x: tuple[float, float]            # x(t) = x0 + x1*(t - t0)
    y: tuple[float, float, float]     # y(t) = y0 + y1*(t - t0) + y2*(t - t0)^2
    puntos: list = field(default_factory=list)   # (t, x, y, puntaje...), uno por cuadro

    def en(self, t: float) -> tuple[float, float]:
        d = t - self.t0
        return self.x[0] + self.x[1] * d, self.y[0] + self.y[1] * d + self.y[2] * d * d

    @property
    def desde(self) -> float:
        return self.puntos[0][0]

    @property
    def hasta(self) -> float:
        return self.puntos[-1][0]

    @property
    def gravedad(self) -> float:
        """La aceleracion vertical en px/s^2 (positiva es hacia abajo)."""
        return 2 * self.y[2]


def _resolver(matriz: list[list[float]], vector: list[float]) -> list[float] | None:
    """Eliminacion de Gauss con pivoteo, para sistemas de 2x2 y 3x3."""
    n = len(vector)
    a = [list(fila) + [v] for fila, v in zip(matriz, vector)]
    for col in range(n):
        pivote = max(range(col, n), key=lambda f: abs(a[f][col]))
        if abs(a[pivote][col]) < 1e-12:
            return None
        a[col], a[pivote] = a[pivote], a[col]
        for f in range(n):
            if f != col:
                factor = a[f][col] / a[col][col]
                for c in range(col, n + 1):
                    a[f][c] -= factor * a[col][c]
    return [a[f][n] / a[f][f] for f in range(n)]


def ajustar(puntos: list, t0: float | None = None) -> Arco | None:
    """El arco de minimos cuadrados por esos puntos (al menos 3, en cuadros
    distintos). None si no se puede (todos en el mismo instante)."""
    if len(puntos) < 3:
        return None
    if t0 is None:
        t0 = sum(p[0] for p in puntos) / len(puntos)
    sumas = [0.0] * 5            # sum d^k, k = 0..4
    sx = [0.0, 0.0]              # sum x*d^k, k = 0..1
    sy = [0.0, 0.0, 0.0]         # sum y*d^k, k = 0..2
    for p in puntos:
        d = p[0] - t0
        potencia = 1.0
        for k in range(5):
            sumas[k] += potencia
            if k < 2:
                sx[k] += p[1] * potencia
            if k < 3:
                sy[k] += p[2] * potencia
            potencia *= d
    coef_x = _resolver([[sumas[0], sumas[1]], [sumas[1], sumas[2]]], sx)
    coef_y = _resolver([[sumas[0], sumas[1], sumas[2]],
                        [sumas[1], sumas[2], sumas[3]],
                        [sumas[2], sumas[3], sumas[4]]], sy)
    if coef_x is None or coef_y is None:
        return None
    return Arco(t0=t0, x=tuple(coef_x), y=tuple(coef_y))


def _uno(azar: random.Random, candidatos: list):
    """Un candidato del cuadro para probar arcos, mas seguido los de mas
    puntaje (el cuarto valor, si hay). Con varios dudosos por cuadro, elegir
    parejo casi nunca junta tres pelotas; contarlos despues no molesta."""
    pesos = [max(p[3], 1e-3) if len(p) > 3 else 1.0 for p in candidatos]
    return azar.choices(candidatos, weights=pesos)[0]


def _explicados(arco: Arco, por_cuadro: dict, tiempos: list[float], tolerancia: float) -> list:
    """El candidato de cada cuadro que cae sobre el arco (el mas cercano), si hay."""
    elegidos = []
    for t in tiempos:
        ax, ay = arco.en(t)
        mejor, distancia = None, tolerancia
        for p in por_cuadro[t]:
            d = ((p[1] - ax) ** 2 + (p[2] - ay) ** 2) ** 0.5
            if d <= distancia:
                mejor, distancia = p, d
        if mejor is not None:
            elegidos.append(mejor)
    return elegidos


def _es_plausible(arco: Arco, gravedad: tuple[float, float], velocidad_minima: float,
                  densidad_minima: float, cuadros_por_segundo: float) -> bool:
    if not gravedad[0] <= arco.gravedad <= gravedad[1]:
        return False
    duracion = arco.hasta - arco.desde
    if duracion <= 0:
        return False
    recorrido = sum(((b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2) ** 0.5
                    for a, b in zip(arco.puntos, arco.puntos[1:]))
    if recorrido / duracion < velocidad_minima:
        return False
    esperados = duracion * cuadros_por_segundo + 1
    return len(arco.puntos) / esperados >= densidad_minima


def buscar_arcos(candidatos: list, tolerancia: float, minimo: int = 6, vueltas: int = 300,
                 extension: float = 0.6, gravedad: tuple[float, float] = GRAVEDAD,
                 velocidad_minima: float = VELOCIDAD_MINIMA,
                 densidad_minima: float = DENSIDAD_MINIMA, semilla: int = 0) -> list[Arco]:
    """Los arcos que explican los candidatos, del que mas explica al que menos.

    candidatos: (t, x, y, ...) en segundos y pixeles; varios por cuadro.
    tolerancia: a cuantos pixeles del arco un candidato cuenta como de el.
    minimo: cuantos cuadros tiene que explicar un arco para valer.
    extension: hasta cuanto mas alla de los tres puntos de prueba se cuentan
    cuadros (lejos de ellos la parabola deja de valer).
    """
    azar = random.Random(semilla)
    por_cuadro: dict[float, list] = {}
    for p in candidatos:
        por_cuadro.setdefault(p[0], []).append(p)
    tiempos_todos = sorted(por_cuadro)
    if len(tiempos_todos) < 2:
        return []
    pasos = [b - a for a, b in zip(tiempos_todos, tiempos_todos[1:])]
    paso = sorted(pasos)[len(pasos) // 2] or 1 / 30
    cuadros_por_segundo = 1 / paso

    def plausible(arco):
        return _es_plausible(arco, gravedad, velocidad_minima, densidad_minima,
                             cuadros_por_segundo)

    minimo = max(minimo, 3)
    arcos, tomados = [], set()
    while True:
        libres = [t for t in tiempos_todos if t not in tomados]
        if len(libres) < minimo:
            break
        # Lo plausible se mira en cada prueba y no al final: si lo que mas
        # cuadros junta es una lampara, hay que seguir buscando la pelota.
        mejor = None
        for _ in range(vueltas):
            tres = sorted(azar.sample(libres, 3))
            arco = ajustar([_uno(azar, por_cuadro[t]) for t in tres])
            if arco is None or not gravedad[0] <= arco.gravedad <= gravedad[1]:
                continue
            cerca = [t for t in libres if tres[0] - extension <= t <= tres[2] + extension]
            arco.puntos = _explicados(arco, por_cuadro, cerca, tolerancia)
            if len(arco.puntos) >= max(minimo, len(mejor.puntos) + 1 if mejor else 0) \
                    and plausible(arco):
                mejor = arco
        if mejor is None:
            break
        # se reajusta con todos los que explica, mientras no explique menos
        for _ in range(2):
            refinado = ajustar(mejor.puntos)
            if refinado is None:
                break
            cerca = [t for t in libres
                     if mejor.desde - extension <= t <= mejor.hasta + extension]
            refinado.puntos = _explicados(refinado, por_cuadro, cerca, tolerancia)
            if len(refinado.puntos) < len(mejor.puntos) or not plausible(refinado):
                break
            mejor = refinado
        arcos.append(mejor)
        tomados.update(t for t in libres if mejor.desde <= t <= mejor.hasta)
    return arcos
