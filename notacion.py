"""
La notacion escrita como una tabla de pasos, para poder cargar tocando.

Escribir la jugada y armarla tocando tienen que producir el mismo texto,
carácter por carácter, porque de eso dependen el volcado, el Excel y las
estadisticas. Por eso la notacion esta descrita una sola vez, aca: el
navegador se baja esta tabla por GET /api/notacion y la interpreta, y los
tests la manejan desde Python contra los volcados de Datos/. Escrita en
JavaScript no se podria testear asi; escrita dos veces, las dos copias se
irian separando sin que nadie se entere.

La tabla NO sabe reglas de voley. No decide quien gana el punto, no valida
nada, no mira el marcador: solo dice que se puede tocar en cada paso y que
pedazo de texto agrega cada toque. De quien es la pelota se lo pregunta al
motor, que es el unico que lo sabe (ver analisis_voley._esperando).

Como se arma una linea
----------------------
Cada toque apila un paso {estado, texto}. La linea es la concatenacion de los
textos, sin el separador que quede adelante:

    "5" "_1" "_6" "_X" "/3" "_3" "/2" "_4" "/4" "_1" "_P"
      ->  5_1_6_X/3_3/2_4/4_1_P

Deshacer es sacar el ultimo paso de la pila. No hay que escribir nada
especial para eso: la linea se recalcula sola y el estado vuelve al que
estaba guardado en el paso. Un toque puede agregar texto vacio (elegir
"Libre" todavia no escribe nada, solo cambia lo que se pregunta despues) y
igual se deshace como cualquier otro.

El separador de adelante
------------------------
Los textos traen su separador puesto ("_1", "/3") y el de la primera ficha se
saca al armar la linea. Asi el saque con dorsal y el saque sin dorsal salen
del mismo camino, sin un caso aparte:

    con dorsal:  "5" + "_1" + "_6"  ->  5_1_6
    sin dorsal:       "_1" + "_6"   ->  1_6

Los toques que se ahorran
-------------------------
Un toque puede valer por dos pasos. La linea que sale es la misma de siempre:
lo unico que cambia es que el pedazo de texto del paso que se salteo viaja
pegado al del toque, en una sola ficha de la pila (y por eso deshacer lo saca
entero, de un toque). Hay tres formas, y las tres estan escritas en la tabla:

    "directo"  En un paso de botones tambien se puede tocar a un jugador, y
               eso vale por uno de los botones. Despues del saque, tocar al
               que recibe es "Sigue" + ese jugador ("_X/7"). Cuando el boton
               cierra la linea ("Defendido"), el jugador no se escribe: queda
               anotado en "arrastre" para que la pantalla arranque la linea
               siguiente con el ya tocado.

    "asume"    En un paso que pide un jugador hay uno que se da por hecho, y
               entonces se ofrece de una lo del paso que sigue. Tocar la zona
               de armado es "armo el armador hacia ahi" ("/3_4"); tocar la
               zona del ataque es "ataco el que juega en la zona a la que se
               armo" ("/88_1"). QUIEN es el armador y a quien se le arma en
               cada zona no se decide aca: lo manda el motor
               (analisis_voley.puestos_en_cancha) y llega por el constructor.

    "junta"    Dos pasos de botones seguidos se muestran como una sola
               grilla: como ataco y que paso ("_PO_P") es un toque.

Ninguna de las tres saca nada: el camino largo sigue estando (el boton
"Sigue", tocar al que arma, tocar al que ataca), porque es el unico que hay
cuando el equipo no tiene rotacion o cuando la jugada no fue la de libro.
"""

# Zonas de la cancha. El 1 es el fondo derecha (el que saca) y la numeracion
# es desde cada lado, asi que la 1 de un lado queda enfrentada a la 5 del
# otro. Las 7/8/9 son la franja del medio.
#
#       (red)
#      4  3  2
#      7  8  9
#      5  6  1
ZONAS_CANCHA = (1, 2, 3, 4, 5, 6, 7, 8, 9)
ZONAS_FONDO = (1, 6, 5)          # desde donde se saca y hacia donde se remata
ZONAS_ARMADO = (1, 2, 3, 4, 5, 6)
ZONAS_TODAS = (1, 2, 3, 4, 5, 6, 7, 8, 9)

