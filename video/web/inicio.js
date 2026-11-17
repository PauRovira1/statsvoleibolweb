/* La lista de videos dados de alta, con lo que tiene marcado cada uno. */
"use strict";

async function cargarVideos(){
  const r = await api("/api/videos");
  $("#cargando").hidden = true;
  if(!r.ok) return avisar(r.mensaje, true);
  if(!r.videos.length){ $("#vacio").hidden = false; return; }

  $("#videos tbody").innerHTML = r.videos.map(v => {
    const nombre = encodeURIComponent(v.nombre);
    if(v.error){
      return `<tr><td>${esc(v.titulo)}</td><td colspan="4" class="nota">${esc(v.error)}</td></tr>`;
    }
    const c = v.cuentas;
    const armadas = [`${c.aceptada} marcadas`,
                     c.pendiente ? `${c.pendiente} por revisar` : "",
                     c.descartada ? `${c.descartada} descartadas` : ""].filter(Boolean).join(" · ");
    const proxy = v.hay_proxy ? "" :
      `<div class="nota">Sin copia liviana: corré <code>python -m video nuevo</code></div>`;
    return `<tr>
      <td><b>${esc(v.titulo)}</b>${proxy}</td>
      <td>${esc(reloj(v.duracion, 0))}</td>
      <td>${esc(armadas)}</td>
      <td>${v.sets || "—"}</td>
      <td class="enlaces"><a href="revision.html?v=${nombre}">Revisar</a>
                           <a href="galeria.html?v=${nombre}">Galería</a></td></tr>`;
  }).join("");
  $("#videos").hidden = false;
}

cargarVideos();
