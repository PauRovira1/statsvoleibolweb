/* Lo que comparten las tres pantallas del analisis de video.
 *
 * Sin dependencias y sin nada remoto, como la app de carga: corre en la PC,
 * contra el servidor de python -m video servir.
 */
"use strict";

const $ = s => document.querySelector(s);
const $$ = s => Array.from(document.querySelectorAll(s));

// Los nombres vienen de archivos con apostrofos y acentos (O'sommer): todo lo
// que se mete en una plantilla pasa por aca.
function esc(valor){
  return String(valor ?? "").replace(/[&<>"']/g, c =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}

function parametro(nombre){
  return new URLSearchParams(location.search).get(nombre);
}

// GET sin datos, POST con. Siempre devuelve un objeto con "ok": un error de
// red no es una excepcion que se escapa, es un mensaje para mostrar. "red"
// distingue "no llego al servidor" (no se guardo nada) de "el servidor dijo
// que no" (lo guardado sigue como estaba).
async function api(ruta, datos){
  const opciones = datos === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify(datos)};
  let respuesta;
  try{
    respuesta = await fetch(ruta, opciones);
  }catch(_){
    return {ok: false, red: true,
            mensaje: "Sin conexión con el servidor de video. " +
                     "¿Sigue abierta la consola con python -m video servir?"};
  }
  try{
    return await respuesta.json();
  }catch(_){
    return {ok: false, red: true,
            mensaje: `El servidor contestó algo inesperado (${respuesta.status}).`};
  }
}

// 754.5 -> "12:34.50"; 3725 -> "1:02:05.00". Se redondea antes de partir para
// que 59.996 no salga "0:60.00".
function reloj(t, decimales = 2){
  if(t == null || !Number.isFinite(t)) return "—";
  const factor = 10 ** decimales;
  let resto = Math.round(Math.abs(t) * factor) / factor;
  const horas = Math.floor(resto / 3600);
  resto -= horas * 3600;
  const minutos = Math.floor(resto / 60);
  const segundos = (resto - minutos * 60).toFixed(decimales)
    .padStart(decimales ? decimales + 3 : 2, "0");
  const signo = t < 0 ? "-" : "";
  return horas ? `${signo}${horas}:${String(minutos).padStart(2, "0")}:${segundos}`
               : `${signo}${minutos}:${segundos}`;
}

const NOMBRE_DEL_TEMPO = {rapida: "rápida", media: "media", alta: "alta"};
const NOMBRE_DEL_LADO = {cerca: "cerca de la cámara", lejos: "lejos de la cámara"};

// Un aviso abajo que se va solo. Los errores quedan mas tiempo.
let relojDelAviso = null;
function avisar(texto, esError = false){
  let caja = $("#aviso");
  if(!caja){
    caja = document.createElement("div");
    caja.id = "aviso";
    caja.setAttribute("role", "status");
    document.body.appendChild(caja);
  }
  caja.className = "mensaje" + (esError ? " error" : "");
  caja.textContent = texto;
  caja.hidden = false;
  clearTimeout(relojDelAviso);
  relojDelAviso = setTimeout(() => { caja.hidden = true; }, esError ? 7000 : 2500);
}

// Preferencias de esta pantalla en este navegador (el armador fijo, los
// filtros). Si el almacenamiento esta bloqueado, se sigue sin recordar nada.
function recordar(clave, valor){
  try{ localStorage.setItem("voley.video." + clave, JSON.stringify(valor)); }catch(_){ /* sin storage */ }
}
function recordado(clave, porDefecto){
  try{
    const texto = localStorage.getItem("voley.video." + clave);
    return texto == null ? porDefecto : JSON.parse(texto);
  }catch(_){ return porDefecto; }
}

// El que escribe en un campo no esta mandando atajos.
function escribiendo(evento){
  return !!evento.target.closest("input, textarea, select");
}
