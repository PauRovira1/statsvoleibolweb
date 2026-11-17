/* Galeria: las armadas aceptadas de todos los videos, filtrables, para verlas
 * de a una (en bucle) o todas seguidas.
 *
 * Como se combinan los filtros: dentro de un grupo alcanza con uno (zona 4 o
 * zona 3); entre grupos se tienen que cumplir todos (zona 4 y armador 3). Un
 * grupo sin nada elegido no filtra. Una armada tiene varias etiquetas:
 * alcanza con que tenga una de las elegidas. El numero al lado de cada
 * opcion es cuantas quedarian eligiendola, con los otros grupos como estan.
 *
 * Solo lee. Para corregir una armada, "corregir" la abre en la revision.
 */
"use strict";

const video = $("#video");
const VELOCIDADES = [0.25, 0.5, 1, 1.5, 2, 4];
const GRUPOS = ["video", "set", "zona", "tempo", "armador", "lado", "etiqueta"];
const SIN = {set: "sin set", zona: "sin zona", tempo: "sin ataque marcado",
             armador: "sin armador", lado: "sin lado"};
const ORDEN_DEL_TEMPO = {rapida: 0, media: 1, alta: 2, "": 3};

let videos = {};
let todas = [];
let lista = [];
let indice = -1;
let seguidas = false;
let saltoPendiente = false;  // se cambio de video y falta saltar al recorte
let filtros = filtrosVacios();

function filtrosVacios(){
  return {video: [], set: [], zona: [], tempo: [], armador: [], lado: [], etiqueta: [], texto: ""};
}

// Los valores de una armada en un grupo, como texto ("" es "sin dato").
function valores(a, grupo){
  switch(grupo){
    case "video": return [a.video];
    case "set": return [String(a.set ?? "")];
    case "zona": return [String(a.zona_destino ?? "")];
    case "tempo": return [a.tempo ?? ""];
    case "armador": return [String(a.armador ?? "")];
    case "lado": return [a.lado ?? ""];
    case "etiqueta": return a.etiquetas.map(e => e.toLowerCase());
  }
  return [];
}

function pasa(a, salvo){
  for(const grupo of GRUPOS){
    if(grupo === salvo || !filtros[grupo].length) continue;
    if(!valores(a, grupo).some(v => filtros[grupo].includes(v))) return false;
  }
  const texto = filtros.texto.trim().toLowerCase();
  return !texto || `${a.nota} ${a.etiquetas.join(" ")}`.toLowerCase().includes(texto);
}

// Las opciones de un grupo: los valores que aparecen, con su nombre.
function opciones(grupo){
  const vistos = new Map();
  todas.forEach(a => valores(a, grupo).forEach(v => {
    if(vistos.has(v)) return;
    let nombre;
    if(v === "") nombre = SIN[grupo];
    else if(grupo === "video") nombre = (videos[v] && videos[v].titulo) || v;
    else if(grupo === "set") nombre = `Set ${v}`;
    else if(grupo === "tempo") nombre = NOMBRE_DEL_TEMPO[v];
    else if(grupo === "armador") nombre = `#${v}`;
    else if(grupo === "lado") nombre = NOMBRE_DEL_LADO[v];
    else if(grupo === "etiqueta") nombre = a.etiquetas.find(e => e.toLowerCase() === v);
    else nombre = v;
    vistos.set(v, nombre);
  }));
  const orden = ([v1, n1], [v2, n2]) => {
    if(grupo === "tempo") return ORDEN_DEL_TEMPO[v1] - ORDEN_DEL_TEMPO[v2];
    if((v1 === "") !== (v2 === "")) return v1 === "" ? 1 : -1;     // "sin" al final
    if(["set", "armador", "zona"].includes(grupo)) return Number(v1) - Number(v2);
    return String(n1).localeCompare(String(n2));
  };
  return [...vistos.entries()].sort(orden);
}

function cuantas(grupo, valor){
  return todas.filter(a => pasa(a, grupo) && valores(a, grupo).includes(valor)).length;
}

// ----------------------------------------------------------------------
function filtrar(){
  const actual = lista[indice];
  lista = todas.filter(a => pasa(a));
  indice = actual ? lista.indexOf(actual) : -1;
  if(actual && indice < 0){
    video.pause();
    seguidas = false;
  }
  recordar("filtros", filtros);
  pintarFiltros();
  pintarResultados();
  pintarLeyenda();
}

