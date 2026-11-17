"""Donde puede estar la pelota en cada cuadro: candidatos (t, x, y, puntaje).

x e y van en fraccion del ancho y del alto del cuadro (0 a 1): asi no
dependen de a que tamano se proceso. Cada detector da varios candidatos por
cuadro, con su puntaje, y no decide cual es la pelota: eso lo resuelven las
trayectorias (una pelota cae libre; un brazo o una cabeza, no).

Dos detectores con la misma salida:

  - Movimiento: con la camara quieta, lo que cambia entre un cuadro y los de
    al lado y tiene tamano de pelota. Barato, y anda justo donde importa: la
    pelota en el aire contra el techo. Se confunde cerca de los jugadores.
  - Modelo: las redes VballNet (ONNX, ver modelos.py), que miran 9 cuadros
    seguidos en gris a 512x288 y devuelven un mapa de calor por cuadro.

Este modulo y lectura.py son los unicos que tocan cv2 y el modelo (regla 6
del plan): numpy, cv2 y onnxruntime se importan al crear el detector.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Candidato:
    t: float
    x: float          # 0 a 1, del ancho
    y: float          # 0 a 1, del alto
    puntaje: float


class DetectorMovimiento:
    """Diferencia de tres cuadros: un pixel se mueve en el cuadro t si cambio
    respecto del anterior Y respecto del siguiente. Con dos cuadros solos
    quedaria tambien la "sombra" de donde estaba la pelota antes.

    Las medidas estan en fraccion del alto del cuadro, para que valgan igual a
    360 que a 1080 de alto: una pelota en el aire, entre cerca y lejos de la
    camara, mide de 1 a 3 % del alto.
    """

    nombre = "movimiento"

    UMBRAL = 14                 # diferencia de gris (0 a 255) que cuenta como cambio
    LADO_MINIMO = 0.006         # del alto: menos es ruido de la compresion
    LADO_MAXIMO = 0.06          # del alto: mas es un jugador
    MAXIMO_POR_CUADRO = 6

    def __init__(self):
        import cv2
        import numpy
        self.cv2, self.np = cv2, numpy

    def _gris(self, cuadro):
        gris = self.cv2.cvtColor(cuadro, self.cv2.COLOR_BGR2GRAY)
        return self.cv2.GaussianBlur(gris, (3, 3), 0)

    def _candidatos(self, t, antes, ahora, despues, color):
        cv2, np = self.cv2, self.np
        alto, ancho = ahora.shape
        cambio = (cv2.absdiff(ahora, antes) > self.UMBRAL) & (cv2.absdiff(despues, ahora) > self.UMBRAL)
        mascara = cv2.dilate(cambio.astype(np.uint8), np.ones((3, 3), np.uint8))
        cantidad, etiquetas, datos, centros = cv2.connectedComponentsWithStats(mascara, connectivity=8)
        lado_min, lado_max = self.LADO_MINIMO * alto, self.LADO_MAXIMO * alto
        hallados = []
        for i in range(1, cantidad):
            x0, y0, w, h, area = datos[i]
            if not (lado_min <= max(w, h) <= lado_max):
                continue
            # Compacta (una pelota movida es un ovalo, no una linea) y aislada:
            # alrededor de una pelota en el aire no se mueve nada; alrededor de
            # una mano, se mueve el resto del jugador.
            compacta = area / float(w * h)
            margen = int(max(w, h))
            xa, ya = max(0, x0 - margen), max(0, y0 - margen)
            xb, yb = min(ancho, x0 + w + margen), min(alto, y0 + h + margen)
            alrededor = int(mascara[ya:yb, xa:xb].sum()) - int(area)
            caja = (xb - xa) * (yb - ya) - w * h
            aislada = 1.0 - min(1.0, alrededor / max(1.0, 0.25 * caja))
            # La pelota es amarilla y azul: un poco de color suma. Las luces del
            # techo y las paredes claras son grises.
            trozo = color[y0:y0 + h, x0:x0 + w]
            saturacion = float(cv2.cvtColor(trozo, cv2.COLOR_BGR2HSV)[..., 1].mean()) / 255.0
            puntaje = 0.45 * aislada + 0.35 * compacta + 0.20 * min(1.0, 2 * saturacion)
            cx, cy = centros[i]
            hallados.append(Candidato(t, (cx + 0.5) / ancho, (cy + 0.5) / alto, round(puntaje, 3)))
        hallados.sort(key=lambda c: -c.puntaje)
        return hallados[:self.MAXIMO_POR_CUADRO]

    def detectar(self, cuadros):
        """(t, [Candidato]) por cada cuadro que entra, salvo el primero y el
        ultimo (les falta un vecino)."""
        anterior = None      # (t, gris, color)
        actual = None
        for t, cuadro in cuadros:
            siguiente = (t, self._gris(cuadro), cuadro)
            if anterior is not None:
                yield actual[0], self._candidatos(actual[0], anterior[1], actual[1],
                                                  siguiente[1], actual[2])
            anterior, actual = actual, siguiente


class DetectorModelo:
    """VballNet sobre ONNX Runtime, en CPU.

    Entran 9 cuadros seguidos (gris, achicados a 512x288, de 0 a 1) y salen 9
    mapas de calor, uno por cuadro, como en el script de inferencia del autor.
    Los grupos de 9 no se pisan. El ultimo grupo, si es mas corto, se completa
    repitiendo su primer cuadro y se toman solo las salidas de los cuadros
    reales (el script del autor, en ese caso, toma salidas de cuadros que ya
    habia devuelto).

    De cada mapa salen las manchas que pasan UMBRAL_BAJO, con su pico como
    puntaje: el autor usa 0,5 para decidir, pero aca se guardan tambien las
    dudosas y la medicion prueba varios cortes.
    """

    UMBRAL_BAJO = 0.1
    MAXIMO_POR_CUADRO = 3

    def __init__(self, modelo, ruta_modelo):
        import cv2
        import numpy
        import onnxruntime
        self.cv2, self.np = cv2, numpy
        self.modelo = modelo
        self.nombre = modelo.nombre
        opciones = onnxruntime.SessionOptions()
        opciones.log_severity_level = 3
        self.sesion = onnxruntime.InferenceSession(str(ruta_modelo), opciones,
                                                   providers=["CPUExecutionProvider"])
        self.entrada = self.sesion.get_inputs()[0].name

    def _preparar(self, cuadro):
        gris = self.cv2.cvtColor(cuadro, self.cv2.COLOR_BGR2GRAY)
        chico = self.cv2.resize(gris, (self.modelo.ancho, self.modelo.alto),
                                interpolation=self.cv2.INTER_AREA)
        return chico.astype(self.np.float32) / 255.0

    def _manchas(self, t, mapa):
        cv2, np = self.cv2, self.np
        alto, ancho = mapa.shape
        mascara = (mapa >= self.UMBRAL_BAJO).astype(np.uint8)
        cantidad, etiquetas, datos, _ = cv2.connectedComponentsWithStats(mascara, connectivity=8)
        hallados = []
        for i in range(1, cantidad):
            x0, y0, w, h, _ = datos[i]
            trozo = mapa[y0:y0 + h, x0:x0 + w] * (etiquetas[y0:y0 + h, x0:x0 + w] == i)
            peso = float(trozo.sum())
            if peso <= 0:
                continue
            filas, columnas = np.indices(trozo.shape)
            cx = x0 + float((trozo * columnas).sum()) / peso
            cy = y0 + float((trozo * filas).sum()) / peso
            hallados.append(Candidato(t, (cx + 0.5) / ancho, (cy + 0.5) / alto,
                                      round(float(trozo.max()), 3)))
        hallados.sort(key=lambda c: -c.puntaje)
        return hallados[:self.MAXIMO_POR_CUADRO]

    def _correr(self, grupo):
        """grupo: los ultimos 9 (t, cuadro preparado). Devuelve sus 9 mapas."""
        clip = self.np.stack([cuadro for _, cuadro in grupo])[None]
        return self.sesion.run(None, {self.entrada: clip})[0][0]

    def detectar(self, cuadros):
        n = self.modelo.cuadros
        grupo, nuevos = [], 0
        for t, cuadro in cuadros:
            grupo.append((t, self._preparar(cuadro)))
            nuevos += 1
            if nuevos == n:
                mapas = self._correr(grupo)
                for i, (tt, _) in enumerate(grupo):
                    yield tt, self._manchas(tt, mapas[i])
                grupo, nuevos = [], 0
        if nuevos:
            relleno = [grupo[0]] * (n - len(grupo))
            mapas = self._correr(relleno + grupo)
            for i, (tt, _) in enumerate(grupo):
                yield tt, self._manchas(tt, mapas[len(relleno) + i])
