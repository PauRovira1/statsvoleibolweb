/* Interfaz web de estadisticas de voley.
 *
 * Tres pestanas sobre la misma pagina: Cargar (la pantalla de la cancha),
 * Partidos (buscar y abrir lo que ya esta en disco) y Jugadores (maqueta).
 * Sin dependencias y sin nada remoto: al costado de la cancha puede no haber
 * internet, asi que hasta el grafico esta dibujado a mano.
 *
 * El partido en curso es de esta pantalla y no del servidor (ver 2a): las
 * lineas viven en el navegador y viajan en cada pedido. El servidor las corre
 * por el motor y contesta como quedo el partido; eso es lo que se pinta.
 */

// ======================================================================
// 0) Utilidades
// ======================================================================
const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));

// Token de la pantalla de carga (ver 2b). Se declara aca porque todos los
// pedidos lo mandan: el servidor rechaza con 401 los que escriben sobre el
// partido si no lo reconoce.
let token = "";

// Cada pedido lleva el partido entero, asi que el cuerpo crece con cada punto.
// En AWS, el WAF de CloudFront corta con un 403 los cuerpos de mas de 8 KB, y
// antes de llegar ahi sus reglas contra ataques pueden confundir una jugada
// con uno. Por eso viaja comprimido: {"z": gzip en base64}, chico y opaco. El
// servidor acepta las dos formas, asi que un navegador sin CompressionStream
// lo sigue mandando como siempre.
async function empaquetar(datos){
  const texto = JSON.stringify(datos);
  if(typeof CompressionStream === "undefined") return texto;
  try{
    const flujo = new Blob([texto]).stream().pipeThrough(new CompressionStream("gzip"));
    const bytes = new Uint8Array(await new Response(flujo).arrayBuffer());
    let binario = "";
    for(let i = 0; i < bytes.length; i += 0x8000)
      binario += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return JSON.stringify({z: btoa(binario)});
  }catch(_){
    return texto;
  }
}

async function api(ruta, datos){
  const cabeceras = token ? {"X-Clave": token} : {};
  if(datos) cabeceras["Content-Type"] = "application/json";
  const opciones = datos
    ? {method:"POST", headers:cabeceras, body: await empaquetar(datos)}
    : {headers:cabeceras};
  let r;
  try{
    r = await fetch(ruta, opciones);
  }catch(_){
    return {ok:false, mensaje:"Sin conexion con el servidor. Lo cargado no se perdio: proba de nuevo."};
  }
  let respuesta;
  try{
    respuesta = await r.json();
  }catch(_){
    // No contesto nuestro servidor sino algo que esta adelante (CloudFront,
    // el WAF): devuelve una pagina HTML. El partido sigue en esta pantalla.
    return {ok:false, mensaje: r.status === 403
      ? "CloudFront rechazo el pedido (403). Lo cargado no se perdio. Si se repite, " +
        "revisa el WAF (ver DESPLIEGUE_AWS.md)."
      : `El servidor contesto algo inesperado (${r.status}). Lo cargado no se perdio: proba de nuevo.`};
  }
  // el servidor se reinicio, o paso el token de otra sesion: vuelve el candado
  if(r.status === 401 || respuesta.clave) olvidarToken();
  return respuesta;
}

// ======================================================================
// 1b) Claro u oscuro
// ======================================================================
// Tres estados y no dos. "Auto" no es lo mismo que elegir oscuro: sigue al
// navegador y cambia CON el, que en un celular que se pasa a oscuro de noche
// es lo que la mayoria quiere. Con dos estados, la primera vez que tocas el
// boton quedas fijo para siempre y no hay forma de volver.
const TEMA = "voley.tema";
const TEMAS = ["auto", "claro", "oscuro"];
const ICONO_TEMA = {auto: "🌗", claro: "☀", oscuro: "☾"};
const COMO_TEMA = {
  auto: "Tema: el del navegador. Tocar para el claro.",
  claro: "Tema: claro. Tocar para el oscuro.",
  oscuro: "Tema: oscuro. Tocar para seguir al navegador.",
};
const prefiereClaro = window.matchMedia("(prefers-color-scheme: light)");

let tema = "auto";
try{ tema = localStorage.getItem(TEMA) || "auto"; }catch(_){ /* sin storage */ }
if(!TEMAS.includes(tema)) tema = "auto";

// La hoja de estilos tiene UNA lista de colores por tema y elige por
// data-tema. En "auto" se copia aca la del navegador en vez de repetir la
// paleta adentro de una media query: dos listas que hay que tocar juntas es
// como se termina con un tema al dia y el otro no.
function aplicarTema(){
  document.documentElement.dataset.tema =
    tema !== "auto" ? tema : (prefiereClaro.matches ? "claro" : "oscuro");
  const boton = $("#btnTema");
  if(boton){
    boton.textContent = ICONO_TEMA[tema];
    boton.title = COMO_TEMA[tema];
  }
}

// En "auto", que cambiarlo en el sistema se vea sin recargar la pagina.
prefiereClaro.addEventListener("change", () => { if(tema === "auto") aplicarTema(); });

$("#btnTema").addEventListener("click", () => {
  tema = TEMAS[(TEMAS.indexOf(tema) + 1) % TEMAS.length];
  try{ localStorage.setItem(TEMA, tema); }catch(_){ /* sin storage, vale para esta visita */ }
  aplicarTema();
});

aplicarTema();

// Casi todo el HTML de esta pagina se arma con plantillas, y los nombres
// vienen de archivos con apostrofos y acentos (O'sommer): sin escapar, un
// nombre asi rompe el atributo o el texto.
function esc(valor){
  return String(valor == null ? "" : valor)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

const num = v => (v == null || v === "" ? 0 : Number(v));
const pct = (parte, total) => total ? (100 * parte / total).toFixed(1) + "%" : "—";
const pctDe = fraccion => (fraccion == null ? "—" : (100 * fraccion).toFixed(1) + "%");
// "10 · 38%": el numero suelto no dice si es mucho o poco sin ir a buscar el
// total a otra columna y dividir de cabeza.
const conParte = (cantidad, total) =>
  !num(total) ? num(cantidad) : `${num(cantidad)} · ${pct(num(cantidad), num(total))}`;

// El orden de las zonas de armado es el del volcado, no el numerico: 6-5 es
// una zona propia y va en el medio.
const ORDEN_ZONAS = ["1", "2", "6-5", "3", "4", "5", "6"];
const ordenZonas = zonas => zonas.slice().sort((a, b) => {
  const ia = ORDEN_ZONAS.indexOf(a), ib = ORDEN_ZONAS.indexOf(b);
  return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || String(a).localeCompare(String(b));
});
// El selector de la pestana Jugadores va por dorsal, de menor a mayor: a
// alguien se lo busca por su numero ("el 13"), no por cuanto toco la pelota.
// El servidor los manda por actividad, que es otro orden util, pero no para
// encontrar a uno.
const porDorsal = jugadores => jugadores.slice().sort((a, b) => {
  const na = parseInt(String(a.dorsal).replace(/\D+/g, ""), 10);
  const nb = parseInt(String(b.dorsal).replace(/\D+/g, ""), 10);
  if(isNaN(na) || isNaN(nb)) return String(a.dorsal).localeCompare(String(b.dorsal));
  return na - nb;
});

// "Jugador 28" ordena por el dorsal, no alfabeticamente (28 antes que 3)
const ordenJugadores = nombres => nombres.slice().sort((a, b) => {
  const na = parseInt(String(a).replace(/\D+/g, ""), 10);
  const nb = parseInt(String(b).replace(/\D+/g, ""), 10);
  return (isNaN(na) ? 1e9 : na) - (isNaN(nb) ? 1e9 : nb);
});

// "grupos" es opcional: una fila de encabezado arriba que junta columnas,
// [{titulo, span}]. Sirve cuando una tabla mezcla cosas (recepcion, ataque,
// saque...) y los encabezados solos no alcanzan para leerla.
function tabla(encabezados, filas, notaAlPie, grupos){
  const arriba = grupos && grupos.length
    ? `<tr>` + grupos.map(g => `<th class="grupo" colspan="${g.span}">${esc(g.titulo)}</th>`).join("") + `</tr>`
    : "";
  const cabeza = arriba + `<tr>` + encabezados.map((h, i) =>
    `<th class="${i ? "num" : ""}">${esc(h)}</th>`).join("") + `</tr>`;
  const cuerpo = filas.map(fila => {
    const celdas = fila.celdas.map((c, i) =>
      `<td class="${i ? "num" : ""}">${esc(c)}</td>`).join("");
    return `<tr class="${fila.total ? "total" : ""}">${celdas}</tr>`;
  }).join("");
  return `<div class="tabla"><table><thead>${cabeza}</thead>
          <tbody>${cuerpo}</tbody></table></div>` +
         (notaAlPie ? `<p class="nota">${esc(notaAlPie)}</p>` : "");
}

// Abrir el archivo en la aplicacion del sistema solo tiene sentido si el
// navegador esta en la misma maquina que el servidor: desde el celular
// abriria Excel en una PC que no se esta mirando.
const esLocal = ["localhost", "127.0.0.1", "[::1]", ""].includes(location.hostname);

const urlDescarga = (archivo, tipo) =>
  `/api/descargar?archivo=${encodeURIComponent(archivo)}&tipo=${encodeURIComponent(tipo)}`;

// ======================================================================
// 1) Pestanas
// ======================================================================
// El orden es el de las pestanas en pantalla, y va de lo general al detalle:
// primero el equipo, despues el jugador, despues el partido suelto. Cargar va
// ultima porque es la que menos se toca: pide la contraseña y se usa una vez
// por partido, mientras que mirar las estadisticas se hace todo el tiempo.
//
// Equipo es la que se abre al entrar. Cargar era la de antes, pensando en la
// cancha, pero ahi se llega igual con un toque y el resto del tiempo lo que
// se quiere ver primero es como viene jugando el equipo.
const VISTAS = ["equipo", "jugadores", "partidos", "cargar"];
let vistaActual = "equipo";

function irA(vista, tocarHash = true){
  if(!VISTAS.includes(vista)) vista = "equipo";
  vistaActual = vista;
  VISTAS.forEach(v => { $("#vista-" + v).hidden = (v !== vista); });
  $$(".pestana").forEach(b => b.classList.toggle("activa", b.dataset.vista === vista));
  if(tocarHash && location.hash !== "#" + vista) location.hash = vista;
  if(vista === "cargar") foco();
  if(vista === "partidos") traerPlantel().then(entrarAPartidos);
  if(vista === "jugadores") traerPlantel().then(pintarJugadores);
  if(vista === "equipo") pintarEquipo();
}

$$(".pestana").forEach(b => b.addEventListener("click", () => irA(b.dataset.vista)));
window.addEventListener("hashchange", () => irA(location.hash.replace("#", ""), false));

// ======================================================================
// 2) CARGAR
// ======================================================================
const campo = $("#linea"), mensaje = $("#mensaje");

// El foco automatico y los atajos son de la pantalla de carga: si el foco se
// robara mientras se esta leyendo un informe, el teclado del celular taparia
// media pantalla en la pestana equivocada.
function foco(){
  if(vistaActual !== "cargar") return;
  if(!token) return campoClave.focus();
  // en el modo visual no se toca el campo: el teclado del celular taparia
  // media cancha justo cuando hay que apretarla
  if(modo === "tocando") return;
  campo.focus();
}

// ======================================================================
// 2a) El partido en curso vive en esta pantalla
// ======================================================================
// Antes el partido era uno solo y vivia en el servidor: dos personas cargando
// al mismo tiempo escribian sobre el mismo partido y se pisaban. Ahora las
// lineas son de este navegador y viajan en cada pedido; el servidor las corre
// por el motor y contesta como quedo, sin guardarse nada. Cada pantalla carga
// lo suyo.
//
// Van en localStorage y no en sessionStorage como el token: recargar la
// pagina, cerrar la pestana sin querer o que se apague la tablet no tienen por
// que costar un partido a medio cargar. Ojo que es por navegador, no por
// pestana: dos pestanas del mismo navegador comparten el partido. Dos personas
// es dos dispositivos (o dos navegadores), que es como se usa.
const PARTIDO_GUARDADO = "voley.partido";
let lineas = [];

// El almacenamiento puede estar bloqueado (modo privado) o lleno: si falla se
// sigue cargando igual, solo que el partido vive en memoria y se pierde al
// recargar. Lo que no puede pasar es que se caiga la pagina.
function recordarLineas(){
  try{ localStorage.setItem(PARTIDO_GUARDADO, JSON.stringify(lineas)); }
  catch(_){ /* sin almacenamiento el partido vive solo en memoria */ }
}

// null es "este navegador nunca cargo nada aca", que no es lo mismo que "no
// hay nada cargado": con null se mira si el servidor tenia un partido a medio
// cargar del modelo viejo (ver arrancarPartido).
function lineasGuardadas(){
  try{
    const crudo = localStorage.getItem(PARTIDO_GUARDADO);
    if(crudo === null) return null;
    const lista = JSON.parse(crudo);
    return Array.isArray(lista) ? lista.map(String) : [];
  }catch(_){ return []; }
}

// Las lineas que valen son las que devuelve el motor, no las que se mandaron:
// una linea que rechaza no entra, y pegar un .txt entero puede cortarse en la
// primera que no entiende.
function anotarLineas(estado){
  if(!estado || !Array.isArray(estado.lineas)) return;
  lineas = estado.lineas.map(String);
  recordarLineas();
}

// Todo lo que toca el partido en curso va por aca: manda la copia de esta
// pantalla y se queda con la que contesta el motor.
async function apiPartido(ruta, datos){
  const r = await api(ruta, Object.assign({lineas}, datos || {}));
  if(r && r.estado) anotarLineas(r.estado);
  return r;
}

// ======================================================================
// 2b) El candado de la carga
// ======================================================================
// Cargar es lo unico que escribe sobre el partido, asi que es lo unico que
// pide la contraseña. Aca nunca se guarda la contraseña ni se la compara: se
// la manda al servidor, que responde con un token. El token va en
// sessionStorage para que recargar la pagina en medio de un partido no
// obligue a escribirla de nuevo, y se pierda al cerrar la pestana.
const GUARDADO = "voley.token";
const formCandado = $("#candado"), campoClave = $("#clave"), avisoClave = $("#mensajeClave");

// El almacenamiento puede estar bloqueado (navegador en modo privado): si
// falla se sigue trabajando igual, solo que la clave se vuelve a pedir en
// cada recarga. Lo que no puede pasar es que se caiga la pagina entera.
function recordar(valor){
  try{
    if(valor) sessionStorage.setItem(GUARDADO, valor);
    else sessionStorage.removeItem(GUARDADO);
  }catch(_){ /* sin almacenamiento el token vive solo en memoria */ }
}
function recordado(){
  try{ return sessionStorage.getItem(GUARDADO) || ""; }catch(_){ return ""; }
}

token = recordado();
// la vista arranca bloqueada en el HTML: si ya hay token se abre ahora mismo,
// sin esperar a revisarCandado(), para no parpadear entre las dos pantallas
pintarCandado();

function pintarCandado(){
  $("#vista-cargar").classList.toggle("bloqueada", !token);
}

function guardarToken(nuevo){
  token = nuevo;
  recordar(nuevo);
  pintarCandado();
}

function olvidarToken(){
  token = "";
  recordar("");
  pintarCandado();
}

function avisoDeClave(texto, ok){
  avisoClave.textContent = texto || "";
  avisoClave.hidden = !texto;
  avisoClave.className = "mensaje" + (texto ? (ok ? " ok" : " error") : "");
}

// La funcion que pide la contraseña: la valida contra el servidor y, si
// acierta, levanta el candado y deja el foco en el campo de la jugada.
async function pedirContraseña(clave){
  if(!clave) return avisoDeClave("Escribi la contraseña.", false);
  avisoDeClave("Comprobando…", true);
  const r = await api("/api/clave", {clave});
  campoClave.value = "";
  if(!r.ok || !r.token) return avisoDeClave(r.mensaje || "Contraseña incorrecta.", false);
  guardarToken(r.token);
  avisoDeClave("", true);
  // el partido es de esta pantalla y el candado no lo toca, pero la pantalla
  // se repinta igual: bloquear y desbloquear no puede dejarla desactualizada
  const estado = await apiPartido("/api/estado");
  if(estado.estado) pintar(estado.estado);
  mostrarMensaje(r.mensaje, true);
  foco();
}

// Al arrancar, el token guardado se revalida: si el servidor se reinicio ya
// no vale y hay que volver a escribir la contraseña.
async function revisarCandado(){
  if(token){
    const r = await api("/api/sesion");
    if(!r.autorizado) olvidarToken();
  }
  pintarCandado();
}

formCandado.addEventListener("submit", ev => {
  ev.preventDefault();
  pedirContraseña(campoClave.value.trim());
});

function mostrarMensaje(texto, ok){
  mensaje.textContent = texto || "";
  mensaje.className = "mensaje" + (texto ? (ok ? " ok" : " error") : "");
}

function mostrarEnlaces(respuesta){
  const caja = $("#enlacesArchivo");
  if(!respuesta || !respuesta.ok || !respuesta.archivo){
    caja.hidden = true;
    caja.innerHTML = "";
    return;
  }
  // Despues de generar el informe interesa abrirlo, no leer la ruta: se deja
  // el enlace directo al archivo y, si el navegador esta en esta PC, el
  // boton que lo abre en Excel.
  const archivo = respuesta.archivo, tipo = respuesta.tipo || "txt";
  const partes = [
    `<a class="enlace" href="${esc(urlDescarga(archivo, tipo))}"
        target="_blank" rel="noopener">Descargar ${esc(archivo)}</a>`
  ];
  if(respuesta.volcado){
    partes.push(`<a class="enlace" href="${esc(urlDescarga(respuesta.volcado, "txt"))}"
                    target="_blank" rel="noopener">Descargar el .txt</a>`);
  }
  if(esLocal){
    partes.push(`<button data-abrir="${esc(archivo)}" data-tipo="${esc(tipo)}">Abrir en esta PC</button>`);
  }
  caja.innerHTML = partes.join("");
  caja.hidden = false;
}

function pintar(e){
  $("#nomA").textContent = e.nombres.A;
  $("#nomB").textContent = e.nombres.B;
  $("#ptsA").textContent = e.marcador.A;
  $("#ptsB").textContent = e.marcador.B;
  $("#numSet").textContent = "Set " + e.set;
  $("#sets").textContent = `Sets ${e.sets_ganados.A} - ${e.sets_ganados.B}`;
  $("#cargados").textContent = e.puntos_cargados + " puntos";

  $("#eqA").classList.toggle("saca", e.etapa === "jugadas" && e.equipo_saca === "A");
  $("#eqB").classList.toggle("saca", e.etapa === "jugadas" && e.equipo_saca === "B");

  // El turno es lo que se mira entre rally y rally: sacador bien destacado.
  // En medio de un punto el sacador ya no viene al caso (el prompt dice quien
  // juega), asi que solo se agrega cuando el motor esta esperando un saque.
  const tocaSacar = e.pendiente && e.pendiente.espera === "saque";
  $("#turno").innerHTML = (tocaSacar && e.jugador_saca != null)
    ? `${esc(e.prompt.replace(/, jugador \d+$/, ""))} · <span class="sacador">saca el ${esc(e.jugador_saca)}</span>`
    : esc(e.prompt);

  // La etapa la dice el motor, asi que puede traer una que esta lista no
  // conozca: sin el "|| """ el campo queda con un "undefined" escrito.
  campo.placeholder = ({
    nombres:"Escribi el nombre y Enter (vacio = A/B)",
    rotacion:"28_S 5 13 88 3 40   (vacio = sin rotacion)",
    mantener_rotacion:"s  o  n",
    equipo_del_cambio:"A  o  B",
    saque_inicial:"A  o  B",
    jugadas:"1_5_X/3_3/2_4/4_1_P"
  })[e.etapa] || "";
  $("#atajos").style.opacity = e.etapa === "jugadas" ? "1" : ".45";

  // La "x" hace cuatro cosas distintas segun donde se este, y desde afuera se
  // ven iguales. Reabrir un set es la unica forma de arreglar una rotacion mal
  // cargada al empezarlo, asi que tiene que decirlo.
  const btnX = $("[data-enviar='x']");
  if(btnX) btnX.textContent = ({
    jugada: "x · deshacer jugada",
    cambio: "x · sacar el cambio",
    tiempo: "x · sacar el tiempo",
    punto:  "x · deshacer punto",
    set:    `x · reabrir el set ${e.historial_sets.length}`,
    nada:   "x · deshacer"
  })[e.deshacer] || "x · deshacer";

  // el contador de la pestana: hay algo cargado que todavia no se guardo
  const chip = $("#chipCargar");
  chip.hidden = !e.lineas.length;
  chip.textContent = e.puntos_cargados || e.lineas.length;

  $("#btnExcelA").textContent = e.nombres.A;
  $("#btnExcelB").textContent = e.nombres.B;

  // ultimos puntos, el mas nuevo arriba
  $("#log").innerHTML = e.ultimos_puntos.length
    ? e.ultimos_puntos.slice().reverse().map(p =>
        `<div class="jugada"><span class="quien">${esc(p.gana)}</span>
         <span style="color:var(--suave)"> · set ${esc(p.set)} · saco ${esc(p.saca)}</span>
         <span class="det">${esc(p.detalle || "—")}</span></div>`).join("")
    : `<p class="nota" style="margin:0">Todavia no hay puntos.</p>`;

  // Formacion actual: cada vez que el equipo recupera el saque gira una
  // posicion (el de la 2 pasa a la 1, y el de la 1 se va a la 6).
  const rot = e.rotaciones;
  $("#rotacion").innerHTML = Object.keys(rot).length
    ? `<div class="tabla"><table><tr><th>Equipo</th><th>Z1 · saca</th><th>Z2</th><th>Z3</th>
       <th>Z4</th><th>Z5</th><th>Z6</th><th>Giros</th></tr>` +
      Object.entries(rot).map(([letra, r]) => {
        const sacando = e.etapa === "jugadas" && e.equipo_saca === letra;
        return `<tr><td>${esc(e.nombres[letra])}</td>` + r.jugadores.map((j, i) =>
          `<td class="zona ${j === r.armador ? "armador" : ""} ${i === 0 && sacando ? "saque" : ""}">
             ${esc(j)}${j === r.armador ? " S" : ""}</td>`).join("") +
          `<td style="color:var(--suave)">${esc(r.giros)}</td></tr>`;
      }).join("") + `</table></div>
      <p class="nota">Formacion actual, no la inicial. En amarillo el armador;
      resaltada la zona 1, que es la que saca.</p>` + liberosHTML(e)
    : `<p class="nota" style="margin:0">Sin rotacion cargada: el numero del sacador es obligatorio.</p>`;

  pintarVisual(e);

  // los botones de tiempo llevan el nombre de cada equipo
  ["A", "B"].forEach(letra => {
    const boton = $("#btnTiempo" + letra);
    if(boton) boton.textContent = "T · tiempo " + (e.nombres[letra] || letra);
  });

  // tiempos y cambios en el orden en que pasaron, con el marcador del momento
  const marcadorDe = i => i.marcador ? `${i.marcador.A}-${i.marcador.B}` : "—";
  const intervenciones = [
    ...(e.tiempos || []).map(t => ({...t, orden: 0})),
    ...e.cambios.map(c => ({...c, orden: 1})),
  ].sort((a, b) => (a.set - b.set) || ((a.puntos ?? 0) - (b.puntos ?? 0)) || (a.orden - b.orden));
  $("#cambios").innerHTML = intervenciones.length
    ? `<div class="tabla"><table><tr><th>Set</th><th>Marcador<br>${esc(e.nombres.A)}-${esc(e.nombres.B)}</th>
         <th>Equipo</th><th>Que</th></tr>` +
      intervenciones.map(i => `<tr><td>${esc(i.set)}</td><td>${esc(marcadorDe(i))}</td>
        <td>${esc(e.nombres[i.equipo])}</td>
        <td>${i.orden === 0 ? "Tiempo" :
          `Sale <span class="zona">#${esc(i.sale)}</span> / entra
           <span class="zona ${i.armador ? "armador" : ""}">#${esc(i.entra)}${i.armador ? " S" : ""}</span>
           (zona ${esc(i.zona)})`}</td></tr>`).join("") + `</table></div>`
    : `<p class="nota" style="margin:0">Sin tiempos ni cambios.</p>`;
}

async function enviar(linea){
  if(!linea && linea !== "") return;
  const r = await apiPartido("/api/enviar", {linea});
  if(r.estado) pintar(r.estado);
  mostrarMensaje(r.mensaje, r.ok);
  if(r.ok) campo.value = "";
  foco();
}

$("#form").addEventListener("submit", ev => { ev.preventDefault(); enviar(campo.value.trim()); });

$$("[data-enviar]").forEach(b =>
  b.addEventListener("click", () => enviar(b.dataset.enviar)));

$("#btnCambio").addEventListener("click", () => {
  // tocando, el cambio tiene su propia pantalla; escribiendo, se deja el
  // prefijo puesto como hasta ahora
  if(modo === "tocando" && estadoActual && estadoActual.etapa === "jugadas"){
    cambioVisual = {sale: null, entra: null, armador: false};
    tecleando = null;
    mostrarMensaje("Los cambios entran entre puntos.", true);
    return pintarVisual(estadoActual);
  }
  campo.value = "C_";
  foco();
  mostrarMensaje("C_entra_sale  (agrega _S sobre el que entra si es cambio de armador)", true);
});

async function accion(ruta, datos){
  const r = await apiPartido(ruta, datos || {});
  if(r.estado) pintar(r.estado);
  mostrarMensaje(r.mensaje, r.ok);
  mostrarEnlaces(r);
  // si la accion escribio un archivo, la lista de Partidos quedo vieja
  if(r.ok && r.archivo) listaPartidosVencida = true;
  foco();
  return r;
}
$("#btnBorrar").addEventListener("click", () => accion("/api/deshacer"));
$("#btnGuardar").addEventListener("click", () => accion("/api/guardar"));

// Excel: elegir A o B con dos botones en vez de escribir el nombre a mano.
$("#btnExcel").addEventListener("click", () => {
  $("#eleccionExcel").hidden = false;
  mostrarMensaje("De que equipo es el informe?", true);
});
$("#btnExcelCancelar").addEventListener("click", () => {
  $("#eleccionExcel").hidden = true;
  mostrarMensaje("", true);
  foco();
});
["A", "B"].forEach(letra => $("#btnExcel" + letra).addEventListener("click", async ev => {
  $("#eleccionExcel").hidden = true;
  mostrarMensaje("Generando el informe…", true);
  await accion("/api/excel", {equipo: ev.currentTarget.textContent});
}));

// Bloquear a mano: para dejar la tablet al costado de la cancha sin que
// cualquiera meta una jugada.
$("#btnBloquear").addEventListener("click", () => {
  olvidarToken();
  avisoDeClave("", true);
  mostrarMensaje("", true);
  foco();
});

$("#btnReiniciar").addEventListener("click", () => {
  if(!confirm("Se pierde todo lo cargado. Seguro?")) return;
  campo.value = "";        // reiniciar tambien borra lo que quedo a medio tipear
  otroPartido();           // lo que se guarde ahora es otro partido, no este
  accion("/api/reiniciar");
});
$("#btnPegar").addEventListener("click", () => {
  otroPartido();
  accion("/api/cargar", {texto: $("#pegar").value});
});
$("#btnStats").addEventListener("click", async () => {
  const r = await apiPartido("/api/estadisticas");
  $("#stats").textContent = r.texto || "—";
});

// ======================================================================
// 3b) Guardar un partido en privado
// ======================================================================
// Guardar el .txt PUBLICA el partido: queda en Partidos y entra en las
// estadisticas de todos. Un partido a medio cargar no se puede publicar
// (faltan sets, los promedios quedarian mal) pero tampoco se puede dejar
// donde esta: mientras se carga vive solo en el localStorage de ESTE
// navegador. Apagar la PC no lo pierde; formatearla, limpiar el navegador o
// que se caiga la tablet, si.
//
// Esto lo sube al mismo lugar que todo lo demas pero aparte de Datos, asi que
// no lo ve nadie y se vuelve a abrir desde aca.
//
// El id: identifica al PARTIDO, no al guardado. Guardar dos veces el mismo
// partido pisa su propia copia en vez de dejar dos, y guardar uno distinto no
// puede pisar al anterior -- que es lo que pasaria con el nombre, porque dos
// partidos contra el mismo rival el mismo dia se llaman igual.
const ID_PARTIDO = "voley.partido.id";
let idPartido = "";

function recordarId(nuevo){
  idPartido = nuevo;
  try{ localStorage.setItem(ID_PARTIDO, nuevo); }catch(_){ /* vive en memoria */ }
  return nuevo;
}

function idDelPartido(){
  if(idPartido) return idPartido;
  try{ idPartido = localStorage.getItem(ID_PARTIDO) || ""; }catch(_){ /* sin storage */ }
  return idPartido || recordarId(Date.now().toString(36) + "-" +
                                 Math.random().toString(36).slice(2, 8));
}

// Lo que se empieza a cargar ahora es otro partido: reiniciar, pegar un .txt o
// abrir uno de Partidos. Sin esto, el guardado siguiente pisaria el privado
// del partido anterior, que es justo lo que no puede pasar.
function otroPartido(){
  recordarId(Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8));
}

