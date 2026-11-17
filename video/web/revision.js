/* Pantalla de revision: marcar armadas a mano, corregirlas y (desde la etapa
 * 5) aceptar o descartar las que proponga la maquina.
 *
 * La pantalla no decide nada: manda operaciones al servidor ("marcar en tal
 * instante", "zona 4") y pinta lo que vuelve. Como se juntan propuestas y
 * decisiones lo sabe fusion.py; como se arma una decision, decisiones.py.
 *
 * Las operaciones salen de a una y en orden (ver operar): cada una lleva la
 * "edicion" que devolvio la anterior, que es como el servidor sabe que nadie
 * guardo en el medio.
 *
 * Dos formas de estar:
 *   - marcando: el video corre suelto. M lo frena y marca en ese cuadro, y la
 *     marca queda elegida mientras el video esta quieto: se la ajusta con las
 *     flechas y M, se le da zona. Al seguir reproduciendo se suelta.
 *   - revisando: se eligio una armada de la lista o de la linea, y su recorte
 *     se repite en bucle hasta soltarla (Esc) o pasar a otra.
 */
"use strict";

const nombre = parametro("v");
const video = $("#video");
const VELOCIDADES = [0.25, 0.5, 1, 1.5, 2, 4];
const CAMPOS = {armador: $("#armador"), etiquetas: $("#etiquetas"), nota: $("#nota")};

let datos = null;          // el video: titulo, duracion, fps
let edicion = 0;
let sets = [];
let armadas = [];
let sePuedeDeshacer = false;
let claveActiva = null;
let enBucle = false;
let armadorFijo = recordado(`armador.${nombre}`, null);
let formSet = null;        // {desde, set, lado} mientras se elige un set
let cola = Promise.resolve();
let enCamino = 0;          // operaciones mandadas sin respuesta
// La M mandada que todavia no volvio: {clave} se llena cuando vuelve. Lo que
// se toca mientras tanto (M y enseguida 4) va a esa marca, aunque despues se
// suelte antes de que el servidor conteste.
let marcaEnCamino = null;
// Cambia cada vez que la persona elige, suelta o marca: una marca que vuelve
// cuando la persona ya esta en otra cosa se guarda, pero no se elige.
let ficha = 0;
let sinConexion = false;   // la ultima operacion no llego al servidor
let campoSucio = false;    // algo escrito en un campo que todavia no se guardo

// ----------------------------------------------------------------------
// Datos

function activa(){ return armadas.find(a => a.clave === claveActiva) || null; }

// Como en el servidor: una pendiente cambia de clave al decidirla, y una
// operacion armada antes de eso llega con la clave vieja.
function buscar(clave){
  if(!clave) return null;
  return armadas.find(a => a.clave === clave) ||
         (clave.startsWith("p:") && armadas.find(a => a.propuesta === clave.slice(2))) || null;
}

function duracion(){ return (datos && datos.duracion) || video.duration || 0; }
function ahora(){ return Math.round(video.currentTime * 1000) / 1000; }

function tramoEn(t){
  let vigente = null;
  for(const tramo of sets){
    if(tramo.desde > t + 1e-9) break;
    vigente = tramo;
  }
  return vigente;
}

function recibir(r){
  datos = r.video;
  edicion = r.edicion;
  sets = r.sets;
  armadas = r.armadas;
  sePuedeDeshacer = !!r.se_puede_deshacer;
  // la elegida puede haber desaparecido (deshacer una marca, otra pestana)
  if(claveActiva && !buscar(claveActiva)){
    claveActiva = null;
    enBucle = false;
  }
  pintar();
}

// ----------------------------------------------------------------------
// Guardar. "op" es la operacion o una funcion que la arma justo antes de
// mandarla (devolviendo null si ya no corresponde).
function operar(op, alTerminar){
  enCamino++;
  mostrarGuardado("guardando");
  cola = cola.then(async () => {
    const pedido = typeof op === "function" ? op() : op;
    if(!pedido) return;
    const r = await api(`/api/videos/${encodeURIComponent(nombre)}/operar`,
                        {edicion, op: pedido});
    sinConexion = !!r.red;
    if(r.conflicto) recibir(r);
    if(!r.ok) return avisar(r.mensaje, true);
    // la elegida puede cambiar de clave al decidirla ("p:..." pasa a "d:...")
    if(pedido.clave && pedido.clave === claveActiva) claveActiva = r.clave;
    recibir(r);
    if(alTerminar) alTerminar(r);
  }).catch(error => avisar(String(error), true))
    .finally(() => {
      enCamino--;
      if(enCamino === 0) mostrarGuardado(sinConexion ? "error" : "ok");
    });
  return cola;
}