# "lado" dice de quien son los circulos (o las zonas) que se encienden:
#   saca   -> el equipo que saca
#   pelota -> el que tiene la pelota en esta linea
#   rival  -> el otro (el que bloquea, y la cancha hacia donde se remata)
# Adentro de UNA linea esto no es una regla de voley: despues del saque la
# pelota es del que recibe, siempre. Lo unico que no se puede deducir es de
# quien es al EMPEZAR una continuacion, y eso lo dice el motor.

PASOS = {
    # ---------------- bloque de saque ----------------
    # Solo se entra aca si el equipo que saca no tiene rotacion cargada. Con
    # rotacion el motor ya sabe a quien le toca y el dorsal se omite, que es
    # lo mismo que hace el que escribe (verificado sobre los 181 saques de
    # Datos/: el dorsal aparece exactamente cuando no hay rotacion).
    "SAQUE_JUGADOR": {
        "titulo": "Quien saca",
        "pide": "jugador", "lado": "saca",
        "prefijo": "", "siguiente": "SAQUE_DESDE",
    },
    "SAQUE_DESDE": {
        "titulo": "Desde que zona saca",
        "pide": "zona", "lado": "saca", "zonas": list(ZONAS_FONDO),
        "prefijo": "_", "siguiente": "SAQUE_HACIA",
    },
    "SAQUE_HACIA": {
        "titulo": "Hacia que zona",
        "pide": "zona", "lado": "pelota", "zonas": list(ZONAS_TODAS),
        "prefijo": "_", "siguiente": "SAQUE_RESULTADO",
    },
    "SAQUE_RESULTADO": {
        "titulo": "Como termino el saque",
        "pide": "boton",
        "opciones": [
            # La potencia se marca antes del resultado (5_1_6_P_A): por eso
            # es un toque que deja en el mismo paso, como el "no cuenta como
            # armado" del ataque.
            {"id": "potencia", "etiqueta": "Potencia", "texto": "_P",
             "siguiente": "SAQUE_RESULTADO", "una_vez": True},
            {"id": "as", "etiqueta": "As", "texto": "_A", "siguiente": "AS_RECEPTOR",
             "tono": "bien"},
            {"id": "error", "etiqueta": "Error", "texto": "_E", "cierra": True, "tono": "mal"},
            {"id": "sigue", "etiqueta": "Sigue", "texto": "_X", "siguiente": "RECIBE_JUGADOR"},
        ],
        # tocar al que recibe ya dice que el saque siguio
        "directo": {"por": "sigue", "lado": "pelota",
                    "titulo": "Toca al que recibe (o como termino el saque)"},
    },

    # El receptor rival al que le hicieron el as: es el receptor objetivo del
    # saque, y sin el los saques que mejor funcionaron no entran en la
    # estrategia de saque. "No se vio" no escribe nada (5_1_6_A, como antes).
    "AS_RECEPTOR": {
        "titulo": "A quien le hizo el as",
        "pide": "jugador", "lado": "pelota",
        "prefijo": "_", "cierra": True,
        "opciones": [
            {"id": "as_sin_receptor", "etiqueta": "No se vio", "texto": "", "cierra": True},
        ],
    },

    # ---------------- recepcion o defensa ----------------
    "RECIBE_JUGADOR": {
        "titulo": "Quien la toca",
        "pide": "jugador", "lado": "pelota",
        "prefijo": "/", "siguiente": "RECIBE_CALIDAD",
        "opciones": [
            # el atajo reemplaza el bloque entero, por eso sale de aca
            {"id": "primera", "etiqueta": "ataca de primera", "texto": "",
             "siguiente": "PRIMERA_JUGADOR", "solo": "continuacion"},
        ],
    },
    "RECIBE_CALIDAD": {
        "titulo": "Con que calidad",
        "pide": "boton",
        "opciones": [
            {"id": "c3", "etiqueta": "3", "texto": "_3", "siguiente": "ARMA_JUGADOR"},
            {"id": "c2", "etiqueta": "2", "texto": "_2", "siguiente": "ARMA_JUGADOR"},
            {"id": "c1", "etiqueta": "1", "texto": "_1", "siguiente": "ARMA_JUGADOR"},
            # El 0 quiere decir dos cosas distintas segun donde se toque, asi
            # que son dos botones y en pantalla solo se ve el que corresponde:
            #
            #   RECIBIENDO UN SAQUE: es un pase malo que igual se juega. El
            #   punto sigue, hay armado y ataque despues.
            #
            #   DEFENDIENDO UN ATAQUE: la pelota se toco pero no se pudo
            #   jugar. El punto termina ahi y es del que la mando.
            #
            # Los dos escriben "_0": la diferencia la da el lugar, y el motor
            # ya la sabe. Antes el de defensa tenia un gemelo que seguia el
            # punto; se retiro, pero el motor lo sigue leyendo por escrito
            # (Y_0/armado/ataque) para que los partidos ya guardados carguen.
            {"id": "c0", "etiqueta": "0", "texto": "_0",
             "siguiente": "ARMA_JUGADOR", "solo": "saque"},
            {"id": "c0_cae", "etiqueta": "0 - no se pudo jugar", "texto": "_0",
             "cierra": True, "tono": "mal", "solo": "continuacion"},
            {"id": "overpass", "etiqueta": "se fue al otro lado", "texto": "_-1",
             "cierra": True},
        ],
    },

    # ---------------- armado ----------------
    "ARMA_JUGADOR": {
        "titulo": "Quien arma",
        "pide": "jugador", "lado": "pelota",
        "prefijo": "/", "siguiente": "ARMA_ZONA",
        # Casi siempre arma el armador, asi que se ofrecen de una las zonas.
        # Los circulos se esconden atras de un boton en vez de quedar vivos:
        # la zona a la que se arma y el jugador que esta parado en ella son la
        # misma celda, y con los dos encendidos no se sabria que se toco.
        "asume": {"quien": "armador",
                  "titulo": "Arma el {jugador}: hacia que zona",
                  "otro": {"id": "arma_otro", "etiqueta": "armo otro jugador"}},
        "opciones": [
            # la pasada de segunda ES el segundo toque: reemplaza armado y
            # ataque juntos, no va despues del armado
            {"id": "segunda", "etiqueta": "la manda de segunda", "texto": "",
             "siguiente": "SEGUNDA_JUGADOR"},
        ],
    },
    "ARMA_ZONA": {
        "titulo": "Hacia que zona arma",
        "pide": "zona", "lado": "pelota", "zonas": list(ZONAS_ARMADO),
        "prefijo": "_", "siguiente": "ATACA_JUGADOR",
        "opciones": [
            {"id": "arma_pasa", "etiqueta": "se paso al otro lado", "texto": "_-1",
             "cierra": True},
            {"id": "arma_mala", "etiqueta": "AX - error de armado", "texto": "_-2",
             "cierra": True, "tono": "mal"},
        ],
    },

    # ---------------- ataque ----------------
    "ATACA_JUGADOR": {
        "titulo": "Quien ataca",
        "pide": "jugador", "lado": "pelota",
        "prefijo": "/", "siguiente": "ATACA_ZONA",
        # A quien se le armo sale de la zona del armado (a 4, el punta
        # delantero). Aca los circulos si quedan vivos: estan en la mitad
        # propia y la zona del ataque en la de enfrente, no se pisan.
        "asume": {"quien": "atacante",
                  "titulo": "Ataca el {jugador}: hacia que zona (o toca a otro)"},
        "opciones": [
            # el "_X" va pegado a la zona de armado, antes del "/" del
            # atacante: por eso se ofrece aca y no despues
            {"id": "sin_armado", "etiqueta": "no cuenta como armado", "texto": "_X",
             "siguiente": "ATACA_JUGADOR", "una_vez": True},
            # La calidad del armado tambien va pegada a la zona de armado, por
            # lo mismo. Es opcional, y de las tres se elige una sola: el
            # "grupo" apaga las otras dos cuando se toca una.
            {"id": "armado_mas", "etiqueta": "A+", "texto": "_A+",
             "siguiente": "ATACA_JUGADOR", "grupo": "calidad_armado", "tono": "bien"},
            {"id": "armado_cero", "etiqueta": "A0", "texto": "_A0",
             "siguiente": "ATACA_JUGADOR", "grupo": "calidad_armado"},
            {"id": "armado_menos", "etiqueta": "A-", "texto": "_A-",
             "siguiente": "ATACA_JUGADOR", "grupo": "calidad_armado", "tono": "mal"},
        ],
    },
    # Tocar la zona ES atacar: antes habia un paso entero para elegir entre
    # "Ataque" y "Libre", y el libre es la excepcion. Queda como un boton al
    # lado. El "Toque" ya no se ofrece: lo que antes se cargaba como toque
    # ahora es un ataque colocado / finta (ver ATACA_FORMA). El motor sigue
    # leyendo el "_T_" de los partidos ya guardados.
    "ATACA_ZONA": {
        "titulo": "Hacia que zona ataca",
        "pide": "zona", "lado": "rival", "zonas": list(ZONAS_FONDO),
        "prefijo": "_", "siguiente": "ATACA_FORMA",
        "opciones": [
            {"id": "libre", "etiqueta": "Libre", "texto": "", "siguiente": "LIBRE_ZONA"},
        ],
    },
    # El libre tambien se puede errar. Va como una opcion mas del
    # paso de la zona y no como un paso aparte porque es lo que pasa en la
    # cancha: la pelota se fue, no fue "a una zona y ademas mal". La zona que
    # se escribe es el 0, el mismo que ya quiere decir "salio mal" en la
    # recepcion y en la defensa.
    "LIBRE_ZONA": {
        "titulo": "Hacia que zona va el libre",
        "pide": "zona", "lado": "rival", "zonas": list(ZONAS_TODAS),
        "prefijo": "_F_", "siguiente": "LIBRE_RESULTADO",
        "opciones": [
            {"id": "libre_malo", "etiqueta": "salio mal - punto del rival",
             "texto": "_F_0", "cierra": True, "tono": "mal"},
        ],
    },
    # Como termino el libre: "_P", "_U_Y" o nada (sigue).
    "LIBRE_RESULTADO": {
        "titulo": "Como termino",
        "pide": "boton",
        "opciones": [
            {"id": "sigue", "etiqueta": "Sigue", "texto": "", "cierra": True},
            {"id": "punto", "etiqueta": "Punto", "texto": "_P", "cierra": True, "tono": "bien"},
            {"id": "bloqueo_usado", "etiqueta": "Block Out", "texto": "",
             "siguiente": "BLOQUEO_USADO"},
        ],
        "directo": {"por": "sigue", "lado": "rival",
                    "titulo": "Como termino (o toca al rival que la levanta)"},
    },
    # Primero como fue el ataque y despues que paso. El texto va en ese mismo
    # orden: 4_1_PO_P. "No se vio" no escribe nada: es para cuando no se pudo
    # ver, y es lo que deja armar tocando los partidos cargados antes de que
    # existiera esta pregunta. El block-out no es una forma: es un resultado.
    #
    # Las dos formas van juntas con el resultado: en pantalla es una grilla
    # con una fila por forma, y un toque escribe las dos cosas ("_PO_P").
    # "No se vio" no se junta: lleva a los resultados solos.
    "ATACA_FORMA": {
        "titulo": "Como ataco y que paso",
        "pide": "boton",
        "opciones": [
            {"id": "potente", "etiqueta": "Ataque potente", "texto": "_PO",
             "siguiente": "ATACA_RESULTADO", "junta": True},
            {"id": "colocado", "etiqueta": "Colocado / finta", "texto": "_CO",
             "siguiente": "ATACA_RESULTADO", "junta": True},
            {"id": "sin_forma", "etiqueta": "No se vio", "texto": "",
             "siguiente": "ATACA_RESULTADO"},
        ],
    },
    "ATACA_RESULTADO": {
        "titulo": "Que paso con el ataque",
        "pide": "boton",
        "opciones": [
            {"id": "punto", "etiqueta": "Punto", "texto": "_P", "cierra": True, "tono": "bien"},
            {"id": "defendido", "etiqueta": "Defendido", "texto": "_D", "cierra": True},
            {"id": "afuera", "etiqueta": "Afuera", "texto": "_O", "cierra": True, "tono": "mal"},
            {"id": "malla", "etiqueta": "Malla", "texto": "_M", "cierra": True, "tono": "mal"},
            {"id": "bloqueo_punto", "etiqueta": "Bloqueo punto", "texto": "",
             "siguiente": "BLOQUEO_PUNTO"},
            {"id": "bloqueo_usado", "etiqueta": "Block Out", "texto": "",
             "siguiente": "BLOQUEO_USADO"},
            {"id": "bloqueo_toca", "etiqueta": "Toque de Bloqueo", "texto": "",
             "siguiente": "BLOQUEO_TOCA"},
            {"id": "bloqueo_rejugable", "etiqueta": "Bloqueo rejugable", "texto": "",
             "siguiente": "BLOQUEO_REJUGABLE"},
        ],
        # Tocar a un rival es "Defendido", y ese rival es el que la toca en la
        # linea que viene. En la grilla de ATACA_FORMA no se ofrece: ahi el
        # toque tendria que decir tambien como fue el ataque, y un circulo no
        # puede decir las dos cosas sin perder una.
        "directo": {"por": "defendido", "lado": "rival",
                    "titulo": "Que paso (o toca al rival que la defendio)"},
    },
    "BLOQUEO_PUNTO": {
        "titulo": "Quien bloqueo",
        "pide": "jugador", "lado": "rival",
        "prefijo": "_B_", "sufijo": "_P", "cierra": True,
    },
    "BLOQUEO_USADO": {
        "titulo": "Block Out: en quien toco el bloqueo",
        "pide": "jugador", "lado": "rival",
        "prefijo": "_U_", "cierra": True,
    },
    # El bloqueador toca el ataque y la pelota sigue de su lado: la que se
    # levanta despues no cuenta como defensa.
    "BLOQUEO_TOCA": {
        "titulo": "Toque de Bloqueo: quien lo toco",
        "pide": "jugador", "lado": "rival",
        "prefijo": "_BD_", "cierra": True,
    },
    "BLOQUEO_REJUGABLE": {
        "titulo": "Quien bloqueo",
        "pide": "jugador", "lado": "rival",
        "prefijo": "_R_", "cierra": True,
    },

    # ---------------- los dos atajos ----------------
    "SEGUNDA_JUGADOR": {
        "titulo": "Quien la manda de segunda",
        "pide": "jugador", "lado": "pelota",
        "prefijo": "/", "siguiente": "SEGUNDA_ZONA",
    },
    "SEGUNDA_ZONA": {
        "titulo": "Hacia que zona la manda",
        "pide": "zona", "lado": "rival", "zonas": list(ZONAS_TODAS),
        "prefijo": "_S_", "siguiente": "SEGUNDA_RESULTADO",
    },
    "SEGUNDA_RESULTADO": {
        "titulo": "Como termino",
        "pide": "boton",
        "opciones": [
            {"id": "punto", "etiqueta": "Punto", "texto": "_P", "cierra": True, "tono": "bien"},
            {"id": "defendido", "etiqueta": "Defendido", "texto": "_D", "cierra": True},
            {"id": "afuera", "etiqueta": "Afuera", "texto": "_O", "cierra": True, "tono": "mal"},
        ],
        "directo": {"por": "defendido", "lado": "rival",
                    "titulo": "Que paso (o toca al rival que la defendio)"},
    },
    "PRIMERA_JUGADOR": {
        "titulo": "Quien ataca de primera",
        "pide": "jugador", "lado": "pelota",
        "prefijo": "/", "siguiente": "PRIMERA_ZONA",
    },
    "PRIMERA_ZONA": {
        "titulo": "Hacia que zona ataca",
        "pide": "zona", "lado": "rival", "zonas": list(ZONAS_FONDO),
        "prefijo": "_A_", "siguiente": "PRIMERA_FORMA",
    },
    "PRIMERA_FORMA": {
        "titulo": "Como ataco y que paso",
        "pide": "boton",
        "opciones": [
            {"id": "potente", "etiqueta": "Ataque potente", "texto": "_PO",
             "siguiente": "PRIMERA_RESULTADO", "junta": True},
            {"id": "colocado", "etiqueta": "Colocado / finta", "texto": "_CO",
             "siguiente": "PRIMERA_RESULTADO", "junta": True},
            {"id": "sin_forma", "etiqueta": "No se vio", "texto": "",
             "siguiente": "PRIMERA_RESULTADO"},
        ],
    },
    "PRIMERA_RESULTADO": {
        "titulo": "Que paso con el ataque",
        "pide": "boton",
        "opciones": [
            {"id": "punto", "etiqueta": "Punto", "texto": "_P", "cierra": True, "tono": "bien"},
            {"id": "defendido", "etiqueta": "Defendido", "texto": "_D", "cierra": True},
        ],
        "directo": {"por": "defendido", "lado": "rival",
                    "titulo": "Que paso (o toca al rival que la defendio)"},
    },
}


