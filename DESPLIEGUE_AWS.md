# Poner la app a correr en AWS

Todo lo que hay que hacer, en orden, desde una cuenta de AWS vacia hasta
abrirla en el celular con tu dominio.

Sale **~$0,15 al año**. Lambda y CloudFront tienen free tier perpetuo (no de
12 meses); lo unico que se paga es S3, y son centavos.

    Internet --HTTPS--> CloudFront --> Lambda Function URL --> lambda_handler
                             |                                      |
                     tu dominio + certificado                  S3 (todo)

En casa no cambia nada: `python servidor_voley.py` sigue andando igual.

## Como leer este documento

Los botones van como **Español** *(English)*, porque la consola traduce casi
todo pero no siempre igual, y buscando el termino en ingles se encuentra
siempre.

**Tres cosas NO se traducen nunca**, aunque la consola este en español:

- Los nombres de policies: `AmazonS3FullAccess`, `AWSLambdaBasicExecutionRole`,
  `CachingDisabled`, `AllViewerExceptHostHeader`. Son identificadores.
- El AWS CLI. Sigue preguntando `AWS Access Key ID` en ingles.
- Namecheap, que es otro sitio y esta en ingles.

## Antes de arrancar

**Dejá la region en `us-east-1` (Norte de Virginia) en TODA la consola.** Esta
arriba a la derecha. Es la mas barata, y es la unica donde CloudFront acepta el
certificado. Si creas algo en otra region no vas a ver un error: simplemente
las cosas no se van a encontrar entre si.

Te va a convenir ir anotando cuatro valores a medida que aparecen:

| Valor | De donde sale | El tuyo |
|---|---|---|
| Nombre del bucket | paso 2 | |
| URL de la funcion | paso 9 | |
| Dominio de la distribucion | paso 12 | |
| Tu subdominio | vos elegis | `www.statsvoleypalestino.lat` |

El orden esta pensado para que cada paso se pueda probar solo. Si algo falla,
falla ahi y no tres pasos despues.

---

# Parte 1 — El almacenamiento

## 1. La alarma de facturacion

Antes de crear un solo recurso.

1. Consola -> **Facturación y administración de costos** *(Billing and Cost
   Management)* -> **Presupuestos** *(Budgets)*.
2. **Crear presupuesto** *(Create budget)* -> **Personalizar (avanzado)**
   *(Customize (advanced))* -> **Presupuesto de costos** *(Cost budget)*.
3. Monto: **3 USD** por mes. Alerta al **50%**.
4. Tu mail, y confirmalo desde el correo que llega.

Ponelo en $3 y no en tu presupuesto real: asi te enteras cuando algo se salio
de lo normal pero todavia no costo nada. Lo normal son 2 centavos al mes.

## 2. El bucket

S3 -> **Crear bucket** *(Create bucket)*.

| Campo | Que poner |
|---|---|
| **Nombre del bucket** *(Bucket name)* | `voley-pau-2026` (unico en todo AWS, **sin puntos**) |
| **Región** *(Region)* | **us-east-1** (Norte de Virginia) |
| **Bloquear todo el acceso público** *(Block all public access)* | **activado** (queda por defecto) |
| **Control de versiones de bucket** *(Bucket Versioning)* | **Habilitar** *(Enable)* |

Sin puntos en el nombre porque S3 se accede como
`bucket.s3.region.amazonaws.com`, y con un punto adentro el certificado
comodin no valida.

El control de versiones guarda cada version de cada partido. Es gratis a este
tamaño y es tu red si un dia se pisa un archivo mal.

## 3. Un usuario para tu PC

**No uses la cuenta raiz para esto.** Sus claves no se pueden limitar y si se
filtran no hay vuelta atras.

IAM -> **Usuarios** *(Users)* -> **Crear usuario** *(Create user)*.

1. Nombre: `pau-cli`. **No** marques el acceso a la consola de administracion.
2. **Adjuntar políticas directamente** *(Attach policies directly)* -> buscar y
   marcar **`AmazonS3FullAccess`**.
   **No saltees esto**: la pantalla te deja darle **Siguiente** *(Next)* sin
   marcar nada, y el usuario queda creado pero sin ningun permiso. Se nota
   recien en el paso 4, con un `AccessDenied ... s3:ListAllMyBuckets` que
   parece un problema del bucket y es del usuario.
3. **Crear usuario** *(Create user)*.
4. Entrar al usuario -> pestaña **Credenciales de seguridad** *(Security
   credentials)* -> **Crear clave de acceso** *(Create access key)* ->
   **Interfaz de línea de comandos (CLI)** *(Command Line Interface)* ->
   confirmar -> **Crear clave de acceso**.