function mostrarGuardado(estado){
  const caja = $("#guardado");
  caja.className = "guardado " + (estado === "guardando" ? "" : estado);
  caja.textContent = {guardando: "Guardando…", ok: "Guardado", error: "Sin conexión: no se guardó"}[estado];
}

// Una operacion sobre la elegida. La armada se fija en el momento del toque:
// si mientras tanto se eligio otra, el cambio va igual a la que se toco. Si
// todavia no hay elegida pero hay una marca en camino (M y enseguida 4), va a
// esa marca: las operaciones salen en orden, asi que cuando le toca a esta la
// marca ya volvio y se sabe su clave.
function sobreLaElegida(armar){
  const clave = claveActiva;
  const pedida = clave ? null : marcaEnCamino;
  if(!clave && !pedida) return avisar("Marcá (M) o elegí una armada primero.");
  operar(() => {
    const a = buscar(clave || pedida.clave);
    return a ? armar(a) : null;
  });
}

// ----------------------------------------------------------------------
// Video

function reproducir(){ video.play().catch(() => { /* lo corto otra orden: no es un error */ }); }

function irA(t){
  const total = duracion();
  video.currentTime = Math.max(0, total ? Math.min(t, total) : t);
}

function saltar(segundos){ irA(video.currentTime + segundos); }

function cuadro(paso){
  video.pause();
  irA(video.currentTime + paso / ((datos && datos.fps) || 30));
}

function velocidad(paso){
  let i = VELOCIDADES.indexOf(video.playbackRate);
  if(i < 0) i = VELOCIDADES.indexOf(1);
  video.playbackRate = VELOCIDADES[Math.min(VELOCIDADES.length - 1, Math.max(0, i + paso))];
}

function reproducirPausar(){
  if(!video.paused) return video.pause();
  const a = activa();
  if(a && !enBucle){
    soltar();            // se termino de ajustar la marca: a seguir mirando
  }else if(a && (video.currentTime < a.t_inicio || video.currentTime >= a.t_fin)){
    video.currentTime = a.t_inicio;
  }
  reproducir();
}

function elegir(clave){
  const a = buscar(clave);
  if(!a) return;
  ficha++;
  marcaEnCamino = null;
  claveActiva = a.clave;
  enBucle = true;
  irA(a.t_inicio);
  reproducir();
  pintar();
}

function soltar(){
  ficha++;
  marcaEnCamino = null;
  claveActiva = null;
  enBucle = false;
  pintar();
}

function vecina(paso){
  if(!armadas.length) return;
  const a = activa();
  let i;
  if(a){
    i = armadas.indexOf(a) + paso;
  }else{
    const t = video.currentTime;
    i = paso > 0 ? armadas.findIndex(x => x.t_armado > t)
                 : armadas.reduce((ultima, x, j) => (x.t_armado < t ? j : ultima), -1);
  }
  if(i >= 0 && i < armadas.length) elegir(armadas[i].clave);
}

// ----------------------------------------------------------------------
// Lo que se hace

function marcar(){
  const a = activa();
  if(video.paused && (a || marcaEnCamino)){
    // Con una elegida y el video quieto, M dice "el armado es en este
    // cuadro". Si la marca de recien todavia no volvio del servidor, es a
    // ella: dos M seguidas no son dos armadas.
    const t = ahora();
    return sobreLaElegida(x => (Math.abs(t - x.t_armado) < 0.0005 ? null
      : {tipo: "cambiar", clave: x.clave, campos: {t_armado: t}}));
  }
  video.pause();
  const t = ahora();
  const campos = armadorFijo == null ? {} : {armador: armadorFijo};
  const mia = ++ficha;
  const pedida = {clave: null};
  marcaEnCamino = pedida;
  operar({tipo: "marcar", t, campos}, r => {
    pedida.clave = r.clave;
    // si mientras volvia se solto o se eligio otra, la marca queda guardada
    // pero no se elige: la persona ya esta en otra cosa
    if(ficha !== mia) return;
    claveActiva = r.clave;
    enBucle = false;
    pintar();
  }).finally(() => { if(marcaEnCamino === pedida) marcaEnCamino = null; });
}