function alternar(grupo, valor){
  const elegidos = filtros[grupo];
  filtros[grupo] = elegidos.includes(valor) ? elegidos.filter(v => v !== valor) : [...elegidos, valor];
  filtrar();
}

function pintarFiltros(){
  const cajas = {video: "#fVideo", set: "#fSet", tempo: "#fTempo", armador: "#fArmador",
                 lado: "#fLado", etiqueta: "#fEtiqueta"};
  for(const [grupo, caja] of Object.entries(cajas)){
    $(caja).innerHTML = opciones(grupo).map(([valor, nombre]) =>
      `<button data-filtro="${grupo}" data-valor="${esc(valor)}"
               class="${filtros[grupo].includes(valor) ? "activa" : ""}">${esc(nombre)}
         <span class="nota">${cuantas(grupo, valor)}</span></button>`).join("")
      || `<span class="nota">—</span>`;
  }
  // la zona es la cancha fija de siempre, con la cuenta en el titulo
  $$('[data-filtro="zona"]').forEach(b => {
    const elegida = filtros.zona.includes(b.dataset.valor);
    b.classList.toggle("elegida", elegida);
    b.classList.toggle("activa", elegida);
    b.title = `${cuantas("zona", b.dataset.valor)} armadas`;
  });
}

function pintarResultados(){
  $("#bTodas").textContent = `Reproducir todas (${lista.length})`;
  $("#bTodas").disabled = !lista.length;
  const variosVideos = Object.keys(videos).length > 1;
  $("#resultados").innerHTML = lista.length ? lista.map((a, i) => {
    const partes = [
      variosVideos ? ((videos[a.video] && videos[a.video].titulo) || a.video) : "",
      a.set ? `set ${a.set}` : "",
      a.zona_destino ? `zona ${a.zona_destino}` : "sin zona",
      a.tempo ? `${NOMBRE_DEL_TEMPO[a.tempo]} (${a.tiempo_vuelo.toFixed(2)} s)` : "",
      a.armador != null ? `armador ${a.armador}` : "",
      a.etiquetas.join(", "),
      videos[a.video] && videos[a.video].hay_proxy ? "" : "(falta la copia para verla)",
    ].filter(Boolean);
    return `<li data-i="${i}" class="${i === indice ? "actual" : ""}">
      <span class="t">${esc(reloj(a.t_armado))}</span>
      <span class="datos">${esc(partes.join(" · "))}${a.nota ? `<span class="nota">${esc(a.nota)}</span>` : ""}</span>
      <a href="revision.html?v=${encodeURIComponent(a.video)}&amp;t=${a.t_armado}">corregir</a></li>`;
  }).join("") : `<li class="nota">${todas.length
    ? "Ninguna armada con estos filtros."
    : "Todavía no hay armadas marcadas: marcalas en la revisión de cada video."}</li>`;
}

function pintarLeyenda(){
  const a = lista[indice];
  if(!a){
    $("#leyenda").textContent = lista.length ? "Elegí una armada de la lista o reproducí todas." : "";
    return;
  }
  $("#leyenda").textContent = [
    `${indice + 1} de ${lista.length}${seguidas ? ", todas seguidas" : ""}`,
    (videos[a.video] && videos[a.video].titulo) || a.video,
    a.set ? `set ${a.set}` : "", reloj(a.t_armado),
    a.zona_destino ? `zona ${a.zona_destino}` : "sin zona",
    a.tempo ? NOMBRE_DEL_TEMPO[a.tempo] : "",
    a.armador != null ? `armador ${a.armador}` : "",
  ].filter(Boolean).join(" · ");
}

// ----------------------------------------------------------------------
function rutaDelProxy(nombreVideo){
  return new URL(`/videos/${encodeURIComponent(nombreVideo)}/proxy.mp4`, location.href).href;
}

function ver(i, todasSeguidas = false){
  const a = lista[i];
  if(!a) return;
  indice = i;
  seguidas = todasSeguidas;
  if(!(videos[a.video] && videos[a.video].hay_proxy)){
    avisar("A ese video le falta la copia liviana: corré python -m video nuevo.", true);
    if(seguidas && i + 1 < lista.length) return ver(i + 1, true);
    return pintarResultados();
  }
  const ruta = rutaDelProxy(a.video);
  if(video.src !== ruta){
    // otro partido: hay que esperar a que cargue para poder saltar
    saltoPendiente = true;
    video.src = ruta;
  }else{
    video.currentTime = a.t_inicio;
    video.play().catch(() => {});
  }
  pintarResultados();
  pintarLeyenda();
  const fila = $(`#resultados li[data-i="${i}"]`);
  if(fila && seguidas) fila.scrollIntoView({block: "nearest"});
}

