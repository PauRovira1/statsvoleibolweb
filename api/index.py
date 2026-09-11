"""
Punto de entrada en Vercel.

Vercel no arranca `python servidor_voley.py`: importa este archivo y, por cada
pedido que llega, instancia la clase `handler`, que tiene que ser un
BaseHTTPRequestHandler. El manejador del proyecto ya lo es (nunca dependio de
nada del ThreadingHTTPServer), asi que aca no hay una segunda implementacion
de la API: se hereda de la de siempre.

`handler` tiene que estar DEFINIDO aca, no importado ni asignado. Vercel no
importa el modulo para averiguar que exporta: le lee el codigo y busca una
definicion de nivel superior con ese nombre. Un `handler = Manejador` es una
asignacion a un nombre que viene de otro archivo, y no lo encuentra:

    Could not find a top-level "app", "application", or "handler"

Por eso la subclase vacia, que sirve igual y ademas es la forma en la que
Vercel documenta esto.

En casa no cambia nada: `python servidor_voley.py` sigue levantando el
servidor local, y este archivo ni se importa.
"""
import sys
from pathlib import Path

# El .py corre desde api/, pero los modulos del proyecto estan un nivel arriba.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from servidor_voley import Manejador   # noqa: E402


class handler(Manejador):      # noqa: N801  (el nombre lo elige Vercel)
    """El manejador de siempre, con el nombre que Vercel busca."""