function zona(n){
  sobreLaElegida(a => ({tipo: "cambiar", clave: a.clave,
                        campos: {zona_destino: a.zona_destino === n ? null : n}}));
}

function tiempoAca(campo){
  const t = ahora();
  sobreLaElegida(a => ({tipo: "cambiar", clave: a.clave, campos: {[campo]: t}}));
}

function aceptarYSeguir(){
  const a = activa();
  if(!a) return reproducir();
  if(a.estado === "aceptada"){
    soltar();
    return reproducir();
  }
  const eraPendiente = a.estado === "pendiente", t = a.t_armado;
  operar({tipo: "aceptar", clave: a.clave}, () => {
    if(eraPendiente && irAPendiente(t)) return;
    soltar();
    reproducir();
  });
}

function descartar(){
  const a = activa();
  if(!a) return avisar("Elegí una armada primero.");
  const t = a.t_armado;
  operar({tipo: "descartar", clave: a.clave}, () => {
    if(!irAPendiente(t)) soltar();
  });
}

function irAPendiente(despuesDe){
  const siguiente = armadas.find(a => a.estado === "pendiente" && a.t_armado > despuesDe);
  if(siguiente) elegir(siguiente.clave);
  return !!siguiente;
}

function deshacer(){
  if(!sePuedeDeshacer && !enCamino) return avisar("No hay nada para deshacer.");
  operar({tipo: "deshacer"}, () => avisar("Deshecho."));
}

// ----------------------------------------------------------------------
// Sets

function abrirSet(){
  video.pause();
  const t = ahora();
  const anterior = tramoEn(t);
  // cada set se cambia de lado: por defecto, el que sigue y del otro lado
  formSet = {desde: t,
             set: anterior ? Math.min(5, anterior.set + 1) : 1,
             lado: anterior && anterior.lado === "cerca" ? "lejos" : "cerca"};
  pintarFormSet();
}

function guardarSet(){
  const f = formSet;
  formSet = null;
  pintarFormSet();
  operar({tipo: "set", desde: f.desde, set: f.set, lado: f.lado},
         () => avisar(`Set ${f.set} desde ${reloj(f.desde)}.`));
}

function cancelarSet(){
  formSet = null;
  pintarFormSet();
}

function teclaDelSet(ev){
  const k = ev.key;
  if(k.length === 1 && k >= "1" && k <= "5") formSet.set = Number(k);
  else if(k === "c" || k === "C") formSet.lado = "cerca";
  else if(k === "l" || k === "L") formSet.lado = "lejos";
  else if(k === "Enter"){ ev.preventDefault(); return guardarSet(); }
  else if(k === "Escape") formSet = null;
  else return;
  ev.preventDefault();
  pintarFormSet();
}

// ----------------------------------------------------------------------
// Campos: armador (queda fijo), etiquetas y nota de la elegida

function valorGuardado(campo){
  const a = activa();
  if(campo === CAMPOS.armador) return armadorFijo ?? "";
  if(!a) return "";
  return campo === CAMPOS.etiquetas ? a.etiquetas.join(", ") : a.nota;
}

function ponerSiNoSeEscribe(campo, valor){
  if(document.activeElement !== campo) campo.value = valor;
}

CAMPOS.armador.addEventListener("change", () => {
  const texto = CAMPOS.armador.value.trim();
  if(texto !== "" && !/^\d{1,3}$/.test(texto)){
    CAMPOS.armador.value = armadorFijo ?? "";
    return avisar("El armador es el número de la camiseta.", true);
  }
  armadorFijo = texto === "" ? null : parseInt(texto, 10);
  recordar(`armador.${nombre}`, armadorFijo);
  if(activa()){
    const clave = claveActiva;
    operar({tipo: "cambiar", clave, campos: {armador: armadorFijo}});
  }else{
    avisar(armadorFijo == null ? "Sin armador fijo." : `Las próximas marcas van con el ${armadorFijo}.`);
  }
});