5. **Copiá las dos** ahora: el secreto no se vuelve a mostrar nunca.

**El secreto no se pega en ningun lado que no sea `aws configure`.** Ni en un
chat, ni en un mail, ni en un archivo del repo. Si alguna vez quedo a la
vista, la unica solucion es borrar esa clave en *Credenciales de seguridad* y
crear otra; cambiarla no "arregla" la vieja, hay que borrarla.

Una **Access Key ID** son 20 caracteres y empieza con `AKIA`. Un **Secret
Access Key** son 40 caracteres. Si lo que copiaste no tiene esa forma,
copiaste otra cosa.

> Si alguna vez pegaste en `aws configure` el link de la consola y la clave de
> tu cuenta, estan guardados en texto plano en `C:\Users\<vos>\.aws\credentials`.
> Conviene cambiar esa clave y rehacer el paso.

## 4. El AWS CLI

Instalalo desde [aws.amazon.com/cli](https://aws.amazon.com/cli/), cerra y
abri la terminal, y:

    aws configure

**El CLI esta en ingles siempre**, no lo traduce la consola:

| Te pregunta | Poné |
|---|---|
| `AWS Access Key ID` | la que empieza con `AKIA` |
| `AWS Secret Access Key` | la de 40 caracteres |
| `Default region name` | `us-east-1` |
| `Default output format` | `json` |

Probalo:

    aws s3 ls

Tiene que listar tu bucket. Si dice `InvalidClientTokenId`, las claves estan
mal copiadas.

## 5. Subir los partidos que ya tenes

`Datos` e `Informes` son las carpetas **del proyecto**, asi que el `cd` es
parte del comando: desde otro lado da "The user-provided path Datos does not
exist".

    cd C:\Users\56982\statsvoleibolweb
    aws s3 sync Datos s3://voley-pau-2026/Datos
    aws s3 sync Informes s3://voley-pau-2026/Informes

`voley-pau-2026` es el nombre de ejemplo. Si el tuyo es otro -- `aws s3 ls` te
lo dice -- cambialo aca, en la policy del paso 7 y en `VOLEY_S3_BUCKET` del
paso 8. Tiene que ser el mismo en los tres lugares.

Si ademas hay partidos en el Blob de Vercel que no estan en el repo, bajalos
primero. En PowerShell:

    $env:BLOB_READ_WRITE_TOKEN = "vercel_blob_rw_..."
    python -c "import almacenamiento as alm; alm.sincronizar_todo(refrescar=True)"

y volve a correr los dos `sync`.

> No te preocupes si un partido queda en los dos lados (en el paquete y en
> S3): la app los muestra una sola vez, prefiriendo el de S3.

## 6. Comprobar que S3 anda — **antes** de tocar Lambda

Este es el paso que te ahorra la tarde:

    cd C:\Users\56982\statsvoleibolweb
    python probar_s3.py --bucket voley-pau-2026

Prueba los cinco permisos uno por uno y dice cual falla:

    1. La configuracion
    2. Listar el bucket       [s3:ListBucket]
    3. Los partidos que hay
    4. Subir un archivo       [s3:PutObject]
    5. Pedir la cabeza        [s3:GetObject]
    6. Bajarlo y comparar     [s3:GetObject]
    7. Borrarlo               [s3:DeleteObject]

    === S3 esta bien. Lo que falle de aca en mas es de Lambda. ===

**No sigas hasta que este paso pase entero.** Si falla aca, el problema es del
bucket o de las credenciales, y desde Lambda el mismo error se ve como un 500
sin explicacion.

---

# Parte 2 — La aplicacion

## 7. El rol de la funcion

Este rol es el de **Lambda**, distinto del usuario del paso 3. Lambda le
inyecta credenciales temporales solas, asi que en la funcion no se guarda
ninguna clave.

IAM -> **Roles** -> **Crear rol** *(Create role)*.

1. **Servicio de AWS** *(AWS service)* -> **Lambda** -> **Siguiente** *(Next)*.
2. Marcar **`AWSLambdaBasicExecutionRole`** (son los logs). **Siguiente**.
3. **Nombre del rol** *(Role name)*: `voley-lambda`. **Crear rol**.
4. Entrar al rol -> **Agregar permisos** *(Add permissions)* -> **Crear
   política insertada** *(Create inline policy)* -> pestaña **JSON**. Pegar
   esto, cambiando el nombre del bucket en los dos lugares:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
    "Resource": [
      "arn:aws:s3:::voley-pau-2026",
      "arn:aws:s3:::voley-pau-2026/*"
    ]
  }]
}
```

5. Nombre: `voley-s3`. **Crear política** *(Create policy)*.

Las **dos** lineas del `Resource` hacen falta: la de arriba (sin barra) es
para listar el bucket, la de abajo para tocar los archivos. Con una sola,
falla con un `AccessDenied` que no dice cual falta.

## 8. La funcion

Armá el paquete en tu PC, siempre desde la carpeta del proyecto:

    cd C:\Users\56982\statsvoleibolweb
    python empaquetar_lambda.py

Deja `lambda_voley.zip`, de medio MB.

Lambda -> **Crear función** *(Create function)* -> **Crear desde cero**
*(Author from scratch)*.

| Campo | Que poner |
|---|---|
| **Nombre de la función** *(Function name)* | `voley` |
| **Tiempo de ejecución** *(Runtime)* | **Python 3.12** |
| **Arquitectura** *(Architecture)* | `x86_64` |
| **Rol de ejecución** *(Execution role)* | Desplegar **Cambiar el rol de ejecución predeterminado** *(Change default execution role)* -> **Usar un rol existente** *(Use an existing role)* -> **voley-lambda** |

> **Ese desplegable viene cerrado.** Si no lo abris y elegis `voley-lambda`,
> Lambda te crea un rol propio llamado `voley-role-XXXXXXXX` que solo sabe
> escribir logs, y la app arranca pero avisa
> `AccessDenied ... s3:ListBucket`. Se arregla sin rehacer nada: **Configuración
> -> Permisos**, clic en el nombre del rol, y le pegas ahi la misma policy del
> paso 7. El `voley-lambda` que queda sin usar se puede borrar.

Creada:

1. **Código** *(Code)* -> **Cargar desde** *(Upload from)* -> **Archivo .zip**
   *(.zip file)* -> subir `lambda_voley.zip`.
2. **Código** -> abajo de todo, **Configuración del tiempo de ejecución**
   *(Runtime settings)* -> **Editar** *(Edit)* ->
   **Controlador** *(Handler)*: **`lambda_handler.handler`** (asi, con el punto).
3. **Configuración** *(Configuration)* -> **Configuración general** *(General
   configuration)* -> **Editar**:
   - **Memoria** *(Memory)*: **512 MB**
   - **Tiempo de espera** *(Timeout)*: **30 seg**
4. **Configuración** -> **Variables de entorno** *(Environment variables)* ->
   **Editar**:

| Clave *(Key)* | Valor *(Value)* |
|---|---|
| `VOLEY_S3_BUCKET` | `voley-pau-2026` |
| `VOLEY_CLAVE` | la contraseña con la que vas a cargar |
| `VOLEY_SECRETO` | cualquier cadena larga que inventes |
| `VOLEY_CACHE_BLOB` | `30` |

`VOLEY_SECRETO` firma los tokens de la pantalla. Si no esta, se usa la
contraseña, y cambiarla te desloguearia.

Las credenciales de AWS **no van aca**. Las pone la plataforma desde el rol.

> 512 MB y 30 s son de sobra: generar el Excel de un partido de 95 puntos
> tarda 0,2 segundos.

## 9. La URL de la funcion y la primera prueba

En la funcion: **Configuración** *(Configuration)* -> **URL de la función**
*(Function URL)* -> **Crear URL de función** *(Create function URL)*.

- **Tipo de autenticación** *(Auth type)*: **NONE**
- **Configurar CORS** *(Configure CORS)*: **desmarcado**

Te queda algo como `https://abc123....lambda-url.us-east-1.on.aws/`. **Anotala.**

