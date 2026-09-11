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

3. **Revisar la version de Python.** Settings → General → Python Version:
   tiene que ser **3.12** (o al menos 3.10). El proyecto usa anotaciones del
   estilo `str | None`, que en 3.9 no son sintaxis valida y hacen fallar el
   import de entrada.

4. **Deploy.** `vercel --prod`, o conectando el repositorio de GitHub.

## Como saber si quedo bien

La pantalla avisa sola: si no hay Blob configurado aparece una franja amarilla
arriba de las pestañas diciendo que lo que se guarde se va a perder. Sin esa
franja, esta guardando de verdad.

## Que hay en cada archivo

    vercel.json        publica public/ y manda el resto a la funcion
    public/            la pagina: index.html, interfaz.css, interfaz.js
    api/index.py       define `handler`, que es el Manejador de siempre
    almacenamiento.py  donde van los archivos y como se hablan con el blob
    requirements.txt   openpyxl, que es lo unico que hace falta instalar

Tres cosas de `vercel.json` que no son decorativas:

**`outputDirectory: "public"`** es lo que hace que Vercel publique *solo* esa
carpeta. Sin eso publica la raiz entera, y los `.py` del proyecto se pueden
bajar como si fueran archivos estaticos. Por eso la pagina se mudo a `public/`
y los modulos se quedaron afuera. Corriendo en casa las URL son las mismas:
el servidor las sirve desde su lista blanca (ver `ESTATICOS`).

**El `rewrite`** manda a la funcion todo lo que no sea un archivo de `public/`.
Los estaticos los entrega el CDN y `/api/...` entra a Python. El destino es
`/api/index`, sin el `.py`.

**`handler` tiene que estar definido en `api/index.py`**, no importado. Vercel
le lee el codigo al archivo buscando una definicion de nivel superior con ese
nombre; no importa el modulo para preguntarle que exporta. Un
`handler = Manejador` no le alcanza y el deploy falla con *Could not find a
top-level "app", "application", or "handler"*. Por eso es una subclase vacia.

## Lo que no funciona alojado

**"Abrir en esta PC"**. Abria el `.xlsx` con Excel en la maquina donde corria
el servidor; alojado esa maquina es un contenedor en un datacenter. El boton
no aparece cuando el sitio no es local, y el endpoint contesta que se descargue
el archivo. Descargar sigue andando igual.