CAMPOS.etiquetas.addEventListener("change", () => {
  const a = activa();
  if(!a) return;
  const lista = CAMPOS.etiquetas.value.split(",").map(e => e.trim()).filter(Boolean);
  operar({tipo: "cambiar", clave: a.clave, campos: {etiquetas: lista}});
});

CAMPOS.nota.addEventListener("change", () => {
  const a = activa();
  if(!a) return;
  operar({tipo: "cambiar", clave: a.clave, campos: {nota: CAMPOS.nota.value}});
});

Object.values(CAMPOS).forEach(campo => {
  campo.addEventListener("input", () => { campoSucio = true; });
  campo.addEventListener("change", () => { campoSucio = false; });
  campo.addEventListener("keydown", ev => {
    // Enter guarda (el blur dispara "change") y Esc deja como estaba; en los
    // dos casos el teclado vuelve a ser de los atajos
    if(ev.key === "Enter"){ ev.preventDefault(); campo.blur(); }
    if(ev.key === "Escape"){
      ev.preventDefault();
      campo.value = valorGuardado(campo);
      campoSucio = false;
      campo.blur();
    }
  });
});

function alternarEtiqueta(etiqueta){
  const minuscula = etiqueta.toLowerCase();
  sobreLaElegida(a => {
    const tiene = a.etiquetas.some(e => e.toLowerCase() === minuscula);
    const lista = tiene ? a.etiquetas.filter(e => e.toLowerCase() !== minuscula)
                        : [...a.etiquetas, etiqueta];
    return {tipo: "cambiar", clave: a.clave, campos: {etiquetas: lista}};
  });
}

// ----------------------------------------------------------------------
// Pintar

function pintar(){
  pintarActiva();
  pintarLista();
  pintarSets();
  pintarLinea();
  pintarEtiquetasUsadas();
  $("[data-accion=deshacer]").disabled = !sePuedeDeshacer;
}

function pintarActiva(){
  const a = activa();
  $("#nadaElegido").hidden = !!a;
  $("#detalle").hidden = !a;
  CAMPOS.etiquetas.disabled = CAMPOS.nota.disabled = !a;
  ponerSiNoSeEscribe(CAMPOS.armador, armadorFijo ?? "");
  ponerSiNoSeEscribe(CAMPOS.etiquetas, a ? a.etiquetas.join(", ") : "");
  ponerSiNoSeEscribe(CAMPOS.nota, a ? a.nota : "");
  if(!a) return;

  const estado = $("#aEstado");
  estado.className = "pastilla " + a.estado;
  estado.textContent = a.estado === "aceptada"
    ? (a.origen === "manual" ? "marcada" : "aceptada")
    : (a.estado === "pendiente" ? "por revisar" : "descartada");
  $("#aTiempo").textContent = reloj(a.t_armado);
  $("#aTiempo").classList.toggle("corregido", a.corregido.includes("t_armado"));
  $("#aDonde").textContent = [a.set ? `set ${a.set}` : "sin set",
                              a.lado ? NOMBRE_DEL_LADO[a.lado] : "",
                              a.armador != null ? `armador ${a.armador}` : "",
                              a.tipo === "segunda" ? "segunda" : ""].filter(Boolean).join(" · ");
  const avisos = [];
  if(a.huerfana) avisos.push("La propuesta de la máquina ya no está: quedó con los datos que tenía.");
  if(a.estado === "pendiente" && a.confianza != null){
    avisos.push(`Confianza ${Math.round(100 * a.confianza)}%` +
                (a.motivos.length ? `: ${a.motivos.join(", ")}` : "."));
  }
  $("#aAviso").hidden = !avisos.length;
  $("#aAviso").textContent = avisos.join(" ");
  $$("#aZonas button").forEach(b =>
    b.classList.toggle("elegida", Number(b.dataset.zona) === a.zona_destino));
  $("#aAtaque").textContent = a.t_ataque == null ? "sin marcar"
    : `${reloj(a.t_ataque)} · vuelo ${a.tiempo_vuelo.toFixed(2)} s · ${NOMBRE_DEL_TEMPO[a.tempo]}`;
  $("#aRecorte").textContent = `${reloj(a.t_inicio, 1)} a ${reloj(a.t_fin, 1)}`;
  $("#bAceptar").hidden = a.estado === "aceptada";
  $("#bDescartar").textContent = a.origen === "manual" ? "Borrar (Supr)" : "Descartar (Supr)";
}

