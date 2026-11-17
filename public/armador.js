/* El armador de jugadas del lado del navegador.
 *
 * La notacion no esta escrita aca: baja de GET /api/notacion, que devuelve la
 * tabla de notacion.py tal cual. Este archivo es el interprete y nada mas:
 * apila el texto que dice la tabla y mueve el cursor al paso que dice la
 * tabla. Si aca apareciera un "si el ataque fue defendido entonces...", la
 * regla estaria escrita dos veces y una de las dos se iba a quedar vieja.
 *
 * De quien es la pelota tampoco se decide aca: lo dice el motor en
 * estado.pendiente, que es lo que se le pasa al constructor. Lo mismo quien
 * es el armador y a quien se le arma en cada zona: llegan del motor
 * (rotaciones[equipo].armador y .juego.atacantes) y aca solo se usan.
 *
 * Los toques que valen por dos pasos ("directo", "asume", "junta") estan
 * explicados en la cabecera de notacion.py. Este archivo tiene que hacer con
 * ellos exactamente lo mismo que el Armador de alla: test_carga_visual le
 * pasa los mismos toques a los dos y compara lo que ofrecen y lo que escriben.
 */

let PASOS = {};

function cargarNotacion(tabla){ PASOS = tabla.pasos || {}; }

const otroEquipo = e => (e === "A" ? "B" : "A");

// La primera ficha trae su separador puesto ("_1", "/3") y se lo saca al
// armar la linea: asi el saque con dorsal y el saque sin dorsal salen del
// mismo camino.
const sinSeparador = t => (t[0] === "_" || t[0] === "/" ? t.slice(1) : t);

function primerPaso(espera, sacadorConocido){
  if(espera === "continuacion") return "RECIBE_JUGADOR";
  return sacadorConocido ? "SAQUE_DESDE" : "SAQUE_JUGADOR";
}

class Armador {
  constructor({espera, equipoSaca, equipoConLaPelota, planteles, sacadorConocido,
               armadores, atacantes}){
    this.espera = espera;
    this.equipoSaca = equipoSaca;
    // Adentro de un bloque de saque la pelota es del que RECIBE: el que saca
    // aparece solo en el paso del saque, que tiene su propio lado. El motor
    // informa equipoConLaPelota = el que saca, porque es quien la tiene antes
    // de sacarla; de ahi en adelante es del otro.
    this.equipoConLaPelota = espera === "saque"
      ? otroEquipo(equipoSaca)
      : (equipoConLaPelota || otroEquipo(equipoSaca));
    this.planteles = planteles || {};
    this.sacadorConocido = !!sacadorConocido;
    // sin estos dos no se asume nada y la carga es toque por toque, como con
    // un equipo sin rotacion
    this.armadores = armadores || {};
    this.atacantes = atacantes || {};
    this.pasos = [];
    this.estado = primerPaso(espera, this.sacadorConocido);
  }

  // ------------------------------------------------------------------
  get linea(){ return sinSeparador(this.pasos.map(p => p.texto).join("")); }
  get cerrada(){ return this.pasos.length > 0 && this.pasos[this.pasos.length - 1].cierra; }
  get paso(){ return PASOS[this.estado] || null; }
  get vacio(){ return this.pasos.length === 0; }

  // El dorsal que ya quedo dicho para la linea que viene: el rival que se
  // toco para decir "Defendido". null si la linea no cerro asi.
  get arrastre(){
    if(!this.cerrada) return null;
    const ultimo = this.pasos[this.pasos.length - 1].arrastra;
    return ultimo == null ? null : ultimo;
  }

  equipoDe(lado){
    if(lado === "saca") return this.equipoSaca;
    if(lado === "rival") return otroEquipo(this.equipoConLaPelota);
    return this.equipoConLaPelota;
  }

  plantelDe(lado){ return (this.planteles[this.equipoDe(lado)] || []).slice(); }

  // El ultimo jugador (o la ultima zona) que se nombro en la linea.
  _ultimo(campo){
    for(let i = this.pasos.length - 1; i >= 0; i--){
      if(this.pasos[i][campo] != null) return this.pasos[i][campo];
    }
    return null;
  }