Abrila en el navegador. Tiene que aparecer la pantalla y dejarte entrar con tu
contraseña. Cargá dos o tres jugadas, guardá, y confirmá que llegaron:

    aws s3 ls s3://voley-pau-2026/Datos/

**Si esto anda, lo dificil ya esta.** Lo que queda es ponerle tu nombre.

Si falla, los logs estan en la funcion -> **Monitorear** *(Monitor)* -> **Ver
registros de CloudWatch** *(View CloudWatch logs)* -> el ultimo **flujo de
registro** *(log stream)*. Los errores de S3 salen con el motivo adentro
(`AccessDenied`, `NoSuchBucket`), que te dice que paso quedo mal.

---

# Parte 3 — Tu dominio

Podes usar la app desde ya con la URL del paso 9. Esta parte es solo para que
tenga un nombre lindo.

## 10. El certificado, en us-east-1

**AWS Certificate Manager (ACM)**, **con `us-east-1` seleccionada arriba a la
derecha**. CloudFront solo lee certificados de esa region. Es el error mas
comun de todo este documento: si lo pedis en otra, no aparece en la lista del
paso 12 y nada explica por que.

1. **Solicitar** *(Request)* -> **Solicitar un certificado público** *(Request a
   public certificate)* -> **Siguiente**.
