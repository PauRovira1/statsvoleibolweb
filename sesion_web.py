"""
Sesion de carga de un partido para la interfaz web.

No reimplementa nada: guarda las lineas tal como se irian tipeando en la
consola y, cada vez que llega una nueva, vuelve a correr el motor entero
(analisis_voley.ejecutar_partido) alimentandolo con esa lista. Es la misma
idea con la que se recarga un partido pegando el .txt, asi que la web y la
consola no pueden divergir.

Reproducir todo de nuevo en cada jugada suena caro pero no lo es: un partido
completo de 95 puntos se rehace en centesimas de segundo, y a cambio deshacer
sale gratis (se saca la ultima linea) y no hay un segundo estado que mantener
sincronizado.

La instantanea no dice solo como va el partido: dice tambien que pregunta
quedo sin contestar ("esperando") y como viene el punto a medias
("pendiente"). Las dos salen del motor, que es el unico que sabe de quien es
la pelota; la pantalla solo las pinta.
"""
import io
import contextlib
from unittest import mock

import analisis_voley as av


# Marcas con las que el motor avisa que rechazo lo que se escribio. Se buscan
# en lo que imprimio para saber si la linea entra o no.
MARCAS_DE_RECHAZO = (
    "Formato invalido",
    "Saca el jugador",
    "Falta el numero del sacador",
    "Respuesta invalida",
    "no esta en cancha",
    "ya esta en cancha",
    "no puede entrar y salir",
    "No hay rotacion cargada",
    "Los cambios se hacen entre puntos",
    "No hay ningun punto para deshacer",
    "Tienen que ser",
    "esta repetido",
    "no es un numero de jugador valido",
    "Marca exactamente un armador",
)

# Cada pregunta del motor (analisis_voley._esperando) contra la etapa que la
# pantalla ya conocia. Son los mismos cuatro nombres de siempre mas
# "mantener_rotacion", que antes no tenia como aparecer.
ETAPA_POR_PREGUNTA = {
    "nombre_equipo": "nombres",
    "rotacion": "rotacion",
    "saque_inicial": "saque_inicial",
    "mantener_rotacion": "mantener_rotacion",
    "saque": "jugadas",
    "continuacion": "jugadas",
}


def _reproducir(lineas: list[str]) -> tuple[dict, str]:
    """Corre el motor con estas lineas. Devuelve (estado, lo que imprimio)."""
    cola = iter(lineas)

    def leer(prompt: str = "") -> str:
        try:
            return next(cola)
        except StopIteration:
            raise av.SinMasEntradas from None

    salida = io.StringIO()
    with mock.patch("builtins.input", leer), contextlib.redirect_stdout(salida):
        estado = av.ejecutar_partido()
    return estado, salida.getvalue()