function pintarLista(){
  const cuenta = {aceptada: 0, pendiente: 0, descartada: 0};
  armadas.forEach(a => { cuenta[a.estado]++; });
  $("#cuenta").textContent = armadas.length
    ? `(${cuenta.aceptada}${cuenta.pendiente ? ` · ${cuenta.pendiente} por revisar` : ""})` : "";
  $("#lista").innerHTML = armadas.length ? armadas.map(a => `
    <li data-clave="${esc(a.clave)}" class="${esc(a.estado)}${a.clave === claveActiva ? " activa" : ""}">
      <span class="t">${esc(reloj(a.t_armado))}</span>
      <span>${a.set ? "S" + esc(a.set) : "—"}</span>
      <span>${a.zona_destino ? "Z" + esc(a.zona_destino) : "Z?"}</span>
      <span>${esc(NOMBRE_DEL_TEMPO[a.tempo] || "")}</span>
      <span class="arm">${a.armador != null ? "#" + esc(a.armador) : ""}</span>
      <span class="etq">${esc(a.etiquetas.join(", "))}</span>
    </li>`).join("")
    : `<li class="nota">Todavía no hay armadas marcadas.</li>`;

  // que la elegida se vea, moviendo solo la lista y no la pagina entera
  const elegida = $("#lista li.activa");
  if(elegida){
    const caja = $("#lista");
    if(elegida.offsetTop < caja.scrollTop) caja.scrollTop = elegida.offsetTop;
    else if(elegida.offsetTop + elegida.offsetHeight > caja.scrollTop + caja.clientHeight)
      caja.scrollTop = elegida.offsetTop + elegida.offsetHeight - caja.clientHeight;
  }
}

function pintarSets(){
  $("#sets").innerHTML = sets.length ? sets.map(s => `
    <li><span>Set ${esc(s.set)} desde ${esc(reloj(s.desde))} · mi equipo ${esc(NOMBRE_DEL_LADO[s.lado])}</span>
      <button data-ir="${s.desde}">ir</button>
      <button data-quitar-set="${s.desde}">quitar</button></li>`).join("")
    : `<li class="nota">En el primer saque de cada set apretá <kbd>S</kbd> y decí de qué lado está tu equipo.</li>`;
}

function pintarFormSet(){
  $("#formSet").hidden = !formSet;
  if(!formSet) return;
  $("#fsDesde").textContent = reloj(formSet.desde);
  $("#fsNumero").innerHTML = [1, 2, 3, 4, 5].map(n =>
    `<button data-set-numero="${n}" class="${n === formSet.set ? "elegida" : ""}">Set ${n}</button>`).join("");
  $$("#fsLado button").forEach(b => b.classList.toggle("elegida", b.dataset.lado === formSet.lado));
}

function pintarEtiquetasUsadas(){
  const todas = new Map();
  armadas.forEach(a => a.etiquetas.forEach(e => {
    if(!todas.has(e.toLowerCase())) todas.set(e.toLowerCase(), e);
  }));
  const a = activa();
  const tiene = new Set((a ? a.etiquetas : []).map(e => e.toLowerCase()));
  $("#etiquetasUsadas").innerHTML = [...todas.values()].sort((x, y) => x.localeCompare(y))
    .map(e => `<button data-etiqueta="${esc(e)}" class="${tiene.has(e.toLowerCase()) ? "activa" : ""}"
                ${a ? "" : "disabled"}>${esc(e)}</button>`).join("");
}

let ultimoReloj = "";

