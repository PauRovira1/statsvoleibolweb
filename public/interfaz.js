/* Interfaz web de estadisticas de voley.
 *
 * Tres pestanas sobre la misma pagina: Cargar (la pantalla de la cancha),
 * Partidos (buscar y abrir lo que ya esta en disco) y Jugadores (maqueta).
 * Sin dependencias y sin nada remoto: al costado de la cancha puede no haber
 * internet, asi que hasta el grafico esta dibujado a mano.
 *
 * La fuente de verdad del partido en curso es el servidor. Aca no se guarda
 * estado del partido: se pinta lo que devuelve /api/estado.
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

async function api(ruta, datos){
  const cabeceras = token ? {"X-Clave": token} : {};
  if(datos) cabeceras["Content-Type"] = "application/json";
  const opciones = datos
    ? {method:"POST", headers:cabeceras, body:JSON.stringify(datos)}
    : {headers:cabeceras};
  const r = await fetch(ruta, opciones);
  const respuesta = await r.json();
  // el servidor se reinicio, o paso el token de otra sesion: vuelve el candado
  if(r.status === 401 || respuesta.clave) olvidarToken();
  return respuesta;
}

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

function tabla(encabezados, filas, notaAlPie){
  const cabeza = encabezados.map((h, i) =>
    `<th class="${i ? "num" : ""}">${esc(h)}</th>`).join("");
  const cuerpo = filas.map(fila => {
    const celdas = fila.celdas.map((c, i) =>
      `<td class="${i ? "num" : ""}">${esc(c)}</td>`).join("");
    return `<tr class="${fila.total ? "total" : ""}">${celdas}</tr>`;
  }).join("");
  return `<div class="tabla"><table><thead><tr>${cabeza}</tr></thead>
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
// El orden es el de las pestanas en pantalla. Cargar va ultima porque es la
// que menos se toca: pide la contraseña y se usa una vez por partido, mientras
// que mirar un informe o la ficha de un jugador se hace todo el tiempo. Igual
// sigue siendo la que se abre al entrar, que es lo que hace falta en la cancha.
const VISTAS = ["partidos", "jugadores", "cargar"];
let vistaActual = "cargar";

function irA(vista, tocarHash = true){
  if(!VISTAS.includes(vista)) vista = "cargar";
  vistaActual = vista;
  VISTAS.forEach(v => { $("#vista-" + v).hidden = (v !== vista); });
  $$(".pestana").forEach(b => b.classList.toggle("activa", b.dataset.vista === vista));
  if(tocarHash && location.hash !== "#" + vista) location.hash = vista;
  if(vista === "cargar") foco();
  if(vista === "partidos") entrarAPartidos();
  if(vista === "jugadores") pintarJugadores();
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
  // el partido pudo avanzar desde otra pantalla mientras este estaba bloqueado
  const estado = await api("/api/estado");
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

  // La "x" hace tres cosas distintas segun donde se este, y desde afuera se
  // ven iguales. Reabrir un set es la unica forma de arreglar una rotacion mal
  // cargada al empezarlo, asi que tiene que decirlo.
  const btnX = $("[data-enviar='x']");
  if(btnX) btnX.textContent = ({
    jugada: "x · deshacer jugada",
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

  $("#cambios").innerHTML = e.cambios.length
    ? `<div class="tabla"><table><tr><th>Set</th><th>Equipo</th><th>Entra</th><th>Sale</th><th>Zona</th></tr>` +
      e.cambios.map(c => `<tr><td>${esc(c.set)}</td><td>${esc(e.nombres[c.equipo])}</td>
        <td class="zona ${c.armador ? "armador" : ""}">${esc(c.entra)}${c.armador ? " S" : ""}</td>
        <td class="zona">${esc(c.sale)}</td><td>${esc(c.zona)}</td></tr>`).join("") + `</table></div>`
    : `<p class="nota" style="margin:0">Sin cambios.</p>`;
}

async function enviar(linea){
  if(!linea && linea !== "") return;
  const r = await api("/api/enviar", {linea});
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
  const r = await api(ruta, datos || {});
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
  accion("/api/reiniciar");
});
$("#btnPegar").addEventListener("click", () => accion("/api/cargar", {texto: $("#pegar").value}));
$("#btnStats").addEventListener("click", async () => {
  const r = await api("/api/estadisticas");
  $("#stats").textContent = r.texto || "—";
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
  filtrar();
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

  const filas = PARTIDOS.filter(p => {
    if(texto && !`${p.equipo} ${p.rival} ${p.fecha}`.toLowerCase().includes(texto)) return false;
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
["#busca", "#filtroEquipo", "#filtroDesde", "#filtroHasta", "#filtroInforme"]
  .forEach(sel => ["input", "change"].forEach(ev =>
    $(sel).addEventListener(ev, filtrar)));
$("#btnLimpiar").addEventListener("click", () => {
  $("#busca").value = ""; $("#filtroEquipo").value = "";
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

async function abrirPartido(id){
  const fila = PARTIDOS.find(p => p.id === id);
  if(!fila) return;
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
];

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
  const boton = $("#btnACargar");
  if(!boton) return;
  boton.addEventListener("click", async () => {
    const chip = $("#chipCargar");
    if(!chip.hidden && !confirm("Hay un partido en curso sin guardar. Se reemplaza por este?")) return;
    boton.disabled = true;
    avisoDetalle("Leyendo el volcado…", true);
    const respuesta = await fetch(urlDescarga(fila.volcado, "txt"));
    const texto = await respuesta.text();
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
  const lineas = texto.split(/\r?\n/);
  const arranque = lineas.findIndex(l => l.trim() === "=== Jugadas cargadas ===");
  const desde = arranque < 0 ? 0 : arranque + 1;
  const jugadas = [];
  for(let i = desde; i < lineas.length; i++){
    if(lineas[i].startsWith("===")) break;
    jugadas.push(lineas[i]);
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

  const equipos = p.orden_equipos;
  partes.push(`<div class="selector" id="selectorEquipo">` + equipos.map((e, i) =>
    `<button data-equipo="${esc(e)}" class="${i ? "" : "activa"}">${esc(e)}</button>`).join("") +
    `</div><div id="statsEquipo"></div>`);
  return partes.join("");
}

function cablearSelectorEquipo(p){
  const pintarEquipo = nombre => {
    $("#statsEquipo").innerHTML = tablasDeEquipo(nombre, p.equipos[nombre]);
    $$("#selectorEquipo button").forEach(b =>
      b.classList.toggle("activa", b.dataset.equipo === nombre));
  };
  $$("#selectorEquipo button").forEach(b =>
    b.addEventListener("click", () => pintarEquipo(b.dataset.equipo)));
  if(p.orden_equipos.length) pintarEquipo(p.orden_equipos[0]);
}

function tablasDeEquipo(nombre, datos){
  if(!datos) return `<p class="nota">El volcado no trae estadisticas de ${esc(nombre)}.</p>`;
  const FASES = ["K1", "K2", "K3", "Saque", "Sin fase"];
  const partes = [];

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
      return {celdas: [j, t, num(r.cal3), num(r.cal2), num(r.cal1), num(r.cal0), num(r.pase),
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
      return {celdas: [j, num(a.totales), num(a.puntos), num(a.defendidos), num(a.fuera),
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
    const filas = bloqueadores.map(j => ({celdas: [j, num(datos.bloqueos_jugador[j]),
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

let planteles = null;
let equipoElegido = null;
let dorsalElegido = null;

async function pintarJugadores(){
  const caja = $("#jugadores");
  if(planteles === null){
    caja.innerHTML = `<p class="nota">Leyendo los partidos guardados…</p>`;
    const r = await api("/api/jugadores");
    avisarDelServidor(r.almacenamiento);
    planteles = r.ok ? r : {equipos: [], descartados: []};
  }
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

  if(!planteles.equipos.length){
    caja.innerHTML = `<p class="nota">Todavia no hay partidos guardados.</p>`;
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
      `<button data-dorsal="${esc(j.dorsal)}" class="${j.dorsal === dorsalElegido ? "activa" : ""}"
        title="${esc(j.partidos)} partidos">${esc(j.dorsal)}${j.armador ? " ·S" : ""}</button>`).join("") +
    `</div>`;

  const cabecera = selectorEquipos + selectorDorsales;
  if(dorsalElegido == null){
    caja.innerHTML = cabecera + `<p class="nota">Sin jugadores en este equipo.</p>`;
    engancharSelectores();
    return;
  }

  const r = await api(`/api/jugador?equipo=${encodeURIComponent(equipoElegido)}` +
                      `&dorsal=${encodeURIComponent(dorsalElegido)}`);
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
        <div class="rol">${j.armador ? "Armador" : "No armador"} · ${esc(j.equipo)}</div>
        <div class="datos">${esc(j.partidos)} partido(s) cargado(s)</div>
      </div>
    </div>
    ${indicadoresJugador(j)}
    ${tablaPorPartido(j)}
    ${j.indicadores.recepciones ? tablasRecepcion(j) : ""}
    ${j.indicadores.ataques ? tablasAtaque(j) : ""}
    ${j.armador ? tablasArmado(j) : ""}
    ${j.evolucion.length > 1 ? `<div class="sub-titulo">Partido a partido</div>` +
                               graficoEvolucion(j) : ""}
    <div class="sub-titulo">El jugador contra el promedio del equipo</div>
    ${tablaComparacion(j)}
    ${notaAlPie(j)}`;

  engancharSelectores();
}

function engancharSelectores(){
  $$("#selectorEquipo button").forEach(b => b.addEventListener("click", () => {
    equipoElegido = b.dataset.equipo;
    dorsalElegido = null;
    pintarJugadores();
  }));
  $$("#selectorDorsal button").forEach(b => b.addEventListener("click", () => {
    dorsalElegido = b.dataset.dorsal;
    pintarJugadores();
  }));
}

// Una linea por partido: es lo que deja ver si mejora o empeora, que en un
// acumulado de varios partidos se pierde.
function tablaPorPartido(j){
  const armador = j.armador;
  const cabeza = armador
    ? ["Partido", "Armados", "Del equipo", "% que armo el", "Ataques", "Bloqueos"]
    : ["Partido", "Recepciones", "% Positiva", "Ataques", "% Punto", "Eficacia", "Bloqueos"];
  const filas = j.por_partido.map(p => ({celdas: armador
    ? [p.etiqueta, p.armados, p.armados_equipo, pct(p.armados, p.armados_equipo),
       p.ataques, p.bloqueos]
    : [p.etiqueta, p.recepciones, pctDe(p.positiva), p.ataques, pctDe(p.punto),
       pctDe(p.eficacia), p.bloqueos]}));
  return `<div class="sub-titulo">Resumen por partido</div>` + tabla(cabeza, filas,
    armador ? null : "Eficacia = (puntos - errores) / ataques.");
}

function indicadoresJugador(j){
  const i = j.indicadores;
  const casillas = [
    ["Recepciones", i.recepciones, ""],
    ["% Positiva", pctDe(i.positiva), "calidad 2+3"],
    ["% Perfecta", pctDe(i.perfecta), "calidad 3"],
    ["Ataques", i.ataques, ""],
    ["% Punto", pctDe(i.punto), "de sus ataques"],
    ["Bloqueos punto", i.bloqueos_punto, ""]
  ];
  return `<div class="indicadores">` + casillas.map(([titulo, valor, base]) =>
    `<div class="indicador"><div class="valor">${esc(valor)}</div>
     <div class="titulo">${esc(titulo)}</div>
     ${base ? `<div class="base">${esc(base)}</div>` : ""}</div>`).join("") + `</div>`;
}

function filaRecepcion(etiqueta, r){
  const t = num(r.recepciones);
  return {celdas: [etiqueta, t, num(r.cal3), num(r.cal2), num(r.cal1), num(r.cal0),
                   num(r.pase), pct(num(r.cal3) + num(r.cal2), t), pct(num(r.cal3), t)]};
}

function tablasRecepcion(j){
  const cabeza = ["", "Recepciones", "Cal. 3", "Cal. 2", "Cal. 1", "Cal. 0",
                  "Pase al otro lado", "% Positiva (2+3)", "% Perfecta (3)"];
  const filas = [Object.assign(filaRecepcion("Partido", j.recepcion.total), {total:true})]
    .concat(j.recepcion.por_set.map(s => filaRecepcion("Set " + s.set, s)));
  return `<div class="sub-titulo">Recepcion</div>` + tabla(cabeza, filas);
}

function tablasAtaque(j){
  const t = j.ataque.total;
  const filaAtaque = (etiqueta, a) => ({celdas: [etiqueta, num(a.ataques), num(a.punto),
    num(a.defendido), num(a.fuera), pct(num(a.punto), num(a.ataques)),
    pct(num(a.defendido), num(a.ataques)), pct(num(a.fuera), num(a.ataques))]});

  const filas = [Object.assign(filaAtaque("Partido", t), {total:true})]
    .concat(j.ataque.por_zona.map(z => filaAtaque("Zona " + z.zona, z)));

  const dirs = j.ataque.direcciones;
  const filasMatriz = j.ataque.matriz_direccion.map(f => ({
    celdas: ["Zona " + f.zona].concat(f.valores,
      [f.valores.reduce((a, b) => a + b, 0)])}));
  const totales = dirs.map((_, i) =>
    j.ataque.matriz_direccion.reduce((a, f) => a + num(f.valores[i]), 0));
  filasMatriz.push({total:true, celdas: ["TOTAL"].concat(totales,
    [totales.reduce((a, b) => a + b, 0)])});

  return `<div class="sub-titulo">Ataque <span class="aclara">totales y por zona de origen</span></div>` +
    tabla(["", "Ataques", "Punto", "Defendido", "Fuera", "% Punto", "% Defendido", "% Fuera"], filas) +
    `<div class="sub-titulo">Ataque por zona de origen y direccion
      <span class="aclara">ataques, no puntos</span></div>` +
    tabla(["Zona"].concat(dirs.map(d => "Hacia " + d), ["Total"]), filasMatriz);
}

function tablasArmado(j){
  if(!j.armado) return `<div class="sub-titulo">Armado
    <span class="aclara">este jugador no es armador</span></div>
    <p class="nota" style="margin-top:0">Sin armados registrados.</p>`;

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

function tablaComparacion(j){
  const i = j.indicadores, e = j.promedio_equipo;
  const filas = [
    ["Recepciones", i.recepciones, e.recepciones, false],
    ["% Positiva (2+3)", i.positiva, e.positiva, true],
    ["% Perfecta (3)", i.perfecta, e.perfecta, true],
    ["Ataques", i.ataques, e.ataques, false],
    ["% Punto de ataque", i.punto, e.punto, true],
    ["Bloqueos punto", i.bloqueos_punto, e.bloqueos_punto, false]
  ].map(([titulo, propio, equipo, esPct]) => ({celdas: [titulo,
    esPct ? pctDe(propio) : propio,
    esPct ? pctDe(equipo) : equipo,
    esPct ? ((propio - equipo) * 100).toFixed(1) + " pp"
          : (propio - equipo > 0 ? "+" : "") + (propio - equipo)]}));
  return tabla(["Metrica", "Jugador", "Promedio del equipo", "Diferencia"], filas,
    "Promedio del equipo: el mismo calculo sobre todos los jugadores del equipo.");
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
      <li class="falta">Nombres: el volcado guarda numeros, no nombres.</li>
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
  .then(() => api("/api/estado")).then(r => {
    avisarDelServidor(r.almacenamiento);
    pintar(r.estado);
    irA(location.hash.replace("#", "") || "cargar", false);
  });

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