  // ------------------------------------------------------------------
  // El jugador que se da por hecho en este paso, o null. No se asume a nadie
  // que no este en la cancha, ni al que acaba de tocar la pelota: nadie la
  // toca dos veces seguidas, asi que si el armador recibio, arma otro.
  asumido(){
    if(this.cerrada) return null;
    const paso = this.paso;
    const asume = paso && paso.asume;
    if(!asume) return null;
    const otro = asume.otro;
    if(otro && this.pasos.some(p => p.estado === this.estado && p.id === otro.id)) return null;
    const equipo = this.equipoDe(paso.lado);
    let candidato = null;
    if(asume.quien === "armador"){
      candidato = this.armadores[equipo];
    } else {
      const porZona = this.atacantes[equipo] || [];
      const zona = this._ultimo("zona");
      candidato = zona ? porZona[zona - 1] : null;
    }
    if(candidato == null || !(this.planteles[equipo] || []).includes(candidato)) return null;
    // el "otro" tecleado llega como texto: se compara escrito
    if(String(candidato) === String(this._ultimo("jugador"))) return null;
    return candidato;
  }

  // Lo que se pregunta ahora. Cambia cuando hay un atajo a mano, para que se
  // vea que el toque vale por dos.
  titulo(){
    const paso = this.paso;
    if(!paso) return "";
    const asumido = this.asumido();
    if(asumido != null) return paso.asume.titulo.replace("{jugador}", String(asumido));
    if(paso.directo && this._directos(paso).length) return paso.directo.titulo;
    return paso.titulo;
  }

  // ------------------------------------------------------------------
  // Lo unico que se puede tocar ahora. Todo lo demas se apaga, y por eso no
  // hace falta saber la notacion para cargar. Los atajos van primero, igual
  // que en notacion.py.
  opciones(){
    if(this.cerrada) return [];
    const paso = this.paso;
    if(!paso) return [];
    const usados = new Set(this.pasos.filter(p => p.estado === this.estado).map(p => p.id));
    // de las opciones con "grupo" se puede tocar una sola por paso
    const gruposUsados = new Set((paso.opciones || [])
      .filter(o => o.grupo && usados.has(o.id)).map(o => o.grupo));
    const salida = [];

    const asumido = this.asumido();
    if(asumido != null) salida.push(...this._delPasoQueSigue(paso, asumido));
    if(paso.directo) salida.push(...this._directos(paso));

    const otro = paso.asume && paso.asume.otro;
    if(asumido != null && otro){
      // los circulos quedan atras de este boton (ver ARMA_JUGADOR en la tabla)
      salida.push({id: otro.id, tipo:"boton", etiqueta: otro.etiqueta, texto:"",
                   siguiente: this.estado, cierra:false, tono:null});
    } else if(paso.pide === "jugador"){
      this.plantelDe(paso.lado).forEach(dorsal =>
        salida.push(this._ficha(paso, "j" + dorsal, "jugador", String(dorsal), dorsal)));
      // Siempre, tenga o no rotacion el equipo: en los partidos guardados el
      // 15% de los dorsales no esta entre los 6 en cancha (son los liberos,
      // que no rotan). Sin esta salida esas jugadas no se podrian cargar.
      salida.push({id:"otro", tipo:"numero", etiqueta:"otro",
                   prefijo: paso.prefijo || "", sufijo: paso.sufijo || "",
                   siguiente: paso.siguiente || null, cierra: !!paso.cierra,
                   lado: paso.lado});
    } else if(paso.pide === "zona"){
      (paso.zonas || []).forEach(zona =>
        salida.push(this._ficha(paso, "z" + zona, "zona", String(zona), zona)));
    }

    (paso.opciones || []).forEach(extra => {
      if(extra.solo && extra.solo !== this.espera) return;
      if(extra.una_vez && usados.has(extra.id)) return;
      if(extra.grupo && gruposUsados.has(extra.grupo)) return;
      if(extra.junta){ salida.push(...this._juntas(extra)); return; }
      salida.push(this._boton(extra, ""));
    });
    return salida;
  }