let privados = [];

function cuandoSeGuardo(segundos){
  if(!segundos) return "";
  const fecha = new Date(segundos * 1000);
  const hoy = new Date();
  const mismodia = fecha.toDateString() === hoy.toDateString();
  const hora = fecha.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
  return mismodia ? `hoy ${hora}` : `${fecha.toLocaleDateString()} ${hora}`;
}

function pintarPrivados(lista){
  privados = Array.isArray(lista) ? lista : [];
  const chip = $("#chipPrivados");
  chip.hidden = !privados.length;
  chip.textContent = privados.length;

  const caja = $("#listaPrivados");
  if(!privados.length){
    caja.innerHTML = `<p class="nota">No hay ninguno guardado en privado.</p>`;
    return;
  }
  caja.innerHTML = privados.map(g => {
    const r = g.resumen || {};
    // el marcador y el set dicen mas que la cantidad de lineas: es como se
    // reconoce cual de dos partidos empezados es el que se estaba cargando
    const donde = [r.sets ? `sets ${r.sets}` : "", r.set ? `set ${r.set}` : "",
                   r.marcador ? r.marcador : "", `${g.lineas} lineas`]
      .filter(Boolean).join(" · ");
    return `<div class="privado" data-id="${esc(g.id)}">
      <div class="que">
        <div class="nombre">${esc(g.nombre)}</div>
        <div class="cuando">${esc(donde)}${g.guardado ? " — " + esc(cuandoSeGuardo(g.guardado)) : ""}</div>
      </div>
      <button data-seguir="${esc(g.id)}">Seguir cargando</button>
      <button class="peligro" data-olvidar="${esc(g.id)}">Borrar</button>
    </div>`;
  }).join("");
}

async function pedirPrivados(){
  // POST aunque solo lea: la contraseña se exige por POST (ver
  // RUTAS_CON_CLAVE), y que la lista pida la clave es lo unico que la hace
  // privada -- por GET se podria saber que partidos hay sin saberla
  const r = await api("/api/privados", {});
  if(r.ok) pintarPrivados(r.privados);
  else $("#listaPrivados").innerHTML = `<p class="nota">${esc(r.mensaje || "No se pudo leer la lista.")}</p>`;
  return r;
}

async function guardarEnPrivado(){
  const boton = $("#btnGuardarPrivado");
  boton.disabled = true;
  const r = await accion("/api/privado/guardar", {id: idDelPartido()});
  boton.disabled = false;
  if(r && r.privados) pintarPrivados(r.privados);
  $("#panelPrivados").open = true;
  return r;
}

// Abrir uno guardado deja esta pantalla cargandolo, y ademas adopta su id:
// desde ahora "guardar en privado" actualiza ESE guardado y no crea otro.
async function seguirPrivado(id){
  const chip = $("#chipCargar");
  if(!chip.hidden && idPartido !== id &&
     !confirm("Hay un partido cargado en esta pantalla. Se reemplaza por el guardado?")) return;
  const r = await accion("/api/privado/abrir", {id});
  if(r.ok) recordarId(id);
}

async function olvidarPrivado(id){
  const guardado = privados.find(g => g.id === id);
  if(!confirm(`Se borra "${guardado ? guardado.nombre : id}" de los guardados en privado.\n\n` +
              `No se puede deshacer. Seguro?`)) return;
  const r = await api("/api/privado/borrar", {id});
  if(r.privados) pintarPrivados(r.privados);
  mostrarMensaje(r.mensaje, r.ok);
}

$("#btnPrivado").addEventListener("click", guardarEnPrivado);
$("#btnGuardarPrivado").addEventListener("click", guardarEnPrivado);
$("#btnRefrescarPrivados").addEventListener("click", pedirPrivados);

// La lista se pide al abrir el panel y no al cargar la pagina: es una lectura
// del almacenamiento y la mayoria de las veces esta pantalla se abre para
// cargar jugadas, no para buscar un partido viejo.
$("#panelPrivados").addEventListener("toggle", ev => {
  if(ev.currentTarget.open) pedirPrivados();
});

$("#listaPrivados").addEventListener("click", ev => {
  const seguir = ev.target.closest("[data-seguir]");
  if(seguir) return seguirPrivado(seguir.dataset.seguir);
  const olvidar = ev.target.closest("[data-olvidar]");
  if(olvidar) return olvidarPrivado(olvidar.dataset.olvidar);
});

// La ayuda de sintaxis se abre y se cierra sin perder lo que se estaba
// escribiendo: se guarda el texto y la posicion del cursor, y el foco vuelve
// al campo como estaba.
$("#panelAyuda").addEventListener("toggle", () => {
  const texto = campo.value, desde = campo.selectionStart, hasta = campo.selectionEnd;
  campo.value = texto;
  foco();
  try{ campo.setSelectionRange(desde, hasta); }catch(_){ /* el campo no tenia foco */ }
});

// Los botones "abrir en esta PC" aparecen en varios lados (informe recien
// generado, detalle de un partido): se atienden todos desde el documento.
document.addEventListener("click", async ev => {
  const boton = ev.target.closest("[data-abrir]");
  if(!boton) return;
  boton.disabled = true;
  const r = await api("/api/abrir", {archivo: boton.dataset.abrir, tipo: boton.dataset.tipo});
  boton.disabled = false;
  if(vistaActual === "cargar") mostrarMensaje(r.mensaje, r.ok);
  else avisoDetalle(r.mensaje, r.ok);
});

// ======================================================================
// 2c) LA CANCHA: cargar tocando
// ======================================================================
// Arma exactamente la misma linea que se escribiria a mano y la manda por el
// mismo POST /api/enviar. No valida nada ni decide quien gano el punto: lo
// unico que sabe es que se puede tocar en cada paso, y eso se lo dice la
// tabla de /api/notacion (ver notacion.py). De quien es la pelota se lo dice
// el motor en estado.pendiente.
//
// Los dos equipos van siempre en el mismo lugar, A arriba y B abajo. Dar
// vuelta la cancha segun quien tiene la pelota se lee mal justo cuando no hay
// tiempo de leerla; encender la mitad que juega se lee de un vistazo.

// Las zonas de cada mitad, en el orden en que se dibujan (3 columnas). La de
// abajo se ve desde atras (4-3-2 contra la red); la de arriba es la misma
// cancha girada media vuelta.
const ZONAS_MITAD = {
  A: [1, 6, 5, 9, 8, 7, 2, 3, 4],
  B: [4, 3, 2, 7, 8, 9, 5, 6, 1]
};

const MODO_GUARDADO = "voley.modo";
let modo = "tocando";
try{ modo = localStorage.getItem(MODO_GUARDADO) || "tocando"; }catch(_){ /* sin storage */ }

let notacionLista = false;
let armador = null;          // la jugada que se esta armando
let claveVisual = "";        // con que estado del motor se armaron los borradores
let tecleando = null;        // {destino, digitos, ranura} mientras se usa el teclado
let cambioVisual = null;     // {sale, entra, armador} mientras se arma un cambio
let rotacionBorrador = null; // la rotacion que se esta cargando
let estadoActual = null;

async function traerNotacion(){
  if(notacionLista) return;
  const r = await api("/api/notacion");
  if(r && r.ok){ cargarNotacion(r); notacionLista = true; }
}

function guardarModo(nuevo){
  modo = nuevo;
  try{ localStorage.setItem(MODO_GUARDADO, nuevo); }catch(_){ /* sin storage */ }
  if(estadoActual) pintarVisual(estadoActual);
  foco();
}

$$(".modos button").forEach(b =>
  b.addEventListener("click", () => guardarModo(b.dataset.modo)));

// ----------------------------------------------------------------------
// Los que se pueden tocar son los que estan REALMENTE en la cancha, no la
// rotacion nominal: con un libero declarado, el cubierto que esta atras no
// esta jugando y el libero si.
function plantelesDe(e){
  const salida = {};
  ["A", "B"].forEach(l => {
    salida[l] = (e.rotaciones[l] && e.rotaciones[l].formacion) || [];
  });
  return salida;
}

// En que estado esta el motor. Todo lo que se arma a mano (la jugada, el
// dorsal a medio teclear, la rotacion, el cambio) vale solo mientras esto no
// se mueva.
function claveDelMotor(e){
  const pendiente = e.pendiente || {}, esperando = e.esperando || {};
  return [e.lineas.length, e.etapa, esperando.que, esperando.equipo, esperando.set,
          pendiente.espera, pendiente.equipo_con_la_pelota,
          e.equipo_saca, e.jugador_saca].join("|");
}

// Tirar TODOS los borradores cuando el motor se movio, no solo el armador.
// Antes cada uno se invalidaba por su cuenta y los que no miraban el conteo
// de lineas sobrevivian a un Reiniciar: la rotacion a medio cargar volvia a
// aparecer en el partido nuevo, y un cambio abierto dejaba la pantalla
// trabada sin forma de salir. Vale igual para deshacer y para pegar un
// partido entero.
function sincronizarConElMotor(e){
  const clave = claveDelMotor(e);
  if(clave === claveVisual) return;
  claveVisual = clave;
  armador = null;
  tecleando = null;
  cambioVisual = null;
  rotacionBorrador = null;
}

function asegurarArmador(e){
  if(armador) return;
  const p = e.pendiente;
  armador = new Armador({
    espera: p.espera,
    equipoSaca: e.equipo_saca,
    equipoConLaPelota: p.equipo_con_la_pelota,
    planteles: plantelesDe(e),
    sacadorConocido: e.jugador_saca != null
  });
}

