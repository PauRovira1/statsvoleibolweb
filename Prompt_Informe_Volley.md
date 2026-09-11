# Prompt reutilizable — Informe de partido en Excel

> Copia todo lo que sigue y pégalo junto con el volcado de estadísticas del partido.

---

Te voy a pasar el volcado de estadísticas de un partido de vóleibol de mi equipo. Genera un archivo **Excel** con el siguiente formato exacto.

## Regla principal

**Solo información, sin juicios de valor.** No incluyas resúmenes ejecutivos, hallazgos, conclusiones, recomendaciones, evaluaciones, semáforos, referencias competitivas ni columnas de "lectura" o "comentario". Únicamente tablas con datos, totales y porcentajes. La única excepción son notas al pie sobre completitud del dato (ej. cuántas acciones no tienen zona registrada).

## Hojas (en este orden y con estos nombres)

**1. Partido**
- Marcador: fila por set con puntos de cada equipo, más filas de "Sets ganados" y "Puntos totales anotados".
- Totales registrados de mi equipo: puntos jugados, recepciones, armados, ataques.

**2. Fases y armador**
- Puntos por fase del rally: una fila por fase (K1, K2, K3, Saque, Sin fase) con Hechos · % de los hechos · Ganados · Por error del rival · Recibidos · % de los recibidos · Ganados por el rival · Por error propio, y fila TOTAL. K1 = recepción, armado y ataque; K2 = primera defensa del rally, armado y ataque; K3 = el resto del rally. "Saque" son los puntos que se definieron en el saque (as o error) sin llegar a la recepción, y "Sin fase" un error en juego antes de cualquier jugada: van aparte para que el total de hechos dé el marcador propio y el de recibidos el del rival. Un punto es **ganado** si lo cerró una acción de quien se lo llevó (ataque punto, usar el bloqueo, bloqueo o as) y **por error** si lo cerró una falla del que lo perdió; el mismo punto es error del rival entre los hechos y error propio entre los recibidos.
- Segunda tabla: puntos por causa, con Causa · Tipo (Ganado / Error) · Hechos · Recibidos y fila TOTAL. Las causas ganadas son ataque punto, ataque usando el bloqueo, bloqueo punto y as de saque; las de error son ataque afuera, ataque a la malla, error de saque, armado malo, defensa perdida y error en juego.
- Tercera y cuarta tabla: puntos **hechos** y puntos **recibidos** con el armador en cada zona. Una fila por zona (1 a 6), una columna por K1 · K2 · K3 · As · Error de saque · Sin fase, más el total y su % del total. El saque va partido en dos porque un as y un error de saque del rival no son la misma situación: en el as sacaba el equipo de la tabla y en el error sacaba el rival. La zona es dónde estaba parado el armador propio (el del flag `_S`) en cada punto, que es como se nombra la rotación: de ahí depende si arma de adelante o de atrás y con cuántos atacantes cuenta. Los puntos cargados sin rotación no tienen zona y no entran en estas dos tablas.
- Si el volcado no trae estos desgloses, en lugar de las tablas va una nota diciendo que hay que recargar el partido con la versión actual.

**3. Recepción**
- Tabla por jugador, ordenada de mayor a menor volumen: Jugador · Recepciones · % del total del equipo · Calidad 3 · Calidad 2 · Calidad 1 · Calidad 0 · Pase al otro lado · % Positiva (cal. 2+3) · % Perfecta (cal. 3). Fila TOTAL al final.
- Si el partido tiene más de un set, una tabla por set con las mismas columnas ("% del set" en lugar de "% del total") y su fila TOTAL.
- Segunda tabla: distribución de calidad del equipo (cada calidad con su conteo y % del total).
- Tercera tabla: recepción según tipo de saque y par de zonas. Columnas: Tipo de saque · Par de zonas · Recibidos · % del total · Calidad 3 · Calidad 2 · Calidad 1 · Calidad 0 · Pase al otro lado · % Positiva (cal. 2+3) · % Perfecta (cal. 3). Una fila por par concreto de zonas (1 a 5, 5 a 1, 6 a 6 dentro de Paralelo; 1 a 1, 5 a 5, 6 a 1, 6 a 5 dentro de Cruzado), una fila "Subtotal <tipo>" por tipo, y fila TOTAL al final. Las zonas se numeran desde cada lado, así que la zona 1 de un lado queda enfrentada a la zona 5 del otro: saque paralelo = va derecho a la zona de enfrente; saque cruzado = va en diagonal. Los saques a otras zonas no entran, y los pares sin recepciones registradas no se listan.