video.addEventListener("loadedmetadata", () => {
  const a = lista[indice];
  if(!saltoPendiente || !a) return;
  saltoPendiente = false;
  video.currentTime = a.t_inicio;
  video.play().catch(() => {});
});

function terminoElRecorte(){
  if(seguidas){
    if(indice + 1 < lista.length) return ver(indice + 1, true);
    video.pause();
    seguidas = false;
    return pintarLeyenda();
  }
  video.currentTime = lista[indice].t_inicio;
  video.play().catch(() => {});
}

function vigilar(){
  const a = lista[indice];
  if(a && !video.paused && !saltoPendiente && video.currentTime >= a.t_fin) terminoElRecorte();
  requestAnimationFrame(vigilar);
}

video.addEventListener("ended", () => { if(lista[indice]) terminoElRecorte(); });
video.addEventListener("click", () => reproducirPausar());
video.addEventListener("ratechange", () => {
  $("#velocidad").textContent = `${video.playbackRate}×`;
});

function reproducirPausar(){
  if(indice < 0) return lista.length && ver(0);
  if(video.paused) video.play().catch(() => {});
  else video.pause();
}

function velocidad(paso){
  let i = VELOCIDADES.indexOf(video.playbackRate);
  if(i < 0) i = VELOCIDADES.indexOf(1);
  video.playbackRate = VELOCIDADES[Math.min(VELOCIDADES.length - 1, Math.max(0, i + paso))];
}

const BOTONES = {
  anterior: () => ver(Math.max(0, indice - 1), seguidas),
  siguiente: () => ver(Math.min(lista.length - 1, indice + 1), seguidas),
  reproducir: reproducirPausar,
  todas: () => ver(0, true),
  masLento: () => velocidad(-1),
  masRapido: () => velocidad(1),
  limpiar: () => { filtros = filtrosVacios(); $("#fTexto").value = ""; filtrar(); },
};

document.addEventListener("click", ev => {
  if(ev.target.closest("a")) return;     // "corregir" es un enlace comun
  const boton = ev.target.closest("button");
  if(boton) boton.blur();
  const accion = ev.target.closest("[data-accion]");
  if(accion && BOTONES[accion.dataset.accion]) return BOTONES[accion.dataset.accion]();
  const filtro = ev.target.closest("[data-filtro]");
  if(filtro) return alternar(filtro.dataset.filtro, filtro.dataset.valor);
  const fila = ev.target.closest("#resultados li[data-i]");
  if(fila) return ver(Number(fila.dataset.i));
});

document.addEventListener("keydown", ev => {
  if(escribiendo(ev) || ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const acciones = {" ": reproducirPausar, "ArrowUp": BOTONES.anterior,
                    "ArrowDown": BOTONES.siguiente, "-": () => velocidad(-1),
                    "+": () => velocidad(1), "=": () => velocidad(1)};
  const accion = acciones[ev.key];
  if(!accion) return;
  ev.preventDefault();
  accion();
});

$("#fTexto").addEventListener("input", () => {
  filtros.texto = $("#fTexto").value;
  filtrar();
});

// ----------------------------------------------------------------------
async function iniciar(){
  const r = await api("/api/armadas");
  if(!r.ok) return avisar(r.mensaje, true);
  videos = r.videos;
  todas = r.armadas.sort((x, y) => x.video.localeCompare(y.video) || x.t_armado - y.t_armado);
  (r.errores || []).forEach(error => avisar(error, true));

  const guardados = recordado("filtros", null);
  if(guardados && typeof guardados === "object"){
    for(const grupo of GRUPOS) if(Array.isArray(guardados[grupo])) filtros[grupo] = guardados[grupo];
    if(typeof guardados.texto === "string") filtros.texto = guardados.texto;
  }
  // desde la lista o la revision de un video: la galeria de ese video
  const desde = parametro("v");
  if(desde) filtros.video = [desde];
  // un filtro recordado de algo que ya no esta dejaria la lista vacia sin
  // que se vea por que
  for(const grupo of GRUPOS){
    const existen = new Set(opciones(grupo).map(([valor]) => valor));
    filtros[grupo] = filtros[grupo].filter(v => existen.has(v));
  }
  $("#fTexto").value = filtros.texto;
  filtrar();
  requestAnimationFrame(vigilar);
}

iniciar();