def primer_paso(espera: str, sacador_conocido: bool) -> str:
    """Con que paso arranca una linea nueva.

    "espera" y el dorsal del sacador los dice el motor: aca no se deduce
    nada."""
    if espera == "continuacion":
        return "RECIBE_JUGADOR"
    return "SAQUE_DESDE" if sacador_conocido else "SAQUE_JUGADOR"


def otro_equipo(equipo: str) -> str:
    return "B" if equipo == "A" else "A"


def sin_separador(texto: str) -> str:
    """La linea no arranca con el separador que trae la primera ficha."""
    return texto[1:] if texto[:1] in ("_", "/") else texto


def tabla() -> dict:
    """Lo que se le manda al navegador. Es la tabla tal cual: el interprete
    de alla no agrega reglas, solo apila texto y mueve el cursor."""
    return {"pasos": PASOS, "zonas_cancha": list(ZONAS_CANCHA)}


class Armador:
    """Arma una linea a base de toques. Es una pila, no un texto.

    Cada toque apila {estado, texto} y deshacer saca el ultimo: por eso
    deshacer es exacto sin importar cuanto texto agrego cada toque, ni si
    agrego cero.

    "armadores" ({equipo: dorsal}) y "atacantes" ({equipo: [a quien se le arma
    en la zona 1, en la 2, ... en la 6]}) son lo que el motor dice de cada
    equipo. Sin ellos no se asume nada y la carga es la de siempre, toque por
    toque: es lo que pasa con un equipo sin rotacion."""

    def __init__(self, espera: str, equipo_saca: str,
                 equipo_con_la_pelota: str | None = None,
                 planteles: dict | None = None, sacador_conocido: bool = True,
                 armadores: dict | None = None, atacantes: dict | None = None):
        self.espera = espera
        self.equipo_saca = equipo_saca
        # Adentro de un bloque de saque la pelota es del que RECIBE: el que
        # saca aparece solo en el paso del saque, que tiene su propio lado.
        # El motor informa equipo_con_la_pelota = el que saca, porque es quien
        # la tiene antes de sacarla; de ahi en adelante es del otro.
        self.equipo_con_la_pelota = (
            otro_equipo(equipo_saca) if espera == "saque"
            else (equipo_con_la_pelota or otro_equipo(equipo_saca)))
        self.planteles = planteles or {}
        self.sacador_conocido = sacador_conocido
        self.armadores = armadores or {}
        self.atacantes = atacantes or {}
        self.pasos: list[dict] = []
        self.estado = primer_paso(espera, sacador_conocido)

    # ------------------------------------------------------------------
    @property
    def linea(self) -> str:
        return sin_separador("".join(paso["texto"] for paso in self.pasos))

    @property
    def cerrada(self) -> bool:
        return bool(self.pasos) and self.pasos[-1]["cierra"]

    @property
    def arrastre(self):
        """El dorsal que ya quedo dicho para la linea que viene: el rival que
        se toco para decir "Defendido". None si la linea no cerro asi."""
        return self.pasos[-1].get("arrastra") if self.cerrada else None

    def equipo_de(self, lado: str) -> str:
        """A que equipo apunta un "lado" en esta linea."""
        if lado == "saca":
            return self.equipo_saca
        if lado == "rival":
            return otro_equipo(self.equipo_con_la_pelota)
        return self.equipo_con_la_pelota

    def plantel_de(self, lado: str) -> list:
        return list(self.planteles.get(self.equipo_de(lado)) or [])

    def _ultimo(self, campo: str):
        """El ultimo jugador (o la ultima zona) que se nombro en la linea."""
        for paso in reversed(self.pasos):
            if paso.get(campo) is not None:
                return paso[campo]
        return None

    # ------------------------------------------------------------------
    def asumido(self):
        """El jugador que se da por hecho en este paso, o None.

        No se asume a nadie que no este en la cancha, ni al que acaba de tocar
        la pelota: nadie la toca dos veces seguidas, asi que si el armador
        recibio, arma otro, y hay que decir quien."""
        if self.cerrada:
            return None
        paso = PASOS[self.estado]
        asume = paso.get("asume")
        if not asume:
            return None
        otro = asume.get("otro")
        if otro and any(p["estado"] == self.estado and p["id"] == otro["id"]
                        for p in self.pasos):
            return None
        equipo = self.equipo_de(paso["lado"])
        if asume["quien"] == "armador":
            candidato = self.armadores.get(equipo)
        else:
            por_zona = self.atacantes.get(equipo) or []
            zona = self._ultimo("zona")
            candidato = por_zona[zona - 1] if zona and zona <= len(por_zona) else None
        if candidato is None or candidato not in (self.planteles.get(equipo) or []):
            return None
        # el "otro" tecleado puede venir como texto: se compara escrito
        if str(candidato) == str(self._ultimo("jugador")):
            return None
        return candidato

    def titulo(self) -> str:
        """Lo que se pregunta ahora. Cambia cuando hay un atajo a mano, para
        que se vea que el toque vale por dos."""
        paso = PASOS[self.estado]
        asumido = self.asumido()
        if asumido is not None:
            return paso["asume"]["titulo"].replace("{jugador}", str(asumido))
        directo = paso.get("directo")
        if directo and self._directos(paso):
            return directo["titulo"]
        return paso["titulo"]

    # ------------------------------------------------------------------
    def opciones(self) -> list[dict]:
        """Lo unico que se puede tocar ahora. La pantalla apaga todo el resto:
        esa es la razon por la que no hace falta saber la notacion.

        Los atajos van primero: asi el que busca como armar una linea (los
        tests) prueba antes el camino corto, que es el que se usa en la
        cancha."""
        if self.cerrada:
            return []
        paso = PASOS[self.estado]
        usados = {p["id"] for p in self.pasos if p["estado"] == self.estado}
        # de las opciones con "grupo" se puede tocar una sola por paso
        grupos_usados = {o.get("grupo") for o in paso.get("opciones", ())
                         if o["id"] in usados and o.get("grupo")}
        salida = []

        asumido = self.asumido()
        if asumido is not None:
            salida.extend(self._del_paso_que_sigue(paso, asumido))
        if paso.get("directo"):
            salida.extend(self._directos(paso))

        otro = (paso.get("asume") or {}).get("otro")
        if asumido is not None and otro:
            # los circulos quedan atras de este boton (ver ARMA_JUGADOR)
            salida.append({"id": otro["id"], "tipo": "boton", "etiqueta": otro["etiqueta"],
                           "texto": "", "siguiente": self.estado, "cierra": False,
                           "tono": None})
        elif paso["pide"] == "jugador":
            for dorsal in self.plantel_de(paso["lado"]):
                salida.append(self._ficha(paso, f"j{dorsal}", "jugador", str(dorsal), dorsal))
            # Siempre, tenga o no rotacion el equipo: en los volcados de
            # Datos/ el 15% de los dorsales no esta entre los 6 en cancha
            # (son los liberos, que no rotan). Sin esta salida esas jugadas no
            # se podrian cargar tocando.
            salida.append({
                "id": "otro", "tipo": "numero", "etiqueta": "otro",
                "prefijo": paso.get("prefijo", ""), "sufijo": paso.get("sufijo", ""),
                "siguiente": paso.get("siguiente"), "cierra": bool(paso.get("cierra")),
            })
        elif paso["pide"] == "zona":
            for zona in paso["zonas"]:
                salida.append(self._ficha(paso, f"z{zona}", "zona", str(zona), zona))

        for extra in paso.get("opciones", ()):
            if extra.get("solo") and extra["solo"] != self.espera:
                continue
            if extra.get("una_vez") and extra["id"] in usados:
                continue
            if extra.get("grupo") and extra["grupo"] in grupos_usados:
                continue
            if extra.get("junta"):
                salida.extend(self._juntas(extra))
                continue
            salida.append(self._boton(extra))
        return salida

    def _ficha(self, paso: dict, identificador: str, tipo: str,
               etiqueta: str, valor) -> dict:
        return {
            "id": identificador, "tipo": tipo, "etiqueta": etiqueta, "valor": valor,
            "texto": f"{paso.get('prefijo', '')}{valor}{paso.get('sufijo', '')}",
            "siguiente": paso.get("siguiente"), "cierra": bool(paso.get("cierra")),
            "lado": paso.get("lado"),
            # a quien (o que zona) nombra el toque: de aca sale despues a
            # quien se asume
            tipo: valor,
        }

    def _boton(self, extra: dict, delante: str = "") -> dict:
        return {"id": extra["id"], "tipo": "boton", "etiqueta": extra["etiqueta"],
                "texto": delante + extra["texto"], "siguiente": extra.get("siguiente"),
                "cierra": bool(extra.get("cierra")), "tono": extra.get("tono")}

    def _del_paso_que_sigue(self, paso: dict, jugador) -> list[dict]:
        """Lo que ofrece el paso siguiente, con el jugador asumido por delante:
        un toque escribe los dos pedazos ("/3" + "_4")."""
        destino = PASOS[paso["siguiente"]]
        delante = f"{paso.get('prefijo', '')}{jugador}{paso.get('sufijo', '')}"
        salida = []
        for zona in destino.get("zonas", ()):
            ficha = self._ficha(destino, f"z{zona}", "zona", str(zona), zona)
            ficha["texto"] = delante + ficha["texto"]
            ficha["jugador"] = jugador
            salida.append(ficha)
        for extra in destino.get("opciones", ()):
            if extra.get("solo") and extra["solo"] != self.espera:
                continue
            boton = self._boton(extra, delante)
            boton["jugador"] = jugador
            salida.append(boton)
        return salida

    def _directos(self, paso: dict) -> list[dict]:
        """Los circulos que valen por un boton de este paso."""
        directo = paso["directo"]
        base = next((o for o in paso.get("opciones", ()) if o["id"] == directo["por"]), None)
        if base is None or (base.get("solo") and base["solo"] != self.espera):
            return []
        destino = None if base.get("cierra") else PASOS[base["siguiente"]]
        salida = []
        for dorsal in self.plantel_de(directo["lado"]):
            ficha = {"id": f"j{dorsal}", "tipo": "jugador", "etiqueta": str(dorsal),
                     "valor": dorsal, "lado": directo["lado"], "jugador": dorsal}
            if destino is None:
                # el boton cerraba la linea: el jugador no se escribe, se
                # lleva a la que viene
                ficha.update(texto=base["texto"], siguiente=None, cierra=True,
                             arrastra=dorsal)
            else:
                ficha.update(
                    texto=(f"{base['texto']}{destino.get('prefijo', '')}"
                           f"{dorsal}{destino.get('sufijo', '')}"),
                    siguiente=destino.get("siguiente"), cierra=bool(destino.get("cierra")))
            salida.append(ficha)
        return salida

    def _juntas(self, extra: dict) -> list[dict]:
        """Este boton y cada uno de los del paso al que lleva, en un toque.
        "fila" es para que la pantalla los agrupe."""
        salida = []
        for final in PASOS[extra["siguiente"]].get("opciones", ()):
            if final.get("solo") and final["solo"] != self.espera:
                continue
            boton = self._boton(final, extra["texto"])
            boton["id"] = f"{extra['id']}+{final['id']}"
            boton["fila"] = extra["etiqueta"]
            salida.append(boton)
        return salida

    # ------------------------------------------------------------------
    def tocar(self, identificador: str, numero=None) -> dict:
        opcion = next((o for o in self.opciones() if o["id"] == identificador), None)
        if opcion is None:
            raise ValueError(f"'{identificador}' no se puede tocar en {self.estado}")
        if opcion["tipo"] == "numero":
            if numero is None:
                raise ValueError("falta el dorsal")
            texto = f"{opcion['prefijo']}{numero}{opcion['sufijo']}"
            jugador = numero
        else:
            texto = opcion["texto"]
            jugador = opcion.get("jugador")

        self.pasos.append({"estado": self.estado, "id": identificador,
                           "texto": texto, "cierra": opcion["cierra"],
                           "numero": numero, "jugador": jugador,
                           "zona": opcion.get("zona"),
                           "arrastra": opcion.get("arrastra")})
        if not opcion["cierra"] and opcion.get("siguiente"):
            self.estado = opcion["siguiente"]
        return opcion

    def deshacer(self) -> bool:
        """Saca el ultimo toque. El estado vuelve al que ese paso tenia
        guardado, asi que no hay que recalcular nada."""
        if not self.pasos:
            return False
        self.estado = self.pasos.pop()["estado"]
        return True

    def copiar(self) -> "Armador":
        otro = Armador(self.espera, self.equipo_saca, self.equipo_con_la_pelota,
                       self.planteles, self.sacador_conocido,
                       self.armadores, self.atacantes)
        otro.pasos = [dict(paso) for paso in self.pasos]
        otro.estado = self.estado
        return otro
