# Subirlo a Vercel

El mismo proyecto corre en los dos lados. En casa no cambia nada:

    python servidor_voley.py

Alojado hay dos cosas que no funcionan solas y que son la razon de casi todos
los cambios de `almacenamiento.py`:

1. **La carpeta del proyecto es de solo lectura.** Guardar un partido en
   `Datos/` falla con un error de disco. Lo unico escribible es `/tmp`.
2. **`/tmp` no persiste ni se comparte.** Cada pedido puede caer en una
   instancia distinta, y la que atendio el anterior se apaga al rato.

Por eso los archivos se escriben en `/tmp` y se publican en **Vercel Blob**,
que es lo unico que sigue estando manana; antes de listar o de leer, la
instancia que atiende baja del blob lo que no tenga. Los partidos e informes
que ya estaban en el repositorio se siguen viendo: viajan en el deploy y se
leen de ahi, aunque no se puedan modificar.

## Los pasos

1. **Crear el Blob store.** En el panel de Vercel: Storage → Create Database →
   Blob. Al conectarlo al proyecto, Vercel agrega solo la variable
   `BLOB_READ_WRITE_TOKEN`.

2. **Poner la clave de carga como variable de entorno.** Settings →
   Environment Variables:

   | Variable | Para que |
   |---|---|
   | `BLOB_READ_WRITE_TOKEN` | la pone Vercel al conectar el Blob store |
   | `VOLEY_CLAVE` | la contraseña para cargar un partido |
   | `VOLEY_SECRETO` | *(opcional)* con que se firman los tokens de sesion |

   `VOLEY_CLAVE` importa: sin ella queda la que esta escrita en
   `analisis_voley.py`, que esta a la vista de cualquiera que mire el
   repositorio. Alojado el sitio lo abre cualquiera.

3. **Deploy.** `vercel --prod`, o conectando el repositorio de GitHub.

## Como saber si quedo bien

La pantalla avisa sola: si no hay Blob configurado aparece una franja amarilla
arriba de las pestañas diciendo que lo que se guarde se va a perder. Sin esa
franja, esta guardando de verdad.

## Que hay en cada archivo

    vercel.json      declara la funcion y manda todos los pedidos a api/index
    api/index.py     lo que Vercel importa; expone el Manejador de siempre
    almacenamiento.py  donde van los archivos y como se hablan con el blob
    requirements.txt   openpyxl, que es lo unico que hace falta instalar

`vercel.json` usa `builds` y `routes` a proposito: asi Vercel no sirve la
carpeta del proyecto como archivos estaticos y los `.py` no se pueden bajar.
Todo lo que se ve (`index.html`, `interfaz.css`, `interfaz.js`) lo entrega la
funcion desde su lista blanca, igual que en casa.

## Lo que no funciona alojado

**"Abrir en esta PC"**. Abria el `.xlsx` con Excel en la maquina donde corria
el servidor; alojado esa maquina es un contenedor en un datacenter. El boton
no aparece cuando el sitio no es local, y el endpoint contesta que se descargue
el archivo. Descargar sigue andando igual.