**4. Armado**
- Armados por zona, ordenado por volumen: Zona · Armados · % del total. Fila TOTAL.
- Si el partido tiene más de un set, una tabla "Armado por zona y set": una fila por set, una columna por zona, columna Total y fila TOTAL (que debe coincidir con la tabla anterior).
- Tabla "Armado por armador": una fila por armador (los marcados con `_S` en la rotación), una columna por zona, más Total y "% del total del equipo". Fila "Otros jugadores" con la diferencia contra el total del equipo —los armados de emergencia que hace cualquier jugador cuando el armador defiende la pelota— y fila TOTAL. Si el volcado no trae el desglose, una nota en lugar de la tabla.
- Si hay más de un set, tabla "Armado por armador y set": Set · Armador · una columna por zona · Total.
- Matriz calidad de recepción × zona armada, en **frecuencia** (filas = calidad 3, 2, 1, 0; columnas = zonas; columna Total; fila TOTAL).
- La misma matriz en **% por fila**.
- La misma matriz abierta por armador, en frecuencia y en % por fila: columnas Armador · Calidad · una por zona · Total, con una fila por cada par (armador, calidad). Sirve para comparar a dónde distribuye cada armador con la misma calidad de recepción. Solo los armadores marcados con `_S`; si el volcado no trae el desglose, no se incluyen estas dos tablas.

**5. Ataque jugador**
- Tabla por jugador, ordenada por volumen de ataques: Jugador · Ataques · % del total de ataques · Puntos · Defendidos · Fuera · % Punto · % Defendido · % Fuera. Fila TOTAL. Los ataques que hacen punto usando el bloqueo cuentan como Puntos del atacante.
- Segunda tabla: bloqueos punto por jugador, ordenada por volumen: Jugador · Bloqueos punto · % del total del equipo. Fila TOTAL. Va aparte de la tabla de ataques porque bloquear no es atacar y hay jugadores que bloquean sin haber atacado. Solo entra el bloqueo que es punto de quien bloquea; los otros toques de bloqueo no, porque uno es punto del atacante y el otro deja la pelota en juego. Si el volcado no trae bloqueos, una nota en lugar de la tabla.
- Tercera tabla: ataques por jugador y zona de origen (una columna por zona, ordenadas por volumen), más columnas "Total con zona", "Sin zona registrada" y "Ataques totales". Fila TOTAL.

**6. Zona y dirección**
- Resultado por zona de origen, ordenado por volumen: Zona · Ataques · % del total · Puntos · Defendidos · Fuera · % Punto · % Fuera. Fila TOTAL.
- Resultado por dirección del ataque (mismas columnas). Fila TOTAL.
- Matriz zona de origen × dirección con ataques totales, columna Total y fila TOTAL.

**No incluyas hoja de detalle jugador × zona × dirección.**

## Formato

- Fuente Arial en todo el archivo. Sin líneas de cuadrícula.
- Título de hoja en banda azul oscuro (`1F3864`), texto blanco, 14 pt negrita.
- Subtítulo de cada tabla en banda azul medio (`2E5C9A`), texto blanco, 11 pt negrita.
- Encabezados de columna: mismo azul medio, texto blanco 10 pt negrita, centrado y con ajuste de texto.
- Celdas de datos con borde fino gris, centradas; primera columna alineada a la izquierda y en negrita.
- Filas TOTAL con relleno gris claro (`F2F2F2`) y negrita.
- Sin colores por rendimiento (nada de verde/amarillo/rojo).
- Porcentajes en formato `0.0%` guardados como fracción.
- Ancho de columna ajustado al contenido; panel superior congelado.

## Cálculos

- **Arma las tablas con fórmulas de Excel sobre la hoja `Datos_Base`**: los totales con `SUM`, los porcentajes como división de celdas (`=D5/B5`), protegidos con `IFERROR` cuando el denominador pueda ser cero. Es la forma de que todos los totales salgan del mismo lugar y cuadren entre sí. Al guardar, esas fórmulas se reemplazan por su resultado (ver Entrega): la hoja `Datos_Base` queda igual, así que se puede auditar de dónde sale cada número, pero el archivo ya no se recalcula solo — para corregir un dato hay que volver a generar el informe.
- Deriva las tablas agregadas de los datos base; no las tipees a mano, para que los totales cuadren entre hojas.
- Antes de entregarme el archivo, verifica que los totales de cada tabla cuadren entre sí (ataques por jugador = ataques por zona + sin zona = ataques por dirección + sin dirección) y avísame de cualquier descuadre en el volcado original.

## Nomenclatura

- Todo en español.
- Calidad de recepción: 3 = perfecta, 2 = buena, 1 = mala, 0 = rota, más "Pase al otro lado".
- Resultado de ataque: Puntos (efectivo/punto directo, incluye usar el bloqueo) · Defendidos · Fuera (incluye ataque bloqueado, a la malla y afuera).
- Zonas tal como vengan en el volcado (1, 2, 3, 4, 6-5).

## Entrega

- Nombre del archivo: `Informe_<MiEquipo>_vs_<Rival>_<AAAA-MM-DD>.xlsx`
- Se entrega **un solo archivo, con los números escritos y sin fórmulas**, porque se abre desde el celular y los visores no recalculan: leen el valor guardado y, si solo hay fórmula, muestran las tablas vacías. Si alguna fórmula no se pudiera calcular, queda sin resolver y se avisa, en lugar de escribir un número posiblemente equivocado.
- En el chat, dime solo qué contiene cada hoja y cualquier inconsistencia de dato que hayas encontrado. Sin análisis del rendimiento.
