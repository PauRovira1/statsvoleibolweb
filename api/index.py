"""
Punto de entrada en Vercel.

Vercel no arranca `python servidor_voley.py`: importa este archivo y, por cada
pedido que llega, instancia la clase `handler`, que tiene que ser un
BaseHTTPRequestHandler. El manejador del proyecto ya lo es (nunca dependio de
nada del ThreadingHTTPServer), asi que aca no hay una segunda implementacion
de la API: se importa la de siempre y se la expone con el nombre que Vercel
busca.

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

handler = Manejador