class SesionPartido:
    """Un partido en curso. Se le mandan lineas y responde con el estado."""

    def __init__(self):
        self.lineas: list[str] = []
        self.estado, self.log = _reproducir([])

    # ------------------------------------------------------------------
    def enviar(self, linea: str) -> dict:
        """Agrega una linea. Si el motor la rechaza no se guarda, y se
        devuelve el mismo mensaje que veria en la consola."""
        candidatas = self.lineas + [linea]
        estado, log = _reproducir(candidatas)
        nuevo = log[len(self.log):]

        rechazo = next((m for m in MARCAS_DE_RECHAZO if m in nuevo), None)
        if rechazo is not None:
            return {"ok": False, "mensaje": _ultimo_mensaje(nuevo), "estado": self.instantanea()}

        self.lineas = candidatas
        self.estado, self.log = estado, log
        return {"ok": True, "mensaje": _ultimo_mensaje(nuevo), "estado": self.instantanea()}

    def deshacer_linea(self) -> dict:
        """Borra la ultima linea cargada, sea del tipo que sea. Es distinto de
        la "x" del motor, que deshace un punto entero."""
        if not self.lineas:
            return {"ok": False, "mensaje": "No hay nada cargado.", "estado": self.instantanea()}
        self.lineas.pop()
        self.estado, self.log = _reproducir(self.lineas)
        return {"ok": True, "mensaje": "Se borro la ultima linea.", "estado": self.instantanea()}

    def reiniciar(self) -> dict:
        self.lineas = []
        self.estado, self.log = _reproducir([])
        return {"ok": True, "mensaje": "Partido nuevo.", "estado": self.instantanea()}

    def reemplazar(self, lineas: list[str]) -> None:
        """Deja la sesion como si se hubieran cargado esas lineas.

        Es como cargar_lineas() pero sin validar de a una: las lineas vienen
        de una sesion que ya se guardo (ver almacenamiento.leer_sesion), asi
        que ya pasaron por el motor. Se usa cuando el que atiende el pedido no
        es el mismo proceso que atendio el anterior, que es lo normal cuando
        esto corre alojado."""
        self.lineas = list(lineas)
        self.estado, self.log = _reproducir(self.lineas)

    def cargar_lineas(self, texto: str) -> dict:
        """Carga de una un partido entero (pegando el .txt). Se corta en la
        primera linea que el motor rechace, para no arrastrar el desfase."""
        self.reiniciar()
        rechazadas = []
        for numero, linea in enumerate(texto.splitlines(), start=1):
            if linea.strip().lower() in av.COMANDOS_SALIDA:
                break
            resultado = self.enviar(linea)
            if not resultado["ok"]:
                rechazadas.append(f"linea {numero}: {linea!r} -> {resultado['mensaje']}")
                break
        mensaje = f"Se cargaron {len(self.lineas)} lineas."
        if rechazadas:
            mensaje += " Se corto en " + rechazadas[0]
        return {"ok": not rechazadas, "mensaje": mensaje, "estado": self.instantanea()}

    # ------------------------------------------------------------------
    def instantanea(self) -> dict:
        """Todo lo que la pantalla necesita saber del partido."""
        estado = self.estado
        nombres = estado["nombres"]
        puntos = estado["puntos"]
        numero_set = len(estado["historial_sets"]) + 1
        equipo_saca = estado["equipo_saca"]
        # vacio solo si la carga termino sola (se escribio "salir"): ahi no
        # quedo ninguna pregunta sin contestar
        esperando = estado.get("esperando") or {}

        return {
            "etapa": self._etapa(esperando),
            "nombres": nombres,
            "marcador": estado["marcador"],
            "set": numero_set,
            "sets_ganados": estado["sets_ganados"],
            "historial_sets": estado["historial_sets"],
            "equipo_saca": equipo_saca,
            "jugador_saca": av.jugador_que_saca(
                estado["rotaciones"], puntos, numero_set, equipo_saca
            ),
            # "jugadores" es la rotacion nominal de AHORA (zonas 1 a 6), que es
            # la que manda el saque y la zona del armador; "formacion" son los
            # que estan realmente en la cancha, con el libero puesto donde
            # corresponde; "inicial" es con la que arranco el set.
            "rotaciones": {
                letra: {
                    "jugadores": av.rotacion_en_cancha(
                        estado["rotaciones"], puntos, numero_set, letra
                    ),
                    "formacion": av.formacion_en_cancha(
                        estado["rotaciones"], puntos, numero_set, letra, equipo_saca
                    ),
                    "liberos": r.get("liberos") or [],
                    "inicial": r["jugadores"],
                    "armador": r["armador"],
                    "giros": av.veces_que_roto(puntos, numero_set, letra),
                }
                for letra, r in estado["rotaciones"].items()
            },
            "cambios": estado["cambios"],
            "puntos_cargados": len(puntos),
            "lineas": self.lineas,
            "ultimos_puntos": self._ultimos_puntos(),
            "prompt": self._prompt(esperando),
            # que esta preguntando el motor, sin el punto a medias (va aparte)
            "esperando": {clave: valor for clave, valor in esperando.items()
                          if clave not in ("jugadas", "entradas")},
            "pendiente": self._pendiente(esperando),
        }

    def _etapa(self, esperando: dict) -> str:
        """En que paso de la carga esta: sirve para que la pantalla sepa que
        pedir (nombres, rotacion, quien saca, o ya las jugadas).

        Sale de lo que el motor dice que esta esperando y no de contar lineas,
        que era lo de antes: contando, las cuatro respuestas que pide un cambio
        de set (mantener la rotacion, las dos rotaciones nuevas y quien saca)
        caian todas en "jugadas" y la pantalla ofrecia la cancha mientras el
        motor esperaba una "n"."""
        return ETAPA_POR_PREGUNTA.get(esperando.get("que"), "jugadas")

    def _pendiente(self, esperando: dict) -> dict:
        """El punto a medias, para la carga visual.

        Una jugada que deja el punto abierto (_D, _R_6, un libre, un toque, un
        overpass) hace que el motor pida otra linea. Esto dice que bloque toca
        y, sobre todo, de que lado quedo la pelota: es el equipo que hay que
        encender en la cancha."""
        que = esperando.get("que")
        jugadas = esperando.get("jugadas") or []
        return {
            "hay": bool(jugadas),
            "espera": que if que in ("saque", "continuacion") else None,
            "equipo_con_la_pelota": esperando.get("equipo_con_la_pelota"),
            "jugadas": jugadas,
            "lineas": list(esperando.get("entradas") or []),
            # lo mismo que se ve en la consola, para mostrarlo mientras se arma
            "secuencia": " | ".join(_describir(bloque) for bloque in jugadas),
        }

    def _prompt(self, esperando: dict) -> str:
        que = esperando.get("que")
        nombres = self.estado["nombres"]
        if que == "nombre_equipo":
            return f"Nombre del equipo {esperando['equipo']} (vacio = usar la letra)"
        if que == "rotacion":
            return (f"Rotacion de {nombres[esperando['equipo']]}: 6 jugadores en zonas 1 a 6, "
                    f"armador con _S (vacio = sin rotacion)")
        if que == "mantener_rotacion":
            return f"Mantener la misma rotacion para el set {esperando['set']}? (s/n)"
        if que == "saque_inicial":
            enunciado = "Que equipo saca primero"
            if esperando.get("set", 1) > 1:
                enunciado += f" en el set {esperando['set']}"
            return f"{enunciado}? A) {nombres['A']}  B) {nombres['B']}"
        if que == "continuacion":
            return f"Juega {nombres[esperando['equipo']]}"
        jugador = esperando.get("jugador")
        equipo = nombres[esperando.get("equipo") or self.estado["equipo_saca"]]
        return f"Saca {equipo}" + (f", jugador {jugador}" if jugador is not None else "")

    def _ultimos_puntos(self, cuantos: int = 12) -> list[dict]:
        nombres = self.estado["nombres"]
        salida = []
        for punto in self.estado["puntos"][-cuantos:]:
            salida.append({
                "set": punto.get("set", 1),
                "gana": nombres[punto["equipo_gana"]],
                "saca": nombres[punto["equipo_saca"]],
                "detalle": " | ".join(_describir(b) for b in punto["jugadas"]),
            })
        return salida

    # ------------------------------------------------------------------
    def estadisticas(self) -> str:
        estado = self.estado
        return av.formatear_estadisticas(
            estado["puntos"], estado["nombres"], estado["armadores"]
        )

    def guardar(self) -> str:
        """Escribe el .txt igual que la consola y devuelve el nombre."""
        estado = self.estado
        historial = list(estado["historial_sets"]) + [dict(estado["marcador"])]
        return av.guardar_reporte_txt(
            estado["entradas_totales"], estado["puntos"], estado["marcador"],
            estado["nombres"], historial, estado["sets_ganados"],
            estado["rotaciones_por_set"], estado["cambios"], estado["armadores"],
        )


def _describir(bloque: dict) -> str:
    try:
        if bloque.get("resultado_saque") is not None or bloque.get("sacador") is not None:
            return av.describir_bloque_saque(bloque)
        return av.describir_bloque_defensa(bloque)
    except Exception:      # un bloque raro no puede tumbar la pantalla
        return "(jugada)"


def _ultimo_mensaje(texto: str) -> str:
    """La ultima linea util de lo que imprimio el motor."""
    lineas = [l.strip() for l in texto.splitlines() if l.strip()]
    return lineas[-1] if lineas else ""