function vivosPorEquipo(){
  const mapa = {A: {jugadores: new Set(), zonas: new Set()},
                B: {jugadores: new Set(), zonas: new Set()}};
  armador.opciones().forEach(o => {
    if(o.tipo === "jugador") mapa[armador.equipoDe(o.lado)].jugadores.add(o.valor);
    else if(o.tipo === "zona") mapa[armador.equipoDe(o.lado)].zonas.add(o.valor);
  });
  return mapa;
}

// ----------------------------------------------------------------------
// Los liberos no salen en la tabla de rotacion porque no ocupan una zona: no
// rotan, entran por el que cubren cuando ese esta atras.
function liberosHTML(e){
  const filas = ["A", "B"].flatMap(letra =>
    ((e.rotaciones[letra] && e.rotaciones[letra].liberos) || []).map(l =>
      `<li><b>${esc(l.jugador)}</b> de ${esc(e.nombres[letra])}, juega por el
       ${l.cubre.map(esc).join(" y el ")}</li>`));
  if(!filas.length) return "";
  return `<p class="nota" style="margin-bottom:4px">Liberos</p>
          <ul class="nota" style="margin:0;padding-left:18px">${filas.join("")}</ul>`;
}

function canchaHTML(e, vivos, opciones){
  return mitadHTML(e, "A", vivos, opciones) +
         `<div class="red"></div>` +
         mitadHTML(e, "B", vivos, opciones);
}

function mitadHTML(e, letra, vivos, opciones){
  opciones = opciones || {};
  const rotacion = e.rotaciones[letra];
  // en el cambio se toca sobre la rotacion nominal, porque tambien se puede
  // sacar a un jugador que ahora mismo esta cubierto por el libero
  const jugadores = (rotacion && (opciones.nominal ? rotacion.jugadores
                                                  : rotacion.formacion)) || [];
  const elArmador = rotacion ? rotacion.armador : null;
  const liberos = new Set(((rotacion && rotacion.liberos) || []).map(l => l.jugador));
  const vivo = vivos[letra] || {jugadores: new Set(), zonas: new Set()};
  // "equipoActivo" es de quien es el paso segun el armador. Hace falta
  // ademas de los circulos vivos porque un equipo sin rotacion no tiene
  // ninguno, y si no su mitad quedaria apagada justo cuando le toca.
  const encendida = letra === opciones.equipoActivo ||
                    vivo.jugadores.size > 0 || vivo.zonas.size > 0;

  const celdas = ZONAS_MITAD[letra].map(zona => {
    const dorsal = (zona <= 6 && jugadores.length) ? jugadores[zona - 1] : null;
    const zonaViva = vivo.zonas.has(zona);
    const jugadorVivo = dorsal != null && vivo.jugadores.has(dorsal);
    const marca = opciones.accion
      ? `data-accion="${esc(opciones.accion)}" data-valor="${esc(dorsal)}"`
      : `data-opcion="j${esc(dorsal)}"`;
    const circulo = dorsal == null ? "" : `
      <button class="jugador ${jugadorVivo ? "viva" : ""}
        ${dorsal === elArmador ? "armador" : ""}
        ${liberos.has(dorsal) ? "libero" : ""}
        ${(zona === 1 && e.equipo_saca === letra && e.jugador_saca === dorsal) ? "saca" : ""}"
        ${jugadorVivo ? marca : "disabled"}>${esc(dorsal)}</button>`;
    return `<div class="celda ${zonaViva ? "zonaViva" : ""}"
                 ${zonaViva ? `data-opcion="z${zona}"` : ""}>
              <span class="numeroZona">${zona}</span>${circulo}</div>`;
  }).join("");

  return `<div class="etiquetaMitad ${encendida ? "encendida" : ""}">
            <span>${esc(e.nombres[letra])}</span>
            ${jugadores.length ? "" : `<span class="sinRotacion">sin rotacion</span>`}
          </div>
          <div class="mitad ${encendida ? "" : "dormida"}">${celdas}</div>`;
}

function tecladoHTML(conVolver){
  const escrito = tecleando.digitos;
  const teclas = [1, 2, 3, 4, 5, 6, 7, 8, 9]
    .map(n => `<button data-tecla="${n}">${n}</button>`).join("");
  return `<div class="teclado">
    <div class="tecleado">${escrito ? esc(escrito) : `<span class="vacio">dorsal…</span>`}</div>
    ${teclas}
    <button data-tecla="borrar" class="tenue">←</button>
    <button data-tecla="0">0</button>
    <button data-tecla="ok" class="primario" ${escrito ? "" : "disabled"}>OK</button>
    ${conVolver ? `<button data-tecla="volver" class="tenue todo">Volver a la cancha</button>` : ""}
  </div>`;
}

function lineaHTML(){
  const linea = armador.linea;
  const sangria = " ".repeat(Math.max(0, linea.length - 1));
  return esc(linea) + (armador.paso ? `\n<span class="falta">${sangria}^</span>` : "");
}

// ----------------------------------------------------------------------
function pintarVisual(e){
  estadoActual = e;
  sincronizarConElMotor(e);
  const visible = (modo === "tocando");
  $("#visual").hidden = !visible;
  $$(".modos button").forEach(b => b.classList.toggle("activa", b.dataset.modo === modo));
  if(!visible) return;
  if(!notacionLista){
    $("#quePide").textContent = "Bajando la notacion…";
    return;
  }
  if(cambioVisual) return pintarCambio(e);
  if(e.etapa !== "jugadas") return pintarPreparacion(e);
  pintarJugada(e);
}

function pintarJugada(e){
  asegurarArmador(e);
  const paso = armador.paso;
  // un equipo sin rotacion no tiene 6 circulos que tocar: se va derecho al
  // teclado, sin obligar a pasar por un boton "otro" que seria el unico
  const sinCirculos = paso && paso.pide === "jugador" &&
                      armador.plantelDe(paso.lado).length === 0;
  if(sinCirculos && !tecleando) tecleando = {destino: "jugada", digitos: ""};

  $("#secuencia").hidden = !e.pendiente.secuencia;
  $("#secuencia").textContent = e.pendiente.secuencia;

  // de quien es el paso: se usa para encender su mitad y para decirlo en el
  // titulo, que es lo unico que queda cuando ese equipo no tiene circulos
  const equipoActivo = armador.equipoDe(
    (paso && (paso.pide === "jugador" || paso.pide === "zona")) ? paso.lado : "pelota");

  $("#cancha").hidden = false;
  $("#cancha").innerHTML = canchaHTML(e, vivosPorEquipo(), {equipoActivo});

  $("#quePide").textContent = paso
    ? `${paso.titulo}${paso.pide === "jugador" ? ` · ${e.nombres[equipoActivo]}` : ""}`
    : "";
  $("#opciones").innerHTML = (tecleando && tecleando.destino === "jugada")
    ? tecladoHTML(!sinCirculos)
    : armador.opciones()
        .filter(o => o.tipo === "boton" || o.tipo === "numero")
        .map(o => `<button data-opcion="${esc(o.id)}"
                    class="${o.tipo === "numero" ? "secundaria" : esc(o.tono || "")}"
                    >${esc(o.etiqueta)}</button>`).join("");

  $("#enCurso").hidden = armador.pasos.length === 0;
  $("#lineaArmada").innerHTML = lineaHTML();
  $("#falta").textContent = paso ? `falta ${paso.titulo.toLowerCase()}` : "";
}

function tocarOpcion(id){
  if(!armador) return;
  const opcion = armador.opciones().find(o => o.id === id);
  if(!opcion) return;
  if(opcion.tipo === "numero"){
    tecleando = {destino: "jugada", digitos: ""};
    return pintarVisual(estadoActual);
  }
  armador.tocar(id);
  if(armador.cerrada) return mandarJugada();
  pintarVisual(estadoActual);
}

async function mandarJugada(){
  const linea = armador.linea;
  // el estado nuevo llega en la respuesta y rehace el armador solo; si el
  // motor la rechaza tambien, arrancando de cero con su mensaje a la vista
  armador = null;
  await enviar(linea);
}

function usarTecla(tecla){
  if(!tecleando) return;
  if(tecla === "volver"){ tecleando = null; return pintarVisual(estadoActual); }
  if(tecla === "borrar"){
    tecleando.digitos = tecleando.digitos.slice(0, -1);
    return pintarVisual(estadoActual);
  }
  if(tecla === "ok"){
    if(!tecleando.digitos) return;
    const numero = parseInt(tecleando.digitos, 10);
    const destino = tecleando.destino, ranura = tecleando.ranura;
    tecleando = null;
    if(destino === "jugada"){
      armador.tocar("otro", numero);
      if(armador.cerrada) return mandarJugada();
    } else if(destino === "rotacion"){
      rotacionBorrador.jugadores[ranura] = numero;
    } else if(destino === "libero"){
      rotacionBorrador.libero = {jugador: numero, cubre: []};
    } else if(destino === "cambio"){
      cambioVisual.entra = numero;
    }
    return pintarVisual(estadoActual);
  }
  if(tecleando.digitos.length < 3) tecleando.digitos += tecla;
  pintarVisual(estadoActual);
}

// ----------------------------------------------------------------------
// Preparacion: hoy son cinco lineas escritas a ciegas.
function pintarPreparacion(e){
  $("#secuencia").hidden = true;
  $("#enCurso").hidden = true;
  const espera = e.esperando || {};
  if(espera.que === "rotacion") return pintarRotacion(e, espera);

  $("#cancha").hidden = true;
  $("#quePide").textContent = e.prompt;

  if(espera.que === "nombre_equipo"){
    $("#opciones").innerHTML = `<div class="preparacion" style="width:100%">
      <input id="campoPrep" autocomplete="off" autocapitalize="words"
             placeholder="Nombre del equipo ${esc(espera.equipo)} (vacio = ${esc(espera.equipo)})">
      <button class="primario grande" data-accion="nombre">Siguiente</button></div>`;
    return;
  }
  if(espera.que === "saque_inicial"){
    $("#opciones").innerHTML = ["A", "B"].map(letra =>
      `<button class="grande" data-accion="saca" data-valor="${letra}">
         Saca ${esc(e.nombres[letra])}</button>`).join("");
    return;
  }
  if(espera.que === "mantener_rotacion"){
    $("#opciones").innerHTML =
      `<button class="grande" data-accion="mantener" data-valor="s">Si, la misma</button>
       <button class="grande" data-accion="mantener" data-valor="n">No, cargar otra</button>`;
    return;
  }
  // el dorsal del que sale existe en los dos equipos: el motor no puede
  // adivinar de cual es y lo pregunta en medio de la carga
  if(espera.que === "equipo_del_cambio"){
    $("#opciones").innerHTML = ["A", "B"].map(letra =>
      `<button class="grande" data-accion="saca" data-valor="${letra}">
         Sale de ${esc(e.nombres[letra])}</button>`).join("");
    return;
  }
  $("#opciones").innerHTML = "";
}

function pintarRotacion(e, espera){
  if(!rotacionBorrador || rotacionBorrador.equipo !== espera.equipo){
    rotacionBorrador = {equipo: espera.equipo, armador: null, liberos: [],
                        libero: null,
                        jugadores: [null, null, null, null, null, null]};
  }
  const puestos = rotacionBorrador.jugadores;
  const declarando = rotacionBorrador.libero;
  const celdas = ZONAS_MITAD.B.map(zona => {
    const dorsal = zona <= 6 ? puestos[zona - 1] : null;
    // mientras se declara un libero, tocar una zona dice a quien cubre en vez
    // de cargar el dorsal de esa zona
    const cubierto = declarando && dorsal != null && declarando.cubre.includes(dorsal);
    const slot = zona > 6 ? "" : `
      <button class="jugador ${dorsal == null ? "" : "viva"}
              ${rotacionBorrador.armador === zona ? "armador" : ""}
              ${cubierto ? "libero" : ""}"
              data-accion="ranura" data-valor="${zona}">${dorsal == null ? "+" : esc(dorsal)}</button>`;
    return `<div class="celda"><span class="numeroZona">${zona}</span>${slot}</div>`;
  }).join("");

  $("#cancha").hidden = false;
  $("#cancha").innerHTML =
    `<div class="etiquetaMitad encendida"><span>${esc(e.nombres[espera.equipo])}</span>
       <span class="sinRotacion">la zona 1 es la que saca</span></div>
     <div class="mitad">${celdas}</div>`;

  $("#quePide").textContent =
    `Rotacion de ${e.nombres[espera.equipo]}: tocá cada zona y poné el dorsal`;

  if(tecleando && (tecleando.destino === "rotacion" || tecleando.destino === "libero")){
    $("#opciones").innerHTML = tecladoHTML(true);
    return;
  }
  if(declarando){
    $("#quePide").textContent =
      `Libero ${declarando.jugador}: tocá a quién cubre (uno o dos)`;
    $("#opciones").innerHTML = `<div class="preparacion" style="width:100%">
      <div class="fila">
        <button class="primario grande" data-accion="liberoListo"
                ${declarando.cubre.length ? "" : "disabled"}>Listo con el libero</button>
        <button class="tenue" data-accion="liberoCancelar">Cancelar</button>
      </div></div>`;
    return;
  }

  const completa = puestos.every(d => d != null) && rotacionBorrador.armador != null;
  const elegirArmador = puestos.map((dorsal, i) => dorsal == null ? "" :
    `<button class="secundaria ${rotacionBorrador.armador === i + 1 ? "bien" : ""}"
             data-accion="armador" data-valor="${i + 1}">${esc(dorsal)}</button>`).join("");
  const yaDeclarados = rotacionBorrador.liberos.map((l, i) =>
    `<button class="secundaria bien" data-accion="liberoSacar" data-valor="${i}"
             title="tocar para quitarlo">${esc(l.jugador)} por el
       ${l.cubre.map(esc).join(" y el ")} ✕</button>`).join("");
  $("#opciones").innerHTML = `<div class="preparacion" style="width:100%">
    <div class="quePide" style="margin:0">Cual es el armador</div>
    <div class="opciones">${elegirArmador || `<span class="nota">Poné los dorsales primero.</span>`}</div>
    <div class="quePide" style="margin:0">Liberos <span class="nota">(opcional)</span></div>
    <div class="opciones">${yaDeclarados}
      <button class="secundaria" data-accion="liberoNuevo"
              ${completa && rotacionBorrador.liberos.length < 2 ? "" : "disabled"}>+ libero</button></div>
    <div class="fila">
      <button class="primario grande" data-accion="rotacionListo" ${completa ? "" : "disabled"}>
        Listo</button>
      <button class="tenue" data-accion="sinRotacion">Sin rotacion</button>
    </div></div>`;
}

// ----------------------------------------------------------------------
// Cambios: se toca al que sale (un circulo de la cancha) y se teclea el que
// entra. El motor deduce el equipo del que sale, asi que aca no se elige.
function pintarCambio(e){
  $("#secuencia").hidden = true;
  $("#enCurso").hidden = true;
  const todos = {A: {jugadores: new Set(), zonas: new Set()},
                 B: {jugadores: new Set(), zonas: new Set()}};
  if(cambioVisual.sale == null){
    ["A", "B"].forEach(letra =>
      ((e.rotaciones[letra] && e.rotaciones[letra].jugadores) || [])
        .forEach(d => todos[letra].jugadores.add(d)));
  }
  $("#cancha").hidden = false;
  $("#cancha").innerHTML = canchaHTML(e, todos, {accion: "cambioSale", nominal: true});

  if(cambioVisual.sale == null){
    $("#quePide").textContent = "Cambio: tocá al que sale";
    // los liberos no ocupan zona, asi que no estan en la cancha dibujada; van
    // aparte para poder cambiar uno por otro, que tambien pasa en un partido
    const liberos = ["A", "B"].flatMap(letra =>
      ((e.rotaciones[letra] && e.rotaciones[letra].liberos) || []).map(l =>
        `<button data-accion="cambioSale" data-valor="${esc(l.jugador)}">
           ${esc(l.jugador)} · libero de ${esc(e.nombres[letra])}</button>`));
    $("#opciones").innerHTML = liberos.join("") +
      `<button class="tenue" data-accion="cambioCancelar">Cancelar el cambio</button>`;
    return;
  }
  if(tecleando && tecleando.destino === "cambio"){
    $("#quePide").textContent = `Sale el ${cambioVisual.sale}. Quien entra?`;
    // con la salida a la vista: si se toco al jugador equivocado, el teclado
    // solo dejaba seguir para adelante
    $("#opciones").innerHTML = tecladoHTML(false) +
      `<div class="fila" style="margin-top:9px">
         <button class="tenue" data-accion="cambioCancelar">Cancelar el cambio</button></div>`;
    return;
  }
  $("#quePide").textContent = `Sale el ${cambioVisual.sale}, entra el ${cambioVisual.entra}`;
  $("#opciones").innerHTML = `<div class="preparacion" style="width:100%">
    <div class="fila">
      <button class="${cambioVisual.armador ? "bien" : ""}" data-accion="cambioArmador">
        ${cambioVisual.armador ? "✓ " : ""}queda como armador</button>
    </div>
    <div class="fila">
      <button class="primario grande" data-accion="cambioListo">Hacer el cambio</button>
      <button class="tenue" data-accion="cambioCancelar">Cancelar</button>
    </div></div>`;
}

function accionVisual(accion, boton){
  const valor = boton.dataset.valor;
  if(accion === "nombre"){
    const campoPrep = $("#campoPrep");
    return enviar(campoPrep ? campoPrep.value.trim() : "");
  }
  if(accion === "saca") return enviar(valor);
  if(accion === "mantener") return enviar(valor);

  if(accion === "ranura"){
    const declarando = rotacionBorrador.libero;
    if(declarando){
      // tocar una zona mientras se declara un libero dice a quien cubre
      const dorsal = rotacionBorrador.jugadores[Number(valor) - 1];
      if(dorsal == null) return;
      const puesto = declarando.cubre.indexOf(dorsal);
      if(puesto >= 0) declarando.cubre.splice(puesto, 1);
      else if(declarando.cubre.length < 2) declarando.cubre.push(dorsal);
      return pintarVisual(estadoActual);
    }
    tecleando = {destino: "rotacion", digitos: "", ranura: Number(valor) - 1};
    return pintarVisual(estadoActual);
  }
  if(accion === "armador"){
    rotacionBorrador.armador = Number(valor);
    return pintarVisual(estadoActual);
  }
  if(accion === "liberoNuevo"){
    tecleando = {destino: "libero", digitos: ""};
    return pintarVisual(estadoActual);
  }
  if(accion === "liberoListo"){
    rotacionBorrador.liberos.push(rotacionBorrador.libero);
    rotacionBorrador.libero = null;
    return pintarVisual(estadoActual);
  }
  if(accion === "liberoCancelar"){
    rotacionBorrador.libero = null;
    return pintarVisual(estadoActual);
  }
  if(accion === "liberoSacar"){
    rotacionBorrador.liberos.splice(Number(valor), 1);
    return pintarVisual(estadoActual);
  }
  if(accion === "rotacionListo"){
    const campo = rotacionBorrador.jugadores.map((dorsal, i) =>
      dorsal + (rotacionBorrador.armador === i + 1 ? "_S" : ""));
    // el libero va al final, aparte de los 6: "9_L_15_10"
    const liberos = rotacionBorrador.liberos.map(l =>
      [l.jugador, "L"].concat(l.cubre).join("_"));
    rotacionBorrador = null;
    return enviar(campo.concat(liberos).join(" "));
  }
  if(accion === "sinRotacion"){ rotacionBorrador = null; return enviar(""); }

  if(accion === "cambioSale"){
    cambioVisual.sale = Number(valor);
    tecleando = {destino: "cambio", digitos: ""};
    return pintarVisual(estadoActual);
  }
  if(accion === "cambioArmador"){
    cambioVisual.armador = !cambioVisual.armador;
    return pintarVisual(estadoActual);
  }
  if(accion === "cambioListo"){
    const marca = cambioVisual.armador ? "_S" : "";
    const linea = `C_${cambioVisual.entra}${marca}_${cambioVisual.sale}`;
    cambioVisual = null;
    return enviar(linea);
  }
  if(accion === "cambioCancelar"){
    cambioVisual = null; tecleando = null;
    return pintarVisual(estadoActual);
  }
}

