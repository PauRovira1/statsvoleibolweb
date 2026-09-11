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

1. **Crear el Blob store.** Desde el panel:

   1. Entrar a [vercel.com](https://vercel.com) y elegir arriba a la izquierda
      la cuenta (o el equipo) donde esta el proyecto.
   2. Pestaña **Storage** → **Create Database** → **Blob**.
   3. Ponerle un nombre (`voley-archivos`, por ejemplo) y dejar la region que
      viene sugerida. **Create**.
   4. Ya creado, entrar al store → **Connect Project** → elegir este proyecto →
      marcar los tres entornos (Production, Preview, Development) → **Connect**.

   Eso solo agrega la variable `BLOB_READ_WRITE_TOKEN` a las del proyecto: no
   hay que copiarla ni pegarla a mano en ningun lado.

   Lo mismo desde la terminal, si esta el CLI instalado:

       npm i -g vercel
       vercel login
       vercel link                        # atar la carpeta al proyecto
       vercel blob store add voley-archivos

   **Importante:** las variables de entorno solo entran en los deploys nuevos.
   Despues de conectar el store hay que volver a desplegar (Deployments → el
   ultimo → los tres puntos → **Redeploy**), o el sitio sigue sin verla.

   Si los nombres de los botones no coinciden exactamente, es que cambio el
   panel: lo que se busca es crear un store de tipo **Blob** y conectarlo al
   proyecto.

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

Para confirmarlo del todo: cargar cualquier cosa, darle a Guardar, y mirar el
store en el panel (Storage → el store → **Browse**). Tiene que aparecer el
`.txt` dentro de `Datos/`.

Guardar y generar el informe ademas verifican: escriben el archivo, lo suben al
Blob y despues le preguntan al Blob si quedo. Si no quedo, el mensaje lo dice
(`[OJO: ... no se pudo subir al Blob ...]`) en vez de contestar "Guardado" a
secas, y el motivo del error queda en los Logs del proyecto. Un "Guardado" o un
"Generado" sin esa coletilla significa que el archivo esta en el Blob.

Si hace falta ver que le llega al servidor, `/api/estado` lo dice: en que
entorno corre (`production` / `preview`) y cuales de las variables que el
proyecto mira estan puestas, con un si/no y sin mostrar nunca el valor.

## Probar el blob desde casa

El token sirve tambien en la notebook, y es la unica forma de probar todo el
camino sin desplegar. En PowerShell:

    vercel env pull .env.local          # baja las variables del proyecto
    $env:BLOB_READ_WRITE_TOKEN = "vercel_blob_rw_..."
    python servidor_voley.py

El proyecto lee la variable del entorno y no del archivo `.env.local`, asi que
hay que ponerla en la sesion como esta arriba. Con ella puesta, lo que se
guarde en casa va al mismo store que el del sitio.

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