function pintarLinea(){
  const total = duracion();
  if(!total){ $("#linea").innerHTML = ""; return; }
  const donde = t => `${(100 * t / total).toFixed(3)}%`;
  const partes = sets.map((s, i) => {
    const hasta = i + 1 < sets.length ? sets[i + 1].desde : total;
    return `<div class="tramo ${esc(s.lado)}" style="left:${donde(s.desde)};width:${donde(hasta - s.desde)}">S${esc(s.set)}</div>`;
  });
  const a = activa();
  if(a) partes.push(`<div class="recorte" style="left:${donde(a.t_inicio)};width:${donde(a.t_fin - a.t_inicio)}"></div>`);
  armadas.forEach(x => partes.push(
    `<div class="marca ${esc(x.estado)}${x.clave === claveActiva ? " activa" : ""}" style="left:${donde(x.t_armado)}"></div>`));
  partes.push(`<div id="cursor" class="cursor"></div>`);
  $("#linea").innerHTML = partes.join("");
  ultimoReloj = "";
}

// Lo que cambia con el video andando: se mira en cada cuadro de pantalla,
// pero se toca el DOM solo cuando cambia el texto.
function pintarReloj(){
  const t = video.currentTime;
  const texto = reloj(t);
  if(texto === ultimoReloj) return;
  ultimoReloj = texto;
  $("#reloj").textContent = texto;
  const tramo = tramoEn(t);
  $("#donde").textContent = tramo ? `· set ${tramo.set}, mi equipo ${NOMBRE_DEL_LADO[tramo.lado]}`
    : (sets.length ? "· antes del primer set" : "· sin sets marcados (S)");
  const cursor = $("#cursor"), total = duracion();
  if(cursor && total) cursor.style.left = `${100 * t / total}%`;
}

function vigilar(){
  const a = activa();
  if(a && enBucle && !video.paused && video.currentTime >= a.t_fin) video.currentTime = a.t_inicio;
  pintarReloj();
  requestAnimationFrame(vigilar);
}

// ----------------------------------------------------------------------
// Teclado y toques

const TECLAS = {
  " ": reproducirPausar,
  "m": marcar,
  "Enter": aceptarYSeguir,
  "Delete": descartar,
  "Backspace": descartar,
  "a": () => tiempoAca("t_ataque"),
  "[": () => tiempoAca("t_inicio"),
  "i": () => tiempoAca("t_inicio"),
  "]": () => tiempoAca("t_fin"),
  "f": () => tiempoAca("t_fin"),
  "z": deshacer,
  "ArrowUp": () => vecina(-1),
  "ArrowDown": () => vecina(1),
  "s": abrirSet,
  "Escape": soltar,
  "-": () => velocidad(-1),
  "+": () => velocidad(1),
  "=": () => velocidad(1),
  "n": () => CAMPOS.armador.focus(),
  "e": () => CAMPOS.etiquetas.focus(),
};

document.addEventListener("keydown", ev => {
  if(escribiendo(ev)) return;
  // En teclados en español "[" y "]" salen con AltGr, que el navegador
  // informa como Ctrl+Alt: eso no es un atajo de Ctrl.
  const altGr = ev.getModifierState && ev.getModifierState("AltGraph");
  if((ev.ctrlKey || ev.metaKey) && !altGr){
    if(ev.key.toLowerCase() === "z"){ ev.preventDefault(); deshacer(); }
    return;
  }
  if(ev.altKey && !altGr) return;
  if(formSet) return teclaDelSet(ev);

  const tecla = ev.key.length === 1 ? ev.key.toLowerCase() : ev.key;
  let accion = TECLAS[tecla];
  if(tecla.length === 1 && tecla >= "1" && tecla <= "6") accion = () => zona(Number(tecla));
  if(tecla === "ArrowLeft") accion = () => (ev.shiftKey ? saltar(-5) : cuadro(-1));
  if(tecla === "ArrowRight") accion = () => (ev.shiftKey ? saltar(5) : cuadro(1));
  if(!accion) return;
  // sin esto, N y E escribirian su letra en el campo que acaban de enfocar
  ev.preventDefault();
  accion();
});

const BOTONES = {
  atras: () => saltar(-5), adelante: () => saltar(5),
  cuadroAtras: () => cuadro(-1), cuadroAdelante: () => cuadro(1),
  reproducir: reproducirPausar, masLento: () => velocidad(-1), masRapido: () => velocidad(1),
  marcar, set: abrirSet, deshacer,
  ataque: () => tiempoAca("t_ataque"), inicio: () => tiempoAca("t_inicio"),
  fin: () => tiempoAca("t_fin"),
  aceptar: aceptarYSeguir, descartar, soltar, guardarSet, cancelarSet,
};

