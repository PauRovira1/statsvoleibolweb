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
            {"id": "as", "etiqueta": "As", "texto": "_A", "cierra": True, "tono": "bien"},
            {"id": "error", "etiqueta": "Error", "texto": "_E", "cierra": True, "tono": "mal"},
            {"id": "sigue", "etiqueta": "Sigue", "texto": "_X", "siguiente": "RECIBE_JUGADOR"},
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
            {"id": "c0", "etiqueta": "0", "texto": "_0", "siguiente": "ARMA_JUGADOR"},
            {"id": "overpass", "etiqueta": "se fue al otro lado", "texto": "_-1",
             "cierra": True},
            # el saque no la tiene: no hay patron X_Z_Z_X/Y_-2 en el motor
            {"id": "perdida", "etiqueta": "defensa perdida", "texto": "_-2",
             "cierra": True, "tono": "mal", "solo": "continuacion"},
        ],
    },

    # ---------------- armado ----------------
    "ARMA_JUGADOR": {
        "titulo": "Quien arma",
        "pide": "jugador", "lado": "pelota",
        "prefijo": "/", "siguiente": "ARMA_ZONA",
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
            {"id": "arma_mala", "etiqueta": "armada mala", "texto": "_-2",
             "cierra": True, "tono": "mal"},
        ],
    },

    # ---------------- ataque ----------------
    "ATACA_JUGADOR": {
        "titulo": "Quien ataca",
        "pide": "jugador", "lado": "pelota",
        "prefijo": "/", "siguiente": "ATACA_TIPO",
        "opciones": [
            # el "_X" va pegado a la zona de armado, antes del "/" del
            # atacante: por eso se ofrece aca y no despues
            {"id": "sin_armado", "etiqueta": "no cuenta como armado", "texto": "_X",
             "siguiente": "ATACA_JUGADOR", "una_vez": True},
        ],
    },
    "ATACA_TIPO": {
        "titulo": "Que hace con la pelota",
        "pide": "boton",
        "opciones": [
            {"id": "ataque", "etiqueta": "Ataque", "texto": "", "siguiente": "ATACA_ZONA"},
            {"id": "libre", "etiqueta": "Libre", "texto": "", "siguiente": "LIBRE_ZONA"},
            {"id": "toque", "etiqueta": "Toque", "texto": "", "siguiente": "TOQUE_ZONA"},
        ],
    },
    "ATACA_ZONA": {
        "titulo": "Hacia que zona ataca",
        "pide": "zona", "lado": "rival", "zonas": list(ZONAS_FONDO),
        "prefijo": "_", "siguiente": "ATACA_RESULTADO",
    },
    "LIBRE_ZONA": {
        "titulo": "Hacia que zona va el libre",
        "pide": "zona", "lado": "rival", "zonas": list(ZONAS_TODAS),
        "prefijo": "_F_", "cierra": True,
    },
    "TOQUE_ZONA": {
        "titulo": "Hacia que zona toca",
        "pide": "zona", "lado": "rival", "zonas": list(ZONAS_TODAS),
        "prefijo": "_T_", "cierra": True,
    },
    "ATACA_RESULTADO": {
        "titulo": "Como termino el ataque",
        "pide": "boton",
        "opciones": [
            {"id": "punto", "etiqueta": "Punto", "texto": "_P", "cierra": True, "tono": "bien"},
            {"id": "defendido", "etiqueta": "Defendido", "texto": "_D", "cierra": True},
            {"id": "afuera", "etiqueta": "Afuera", "texto": "_O", "cierra": True, "tono": "mal"},
            {"id": "malla", "etiqueta": "Malla", "texto": "_M", "cierra": True, "tono": "mal"},
            {"id": "bloqueo_punto", "etiqueta": "Bloqueo punto", "texto": "",
             "siguiente": "BLOQUEO_PUNTO"},
            {"id": "bloqueo_usado", "etiqueta": "Toco el bloqueo", "texto": "",
             "siguiente": "BLOQUEO_USADO"},
            {"id": "bloqueo_rejugable", "etiqueta": "Bloqueo rejugable", "texto": "",
             "siguiente": "BLOQUEO_REJUGABLE"},
        ],
    },
    "BLOQUEO_PUNTO": {
        "titulo": "Quien bloqueo",
        "pide": "jugador", "lado": "rival",
        "prefijo": "_B_", "sufijo": "_P", "cierra": True,
    },
    "BLOQUEO_USADO": {
        "titulo": "En quien toco el bloqueo",
        "pide": "jugador", "lado": "rival",
        "prefijo": "_U_", "cierra": True,
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
    },
    "PRIMERA_JUGADOR": {
        "titulo": "Quien ataca de primera",
        "pide": "jugador", "lado": "pelota",
        "prefijo": "/", "siguiente": "PRIMERA_ZONA",
    },
    "PRIMERA_ZONA": {
        "titulo": "Hacia que zona ataca",
        "pide": "zona", "lado": "rival", "zonas": list(ZONAS_FONDO),
        "prefijo": "_A_", "siguiente": "PRIMERA_RESULTADO",
    },
    "PRIMERA_RESULTADO": {
        "titulo": "Como termino",
        "pide": "boton",
        "opciones": [
            {"id": "punto", "etiqueta": "Punto", "texto": "_P", "cierra": True, "tono": "bien"},
            {"id": "defendido", "etiqueta": "Defendido", "texto": "_D", "cierra": True},
        ],
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
    agrego cero."""

    def __init__(self, espera: str, equipo_saca: str,
                 equipo_con_la_pelota: str | None = None,
                 planteles: dict | None = None, sacador_conocido: bool = True):
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
        self.pasos: list[dict] = []
        self.estado = primer_paso(espera, sacador_conocido)

    # ------------------------------------------------------------------
    @property
    def linea(self) -> str:
        return sin_separador("".join(paso["texto"] for paso in self.pasos))

    @property
    def cerrada(self) -> bool:
        return bool(self.pasos) and self.pasos[-1]["cierra"]

    def equipo_de(self, lado: str) -> str:
        """A que equipo apunta un "lado" en esta linea."""
        if lado == "saca":
            return self.equipo_saca
        if lado == "rival":
            return otro_equipo(self.equipo_con_la_pelota)
        return self.equipo_con_la_pelota

    def plantel_de(self, lado: str) -> list:
        return list(self.planteles.get(self.equipo_de(lado)) or [])

    # ------------------------------------------------------------------
    def opciones(self) -> list[dict]:
        """Lo unico que se puede tocar ahora. La pantalla apaga todo el resto:
        esa es la razon por la que no hace falta saber la notacion."""
        if self.cerrada:
            return []
        paso = PASOS[self.estado]
        usados = {p["id"] for p in self.pasos if p["estado"] == self.estado}
        salida = []

        if paso["pide"] == "jugador":
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
            salida.append({
                "id": extra["id"], "tipo": "boton", "etiqueta": extra["etiqueta"],
                "texto": extra["texto"], "siguiente": extra.get("siguiente"),
                "cierra": bool(extra.get("cierra")), "tono": extra.get("tono"),
            })
        return salida

    def _ficha(self, paso: dict, identificador: str, tipo: str,
               etiqueta: str, valor) -> dict:
        return {
            "id": identificador, "tipo": tipo, "etiqueta": etiqueta, "valor": valor,
            "texto": f"{paso.get('prefijo', '')}{valor}{paso.get('sufijo', '')}",
            "siguiente": paso.get("siguiente"), "cierra": bool(paso.get("cierra")),
            "lado": paso.get("lado"),
        }

    # ------------------------------------------------------------------
    def tocar(self, identificador: str, numero=None) -> dict:
        opcion = next((o for o in self.opciones() if o["id"] == identificador), None)
        if opcion is None:
            raise ValueError(f"'{identificador}' no se puede tocar en {self.estado}")
        if opcion["tipo"] == "numero":
            if numero is None:
                raise ValueError("falta el dorsal")
            texto = f"{opcion['prefijo']}{numero}{opcion['sufijo']}"
        else:
            texto = opcion["texto"]

        self.pasos.append({"estado": self.estado, "id": identificador,
                           "texto": texto, "cierra": opcion["cierra"],
                           "numero": numero})
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
                       self.planteles, self.sacador_conocido)
        otro.pasos = [dict(paso) for paso in self.pasos]
        otro.estado = self.estado
        return otro