  _ficha(paso, id, tipo, etiqueta, valor){
    const ficha = {id, tipo, etiqueta, valor,
                   texto: (paso.prefijo || "") + valor + (paso.sufijo || ""),
                   siguiente: paso.siguiente || null, cierra: !!paso.cierra,
                   lado: paso.lado};
    // a quien (o que zona) nombra el toque: de aca sale despues a quien se asume
    ficha[tipo] = valor;
    return ficha;
  }

  _boton(extra, delante){
    return {id: extra.id, tipo:"boton", etiqueta: extra.etiqueta,
            texto: delante + extra.texto, siguiente: extra.siguiente || null,
            cierra: !!extra.cierra, tono: extra.tono || null};
  }

  // Lo que ofrece el paso siguiente, con el jugador asumido por delante: un
  // toque escribe los dos pedazos ("/3" + "_4").
  _delPasoQueSigue(paso, jugador){
    const destino = PASOS[paso.siguiente];
    const delante = (paso.prefijo || "") + jugador + (paso.sufijo || "");
    const salida = [];
    (destino.zonas || []).forEach(zona => {
      const ficha = this._ficha(destino, "z" + zona, "zona", String(zona), zona);
      ficha.texto = delante + ficha.texto;
      ficha.jugador = jugador;
      salida.push(ficha);
    });
    (destino.opciones || []).forEach(extra => {
      if(extra.solo && extra.solo !== this.espera) return;
      const boton = this._boton(extra, delante);
      boton.jugador = jugador;
      salida.push(boton);
    });
    return salida;
  }

  // Los circulos que valen por un boton de este paso.
  _directos(paso){
    const directo = paso.directo;
    const base = (paso.opciones || []).find(o => o.id === directo.por);
    if(!base || (base.solo && base.solo !== this.espera)) return [];
    const destino = base.cierra ? null : PASOS[base.siguiente];
    return this.plantelDe(directo.lado).map(dorsal => {
      const ficha = {id: "j" + dorsal, tipo:"jugador", etiqueta: String(dorsal),
                     valor: dorsal, lado: directo.lado, jugador: dorsal};
      if(!destino){
        // el boton cerraba la linea: el jugador no se escribe, se lleva a la
        // que viene
        Object.assign(ficha, {texto: base.texto, siguiente: null, cierra: true,
                              arrastra: dorsal});
      } else {
        Object.assign(ficha, {
          texto: base.texto + (destino.prefijo || "") + dorsal + (destino.sufijo || ""),
          siguiente: destino.siguiente || null, cierra: !!destino.cierra});
      }
      return ficha;
    });
  }

  // Este boton y cada uno de los del paso al que lleva, en un toque. "fila"
  // es para que la pantalla los agrupe.
  _juntas(extra){
    const salida = [];
    (PASOS[extra.siguiente].opciones || []).forEach(final => {
      if(final.solo && final.solo !== this.espera) return;
      const boton = this._boton(final, extra.texto);
      boton.id = extra.id + "+" + final.id;
      boton.fila = extra.etiqueta;
      salida.push(boton);
    });
    return salida;
  }

  // ------------------------------------------------------------------
  tocar(id, numero){
    const opcion = this.opciones().find(o => o.id === id);
    if(!opcion) return null;
    const esNumero = opcion.tipo === "numero";
    const texto = esNumero ? opcion.prefijo + numero + opcion.sufijo : opcion.texto;
    const jugador = esNumero ? numero : opcion.jugador;
    this.pasos.push({estado: this.estado, id, texto, cierra: opcion.cierra,
                     jugador: jugador == null ? null : jugador,
                     zona: opcion.zona == null ? null : opcion.zona,
                     arrastra: opcion.arrastra == null ? null : opcion.arrastra});
    if(!opcion.cierra && opcion.siguiente) this.estado = opcion.siguiente;
    return opcion;
  }

  // Sacar el ultimo paso de la pila. El estado vuelve al que ese paso tenia
  // guardado, asi que no hay nada que recalcular ni que se pueda desfasar.
  deshacer(){
    if(!this.pasos.length) return false;
    this.estado = this.pasos.pop().estado;
    return true;
  }
}