// Un solo oyente para toda la cancha: los botones se redibujan en cada toque
// y enganchar uno por uno seria volver a engancharlos todo el tiempo.
$("#visual").addEventListener("click", ev => {
  const tocado = ev.target.closest("[data-tecla],[data-opcion],[data-accion]");
  if(!tocado || tocado.disabled) return;
  if(tocado.dataset.tecla !== undefined) return usarTecla(tocado.dataset.tecla);
  if(tocado.dataset.opcion !== undefined) return tocarOpcion(tocado.dataset.opcion);
  accionVisual(tocado.dataset.accion, tocado);
});

$("#visual").addEventListener("keydown", ev => {
  if(ev.key === "Enter" && ev.target.id === "campoPrep"){
    ev.preventDefault();
    enviar(ev.target.value.trim());
  }
});

// Deshacer el paso saca una ficha de la linea que se esta armando. No tiene
// nada que ver con la "x" del motor, que deshace un punto entero: por eso
// vive aca abajo y no entre los atajos.
$("#btnDeshacerPaso").addEventListener("click", () => {
  if(!armador) return;
  if(tecleando && tecleando.digitos){ tecleando.digitos = ""; return pintarVisual(estadoActual); }
  tecleando = null;
  armador.deshacer();
  pintarVisual(estadoActual);
});

$("#btnCancelarJugada").addEventListener("click", () => {
  if(!armador) return;
  tecleando = null;
  while(armador.deshacer()){ /* hasta vaciar la pila */ }
  pintarVisual(estadoActual);
});

// ======================================================================
// 3) PARTIDOS
// ======================================================================
let PARTIDOS = [];
let listaPartidosVencida = true;    // se vuelve a pedir al entrar a la pestana
let elegido = null;                 // id del partido abierto

async function entrarAPartidos(){
  if(!listaPartidosVencida) return;
  listaPartidosVencida = false;
  const r = await api("/api/partidos");
  avisarDelServidor(r.almacenamiento);
  if(!r.ok){
    $("#listaPartidos").innerHTML = `<p class="nota" style="margin:0">${esc(r.mensaje)}</p>`;
    return;
  }
  PARTIDOS = r.partidos;
  llenarFiltroEquipos();
  llenarFiltroTorneos();
  filtrar();
}

// Las etiquetas que existen, sacadas de los partidos. No hay una lista fija
// de campeonatos en ningun lado: el que se escribe una vez pasa a estar.
function llenarFiltroTorneos(){
  const select = $("#filtroTorneo");
  if(!select) return;
  const etiquetas = new Set();
  PARTIDOS.forEach(p => etiquetasDePartido(p).forEach(e => etiquetas.add(e)));
  const antes = select.value;
  select.innerHTML = `<option value="">Todos</option>` +
    Array.from(etiquetas).sort().map(e =>
      `<option value="${esc(e)}">${esc(e)}</option>`).join("");
  select.value = antes;
}

function llenarFiltroEquipos(){
  const equipos = new Set();
  PARTIDOS.forEach(p => { equipos.add(p.equipo); equipos.add(p.rival); });
  const select = $("#filtroEquipo"), elegidoAntes = select.value;
  select.innerHTML = `<option value="">Todos</option>` +
    Array.from(equipos).filter(Boolean).sort()
      .map(e => `<option value="${esc(e)}">${esc(e)}</option>`).join("");
  select.value = elegidoAntes;
}

function filtrar(){
  const texto = $("#busca").value.trim().toLowerCase();
  const equipo = $("#filtroEquipo").value;
  const desde = $("#filtroDesde").value, hasta = $("#filtroHasta").value;
  const soloInforme = $("#filtroInforme").checked;
  const torneo = $("#filtroTorneo") ? $("#filtroTorneo").value : "";

  const filas = PARTIDOS.filter(p => {
    // el buscador tambien mira las etiquetas: escribir "nacional" alcanza
    if(texto && !`${p.equipo} ${p.rival} ${p.fecha} ${p.torneo || ""}`
        .toLowerCase().includes(texto)) return false;
    if(torneo && !etiquetasDePartido(p).includes(torneo)) return false;
    if(equipo && p.equipo !== equipo && p.rival !== equipo) return false;
    if(desde && p.fecha < desde) return false;
    if(hasta && p.fecha > hasta) return false;
    if(soloInforme && !p.informe) return false;
    return true;
  });

  const caja = $("#listaPartidos");
  if(!filas.length){
    // decir que se busco, no dejar una tabla vacia
    const dichos = [];
    if(texto) dichos.push(`"${texto}"`);
    if(equipo) dichos.push(`equipo ${equipo}`);
    if(desde) dichos.push(`desde ${desde}`);
    if(hasta) dichos.push(`hasta ${hasta}`);
    if(torneo) dichos.push(torneo);
    if(soloInforme) dichos.push("solo con informe");
    caja.innerHTML = `<p class="nota" style="margin:0">Ningun partido coincide con ` +
      esc(dichos.length ? dichos.join(" · ") : "el filtro") +
      `. Hay ${PARTIDOS.length} partidos guardados.</p>`;
    return;
  }

  caja.innerHTML = filas.map(p => {
    const parciales = p.parciales.length ? p.parciales.join("  ") : "sin parciales";
    return `<button class="partido ${p.id === elegido ? "elegido" : ""}" data-id="${esc(p.id)}">
      <span class="fecha">${esc(p.fecha || "sin fecha")}${p.hora ? " " + esc(p.hora) : ""}</span>
      <span class="equipos">${esc(p.equipo)} <span class="rival">vs ${esc(p.rival)}</span></span>
      <span class="tanteo">${esc(p.sets || "—")}</span>
      <span class="detalles">
        ${etiquetasDePartido(p).map(e =>
          `<span class="torneo">${esc(e)}</span>`).join("")}
        <span>${esc(parciales)}</span>
        <span>${p.puntos ? esc(p.puntos) + " puntos" : "puntos sin dato"}</span>
        <span class="marca ${p.volcado ? "si" : "no"}">txt ${p.volcado ? "si" : "no"}</span>
        <span class="marca ${p.informe ? "si" : "no"}">xlsx ${p.informe ? "si" : "no"}</span>
      </span></button>`;
  }).join("");

  caja.querySelectorAll(".partido").forEach(b =>
    b.addEventListener("click", () => abrirPartido(b.dataset.id)));
}

// se escuchan los dos eventos porque el desplegable y el interruptor no
// disparan "input" en todos los navegadores, y el buscador tiene que filtrar
// mientras se escribe sin apretar Enter
["#busca", "#filtroEquipo", "#filtroTorneo", "#filtroDesde", "#filtroHasta",
 "#filtroInforme"]
  .forEach(sel => ["input", "change"].forEach(ev =>
    $(sel).addEventListener(ev, filtrar)));
$("#btnLimpiar").addEventListener("click", () => {
  $("#busca").value = ""; $("#filtroEquipo").value = "";
  if($("#filtroTorneo")) $("#filtroTorneo").value = "";
  $("#filtroDesde").value = ""; $("#filtroHasta").value = "";
  $("#filtroInforme").checked = false;
  filtrar();
});

function avisoPartidos(texto, ok = true){
  const caja = $("#avisoPartidos");
  if(!caja) return;
  caja.textContent = texto || "";
  caja.className = "mensaje" + (texto ? (ok ? " ok" : " error") : "");
  caja.hidden = !texto;
}


function avisoDetalle(texto, ok){
  const caja = $("#avisoDetalle");
  if(!caja) return;
  caja.textContent = texto || "";
  caja.className = "mensaje" + (texto ? (ok ? " ok" : " error") : "");
  caja.hidden = !texto;
}

let volcadoAbierto = null;   // de que partido es el detalle que se esta mirando

async function abrirPartido(id){
  const fila = PARTIDOS.find(p => p.id === id);
  if(!fila) return;
  volcadoAbierto = fila.volcado || null;
  avisoPartidos("");      // el aviso del borrado anterior ya no viene al caso
  elegido = id;
  filtrar();

  // El informe es lo que se viene a mirar: va arriba de todo y ocupa la
  // pantalla. Lo que se puede sacar del .txt es lo mismo pero peor armado,
  // asi que queda atras, plegado, y se abre solo cuando no hay informe.
  const caja = $("#detalle");
  caja.hidden = false;
  caja.innerHTML = `<div class="detalle">${cabezaPartido(fila)}
    <div class="mensaje" id="avisoDetalle" hidden></div>
    <div id="cuerpoInforme"></div>
    <details class="panel suelto" id="panelVolcado">
      <summary>Rotaciones, cambios y estadisticas del volcado .txt</summary>
      <div class="cuerpo libre" id="cuerpoPartido">
        <p class="nota" style="margin:0">Leyendo el volcado…</p></div>
    </details></div>`;
  caja.scrollIntoView({behavior:"smooth", block:"start"});
  cablearBotonesPartido(fila);

  // el .xlsx se pide primero para que aparezca cuanto antes; el volcado se
  // lee en paralelo y se pinta adentro del panel plegado
  let informe = null;
  if(fila.informe){
    informe = verInforme(fila.informe);
  }else{
    $("#cuerpoInforme").innerHTML =
      `<p class="nota">Este partido todavia no tiene informe .xlsx. Se genera desde la
       pestana Cargar: traelo con el boton de aca arriba y toca Excel.</p>`;
  }

  if(fila.volcado){
    const r = await api("/api/partido?archivo=" + encodeURIComponent(fila.volcado));
    $("#cuerpoPartido").innerHTML = r.ok
      ? cuerpoPartido(r.partido)
      : `<p class="nota" style="margin:0">${esc(r.mensaje)}</p>`;
    if(r.ok) cablearSelectorEquipo(r.partido);
  }else{
    $("#cuerpoPartido").innerHTML =
      `<p class="nota" style="margin:0">De este partido solo quedo el informe .xlsx;
       el volcado .txt no esta.</p>`;
  }
  // sin informe, lo del volcado es lo unico que hay: se muestra abierto
  if(!fila.informe) $("#panelVolcado").open = true;
  if(informe) await informe;
}

function cabezaPartido(fila){
  const botones = [];
  if(fila.informe && esLocal){
    botones.push(`<button data-abrir="${esc(fila.informe)}" data-tipo="xlsx">Abrir el Excel en esta PC</button>`);
  }
  if(fila.informe){
    botones.push(`<a class="enlace" href="${esc(urlDescarga(fila.informe, "xlsx"))}"
                     target="_blank" rel="noopener">Descargar el .xlsx</a>`);
  }
  if(fila.volcado){
    botones.push(`<a class="enlace" href="${esc(urlDescarga(fila.volcado, "txt"))}"
                     target="_blank" rel="noopener">Descargar el .txt</a>`);
    botones.push(`<button id="btnACargar">Cargar en la pestana Cargar</button>`);
  }
  // Borrar pide la contraseña, asi que el boton solo esta cuando ya se
  // escribio: sin sesion el servidor contestaria 401 y el boton no seria mas
  // que una forma de que te pidan la clave a destiempo.
  if(token && fila.volcado){
    botones.push(`<button id="btnCorregir">Corregir estos datos</button>`);
    // el editor vive al lado de las tablas que muestran los nombres, que
    // estan adentro del panel plegado: desde aca se llega sin buscarlo
    botones.push(`<button id="btnAbrirNombres">Nombres de los jugadores</button>`);
  }
  if(token){
    botones.push(`<button class="peligro" id="btnBorrarPartido">Borrar este partido</button>`);
  }
  const corregido = (fila.corregido || []).length
    ? `<div class="nota">Corregido a mano: ${esc((fila.corregido || []).join(", "))}</div>`
    : "";
  return `<div class="cabeza">
    <h2>${esc(fila.equipo)} vs ${esc(fila.rival)}</h2>
    <div class="sub">${esc(fila.fecha || "sin fecha")}${fila.hora ? " · " + esc(fila.hora) : ""}
      · sets ${esc(fila.sets || "—")}
      · ${fila.puntos ? esc(fila.puntos) + " puntos cargados" : "puntos sin dato"}</div>
    <div class="parciales">${fila.parciales.map(p =>
        `<span class="parcial">${esc(p)}</span>`).join("") ||
        `<span class="nota">Sin parciales</span>`}</div>
    ${corregido}
    <div class="fila">${botones.join("")}</div>
    <div id="correccion" hidden></div></div>`;
}

// El resumen de la fila se lee del .txt, y casi siempre con eso alcanza. Lo
// que el archivo no puede saber es cual de varios informes del mismo dia le
// corresponde: el nombre del informe no lleva la hora, asi que dos guardados
// del mismo partido comparten archivo y el automatico se lo cuelga al primero.
const CAMPOS_CORREGIBLES = [
  ["fecha", "Fecha", "2026-09-14"],
  ["hora", "Hora", "04:30"],
  ["equipo", "Equipo", "Palestino"],
  ["rival", "Rival", "Español"],
  ["sets", "Sets", "0-2"],
  ["puntos", "Puntos cargados", "92"],
  ["torneo", "Etiquetas", "#nacional2026 #semifinal"],
];