2. **Nombre de dominio completo** *(Fully qualified domain name)*:
   **`www.statsvoleypalestino.lat`**
3. **Método de validación** *(Validation method)*: **Validación de DNS** *(DNS
   validation)*.
4. **Solicitar** *(Request)*.

Entrá al certificado y copiá el **Nombre CNAME** *(CNAME name)* y el **Valor
CNAME** *(CNAME value)*.

## 11. Namecheap: validar el certificado

**Namecheap esta en ingles**, no lo traduce nadie.

*Domain List* -> **Manage** -> pestaña **Advanced DNS** -> *Add New Record*.

| Campo | Que poner |
|---|---|
| Type | **CNAME Record** |
| Host | el *CNAME name* de ACM, **sin tu dominio al final** |
| Value | el *CNAME value* de ACM, **con el punto final incluido** |
| TTL | Automatic |

El punto final del Value se deja: hace explicito que es un nombre absoluto, y
es el mismo formato que usan los registros por defecto de Namecheap
(`parkingpage.namecheap.com.`). Sin el tambien suele andar, pero con el no hay
manera de que se interprete mal.

ACM te muestra algo como `_a1b2c3.www.statsvoleypalestino.lat.`, pero Namecheap agrega
tu dominio solo. En **Host** va unicamente `_a1b2c3.www`. Si pegas el nombre
entero queda `_a1b2c3.www.statsvoleypalestino.lat.statsvoleypalestino.lat` y no valida nunca.

Volvé a ACM y esperá a que diga **Emitido** *(Issued)*. Suele tardar unos
minutos.

## 12. CloudFront

CloudFront -> **Crear distribución** *(Create distribution)*.

**Origen** *(Origin)*

| Campo | Que poner |
|---|---|
| **Dominio de origen** *(Origin domain)* | el host de la URL de la funcion, **sin `https://` ni la barra final** |
| **Protocolo** *(Protocol)* | **Solo HTTPS** *(HTTPS only)* |

O sea `abc123....lambda-url.us-east-1.on.aws`. Escribilo a mano; no lo elijas
de la lista desplegable, que ofrece buckets.

**Comportamiento de caché predeterminado** *(Default cache behavior)*

| Campo | Que poner |
|---|---|
| **Política de protocolo del visor** *(Viewer protocol policy)* | **Redirigir HTTP a HTTPS** *(Redirect HTTP to HTTPS)* |
| **Métodos HTTP permitidos** *(Allowed HTTP methods)* | **GET, HEAD, OPTIONS, PUT, POST, PATCH, DELETE** |
| **Política de caché** *(Cache policy)* | **`CachingDisabled`** |
| **Política de solicitudes de origen** *(Origin request policy)* | **`AllViewerExceptHostHeader`** |
| **Comprimir objetos automáticamente** *(Compress objects automatically)* | **Sí** *(Yes)* |

Esas dos policies **se llaman asi en ingles tambien en la consola en
español**: son identificadores de AWS, no texto traducible. Y son las dos que
hacen que esto funcione:

- **`CachingDisabled`**: la app es toda dinamica. Con cache, cargar una jugada
  podria contestarte el estado anterior.
- **`AllViewerExceptHostHeader`**: pasa todas las cabeceras **menos** `Host`.
  Una URL de funcion rechaza los pedidos que traen el `Host` de otro dominio,
  asi que sin esta politica **todo** contesta 403.

**Configuración** *(Settings)*

| Campo | Que poner |
|---|---|
| **Clase de precio** *(Price class)* | **Usar solo América del Norte y Europa** *(Use only North America and Europe)* |
| **Nombre de dominio alternativo (CNAME)** *(Alternate domain name)* | `www.statsvoleypalestino.lat` |
| **Certificado SSL personalizado** *(Custom SSL certificate)* | el del paso 10 |

**Crear distribución**. Tarda unos minutos en pasar a **Habilitada**
*(Enabled)*. Copiá el **Nombre de dominio de la distribución** *(Distribution
domain name)*, que es como `d1234abcd.cloudfront.net`.