document.addEventListener("click", ev => {
  const boton = ev.target.closest("button");
  // que Espacio y Enter sigan siendo atajos y no "tocar el boton otra vez"
  if(boton) boton.blur();
  const accion = ev.target.closest("[data-accion]");
  if(accion && BOTONES[accion.dataset.accion]) return BOTONES[accion.dataset.accion]();
  const conZona = ev.target.closest("[data-zona]");
  if(conZona) return zona(Number(conZona.dataset.zona));
  const fila = ev.target.closest("#lista li[data-clave]");
  if(fila) return elegir(fila.dataset.clave);
  const ir = ev.target.closest("[data-ir]");
  if(ir){ soltar(); return irA(Number(ir.dataset.ir)); }
  const quitar = ev.target.closest("[data-quitar-set]");
  if(quitar) return operar({tipo: "quitar_set", desde: Number(quitar.dataset.quitarSet)});
  const numero = ev.target.closest("[data-set-numero]");
  if(numero && formSet){ formSet.set = Number(numero.dataset.setNumero); return pintarFormSet(); }
  const lado = ev.target.closest("[data-lado]");
  if(lado && formSet){ formSet.lado = lado.dataset.lado; return pintarFormSet(); }
  const etiqueta = ev.target.closest("[data-etiqueta]");
  if(etiqueta) return alternarEtiqueta(etiqueta.dataset.etiqueta);
});

$("#linea").addEventListener("click", ev => {
  const total = duracion();
  if(!total) return;
  const caja = ev.currentTarget.getBoundingClientRect();
  const x = ev.clientX - caja.left;
  // una raya a menos de 8 px es esa armada; si no, se salta a ese instante
  let cercana = null, distancia = 8;
  armadas.forEach(a => {
    const d = Math.abs(a.t_armado / total * caja.width - x);
    if(d < distancia){ cercana = a; distancia = d; }
  });
  if(cercana) return elegir(cercana.clave);
  if(claveActiva) soltar();
  irA(x / caja.width * total);
});

video.addEventListener("click", reproducirPausar);
video.addEventListener("loadedmetadata", pintarLinea);
// un recorte que llega al final del video: el video termina antes de que
// vigilar() lo vea pasar el fin
video.addEventListener("ended", () => {
  const a = activa();
  if(a && enBucle){ video.currentTime = a.t_inicio; reproducir(); }
});
video.addEventListener("ratechange", () => {
  $("#velocidad").textContent = `${video.playbackRate}×`;
});
video.addEventListener("error", () =>
  avisar("El navegador no pudo abrir la copia liviana del video.", true));

// Cerrar con algo escrito sin guardar, o con un guardado en camino.
window.addEventListener("beforeunload", ev => {
  if(campoSucio || enCamino) ev.preventDefault();
});

// ----------------------------------------------------------------------
async function iniciar(){
  if(!nombre){
    $("#titulo").textContent = "Falta el video";
    return avisar("Elegí un video en la lista.", true);
  }
  const r = await api(`/api/videos/${encodeURIComponent(nombre)}`);
  if(!r.ok){
    $("#titulo").textContent = "No se pudo abrir";
    return avisar(r.mensaje, true);
  }
  recibir(r);
  document.title = `${datos.titulo} · revisión`;
  $("#titulo").textContent = datos.titulo;
  $("#duracion").textContent = `de ${reloj(datos.duracion, 0)}`;
  $("#aGaleria").href = `galeria.html?v=${encodeURIComponent(nombre)}`;
  if(!datos.hay_proxy){
    $("#sinProxy").hidden = false;
  }else{
    // ?t= viene de la galeria: se abre con esa armada elegida
    const t = parseFloat(parametro("t"));
    if(Number.isFinite(t)){
      video.addEventListener("loadedmetadata", () => {
        const a = armadas.find(x => Math.abs(x.t_armado - t) < 0.01);
        if(a) elegir(a.clave);
        else irA(t);
      }, {once: true});
    }
    video.src = `/videos/${encodeURIComponent(nombre)}/proxy.mp4`;
  }
  requestAnimationFrame(vigilar);
}

iniciar();