// "#apertura" escrito de cinco formas distintas serian cinco campeonatos, asi
// que se normaliza igual que en el servidor: minusculas y con numeral.
function etiquetasDePartido(p){
  return String(p.torneo || "").split(/[\s,]+/)
    .map(x => x.trim().replace(/^#/, "").toLowerCase())
    .filter(Boolean).map(x => "#" + x)
    .filter((x, i, todas) => todas.indexOf(x) === i);
}

function informesConocidos(){
  const nombres = new Set();
  (PARTIDOS || []).forEach(f => { if(f.informe) nombres.add(f.informe); });
  return Array.from(nombres).sort();
}

function formularioCorreccion(fila){
  const campos = CAMPOS_CORREGIBLES.map(([clave, etiqueta, ejemplo]) =>
    `<label class="campoCorreccion"><span>${esc(etiqueta)}</span>
       <input data-campo="${clave}" value="${esc(fila[clave] == null ? "" : fila[clave])}"
              placeholder="${esc(ejemplo)}"></label>`).join("");
  const opciones = ['<option value="">(ninguno)</option>'].concat(
    informesConocidos().map(n =>
      `<option value="${esc(n)}" ${n === fila.informe ? "selected" : ""}>${esc(n)}</option>`));
  return `<div class="correccion">
    <p class="nota" style="margin-top:0">Lo que pongas acá gana sobre lo que dice el .txt.
    El archivo no se toca: se puede volver atrás cuando quieras.</p>
    <div class="camposCorreccion">${campos}
      <label class="campoCorreccion"><span>Parciales</span>
        <input data-campo="parciales" value="${esc((fila.parciales || []).join(", "))}"
               placeholder="20-25, 22-25"></label>
      <label class="campoCorreccion"><span>Informe .xlsx</span>
        <select data-campo="informe">${opciones.join("")}</select></label>
    </div>
    <div class="fila">
      <button class="primario" id="btnGuardarCorreccion">Guardar</button>
      <button class="tenue" id="btnQuitarCorreccion">Volver a lo que dice el .txt</button>
      <button class="tenue" id="btnCerrarCorreccion">Cancelar</button>
    </div></div>`;
}

function cablearCorreccion(fila){
  const abrir = $("#btnCorregir");
  if(!abrir) return;
  const caja = $("#correccion");
  abrir.addEventListener("click", () => {
    caja.hidden = !caja.hidden;
    caja.innerHTML = caja.hidden ? "" : formularioCorreccion(fila);
    if(caja.hidden) return;

    const mandar = async campos => {
      const r = await api("/api/corregir", {volcado: fila.volcado, campos});
      avisoDetalle(r.mensaje, r.ok);
      if(!r.ok) return;
      listaPartidosVencida = true;
      await entrarAPartidos();
      await abrirPartido(fila.volcado || fila.id);
    };
    // Lo que tenia el formulario al abrirse. Solo se guarda como correccion
    // lo que se haya tocado (o lo que ya estaba corregido): si se mandaran
    // todos los campos, la fila dejaria de seguir al .txt para cosas que
    // nadie quiso cambiar, y arreglar el .txt despues no serviria de nada.
    const inicial = {};
    $$("#correccion [data-campo]").forEach(c => { inicial[c.dataset.campo] = c.value.trim(); });

    $("#btnGuardarCorreccion").addEventListener("click", () => {
      const campos = {};
      const yaCorregidos = fila.corregido || [];
      $$("#correccion [data-campo]").forEach(campo => {
        const clave = campo.dataset.campo, valor = campo.value.trim();
        if(!valor) return;
        if(valor === inicial[clave] && !yaCorregidos.includes(clave)) return;
        campos[clave] = clave === "parciales"
          ? valor.split(",").map(p => p.trim()).filter(Boolean)
          : valor;
      });
      mandar(campos);
    });
    $("#btnQuitarCorreccion").addEventListener("click", () => mandar({}));
    $("#btnCerrarCorreccion").addEventListener("click", () => {
      caja.hidden = true; caja.innerHTML = "";
    });
  });
}

function cablearBotonesPartido(fila){
  cablearBorrado(fila);
  cablearCorreccion(fila);

  const atajo = $("#btnAbrirNombres");
  if(atajo) atajo.addEventListener("click", () => {
    $("#panelVolcado").open = true;
    const boton = $("#btnNombresPartido");
    if(!boton) return avisoDetalle("Este partido no trae jugadores en el volcado.", false);
    if($("#cajaNombresPartido").hidden) boton.click();
    boton.scrollIntoView({behavior: "smooth", block: "center"});
  });
  const boton = $("#btnACargar");
  if(!boton) return;
  boton.addEventListener("click", async () => {
    const chip = $("#chipCargar");
    if(!chip.hidden && !confirm("Hay un partido en curso sin guardar. Se reemplaza por este?")) return;
    boton.disabled = true;
    avisoDetalle("Leyendo el volcado…", true);
    const respuesta = await fetch(urlDescarga(fila.volcado, "txt"));
    const texto = await respuesta.text();
    otroPartido();      // es otro partido: no pisa el privado del que estaba
    const r = await accion("/api/cargar", {texto: soloLasJugadas(texto)});
    boton.disabled = false;
    avisoDetalle(r.mensaje, r.ok);
    if(r.ok) irA("cargar");
  });
}

// Borrar es lo unico de esta pantalla que no se puede deshacer: se borra el
// archivo, no se manda a ningun lado. Por eso el confirm dice exactamente que
// archivos se van, y el boton queda deshabilitado mientras tanto para que un
// doble toque nervioso no dispare dos veces.
function cablearBorrado(fila){
  const boton = $("#btnBorrarPartido");
  if(!boton) return;
  boton.addEventListener("click", async () => {
    const quees = [fila.volcado && "el volcado .txt", fila.informe && "el informe .xlsx"]
      .filter(Boolean).join(" y ");
    if(!confirm(`Se borra ${quees} de ${fila.equipo} vs ${fila.rival}` +
                `${fila.fecha ? " del " + fila.fecha : ""}.

No se puede deshacer. Seguro?`)) return;

    boton.disabled = true;
    avisoDetalle("Borrando…", true);
    const r = await api("/api/borrar", {volcado: fila.volcado, informe: fila.informe});
    boton.disabled = false;
    if(!r.ok) return avisoDetalle(r.mensaje, false);

    // el partido ya no existe: se cierra el detalle y se vuelve a pedir la
    // lista, que es la unica forma de que el listado no quede mintiendo
    $("#detalle").hidden = true;
    elegido = null;
    listaPartidosVencida = true;
    await entrarAPartidos();
    avisoPartidos(r.mensaje);
  });
}

// El .txt guardado empieza con las lineas tal como se tipearon y sigue con
// las estadisticas. /api/cargar espera solo esas lineas, asi que se corta en
// la seccion siguiente. Las lineas vacias del medio son respuestas validas
// (una rotacion vacia), por eso se saca solo el blanco del final.
function soloLasJugadas(texto){
  // "renglones" y no "lineas": lineas es el partido de esta pantalla (ver 2a)
  const renglones = texto.split(/\r?\n/);
  const arranque = renglones.findIndex(l => l.trim() === "=== Jugadas cargadas ===");
  const desde = arranque < 0 ? 0 : arranque + 1;
  const jugadas = [];
  for(let i = desde; i < renglones.length; i++){
    if(renglones[i].startsWith("===")) break;
    jugadas.push(renglones[i]);
  }
  while(jugadas.length && jugadas[jugadas.length - 1].trim() === "") jugadas.pop();
  return jugadas.join("\n");
}

// ---------- el volcado como tablas ----------
function cuerpoPartido(p){
  const partes = [];

  if(p.rotaciones.length){
    const filas = [];
    p.rotaciones.forEach(r => r.equipos.forEach(e => filas.push({celdas:
      [`Set ${r.set}`, e.equipo].concat(e.jugadores.map(j =>
        j === e.armador ? j + " S" : j))})));
    partes.push(`<div class="sub-titulo">Rotaciones por set
      <span class="aclara">zonas 1 a 6, S = armador</span></div>` +
      tabla(["Set", "Equipo", "Z1", "Z2", "Z3", "Z4", "Z5", "Z6"], filas));
  }

  if(p.cambios.length){
    partes.push(`<div class="sub-titulo">Cambios registrados</div>` +
      tabla(["Set", "Equipo", "Entra", "Sale", "Zona", "Detalle"],
        p.cambios.map(c => ({celdas: [c.set, c.equipo, c.entra, c.sale, c.zona, c.detalle || "—"]}))));
  }

  // id propio y no "selectorEquipo": la pestana Jugadores tiene el suyo, y
  // con las dos vistas pintadas los ids repetidos cruzaban los clicks
  const equipos = p.orden_equipos;
  partes.push(`<div class="selector" id="selectorEquipoPartido">` + equipos.map((e, i) =>
    `<button data-equipo="${esc(e)}" class="${i ? "" : "activa"}">${esc(e)}</button>`).join("") +
    `</div><div id="statsEquipoPartido"></div>`);
  return partes.join("");
}

function cablearSelectorEquipo(p){
  const pintarEquipo = nombre => {
    $("#statsEquipoPartido").innerHTML = tablasDeEquipo(nombre, p.equipos[nombre]);
    $$("#selectorEquipoPartido button").forEach(b =>
      b.classList.toggle("activa", b.dataset.equipo === nombre));
    cablearNombresDelPartido(nombre, p.equipos[nombre], pintarEquipo);
  };
  $$("#selectorEquipoPartido button").forEach(b =>
    b.addEventListener("click", () => pintarEquipo(b.dataset.equipo)));
  if(p.orden_equipos.length) pintarEquipo(p.orden_equipos[0]);
}

// Los dorsales que jugaron ese partido con ese equipo. Salen de las propias
// tablas del volcado: no hay una lista de plantel adentro del .txt.
function dorsalesDelPartido(datos){
  const vistos = new Set();
  [datos.recepciones, datos.ataques_jugador, datos.bloqueos_jugador].forEach(obj =>
    Object.keys(obj || {}).forEach(clave => {
      const dorsal = String(clave).replace(/\D+/g, "");
      if(dorsal) vistos.add(dorsal);
    }));
  return Array.from(vistos).sort((a, b) => Number(a) - Number(b));
}

// El numero no es de nadie para siempre: el 13 del año pasado puede no ser el
// de este. Por eso un partido viejo puede tener sus propios nombres, que
// pisan a los del equipo sin tocarlos.
function editorNombresPartido(equipo, datos){
  const delEquipo = ((PLANTEL || {}).plantel || {})[equipo] || {};
  const propios = (((PLANTEL || {}).partidos || {})[volcadoAbierto] || {})[equipo] || {};
  const campos = dorsalesDelPartido(datos).map(d =>
    `<label class="campoCorreccion"><span>${esc(d)}</span>
       <input data-dorsal="${esc(d)}" value="${esc(propios[d] || "")}"
              placeholder="${esc(delEquipo[d] || "sin nombre")}" autocomplete="off"></label>`).join("");
  if(!campos) return "";
  return `<div class="correccion" id="panelNombresPartido">
    <p class="nota" style="margin-top:0">Nombres de ${esc(equipo)} en ESTE partido.
    En gris estan los del equipo, que es lo que se usa si dejas el campo vacio.</p>
    <div class="camposCorreccion">${campos}</div>
    <div class="fila">
      <button class="primario" id="btnGuardarNombresPartido">Guardar</button>
      <button class="tenue" id="btnQuitarNombresPartido">Usar los del equipo</button>
      <button class="tenue" id="btnCerrarNombresPartido">Cancelar</button>
    </div></div>`;
}

function cablearNombresDelPartido(equipo, datos, repintar){
  const abrir = $("#btnNombresPartido");
  if(!abrir) return;
  const caja = $("#cajaNombresPartido");
  abrir.addEventListener("click", () => {
    caja.hidden = !caja.hidden;
    caja.innerHTML = caja.hidden ? "" : editorNombresPartido(equipo, datos);
    if(caja.hidden) return;

    const mandar = async nombres => {
      const r = await api("/api/plantel",
                          {equipo, nombres, volcado: volcadoAbierto});
      avisoDetalle(r.mensaje, r.ok);
      if(!r.ok) return;
      PLANTEL = null;            // que las tablas los vuelvan a leer
      await traerPlantel();
      repintar(equipo);          // se repinta con los nombres nuevos
    };
    $("#btnGuardarNombresPartido").addEventListener("click", () => {
      const nombres = {};
      $$("#panelNombresPartido [data-dorsal]").forEach(c => {
        nombres[c.dataset.dorsal] = c.value.trim();
      });
      mandar(nombres);
    });
    $("#btnQuitarNombresPartido").addEventListener("click", () => mandar({}));
    $("#btnCerrarNombresPartido").addEventListener("click", () => {
      caja.hidden = true; caja.innerHTML = "";
    });
  });
}

function tablasDeEquipo(nombre, datos){
  if(!datos) return `<p class="nota">El volcado no trae estadisticas de ${esc(nombre)}.</p>`;
  const FASES = ["K1", "K2", "K3", "Saque", "Sin fase"];
  const partes = [];

  // Solo con la clave puesta: guardar nombres escribe, y sin token el
  // servidor contestaria 401
  if(token && volcadoAbierto && dorsalesDelPartido(datos).length){
    partes.push(`<div class="fila" style="margin:0 0 4px">
      <button id="btnNombresPartido">Nombres de este partido</button></div>
      <div id="cajaNombresPartido" hidden></div>`);
  }

  // 1) puntos por fase, hechos contra recibidos
  const vacia = {total:0, ganados:0, error:0};
  const filasFase = FASES.map(fase => {
    const h = datos.fases.hechos[fase] || vacia, r = datos.fases.recibidos[fase] || vacia;
    return {celdas: [fase, h.total, h.ganados, h.error, r.total, r.ganados, r.error]};
  });
  const suma = (lado, clave) => FASES.reduce((t, f) =>
    t + num((datos.fases[lado][f] || vacia)[clave]), 0);
  filasFase.push({total:true, celdas: ["TOTAL",
    suma("hechos", "total"), suma("hechos", "ganados"), suma("hechos", "error"),
    suma("recibidos", "total"), suma("recibidos", "ganados"), suma("recibidos", "error")]});
  partes.push(`<div class="sub-titulo">Puntos por fase del rally</div>` +
    tabla(["Fase", "Hechos", "Ganados", "Por error", "Recibidos", "Ganados", "Por error"],
      filasFase, "Hechos: puntos que gano este equipo. Recibidos: los que gano el rival."));

  // 2) puntos por causa
  const causas = Array.from(new Set(
    Object.keys(datos.causas.hechos).concat(Object.keys(datos.causas.recibidos))));
  if(causas.length){
    const filas = causas.map(c => ({celdas: [c, num(datos.causas.hechos[c]), num(datos.causas.recibidos[c])]}));
    filas.push({total:true, celdas: ["TOTAL",
      causas.reduce((t, c) => t + num(datos.causas.hechos[c]), 0),
      causas.reduce((t, c) => t + num(datos.causas.recibidos[c]), 0)]});
    partes.push(`<div class="sub-titulo">Puntos por causa</div>` +
      tabla(["Causa", "Hechos", "Recibidos"], filas));
  }

  // 3) armado por zona
  const zonas = ordenZonas(Object.keys(datos.armado_zona));
  if(zonas.length){
    const total = zonas.reduce((t, z) => t + num(datos.armado_zona[z]), 0);
    const filas = zonas.map(z => ({celdas: [`Zona ${z}`, num(datos.armado_zona[z]),
                                            pct(num(datos.armado_zona[z]), total)]}));
    filas.push({total:true, celdas: ["TOTAL", total, pct(total, total)]});
    partes.push(`<div class="sub-titulo">Armado por zona</div>` +
      tabla(["Zona", "Armados", "% del total"], filas));
  }

  // 4) recepcion por jugador
  const receptores = ordenJugadores(Object.keys(datos.recepciones));
  if(receptores.length){
    const totalDe = r => num(r.cal3) + num(r.cal2) + num(r.cal1) + num(r.cal0) + num(r.pase);
    const acumulado = {cal3:0, cal2:0, cal1:0, cal0:0, pase:0};
    const filas = receptores.map(j => {
      const r = datos.recepciones[j], t = totalDe(r);
      Object.keys(acumulado).forEach(k => { acumulado[k] += num(r[k]); });
      return {celdas: [conNombre(nombre, j, volcadoAbierto), t,
                       num(r.cal3), num(r.cal2), num(r.cal1), num(r.cal0), num(r.pase),
                       pct(num(r.cal3) + num(r.cal2), t), pct(num(r.cal3), t)]};
    });
    const t = totalDe(acumulado);
    filas.push({total:true, celdas: ["TOTAL", t, acumulado.cal3, acumulado.cal2,
      acumulado.cal1, acumulado.cal0, acumulado.pase,
      pct(acumulado.cal3 + acumulado.cal2, t), pct(acumulado.cal3, t)]});
    partes.push(`<div class="sub-titulo">Recepcion por jugador</div>` +
      tabla(["Jugador", "Recepciones", "Cal. 3", "Cal. 2", "Cal. 1", "Cal. 0",
             "Pase al otro lado", "% Positiva (2+3)", "% Perfecta (3)"], filas));
  }

  // 5) ataque por jugador
  const atacantes = ordenJugadores(Object.keys(datos.ataques_jugador));
  if(atacantes.length){
    const acumulado = {totales:0, puntos:0, defendidos:0, fuera:0};
    const filas = atacantes.map(j => {
      const a = datos.ataques_jugador[j];
      Object.keys(acumulado).forEach(k => { acumulado[k] += num(a[k]); });
      return {celdas: [conNombre(nombre, j, volcadoAbierto),
                       num(a.totales), num(a.puntos), num(a.defendidos), num(a.fuera),
                       pct(num(a.puntos), num(a.totales)), pct(num(a.fuera), num(a.totales))]};
    });
    filas.push({total:true, celdas: ["TOTAL", acumulado.totales, acumulado.puntos,
      acumulado.defendidos, acumulado.fuera,
      pct(acumulado.puntos, acumulado.totales), pct(acumulado.fuera, acumulado.totales)]});
    partes.push(`<div class="sub-titulo">Ataque por jugador</div>` +
      tabla(["Jugador", "Ataques", "Punto", "Defendido", "Fuera", "% Punto", "% Fuera"], filas));
  }

  // 6) bloqueos punto
  const bloqueadores = ordenJugadores(Object.keys(datos.bloqueos_jugador || {}));
  if(bloqueadores.length){
    const total = bloqueadores.reduce((t, j) => t + num(datos.bloqueos_jugador[j]), 0);
    const filas = bloqueadores.map(j => ({celdas: [conNombre(nombre, j, volcadoAbierto),
                                                   num(datos.bloqueos_jugador[j]),
                                                   pct(num(datos.bloqueos_jugador[j]), total)]}));
    filas.push({total:true, celdas: ["TOTAL", total, pct(total, total)]});
    partes.push(`<div class="sub-titulo">Bloqueos punto por jugador</div>` +
      tabla(["Jugador", "Bloqueos punto", "% del total"], filas));
  }

  return partes.join("");
}

// ---------- el .xlsx renderizado ----------
let INFORME = null;

async function verInforme(archivo){
  const caja = $("#cuerpoInforme");
  const titulo = extra =>
    `<div class="titulo-informe">Informe <span class="aclara">${esc(archivo)}</span>${extra || ""}</div>`;

  caja.innerHTML = titulo() + `<p class="nota">Leyendo el .xlsx…</p>`;
  const r = await api("/api/informe?archivo=" + encodeURIComponent(archivo));
  if(!r.ok){
    caja.innerHTML = titulo() + `<p class="nota">${esc(r.mensaje)}</p>`;
    return;
  }
  INFORME = r.informe;
  const hojas = INFORME.hojas;
  caja.innerHTML = titulo() +
    (INFORME.avisos.length ? `<p class="nota">${esc(INFORME.avisos.join(" · "))}</p>` : "") +
    `<div class="selector hojas" id="selectorHoja">` + hojas.map((h, i) =>
      `<button data-hoja="${i}" class="${i ? "" : "activa"}">${esc(h.nombre)}${h.oculta ? " ·" : ""}</button>`
    ).join("") + `</div>
    <div class="panel visor"><div class="cuerpo hoja" id="hoja"></div></div>`;

  $$("#selectorHoja button").forEach(b => b.addEventListener("click", () => {
    $$("#selectorHoja button").forEach(o => o.classList.toggle("activa", o === b));
    pintarHoja(hojas[Number(b.dataset.hoja)]);
  }));
  pintarHoja(hojas[0]);
}

function pintarHoja(hoja){
  // los titulos y las notas van combinados en el Excel: aca se estiran con
  // colspan para que la tabla no quede con celdas sueltas. Esas filas se
  // marcan aparte porque son las unicas que no llevan la primera columna
  // anclada: no hay nada a la izquierda que valga la pena dejar fijo.
  const filas = hoja.filas.map(f => {
    const combinada = ["titulo", "subtitulo", "nota", "vacia"].includes(f.tipo);
    const celdas = combinada
      ? `<td colspan="${hoja.columnas || 1}">${esc(f.celdas[0] || "")}</td>`
      : f.celdas.map(c => `<td>${esc(c)}</td>`).join("");
    return `<tr class="${f.tipo}${combinada ? " combinada" : ""}">${celdas}</tr>`;
  }).join("");
  // el marco del visor se mueve en las dos direcciones a la vez: la barra
  // horizontal tiene que estar al pie de la ventana, no al pie de la hoja
  const visor = $("#hoja");
  visor.innerHTML = `<table>${filas}</table>`;
  // al cambiar de hoja se vuelve arriba y a la izquierda, como en Excel
  visor.scrollTop = 0;
  visor.scrollLeft = 0;
}

// ======================================================================
// 4) JUGADORES
// ======================================================================
// Todo sale de /api/jugadores y /api/jugador. El servidor relee los volcados
// de Datos/ en cada pedido, asi que un partido recien guardado ya aparece sin
// ningun paso extra. Los equipos vienen ordenados por cantidad de partidos:
// el propio queda primero, y "Palestino B" va a aparecer solo el dia que se
// cargue un partido suyo.

// {plantel: {equipo: {dorsal: nombre}}, partidos: {volcado: {equipo: {...}}}}
let PLANTEL = null;

async function traerPlantel(){
  if(PLANTEL) return PLANTEL;
  const r = await api("/api/plantel");
  PLANTEL = (r && r.ok)
    ? {plantel: r.plantel || {}, partidos: r.partidos || {},
       posiciones: r.posiciones || {}}
    : {plantel: {}, partidos: {}, posiciones: {}};
  return PLANTEL;
}

// Las tablas de un volcado hablan de "Jugador 13", que es lo que el .txt
// guarda. Si ese numero tiene nombre anotado se muestra al lado: el numero
// manda igual, porque es por lo que se lo busca.
function nombresDe(equipo, volcado){
  // La base es el ultimo nombre conocido de cada dorsal: el del equipo, y si
  // no tiene, el del partido mas nuevo donde se le haya puesto uno (el nombre
  // del archivo lleva la fecha, asi que ordenarlos alcanza). Encima van los
  // propios de este partido, que son los que mandan cuando el 13 del año
  // pasado no es el de este. Misma regla que en el servidor.
  const porPartido = (PLANTEL || {}).partidos || {};
  const base = {};
  Object.keys(porPartido).sort().forEach(v =>
    Object.assign(base, porPartido[v][equipo] || {}));
  Object.assign(base, ((PLANTEL || {}).plantel || {})[equipo] || {});
  return Object.assign(base, porPartido[volcado] && porPartido[volcado][equipo] || {});
}

function conNombre(equipo, clave, volcado){
  const dorsal = String(clave).replace(/\D+/g, "");
  const nombre = nombresDe(equipo, volcado)[dorsal];
  return nombre ? `${clave} · ${nombre}` : clave;
}

let planteles = null;
let equipoElegido = null;
let dorsalElegido = null;
let filtroJugadores = "";       // lo escrito en el buscador
let filtroEtiqueta = "";        // "" = todas las posiciones
// De que campeonato son los numeros: "" = todos los partidos juntos. Es uno
// solo y no una lista a proposito -- sumar dos ligas elegidas a mano da un
// promedio que no es de ninguna de las dos y que despues nadie puede volver a
// encontrar. O es todo, o es un campeonato.
//
// Este filtra en el SERVIDOR (cambia que partidos se suman), a diferencia del
// de posiciones, que solo esconde botones. Y vale para Jugadores Y para
// Equipo porque las dos salen del mismo "planteles": si valiera para una
// sola, la otra mostraria el recuento de partidos de una liga con las
// estadisticas de todas.
let torneoElegido = "";
let soloVarios = false;         // mostrar solo a los que juegan en 2+ equipos
// El resumen del equipo se elige como si fuera un jugador mas: mismo selector,
// mismo lugar. Asi no hace falta otra pestaña ni otro nivel de navegacion.
let editandoNombres = false;    // si el panel de nombres esta abierto

// Las cinco etiquetas. "Armador" va primero porque es la unica que el propio
// partido puede saber: la marca el _S de la rotacion. Tambien se puede poner
// a mano, para los partidos cargados sin rotacion, y las dos fuentes se suman
// (ver estadisticas_jugadores.marcado_como_armador).
const ETIQUETAS = ["Armador", "Libero", "Punta", "Opuesto", "Central"];

// Un jugador puede tener dos: el armador titular tambien es alguien que juega
// de algo. Por eso es una lista y no un campo.
function etiquetasDe(j){
  const lista = [];
  if(j.armador) lista.push("Armador");
  if(j.posicion && j.posicion !== "Armador") lista.push(j.posicion);
  return lista;
}


const esLibero = j => j.posicion === "Libero";

const etiquetaHTML = e =>
  `<span class="etiquetaPos ${e.toLowerCase()}">${esc(e)}</span>`;

// Para buscar "Sofia" y que aparezca "Sofía": sin sacar los acentos, el
// buscador obliga a escribirlos igual que quien cargo el nombre.
const sinAcentos = texto => String(texto || "").toLowerCase()
  .normalize("NFD").replace(/[̀-ͯ]/g, "");

// El volcado guarda numeros, no nombres: en la cancha se grita "el 13". Pero
// el numero solo no dice quien es -- dos equipos pueden tener un 13, y el 13
// de este año puede no ser el del anterior -- asi que los nombres se anotan
// aparte. No tocan el volcado ni el Excel.
function editorDeNombres(equipo, jugadores){
  // "Armador" tambien se ofrece: hace falta para los partidos cargados sin
  // rotacion, donde no hay ningun _S del que sacarlo. Marcarlo a mano suma al
  // _S, no lo pisa, asi que no puede contradecir al volcado.
  const opciones = j => [""].concat(ETIQUETAS).map(e =>
    `<option value="${esc(e)}" ${e === (j.posicion || "") ? "selected" : ""}>${
      e || "sin posicion"}</option>`).join("");
  const campos = jugadores.map(j =>
    `<label class="campoCorreccion"><span>${esc(j.dorsal)}${j.armador ? " ·S" : ""}</span>
       <input data-dorsal="${esc(j.dorsal)}" value="${esc(j.nombre || "")}"
              placeholder="sin nombre" autocomplete="off">
       <select class="posicionJugador" data-posicion="${esc(j.dorsal)}">${opciones(j)}</select>
     </label>`).join("");
  return `<div class="correccion" id="panelNombres">
    <p class="nota" style="margin-top:0">Nombre y posicion de cada jugador de
    ${esc(equipo.nombre)}. Se usan solo para mirar: el volcado y el Excel siguen guardando
    el numero. Al que lleva <code>_S</code> en la rotacion ya se lo marca como armador
    solo; ponerlo aca sirve para los partidos cargados sin rotacion, y nunca le saca
    el rol a nadie.</p>
    <div class="camposCorreccion">${campos}</div>
    <div class="fila">
      <button class="primario" id="btnGuardarNombres">Guardar</button>
      <button class="tenue" id="btnCerrarNombres">Cancelar</button>
    </div></div>`;
}

async function pintarJugadores(){
  const caja = $("#jugadores");
  await traerPlanteles(caja);
  // Los duplicados se avisan en vez de descartarlos en silencio: contar dos
  // veces el mismo partido duplicaria las cifras de todos sin que se note.
  const aviso = $("#avisoDuplicados");
  if(planteles.descartados && planteles.descartados.length){
    aviso.innerHTML = `<b>${planteles.descartados.length} volcado(s) no se cuentan</b>
      porque son recargas de un partido ya contado:<br>` +
      planteles.descartados.map(d =>
        `<code>${esc(d.archivo)}</code> — ${esc(d.motivo)}`).join("<br>");
    aviso.hidden = false;
  } else {
    aviso.hidden = true;
  }

  // Va arriba de todo porque es el filtro mas ancho: decide QUE partidos se
  // suman, y todo lo de abajo sale de eso.
  const selectorTorneo = pintarTorneos("filtroTorneoJugadores");
  if(!planteles.equipos.length){
    caja.innerHTML = selectorTorneo + sinPartidos();
    engancharTorneos("filtroTorneoJugadores", pintarJugadores);
    return;
  }

  let equipo = planteles.equipos.find(e => e.nombre === equipoElegido);
  if(!equipo){ equipo = planteles.equipos[0]; equipoElegido = equipo.nombre; }
  const jugadores = porDorsal(equipo.jugadores);
  if(!jugadores.some(j => j.dorsal === dorsalElegido)){
    dorsalElegido = jugadores.length ? jugadores[0].dorsal : null;
  }

  const selectorEquipos = `<div class="selector" id="selectorEquipo">` +
    planteles.equipos.map(e =>
      `<button data-equipo="${esc(e.nombre)}" class="${e.nombre === equipoElegido ? "activa" : ""}">
        ${esc(e.nombre)}<span class="chip">${esc(e.partidos)}</span></button>`).join("") +
    `</div>`;

  const selectorDorsales = `<div class="selector" id="selectorDorsal">` +
    jugadores.map(j =>
      `<button data-dorsal="${esc(j.dorsal)}" data-nombre="${esc(j.nombre || "")}"
        data-etiquetas="${esc(etiquetasDe(j).join(" "))}"
        data-equipos="${esc(j.equipos || 0)}"
        class="${j.dorsal === dorsalElegido ? "activa" : ""}"
        title="${esc(j.partidos)} partidos${j.equipos > 1
          ? " · juega en " + j.equipos + " equipos" : ""}">${esc(j.dorsal)}${
          j.equipos > 1 ? `<span class="enVarios">${esc(j.equipos)}</span>` : ""}${
          j.nombre ? `<span class="nombreJugador">${esc(j.nombre)}</span>` : ""}${
          etiquetasDe(j).map(etiquetaHTML).join("")}</button>`).join("") +
    `<span class="nota" id="sinCoincidencias" hidden>Ningun jugador con ese nombre o numero.</span>` +
    `</div>`;

  // El buscador filtra los botones en el DOM, sin volver a pintar: si
  // repintara, cada tecla pediria la ficha de vuelta y el campo perderia el
  // foco a la segunda letra.
  // Solo se ofrecen las etiquetas que alguien tiene: un filtro que siempre
  // deja la lista vacia no sirve de nada y ocupa lugar en un celular.
  const usadas = ETIQUETAS.filter(e => jugadores.some(j => etiquetasDe(j).includes(e)));
  const hayVarios = jugadores.some(j => j.equipos > 1);
  const filtroPorEtiqueta = (usadas.length || hayVarios)
    ? `<div class="filtroEtiquetas" id="filtroEtiquetas">
    <button data-etiqueta="" class="${filtroEtiqueta ? "" : "activa"}">Todos</button>` +
    usadas.map(e => `<button data-etiqueta="${esc(e)}"
      class="etiquetaPos ${e.toLowerCase()} ${filtroEtiqueta === e ? "activa" : ""}"
      >${esc(e)}</button>`).join("") +
    (hayVarios ? `<span class="separadorFiltro"></span>
      <button data-varios="1" class="enVariosFiltro ${soloVarios ? "activa" : ""}"
        >En varios equipos</button>` : "") +
    `</div>` : "";

  const buscador = `<div class="buscadorJugadores">
    <input id="buscarJugador" placeholder="Buscar por nombre o numero"
           value="${esc(filtroJugadores)}" autocomplete="off" spellcheck="false">
    ${token ? `<button id="btnNombres">${editandoNombres ? "Cerrar" : "Nombres"}</button>` : ""}
  </div>` + filtroPorEtiqueta;

  const cabecera = selectorTorneo + selectorEquipos + buscador +
    (editandoNombres ? editorDeNombres(equipo, jugadores) : "") + selectorDorsales;
  if(dorsalElegido == null){
    caja.innerHTML = cabecera + `<p class="nota">Sin jugadores en este equipo.</p>`;
    engancharSelectores();
    return;
  }

  const r = await api(`/api/jugador?equipo=${encodeURIComponent(equipoElegido)}` +
                      `&dorsal=${encodeURIComponent(dorsalElegido)}` +
                      `&campeonato=${encodeURIComponent(torneoElegido)}`);
  if(!r.ok){
    caja.innerHTML = cabecera + `<p class="nota">${esc(r.mensaje)}</p>`;
    engancharSelectores();
    return;
  }
  const j = r.jugador;

  caja.innerHTML = cabecera + `
    <div class="ficha" style="margin-top:12px">
      <div class="dorsal">${esc(j.dorsal)}</div>
      <div>
        ${j.nombre ? `<div class="nombreFicha">${esc(j.nombre)}</div>` : ""}
        <div class="rol">${etiquetasDe(j).map(etiquetaHTML).join("") ||
          `<span class="etiquetaPos">sin posicion</span>`} · ${esc(j.equipo)}</div>
        <div class="datos">${esc(j.partidos)} partido(s) cargado(s)</div>
      </div>
    </div>
    ${indicadoresJugador(j)}
    ${enCadaEquipo(j)}
    ${tablaPorPartido(j)}
    ${!j.armador && j.indicadores.recepciones ? tablasRecepcion(j) : ""}
    ${j.defensa ? tablasDefensa(j) : ""}
    ${!esLibero(j) && j.indicadores.ataques ? tablasAtaque(j) : ""}
    ${j.libres ? tablasLibres(j) : ""}
    ${j.saque ? tablasSaque(j) : ""}
    ${j.armador ? tablasArmado(j) : ""}
    ${j.armado_calidad ? tablasCalidadArmado(j) : ""}
    ${j.rotacion ? tablasRotacion(j) : ""}
    ${j.evolucion.length > 1 ? `<div class="sub-titulo">Partido a partido</div>` +
                               graficoEvolucion(j) : ""}
    ${tablaComparacion(j)}
    ${notaAlPie(j)}`;

  engancharSelectores();
}

// Los planteles se piden una vez y los comparten Jugadores y Equipo. Con el
// filtro de campeonato puesto, ese pedido deja de ser siempre el mismo: por
// eso se centralizo aca en vez de repetirlo en las dos pantallas.
async function traerPlanteles(caja){
  if(planteles !== null) return planteles;
  caja.innerHTML = `<p class="nota">Leyendo los partidos guardados…</p>`;
  const r = await api("/api/jugadores?campeonato=" + encodeURIComponent(torneoElegido));
  avisarDelServidor(r.almacenamiento);
  planteles = r.ok ? r : {equipos: [], descartados: [], campeonatos: []};
  return planteles;
}

const sinPartidos = () => `<p class="nota">${torneoElegido
  ? "No hay partidos de " + esc(torneoElegido) + ". Las etiquetas se ponen en Partidos."
  : "Todavia no hay partidos guardados."}</p>`;

// Los campeonatos salen de TODOS los partidos, no de los que quedan despues
// de filtrar: si salieran de los filtrados, elegir uno borraria los demas del
// selector y no habria como volver.
// El id lo pone el que llama: Jugadores y Equipo estan las dos en el DOM al
// mismo tiempo (una escondida), asi que si compartieran id habria dos
// elementos con el mismo y engancharTorneos cablearia los botones de la otra.
function pintarTorneos(id){
  const torneos = (planteles && planteles.campeonatos) || [];
  if(!torneos.length) return "";
  const boton = (valor, texto) =>
    `<button data-torneo="${esc(valor)}" class="${
      valor === torneoElegido ? "activa" : ""}">${esc(texto)}</button>`;
  return `<div class="filtroEtiquetas torneos" id="${id}">` +
    boton("", "#todos") + torneos.map(t => boton(t, t)).join("") +
    `</div>`;
}

// Cambiar de campeonato cambia que partidos se suman, asi que hay que volver
// a pedirlos: no alcanza con esconder botones, como hace el de posiciones.
// Uno solo a la vez -- volver a tocar el que ya esta puesto no hace nada, que
// es como se evita el "ninguno elegido" sin explicarlo.
function engancharTorneos(id, repintar){
  $$(`#${id} button`).forEach(b =>
    b.addEventListener("click", () => {
      if((b.dataset.torneo || "") === torneoElegido) return;
      torneoElegido = b.dataset.torneo || "";
      planteles = null;   // cambio que partidos se suman: hay que pedirlos
      repintar();
    }));
}

function engancharSelectores(){
  engancharTorneos("filtroTorneoJugadores", pintarJugadores);
  $$("[data-otro-equipo]").forEach(b => b.addEventListener("click", () => {
    equipoElegido = b.dataset.otroEquipo;
    dorsalElegido = b.dataset.otroDorsal;
    filtroJugadores = "";
    pintarJugadores();
  }));
  $$("#selectorEquipo button").forEach(b => b.addEventListener("click", () => {
    equipoElegido = b.dataset.equipo;
    dorsalElegido = null;
    filtroJugadores = "";        // el filtro es de un equipo, no del otro
    pintarJugadores();
  }));
  $$("#selectorDorsal button").forEach(b => b.addEventListener("click", () => {
    dorsalElegido = b.dataset.dorsal;
    pintarJugadores();
  }));

  const buscador = $("#buscarJugador");
  if(buscador){
    aplicarFiltroJugadores();
    buscador.addEventListener("input", () => {
      filtroJugadores = buscador.value;
      aplicarFiltroJugadores();
    });
  }

  // El filtro por etiqueta esconde botones, igual que el buscador: repintar
  // pediria la ficha de nuevo y perderia el foco del campo de busqueda.
  $$("#filtroEtiquetas button").forEach(b => b.addEventListener("click", () => {
    if(b.dataset.varios !== undefined){
      soloVarios = !soloVarios;
      b.classList.toggle("activa", soloVarios);
    } else {
      filtroEtiqueta = b.dataset.etiqueta === filtroEtiqueta ? "" : b.dataset.etiqueta;
      $$("#filtroEtiquetas button[data-etiqueta]").forEach(o =>
        o.classList.toggle("activa", (o.dataset.etiqueta || "") === filtroEtiqueta));
    }
    aplicarFiltroJugadores();
  }));

  const abrir = $("#btnNombres");
  if(abrir) abrir.addEventListener("click", () => {
    editandoNombres = !editandoNombres;
    pintarJugadores();
  });
  const cerrar = $("#btnCerrarNombres");
  if(cerrar) cerrar.addEventListener("click", () => {
    editandoNombres = false;
    pintarJugadores();
  });
  const guardar = $("#btnGuardarNombres");
  if(guardar) guardar.addEventListener("click", async () => {
    const nombres = {}, posiciones = {};
    $$("#panelNombres [data-dorsal]").forEach(c => { nombres[c.dataset.dorsal] = c.value.trim(); });
    $$("#panelNombres [data-posicion]").forEach(c => { posiciones[c.dataset.posicion] = c.value; });
    guardar.disabled = true;
    const r = await api("/api/plantel", {equipo: equipoElegido, nombres, posiciones});
    guardar.disabled = false;
    if(!r.ok) return avisoJugadores(r.mensaje, false);
    editandoNombres = false;
    planteles = null;            // que se vuelvan a pedir con los nombres nuevos
    PLANTEL = null;              // y que las tablas de Partidos los vean tambien
    await traerPlantel();
    await pintarJugadores();
    avisoJugadores(r.mensaje, true);
  });
}

// El buscador esconde botones en vez de repintar: repintar pediria la ficha
// de nuevo en cada tecla y el campo perderia el foco.
function aplicarFiltroJugadores(){
  const buscado = sinAcentos(filtroJugadores).trim();
  let visibles = 0;
  $$("#selectorDorsal button").forEach(b => {
    const porNombre = !buscado ||
      sinAcentos(b.dataset.dorsal).includes(buscado) ||
      sinAcentos(b.dataset.nombre).includes(buscado);
    // los dos filtros se suman: buscar "Sofia" entre los punteros
    const porEtiqueta = !filtroEtiqueta ||
      (b.dataset.etiquetas || "").split(" ").includes(filtroEtiqueta);
    const porVarios = !soloVarios || Number(b.dataset.equipos || 0) > 1;
    const entra = porNombre && porEtiqueta && porVarios;
    b.hidden = !entra;
    if(entra) visibles++;
  });
  const aviso = $("#sinCoincidencias");
  if(aviso){
    const puestos = [filtroEtiqueta, soloVarios && "en varios equipos"]
      .filter(Boolean).join(" + ");
    aviso.textContent = puestos && !buscado
      ? `Ningun jugador ${puestos}.`
      : "Ningun jugador con ese nombre o numero.";
    aviso.hidden = visibles > 0;
  }
}

function avisoJugadores(texto, ok){
  const caja = $("#avisoDuplicados");
  if(!caja) return;
  caja.textContent = texto || "";
  caja.hidden = !texto;
  caja.style.borderColor = ok ? "var(--ok)" : "var(--error)";
  caja.style.color = ok ? "var(--ok)" : "var(--error)";
}

// Una linea por partido: es lo que deja ver si mejora o empeora, que en un
// acumulado de varios partidos se pierde.
// Las columnas van agrupadas por fundamento y solo aparecen los grupos que
// este jugador hizo en algun partido: al libero no le salen columnas de
// ataque, a un central que no saca no le sale el saque. Asi la tabla dice lo
// que el jugador hace y no se llena de ceros. La ultima fila es el total.
function tablaPorPartido(j){
  const partidos = j.por_partido || [];
  if(!partidos.length) return "";
  const hay = clave => partidos.some(p => num(p[clave]) > 0);
  const sumaDe = clave => partidos.reduce((t, p) => t + num(p[clave]), 0);
  const ataquesPunto = p => Math.round(num(p.punto) * num(p.ataques));
  const ataquesEficacia = p => Math.round(num(p.eficacia) * num(p.ataques));
  const positivas = p => Math.round(num(p.positiva) * num(p.recepciones));

  const grupos = [
    {titulo: "Recepción", si: !j.armador && hay("recepciones"),
     cab: ["Rec.", "% Pos."],
     celdas: p => [p.recepciones, pct(positivas(p), num(p.recepciones))],
     total: () => [sumaDe("recepciones"),
                   pct(partidos.reduce((t, p) => t + positivas(p), 0), sumaDe("recepciones"))]},
    {titulo: "Defensa", si: hay("defensas"),
     cab: ["Def.", "% Pos."],
     celdas: p => [p.defensas, pct(num(p.defensa_positiva), num(p.defensas))],
     total: () => [sumaDe("defensas"), pct(sumaDe("defensa_positiva"), sumaDe("defensas"))]},
    {titulo: "Ataque", si: !esLibero(j) && hay("ataques"),
     cab: ["Atq.", "% Punto", "Eficacia"],
     celdas: p => [p.ataques, pctDe(p.punto), pctDe(p.eficacia)],
     total: () => {
       const n = sumaDe("ataques");
       return [n, pct(partidos.reduce((t, p) => t + ataquesPunto(p), 0), n),
               pct(partidos.reduce((t, p) => t + ataquesEficacia(p), 0), n)];
     }},
    {titulo: "Saque", si: hay("saques"),
     cab: ["Saq.", "As", "Err.", "Pot."],
     celdas: p => [p.saques, p.aces, p.errores_saque, p.potencia],
     total: () => [sumaDe("saques"), sumaDe("aces"), sumaDe("errores_saque"), sumaDe("potencia")]},
    {titulo: "Bloqueo", si: !esLibero(j) && (hay("bloqueos") || hay("toques_bloqueo")),
     cab: ["Punto", "Toques"],
     celdas: p => [p.bloqueos, p.toques_bloqueo],
     total: () => [sumaDe("bloqueos"), sumaDe("toques_bloqueo")]},
    {titulo: "Armado", si: j.armador || hay("armados"),
     cab: ["Armados", "% del equipo", "% A+", "AX"],
     celdas: p => [p.armados, pct(num(p.armados), num(p.armados_equipo)),
                   pct(num(p.armado_mas), num(p.armado_calificados)), p.armado_ax],
     total: () => [sumaDe("armados"), pct(sumaDe("armados"), sumaDe("armados_equipo")),
                   pct(sumaDe("armado_mas"), sumaDe("armado_calificados")), sumaDe("armado_ax")]},
    {titulo: "En cancha", si: hay("en_cancha"),
     cab: ["Puntos", "% Ganados"],
     celdas: p => [p.en_cancha, pct(num(p.en_cancha_ganados), num(p.en_cancha))],
     total: () => [sumaDe("en_cancha"), pct(sumaDe("en_cancha_ganados"), sumaDe("en_cancha"))]},
  ].filter(g => g.si);
  if(!grupos.length) return "";

  const cabeza = ["Partido"].concat(...grupos.map(g => g.cab));
  const filas = partidos.map(p => ({celdas: [p.etiqueta].concat(...grupos.map(g => g.celdas(p)))}));
  if(partidos.length > 1)
    filas.push({total: true, celdas: ["TOTAL"].concat(...grupos.map(g => g.total()))});
  const notas = [];
  if(grupos.some(g => g.titulo === "Ataque")) notas.push("Eficacia = (puntos - errores) / ataques.");
  if(grupos.some(g => g.titulo === "Saque")) notas.push("Pot. = saques de potencia.");
  if(grupos.some(g => g.titulo === "Armado")) notas.push("% A+ sobre los armados calificados.");
  if(grupos.some(g => g.titulo === "En cancha"))
    notas.push("En cancha: puntos jugados con el en la formacion y % ganados por el equipo.");
  return `<div class="sub-titulo">Resumen por partido</div>` + tabla(cabeza, filas,
    notas.join(" "), [{titulo: "", span: 1}].concat(grupos.map(g => ({titulo: g.titulo, span: g.cab.length}))));
}

// ----------------------------------------------------------------------
// La pestaña Equipo. Comparte "equipoElegido" con Jugadores a proposito: si
// se esta mirando a Palestino B, pasar de una pestaña a la otra sigue
// hablando del mismo equipo.
async function pintarEquipo(){
  const caja = $("#equipo");
  await traerPlanteles(caja);
  const selectorTorneo = pintarTorneos("filtroTorneoEquipo");
  if(!planteles.equipos.length){
    caja.innerHTML = selectorTorneo + sinPartidos();
    engancharTorneos("filtroTorneoEquipo", pintarEquipo);
    return;
  }

  let equipo = planteles.equipos.find(e => e.nombre === equipoElegido);
  if(!equipo){ equipo = planteles.equipos[0]; equipoElegido = equipo.nombre; }

  // con un solo equipo el selector es un boton que no hace nada: ocupa una
  // fila entera en un celular y no ofrece ninguna eleccion
  const selector = planteles.equipos.length < 2 ? "" :
    `<div class="selector" id="selectorEquipoResumen">` + planteles.equipos.map(e =>
      `<button data-equipo="${esc(e.nombre)}" class="${e.nombre === equipoElegido ? "activa" : ""}">
        ${esc(e.nombre)}<span class="chip">${esc(e.partidos)}</span></button>`).join("") +
    `</div>`;

  const r = await api(`/api/equipo?equipo=${encodeURIComponent(equipoElegido)}` +
                      `&campeonato=${encodeURIComponent(torneoElegido)}`);
  caja.innerHTML = selectorTorneo + selector +
    (r.ok ? resumenEquipoHTML(r.equipo) : `<p class="nota">${esc(r.mensaje)}</p>`);
  engancharTorneos("filtroTorneoEquipo", pintarEquipo);

  $$("#selectorEquipoResumen button").forEach(b => b.addEventListener("click", () => {
    equipoElegido = b.dataset.equipo;
    dorsalElegido = null;     // el jugador que estaba elegido era del otro
    pintarEquipo();
  }));
}


// ----------------------------------------------------------------------
// Resumen del equipo. Las mismas metricas que una ficha, pero de preguntas
// que no son de nadie en particular: en que fase se ganan los puntos, que
// arma el armador segun como vino la recepcion, hacia donde se ataca desde
// cada zona. Un jugador no las puede contestar solo.
function resumenEquipoHTML(e){
  const i = e.indicadores;
  const casillas = [
    ["Puntos hechos", i.hechos, ""],
    ["Puntos recibidos", i.recibidos, ""],
    ["Recepciones", i.recepciones, ""],
    ["% Positiva", pctDe(i.positiva), "calidad 2+3"],
    ["Defensas", i.defensas, ""],
    ["% Def. positiva", pctDe(i.defensa_positiva), "calidad 2+3"],
    ["Ataques", i.ataques, ""],
    ["% Punto", pctDe(i.punto), "de sus ataques"],
    ["Eficacia", pctDe(i.eficacia), "(puntos - errores) / ataques"],
    ["Bloqueos punto", i.bloqueos_punto, ""],
  ];
  return `
    <div class="ficha" style="margin-top:12px">
      <div class="dorsal equipoEntero">${esc(e.equipo.slice(0, 2).toUpperCase())}</div>
      <div>
        <div class="nombreFicha">${esc(e.equipo)}</div>
        <div class="datos">${esc(e.partidos)} partido(s) · ${esc(e.sets)} set(s)</div>
      </div>
    </div>
    <div class="indicadores">` + casillas.map(([titulo, valor, base]) =>
      `<div class="indicador"><div class="valor">${esc(valor)}</div>
       <div class="titulo">${esc(titulo)}</div>
       ${base ? `<div class="base">${esc(base)}</div>` : ""}</div>`).join("") + `</div>` +
    fasesHTML(e) + causasHTML(e) + distribucionHTML(e) + direccionHTML(e) +
    recepcionEquipoHTML(e) + defensaEquipoHTML(e) + porPartidoEquipoHTML(e);
}

// En que fase del rally se ganan y se pierden los puntos. El saldo es lo que
// dice de un vistazo que fase da puntos y cual los regala: un K1 con saldo
// negativo significa que el equipo pierde mas de lo que gana recibiendo.
function fasesHTML(e){
  const filas = e.fases.filter(f => f.hechos || f.recibidos).map(f => ({
    celdas: [f.fase, f.hechos, pctDe(f.hechos_reparto), f.hechos_ganados, f.hechos_error,
             f.recibidos, pctDe(f.recibidos_reparto),
             (f.saldo > 0 ? "+" : "") + f.saldo],
  }));
  return `<div class="sub-titulo">Puntos por fase del rally</div>` + tabla(
    ["Fase", "Hechos", "% de los hechos", "Ganados", "Por error",
     "Recibidos", "% de los recibidos", "Saldo"], filas,
    "K1 = punto sobre la propia recepcion. K2 = sobre la defensa del contraataque. " +
    "K3 = de ahi en adelante. Saldo = hechos menos recibidos en esa fase.");
}

function causasHTML(e){
  const filas = c => c.filter(x => x.hechos || x.recibidos)
    .map(x => ({celdas: [x.causa, x.hechos, x.recibidos]}));
  return `<div class="sub-titulo">Como se ganan los puntos</div>` +
    tabla(["Causa", "A favor", "En contra"], filas(e.causas.ganados)) +
    `<div class="sub-titulo">Como se pierden</div>` +
    tabla(["Error", "Propios", "Del rival"], filas(e.causas.errores),
          "\"Propios\" son puntos que regalo el equipo; \"del rival\", los que le regalaron.");
}

// La pregunta del armador: cuanto se achica el juego cuando la recepcion no
// viene bien. Con calidad 3 puede ir a cualquier lado; con calidad 0 casi
// siempre termina en la misma zona, y el rival lo sabe.
function distribucionHTML(e){
  const z = e.distribucion.zonas;
  if(!z.length) return "";
  const filas = e.distribucion.filas.filter(f => f.total).map(f => ({
    celdas: [`Calidad ${f.calidad}`, f.total].concat(
      f.valores.map((v, k) => v ? `${v} · ${pctDe(f.reparto[k])}` : "—")),
  }));
  return `<div class="sub-titulo">Distribucion del armado segun la recepcion</div>` +
    tabla(["Recepcion", "Armados"].concat(z.map(x => "Zona " + x)), filas,
          "Cada fila reparte el 100% de los armados que salieron de esa calidad de pase.");
}

// Hacia donde ataca el equipo desde cada zona de origen, y con que resultado.
function direccionHTML(e){
  const d = e.direccion.direcciones;
  if(!e.direccion.filas.length) return "";
  const filas = e.direccion.filas.map(f => ({
    celdas: [`Zona ${f.zona}`, `${f.ataques} · ${pctDe(f.punto)}`, pctDe(f.del_total)].concat(
      f.hacia.map(h => h.ataques ? `${h.ataques} · ${pctDe(h.reparto)} · ${pctDe(h.punto)} pt`
                                 : "—")),
  }));
  return `<div class="sub-titulo">Hacia donde se ataca, por zona de origen</div>` +
    tabla(["Desde", "Ataques · % punto", "% del total"].concat(d.map(x => "Hacia " + x)),
          filas,
          "\"Ataques · % punto\": cuantos salieron de esa zona y que parte fueron " +
          "punto. \"% del total\" es cuanto se usa la zona, que es otra cosa: la mas " +
          "usada puede ser la menos efectiva. En las columnas Hacia: ataques · que " +
          "parte de los de esa zona · que parte fueron punto.");
}

function recepcionEquipoHTML(e){
  const t = e.recepcion.total;
  const cabeza = ["", "Recepciones", "Cal. 3", "Cal. 2", "Cal. 1", "Cal. 0",
                  "Pase al otro lado", "% Positiva"];
  const total = {total: true, celdas: ["Todas", t.recepciones, t.cal3, t.cal2, t.cal1,
    t.cal0, t.pase, pct(t.cal3 + t.cal2, t.recepciones)]};
  const filas = [total].concat(e.recepcion.por_tipo.filter(f => f.recepciones).map(f => ({
    celdas: [`${f.tipo} (${f.ruta})`, f.recepciones, f.cal3, f.cal2, f.cal1, f.cal0,
             f.pase, pctDe(f.positiva)],
  })));
  return `<div class="sub-titulo">Recepcion, y contra que saque</div>` +
    tabla(cabeza, filas, "La ruta es de que zona salio el saque a cual cayo.");
}

function defensaEquipoHTML(e){
  const d = e.defensa;
  if(!d || !d.defensas) return "";
  return `<div class="sub-titulo">Defensa del equipo</div>` + tabla(
    ["", "Defensas", "Cal. 3", "Cal. 2", "Cal. 1", "Cal. 0", "Pase al otro lado",
     "% Positiva"],
    [{total: true, celdas: ["Todas", d.defensas, d.cal3, d.cal2, d.cal1, d.cal0,
                            d.pase, pct(d.cal3 + d.cal2, d.defensas)]}],
    "La calidad 0 incluye la pelota que nadie llego a levantar.");
}

function porPartidoEquipoHTML(e){
  const filas = e.por_partido.map(p => ({celdas: [
    p.etiqueta, `${p.hechos}-${p.recibidos}`, p.recepciones, pctDe(p.positiva),
    p.ataques, pctDe(p.punto), pctDe(p.eficacia), p.bloqueos]}));
  return `<div class="sub-titulo">Partido a partido</div>` + tabla(
    ["Partido", "Puntos", "Recepciones", "% Positiva", "Ataques", "% Punto",
     "Eficacia", "Bloqueos"], filas);
}

// La misma persona puede jugar en la primera y en la segunda, con numeros
// distintos en cada una. Sus cifras van separadas y nunca sumadas: el promedio
// de las dos taparia justamente la diferencia entre jugar en una y en la otra,
// que es lo que se quiere mirar.
//
// El cruce se hace por NOMBRE, no por dorsal: la misma persona puede ser la 13
// en la A y la 7 en la B. Por eso sin nombre anotado esto no aparece.
function enCadaEquipo(j){
  if(!j.tambien_en || !j.tambien_en.length) return "";
  const cabeza = ["Equipo", "Partidos", "Recepciones", "% Positiva", "Ataques",
                  "% Punto", "Eficacia", "Armados", "Bloqueos"];
  const fila = (e, aqui) => ({
    total: aqui,
    celdas: [`${e.equipo} · #${e.dorsal}`, e.partidos, e.recepciones,
             pctDe(e.positiva), e.ataques, pctDe(e.punto), pctDe(e.eficacia),
             e.armados, e.bloqueos],
  });
  const filas = [fila(j.aqui, true)].concat(j.tambien_en.map(e => fila(e, false)));
  const irA = j.tambien_en.map(e =>
    `<button class="secundaria" data-otro-equipo="${esc(e.equipo)}"
       data-otro-dorsal="${esc(e.dorsal)}">Ver en ${esc(e.equipo)}</button>`).join("");
  return `<div class="sub-titulo">${esc(j.nombre || "El jugador")} en cada equipo</div>` +
    tabla(cabeza, filas, "Se cruzan por nombre, no por numero: la misma persona " +
          "puede tener un dorsal distinto en cada equipo.") +
    `<div class="fila">${irA}</div>`;
}

function indicadoresJugador(j){
  const i = j.indicadores;
  // El libero no ataca ni bloquea (las dos son falta) y al armador no se le
  // miden las recepciones: mostrarles esas casillas en cero no es
  // informacion, es ruido que ademas hace dudar del dato. Si igual hay
  // numeros ahi son de una jugada de emergencia, y se ven en el resumen por
  // partido. Es la misma regla que usa la tabla de comparacion de abajo.
  const casillas = [
    ["Recepciones", i.recepciones, "", !j.armador],
    ["% Positiva", pctDe(i.positiva), "calidad 2+3", !j.armador],
    ["% Perfecta", pctDe(i.perfecta), "calidad 3", !j.armador],
    // la defensa la hacen todos, tambien el armador: es la unica casilla que
    // no se esconde por rol
    ["Defensas", i.defensas, "", true],
    ["% Def. positiva", pctDe(i.defensa_positiva), "calidad 2+3", true],
    ["Ataques", i.ataques, "", !esLibero(j)],
    ["% Punto", pctDe(i.punto), "de sus ataques", !esLibero(j)],
    ["Bloqueos punto", i.bloqueos_punto, "", !esLibero(j)],
    // las nuevas solo aparecen si hay algo: un 0 en todos los partidos viejos
    // no es un dato
    ["Toques de bloqueo", i.toques_bloqueo, "frena el ataque, sigue el punto",
     !esLibero(j) && num(i.toques_bloqueo) > 0],
    ["Saques", i.saques, `${num(i.aces)} as · ${num(i.errores_saque)} error`, num(i.saques) > 0],
    ["% As", pct(num(i.aces), num(i.saques)), "de sus saques", num(i.saques) > 0]
  ].filter(c => c[3]);
  return `<div class="indicadores">` + casillas.map(([titulo, valor, base]) =>
    `<div class="indicador"><div class="valor">${esc(valor)}</div>
     <div class="titulo">${esc(titulo)}</div>
     ${base ? `<div class="base">${esc(base)}</div>` : ""}</div>`).join("") + `</div>`;
}


// El desglose set por set de un jugador suelto no dice nada: son tres o
// cuatro recepciones por set y el porcentaje salta de 0 a 100 con una sola
// pelota. Queda el total del partido, y cada calidad dice que parte es.
function tablasRecepcion(j){
  const r = j.recepcion.total, t = num(r.recepciones);
  const cabeza = ["Recepciones", "Cal. 3", "Cal. 2", "Cal. 1", "Cal. 0",
                  "Pase al otro lado", "% Positiva (2+3)", "% Perfecta (3)"];
  const fila = {total: true, celdas: [t,
    conParte(r.cal3, t), conParte(r.cal2, t), conParte(r.cal1, t), conParte(r.cal0, t),
    conParte(r.pase, t), pct(num(r.cal3) + num(r.cal2), t), pct(num(r.cal3), t)]};
  return `<div class="sub-titulo">Recepcion</div>` + tabla(cabeza, [fila]);
}

// Defender un ataque no es recibir un saque, aunque se anoten igual: se
// entrenan aparte y un mismo jugador puede ser bueno en una y malo en la otra.
// Por eso va en su propia tabla y no como una fila mas de la de recepcion.

function tablasDefensa(j){
  const d = j.defensa.total, t = num(d.defensas);
  const cabeza = ["Defensas", "Cal. 3", "Cal. 2", "Cal. 1", "Cal. 0",
                  "Pase al otro lado", "% Positiva (2+3)", "% Perfecta (3)"];
  const filas = [{total: true, celdas: [t,
    conParte(d.cal3, t), conParte(d.cal2, t), conParte(d.cal1, t), conParte(d.cal0, t),
    conParte(d.pase, t),
    pct(num(d.cal3) + num(d.cal2), t), pct(num(d.cal3), t)]}];
  return `<div class="sub-titulo">Defensa</div>` + tabla(cabeza, filas,
    "La calidad 0 incluye la pelota que no se pudo jugar, que es punto para el " +
    "rival; un pase al otro lado deja la pelota del otro lado y el punto sigue.");
}

function tablasAtaque(j){
  const t = j.ataque.total;
  const filaAtaque = (etiqueta, a) => ({celdas: [etiqueta, num(a.ataques), num(a.punto),
    num(a.defendido), num(a.fuera), pct(num(a.punto), num(a.ataques)),
    pct(num(a.defendido), num(a.ataques)), pct(num(a.fuera), num(a.ataques))]});

  const filas = [Object.assign(filaAtaque("Partido", t), {total:true})]
    .concat(j.ataque.por_zona.map(z => filaAtaque("Zona " + z.zona, z)));

  // Cada celda de la matriz lleva los ataques y que porcentaje fue punto: 27
  // ataques hacia la 6 no dicen nada hasta saber cuantos entraron. Sin
  // ataques no se muestra un porcentaje, que seria dividir por cero.
  const celdaMatriz = (ataques, puntos) =>
    ataques ? `${ataques} · ${pct(puntos, ataques)}` : "0";

  const dirs = j.ataque.direcciones;
  const suma = lista => lista.reduce((a, b) => a + num(b), 0);
  const filasMatriz = j.ataque.matriz_direccion.map(f => ({
    celdas: ["Zona " + f.zona]
      .concat(f.valores.map((v, i) => celdaMatriz(num(v), num((f.puntos || [])[i]))),
              [celdaMatriz(suma(f.valores), suma(f.puntos || []))])}));

  const totales = dirs.map((_, i) =>
    suma(j.ataque.matriz_direccion.map(f => f.valores[i])));
  const totalesPunto = dirs.map((_, i) =>
    suma(j.ataque.matriz_direccion.map(f => (f.puntos || [])[i])));
  filasMatriz.push({total:true, celdas: ["TOTAL"]
    .concat(totales.map((v, i) => celdaMatriz(v, totalesPunto[i])),
            [celdaMatriz(suma(totales), suma(totalesPunto))])});

  return `<div class="sub-titulo">Ataque <span class="aclara">totales y por zona de origen</span></div>` +
    tabla(["", "Ataques", "Punto", "Defendido", "Fuera", "% Punto", "% Defendido", "% Fuera"], filas) +
    `<div class="sub-titulo">Ataque por zona de origen y direccion
      <span class="aclara">ataques · % que fueron punto</span></div>` +
    tabla(["Zona"].concat(dirs.map(d => "Hacia " + d), ["Total"]), filasMatriz) +
    tablaAtaquePorCalidad(j) + tablaAtaquePorTipo(j);
}

// Lo que hizo con cada pelota que le armaron: no es lo mismo fallar una A-
// que una A+.
function tablaAtaquePorCalidad(j){
  const filas = (j.ataque.por_calidad_armado || []).filter(f => num(f.ataques));
  if(!filas.length) return "";
  return `<div class="sub-titulo">Ataque segun la calidad del armado</div>` + tabla(
    ["Armado", "Ataques", "Punto", "Defendido", "Fuera", "% Punto", "Eficacia"],
    filas.map(f => ({celdas: [f.calidad, f.ataques, f.punto, f.defendido, f.fuera,
      pct(num(f.punto), num(f.ataques)), pct(num(f.punto) - num(f.fuera), num(f.ataques))]})),
    "Solo ataques que vienen de un armado. Eficacia = (puntos - errores) / ataques.");
}

// Tipo de resolucion por direccion final: un porcentaje muy alto en una
// sola direccion es un patron que el rival puede leer.
function tablaAtaquePorTipo(j){
  const tipos = j.ataque.por_tipo || [];
  if(!tipos.length) return "";
  const dirs = j.ataque.direcciones;
  const suma = lista => lista.reduce((a, b) => a + num(b), 0);
  const celda = (n, p) => n ? `${n} · ${pct(p, n)}` : "0";
  const fila = (etiqueta, valores, puntos, total) => ({total, celdas: [etiqueta]
    .concat(valores.map((v, i) => celda(num(v), num(puntos[i]))),
            [celda(suma(valores), suma(puntos)),
             pct(Math.max(...valores.map(num)), suma(valores))])});
  const filas = tipos.map(t => fila(t.tipo, t.valores, t.puntos));
  if(tipos.length > 1){
    const valores = dirs.map((_, i) => suma(tipos.map(t => t.valores[i])));
    const puntos = dirs.map((_, i) => suma(tipos.map(t => t.puntos[i])));
    filas.push(fila("TOTAL", valores, puntos, true));
  }
  return `<div class="sub-titulo">Tipo de ataque y direccion final
      <span class="aclara">ataques · % que fueron punto</span></div>` + tabla(
    ["Tipo"].concat(dirs.map(d => "Hacia " + d), ["Total", "% dir. mas usada"]), filas,
    "Un % muy alto en una sola direccion es un patron previsible. El block-out se " +
    "toma del resultado; \"Sin tipo\" son los ataques cargados sin marcar potente o colocado.");
}

function tablasLibres(j){
  return `<div class="sub-titulo">Libres y toques <span class="aclara">no cuentan como ataque</span></div>` +
    tabla(["", "Total", "Punto", "Block Out", "Sigue", "Malo", "% Punto"],
      j.libres.map(l => ({celdas: [l.tipo, l.total, l.punto, l.usado, l.sigue, l.malo,
        pct(num(l.punto) + num(l.usado), num(l.total))]})),
      "% Punto incluye los que usaron el bloqueo (Block Out).");
}

function tablasSaque(j){
  const s = j.saque, t = s.total;
  const fila = (etiqueta, d, total) => ({total, celdas: [etiqueta, num(d.saques), num(d.as),
    num(d.error), num(d.saques) - num(d.as) - num(d.error),
    pct(num(d.as), num(d.saques)), pct(num(d.error), num(d.saques))]});
  const filas = s.por_tipo.filter(d => num(d.saques)).map(d => fila(d.tipo, d))
    .concat([fila("TOTAL", t, true)]);
  const estrategias = (s.estrategias || []).map(e => {
    const recibidos = num(e.rec3) + num(e.rec2) + num(e.rec1) + num(e.rec0_pase);
    return {celdas: [`De ${e.par}`, e.saques, e.as, e.error, e.rec3, e.rec2, e.rec1,
      e.rec0_pase, pct(num(e.rec3), recibidos), pct(num(e.ganados), num(e.saques))]};
  });
  return `<div class="sub-titulo">Saque <span class="aclara">normal y de potencia</span></div>` +
    tabla(["", "Saques", "As", "Error", "En juego", "% As", "% Error"], filas) +
    (estrategias.length ? `<div class="sub-titulo">Estrategia de saque
       <span class="aclara">zona de origen → zona objetivo</span></div>` +
     tabla(["Estrategia", "Saques", "As", "Error", "Rec 3", "Rec 2", "Rec 1", "Rec 0 / pase",
            "% Rec 3 rival", "% Puntos ganados"], estrategias,
       "% Rec 3 rival bajo = el saque complica. % Puntos ganados: el rally lo gano su equipo.") : "");
}

function tablasCalidadArmado(j){
  const c = j.armado_calidad, t = c.total;
  const calificados = ["A+", "A0", "A-", "AX"].reduce((s, k) => s + num(t[k]), 0);
  const filaTotal = {total: true, celdas: ["TOTAL", t["A+"], t["A0"], t["A-"], t["AX"],
    calificados, pct(num(t["A+"]), calificados), pct(num(t["A-"]), calificados),
    pct(num(t["AX"]), calificados), t["Sin calificar"]]};
  const filasZona = (c.por_zona || []).map(z => {
    const n = num(z["A+"]) + num(z["A0"]) + num(z["A-"]);
    return {celdas: ["Zona " + z.zona, z["A+"], z["A0"], z["A-"], "—", n,
      pct(num(z["A+"]), n), pct(num(z["A-"]), n), "—", z["Sin calificar"]]};
  });
  return `<div class="sub-titulo">Calidad del armado <span class="aclara">por zona armada</span></div>` +
    tabla(["Zona", "A+", "A0", "A-", "AX", "Calificados", "% A+", "% A-", "% AX", "Sin calificar"],
      filasZona.concat([filaTotal]),
      "A+: atacante en situacion favorable. A0: normal. A-: dificil, previsible o fuera de " +
      "sistema. AX: error de armado (no tiene zona: la armada mala termina el punto).");
}

function tablasRotacion(j){
  const c = j.rotacion.en_cancha;
  if(!num(c.jugados)) return "";
  return `<div class="sub-titulo">Con el en cancha</div>` + tabla(
      ["Puntos jugados", "Ganados", "% Ganados", "Sacando", "% Break", "Recibiendo", "% Side-out"],
      [{celdas: [c.jugados, c.ganados, pct(num(c.ganados), num(c.jugados)),
        c.saque_jugados, pct(num(c.saque_ganados), num(c.saque_jugados)),
        c.rec_jugados, pct(num(c.rec_ganados), num(c.rec_jugados))]}],
      "Puntos del equipo con el en la formacion (sin contar cuando lo reemplaza el libero). " +
      "Break: puntos ganados sacando. Side-out: puntos ganados recibiendo.");
}


function tablasArmado(j){
  // Aca se llega estando marcado como armador (por el _S o a mano) pero sin
  // haber armado nada en lo cargado. Antes decia "este jugador no es
  // armador", que contradice a la etiqueta que se ve dos lineas mas arriba.
  if(!j.armado) return `<div class="sub-titulo">Armado
    <span class="aclara">sin armados en lo cargado</span></div>
    <p class="nota" style="margin-top:0">Esta marcado como armador, pero no armo
    ninguna pelota en los partidos que hay cargados.</p>`;

  const a = j.armado;
  const filas = a.por_zona.map(z => ({celdas: ["Zona " + z.zona, z.armados,
                                               pct(z.armados, a.total)]}));
  filas.push({total:true, celdas: ["TOTAL", a.total, pct(a.total, a.total)]});

  const filasMatriz = a.matriz_calidad.map(f => ({
    celdas: ["Calidad " + f.calidad].concat(f.valores,
      [f.valores.reduce((x, y) => x + y, 0)])}));
  const totales = a.zonas.map((_, i) =>
    a.matriz_calidad.reduce((t, f) => t + num(f.valores[i]), 0));
  filasMatriz.push({total:true, celdas: ["TOTAL"].concat(totales,
    [totales.reduce((x, y) => x + y, 0)])});

  return `<div class="sub-titulo">Armado <span class="aclara">${esc(a.total)} armados</span></div>` +
    tabla(["Zona armada", "Armados", "% del total"], filas) +
    `<div class="sub-titulo">Calidad de la recepcion y zona armada</div>` +
    tabla(["Recepcion"].concat(a.zonas.map(z => "Zona " + z), ["Total"]), filasMatriz);
}

// Grafico a mano: dos lineas sobre una grilla de 0 a 100%. Sin librerias
// porque en la cancha puede no haber internet, y una linea de tres puntos no
// justifica traer una.
function graficoEvolucion(j){
  const datos = j.evolucion;
  const ancho = 320, alto = 150, izq = 34, der = 10, arr = 12, aba = 24;
  const x = i => izq + (datos.length === 1 ? (ancho - izq - der) / 2
    : i * (ancho - izq - der) / (datos.length - 1));
  const y = f => arr + (1 - f) * (alto - arr - aba);

  const grilla = [0, 0.25, 0.5, 0.75, 1].map(f =>
    `<line x1="${izq}" y1="${y(f).toFixed(1)}" x2="${ancho - der}" y2="${y(f).toFixed(1)}"
           stroke="#2b3543" stroke-width="1"/>
     <text x="${izq - 6}" y="${(y(f) + 3.5).toFixed(1)}" fill="#93a1b5" font-size="9"
           text-anchor="end">${Math.round(f * 100)}%</text>`).join("");

  const linea = (clave, color) => {
    const puntos = datos.map((d, i) => `${x(i).toFixed(1)},${y(d[clave]).toFixed(1)}`).join(" ");
    const pelotas = datos.map((d, i) =>
      `<circle cx="${x(i).toFixed(1)}" cy="${y(d[clave]).toFixed(1)}" r="3.2" fill="${color}"/>`).join("");
    return `<polyline points="${puntos}" fill="none" stroke="${color}" stroke-width="2"
             stroke-linejoin="round"/>${pelotas}`;
  };

  // etiquetas cortas: "vs UVC (2026-09-04)" no entra debajo del grafico
  const corta = t => String(t).replace(/^vs\s*/, "").replace(/\s*\(.*\)$/, "");
  const ejeX = datos.map((d, i) =>
    `<text x="${x(i).toFixed(1)}" y="${alto - 8}" fill="#93a1b5" font-size="10"
           text-anchor="middle">${esc(corta(d.etiqueta))}</text>`).join("");

  return `<div class="grafico">
    <svg viewBox="0 0 ${ancho} ${alto}" role="img"
         aria-label="Evolucion por set del jugador ${esc(j.dorsal)}">
      ${grilla}${ejeX}
      ${linea("recepcion_positiva", "#4aa3ff")}
      ${linea("ataque_punto", "#ffc857")}
    </svg>
    <div class="leyenda">
      <span><i style="background:#4aa3ff"></i>% positiva de recepcion</span>
      <span><i style="background:#ffc857"></i>% punto de ataque</span>
    </div></div>`;
}

// Contra que se compara a alguien. Dos reglas, las dos por el mismo motivo:
// que la comparacion sea entre pares.
//
//   1) El promedio de cada cosa sale SOLO de los que la hacen. Lo calcula el
//      servidor (ver estadisticas_jugadores._promedio_equipo) y viene con
//      cuantos jugadores lo componen.
//
//   2) Las filas dependen de que juega. Un libero no ataca ni bloquea -- no
//      es que le vaya mal, es que no puede, es falta -- y al armador no se le
//      miden recepciones. Ponerles un 0 ahi no es un dato, es ruido que
//      ademas los hace ver peor de lo que son.
const GRUPOS_COMPARACION = [
  {clave: "recepciones", quienes: "reciben",
   filas: [["Recepciones", "recepciones", false],
           ["% Positiva (2+3)", "positiva", true],
           ["% Perfecta (3)", "perfecta", true]]},
  {clave: "defensas", quienes: "defienden",
   filas: [["Defensas", "defensas", false],
           ["% Defensa positiva", "defensa_positiva", true]]},
  {clave: "ataques", quienes: "atacan",
   filas: [["Ataques", "ataques", false],
           ["% Punto de ataque", "punto", true]]},
  {clave: "bloqueos_punto", quienes: "bloquean",
   filas: [["Bloqueos punto", "bloqueos_punto", false]]},
  {clave: "armados", quienes: "arman",
   filas: [["Armados", "armados", false]]},
];

function leAplica(grupo, j){
  if(grupo.clave === "recepciones") return !j.armador;
  if(grupo.clave === "ataques" || grupo.clave === "bloqueos_punto") return !esLibero(j);
  if(grupo.clave === "armados") return !!j.armador;
  return true;      // defender lo hacen todos, tambien el libero
}

function tablaComparacion(j){
  const i = j.indicadores, e = j.promedio_equipo || {};
  const grupos = GRUPOS_COMPARACION.filter(g => {
    if(!leAplica(g, j)) return false;
    const cuantos = (e[g.clave] || {}).jugadores || 0;
    if(!cuantos) return false;              // nadie del equipo la hace: 0 contra 0
    // si el unico que la hace es el, el promedio ES el: no hay con quien
    // compararlo y la fila solo diria "+0.0"
    return !(cuantos === 1 && (i[g.clave] || 0) > 0);
  });
  if(!grupos.length) return "";

  const filas = grupos.flatMap(g => g.filas
    // un porcentaje sobre cero intentos no es un rendimiento, es una
    // ausencia: "0% de efectividad, -30 pp" de alguien que no ataco nunca se
    // lee como que ataca mal. El conteo si queda, que es lo que lo dice.
    .filter(([, , esPct]) => !esPct || (i[g.clave] || 0) > 0)
  ).map(([titulo, clave, esPct]) => {
    const propio = i[clave] || 0, equipo = (e[clave] || {}).valor || 0;
    return {celdas: [titulo,
      esPct ? pctDe(propio) : propio,
      esPct ? pctDe(equipo) : equipo,
      // sin redondear, 27 - 17.1 sale "9.899999999999999"
      esPct ? ((propio - equipo) * 100).toFixed(1) + " pp"
            : (propio - equipo > 0 ? "+" : "") + (propio - equipo).toFixed(1)]};
  });

  const cuantos = grupos.map(g => `${e[g.clave].jugadores} ${g.quienes}`).join(", ");
  // solo lo que NO PUEDE hacer por su posicion. El armado de los que no son
  // armadores tambien se esconde, pero por otro motivo (no tiene sentido
  // medirle el armado a un central), y meterlo en la misma frase mentiria.
  const nopuede = esLibero(j)
    ? " A un libero no se le listan ataques ni bloqueos: no es que le vayan mal, es que no los hace."
    : (j.armador ? " Al armador no se le listan las recepciones." : "");
  return `<div class="sub-titulo">El jugador contra los que hacen lo mismo</div>` +
    tabla(["Metrica", "Jugador", "Promedio del equipo", "Diferencia"], filas,
      `Cada promedio sale solo de los que hacen esa accion (${cuantos}), no de todo ` +
      `el plantel: repartido entre los que nunca reciben, el promedio de recepcion ` +
      `da la mitad y cualquier receptor parece estar muy por encima del equipo.` +
      nopuede);
}

function notaAlPie(j){
  const armado = j.armado;
  const faltaMatriz = armado && armado.con_recepcion < armado.total;
  return `<div class="pie">
    <h3>Como leer estos numeros</h3>
    <ul>
      <li>Todo sale de los partidos guardados en Datos/, sumados en el momento.
      Al guardar un partido nuevo, aparece aca sin ningun paso extra.</li>
      ${faltaMatriz ? `<li>La tabla de calidad de recepcion suma
        ${esc(armado.con_recepcion)} de los ${esc(armado.total)} armados: solo entran los
        que vienen de una recepcion de saque. El resto son de transicion, despues de
        una defensa, donde no hay calidad que anotar.</li>` : ""}
      <li>Los jugadores se identifican por equipo y dorsal, no por dorsal solo:
      el 3 de un equipo y el 3 del rival son personas distintas.</li>
    </ul>
    <h3>Que falta agregarle al motor</h3>
    <ul>
      <li class="falta">Saque por jugador: ases y errores propios. El volcado guarda
      el saque de cada punto pero no lo suma por sacador.</li>
      <li class="falta">Ataque abierto por set. Hoy solo la recepcion y el armado se
      guardan set por set.</li>
      <li>Nombres: el volcado sigue guardando numeros, que es lo que se grita en
      la cancha. Los nombres se anotan con el boton "Nombres" de aca arriba y se
      usan solo para mirar; el .txt y el Excel no cambian.</li>
    </ul></div>`;
}

// ======================================================================
// Arranque
// ======================================================================
// La pestana por defecto es Cargar; el hash solo se respeta si esta puesto,
// que es el caso de recargar la pagina sin querer perder donde se estaba.
// La tabla de la notacion se baja antes de pintar: sin ella el modo visual no
// sabe que ofrecer. Es un archivo fijo, asi que se pide una sola vez.
Promise.all([revisarCandado(), traerNotacion()])
  .then(arrancarPartido).then(r => {
    avisarDelServidor(r.almacenamiento);
    pintar(r.estado);
    irA(location.hash.replace("#", "") || "equipo", false);
  });

// El partido lo guarda este navegador (ver 2a), asi que al abrir la pagina se
// manda lo guardado y el motor lo rearma. Es el mismo camino de siempre: el
// partido se rehace desde la primera linea en cada pedido, aca tambien.
//
// La primera vez que se abre la pagina despues del cambio todavia no hay nada
// guardado en este navegador. Ahi se mira la sesion compartida, que es donde
// vivia el partido antes: si habia uno a medio cargar se lo trae en vez de
// perderlo. Pasa una sola vez, porque desde ese momento ya hay algo guardado
// aca, aunque sea una lista vacia.
async function arrancarPartido(){
  const guardadas = lineasGuardadas();
  if(guardadas !== null){
    lineas = guardadas;
    return apiPartido("/api/estado");
  }
  const r = await api("/api/estado");       // GET: la sesion compartida
  anotarLineas(r.estado);
  recordarLineas();                          // desde ahora el partido es de aca
  if(lineas.length){
    mostrarMensaje("Este partido estaba a medio cargar en el servidor y se paso a "
                   + "esta pantalla. Ahora cada pantalla carga el suyo.", true);
  }
  return r;
}

// Alojado, la carpeta del proyecto es de solo lectura y lo unico escribible es
// un /tmp que se borra solo: si no hay un almacenamiento de verdad detras, lo
// que se guarde se va a perder. El servidor lo dice en /api/estado y aca se
// muestra arriba de todo, que es donde se mira antes de empezar a cargar.
function avisarDelServidor(info){
  const caja = $("#avisoServidor");
  if(!caja) return;
  const avisos = (info && info.avisos) || [];
  caja.textContent = avisos.join(" ");
  caja.hidden = avisos.length === 0;
}