## 13. Namecheap: apuntar el dominio

Este es el segundo CNAME y **no reemplaza al del paso 11**: hacen cosas
distintas y los dos tienen que quedar.

| | Paso 11 | Paso 13 (este) |
|---|---|---|
| Host | `_ba91....www` | `www` |
| Apunta a | `...acm-validations.aws.` | `dXXXX.cloudfront.net` |
| Para que | probarle a AWS que el dominio es tuyo | mandar a la gente a la app |
| Lo visita alguien | nunca | todo el trafico |

El del paso 11 es una prueba de identidad: ACM invento un nombre al azar y
solo quien controla el DNS puede publicarlo. **No lo borres nunca**, ni
despues de que el certificado diga Emitido: ACM lo vuelve a consultar cada año
para renovarlo solo, y sin el la renovacion falla y un dia el sitio se queda
sin HTTPS sin avisar.

Son hosts distintos, asi que conviven sin conflicto.

Advanced DNS -> *Add New Record*:

| Campo | Que poner |
|---|---|
| Type | **CNAME Record** |
| Host | `www` |
| Value | `d1234abcd.cloudfront.net` |
| TTL | Automatic |

**Dejá el DNS en Namecheap.** Mover la zona a Route 53 cuesta $0,50 al mes por
hosted zone: $6 al año, cuarenta veces toda la cuenta de AWS de este proyecto.

### Que el dominio pelado tambien ande

Alguien lo va a escribir sin `www` y le va a dar `DNS_PROBE_FINISHED_NXDOMAIN`,
porque la raiz no tiene ningun registro. Se arregla gratis con otro registro:

| Campo | Que poner |
|---|---|
| Type | **URL Redirect Record** |
| Host | `@` |
| Value | `https://www.statsvoleypalestino.lat/` |
| Redirect type | `Permanent (301)` |

**No pongas un ALIAS de la raiz a CloudFront.** El certificado cubre solo
`www.statsvoleypalestino.lat`, asi que el dominio pelado mostraria una
advertencia de certificado. Para servirlo de verdad habria que pedir un
certificado que cubra los dos nombres y agregarlo en CloudFront; el redirect
hace el mismo trabajo sin nada de eso.

## 14. Probar de verdad

Esperá unos minutos a que propague y abrí **https://www.statsvoleypalestino.lat**
**desde el celular**, que es donde la vas a usar.

Cargá un partido de prueba entero: rotaciones, un cambio, un líbero, cerrá un
set, generá el Excel y bajalo. Confirmá que el `.xlsx` abre bien — por el
camino de Lambda viaja en base64 y es lo unico que no se puede verificar
desde la PC.

Despues borralo desde la pantalla de Partidos.

## 15. Apagar Vercel

Recien cuando lo de arriba ande.

1. Vercel: pausar o borrar el proyecto.
2. **No borres el Blob store todavia.** Dejalo un mes; sin escrituras no gasta
   operaciones.

---

# Despues

## Cambiar el codigo

El codigo vive adentro del `.zip`, asi que **cada cambio necesita un zip
nuevo**. Son dos comandos:

    cd C:\Users\56982\statsvoleibolweb
    python -m unittest discover -p "test_*.py"
    python empaquetar_lambda.py --subir

`--subir` arma el zip y lo manda a la funcion `voley`. Tarda unos segundos.

**El partido que este cargado no se pierde.** La sesion vive en S3, no en la
memoria de la funcion, asi que el primer pedido despues de la actualizacion la
vuelve a leer de ahi. Se puede actualizar en medio de un partido.

No hay que tocar CloudFront (no cachea nada), ni el rol, ni la URL, ni S3.

### Permiso para subir, una sola vez

El usuario `pau-cli` arranca con acceso solo a S3, asi que la primera vez
`--subir` falla con `AccessDenied ... lambda:UpdateFunctionCode`. Se le agrega
el permiso una vez y listo:

IAM -> **Usuarios** -> `pau-cli` -> **Agregar permisos** -> **Crear política
insertada** -> pestaña **JSON**:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["lambda:UpdateFunctionCode", "lambda:GetFunction"],
    "Resource": "arn:aws:lambda:us-east-1:*:function:voley"
  }]
}
```

Nombre: `voley-deploy`. Es solo sobre esta funcion y solo para actualizar el
codigo: no puede borrarla ni cambiarle la configuracion.

### Si preferis no usar el CLI

    python empaquetar_lambda.py

y subir `lambda_voley.zip` a mano: Lambda -> `voley` -> **Código** -> **Cargar
desde** -> **Archivo .zip**. No hace falta el permiso de arriba.

### Lo que NO necesita zip nuevo

Cambiar la contraseña, el bucket o cualquier variable se hace en
**Configuración -> Variables de entorno**, y toma efecto en el proximo pedido.

## El dia a dia

| Que | Como |
|---|---|
| Ver los logs | Lambda -> `voley` -> **Monitorear** *(Monitor)* -> **Ver registros de CloudWatch** |
| Bajarte los partidos | `aws s3 sync s3://voley-pau-2026/Datos Datos` |
| Cambiar la contraseña | Lambda -> **Configuración** -> **Variables de entorno** |
| Ver cuanto gastaste | **Facturación** *(Billing)* -> **Facturas** *(Bills)* |
| Recuperar un archivo pisado | S3 -> el archivo -> pestaña **Versiones** *(Versions)* |
| Borrar una clave de acceso | IAM -> **Usuarios** -> `pau-cli` -> **Credenciales de seguridad** -> **Acciones** *(Actions)* -> **Eliminar** |

## Lo que cuesta

| Item | Al mes |
|---|---|
| Lambda | **$0** — 1M invocaciones y 400.000 GB-s, perpetuo. Usas el 0,8% |
| CloudFront | **$0** — 1 TB y 10M pedidos, perpetuo |
| Certificado ACM | **$0** |
| DNS en Namecheap | **$0**, ya pagado con el dominio |
| S3 | ~$0,012 |
| | **~$0,15 al año** |

## Si algo no anda

Los mensajes de error **salen en ingles aunque la consola este en español**.

| Sintoma | Casi siempre es |
|---|---|
| `aws s3 ls` da `InvalidClientTokenId` | Las claves estan mal copiadas (paso 3) |
| `aws s3 ls` da `AccessDenied ... s3:ListAllMyBuckets` | Al usuario no se le adjunto ninguna policy (paso 3.2) |
| `probar_s3.py` falla al listar | A la policy le falta el ARN **sin** la barra |
| `probar_s3.py` falla al subir | A la policy le falta el ARN **con** `/*` |
| Lambda da 500 y el log dice `No module named 'lambda_function'` | El **Controlador** *(Handler)* quedo en el default: va `lambda_handler.handler` |
| La app abre pero avisa `AccessDenied ... s3:ListBucket` | La funcion quedo con un rol `voley-role-XXXXXXXX` que Lambda creo solo (paso 8) |
| Se ven partidos viejos y no los nuevos | Falta `VOLEY_S3_BUCKET`: sin ella escribe en `/tmp` y se pierde |
| Carga la pantalla pero no deja entrar | `VOLEY_CLAVE` no esta puesta, o no es la que tipeas |
| Lambda da `NoSuchBucket` | `VOLEY_S3_BUCKET` mal escrito, o con comillas pegadas |
| CloudFront da **403** en todo | Falta la politica de solicitudes de origen **`AllViewerExceptHostHeader`** |
| CloudFront da **403** en una jugada puntual y el resto anda | El WAF la confundio con un ataque. CloudFront -> **Seguridad** -> activar *monitor mode* para ver que regla salto |
| El certificado no aparece en CloudFront | Lo pediste fuera de **us-east-1** |
| ACM nunca valida | En Namecheap el **Host** lleva el dominio repetido |
| El dominio no resuelve | Todavia propaga; probá en una ventana de incognito |

## Que hay en el repo para esto

| Archivo | Que hace |
|---|---|
| `almacen_s3.py` | Habla con S3. Firma SigV4 a mano, sin boto3 |
| `lambda_handler.py` | Traduce el evento de Lambda al manejador de siempre |
| `empaquetar_lambda.py` | Arma el `.zip` |
| `probar_s3.py` | Comprueba S3 desde tu PC (paso 6) |
| `test_almacen_s3.py` | 28 tests, incluidos los vectores de firma de AWS |
| `test_lambda_handler.py` | 15 tests de la traduccion |

Lambda se comporta igual que Vercel: pedidos aislados, carpeta de solo lectura
y `/tmp` efimero. Ese camino ya estaba en el proyecto desde antes —
`EN_SERVERLESS` en `almacenamiento.py` detecta `AWS_LAMBDA_FUNCTION_NAME` — asi
que lo unico que cambio en la migracion fue **contra quien habla la capa de
almacenamiento**.
