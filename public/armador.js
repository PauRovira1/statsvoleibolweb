/* El armador de jugadas del lado del navegador.
 *
 * La notacion no esta escrita aca: baja de GET /api/notacion, que devuelve la
 * tabla de notacion.py tal cual. Este archivo es el interprete y nada mas:
 * apila el texto que dice la tabla y mueve el cursor al paso que dice la
 * tabla. Si aca apareciera un "si el ataque fue defendido entonces...", la
 * regla estaria escrita dos veces y una de las dos se iba a quedar vieja.
 *
 * De quien es la pelota tampoco se decide aca: lo dice el motor en
 * estado.pendiente, que es lo que se le pasa al constructor.
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
  constructor({espera, equipoSaca, equipoConLaPelota, planteles, sacadorConocido}){
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
    this.pasos = [];
    this.estado = primerPaso(espera, this.sacadorConocido);
  }

  // ------------------------------------------------------------------
  get linea(){ return sinSeparador(this.pasos.map(p => p.texto).join("")); }
  get cerrada(){ return this.pasos.length > 0 && this.pasos[this.pasos.length - 1].cierra; }
  get paso(){ return PASOS[this.estado] || null; }
  get vacio(){ return this.pasos.length === 0; }

  equipoDe(lado){
    if(lado === "saca") return this.equipoSaca;
    if(lado === "rival") return otroEquipo(this.equipoConLaPelota);
    return this.equipoConLaPelota;
  }

  plantelDe(lado){ return (this.planteles[this.equipoDe(lado)] || []).slice(); }

  // ------------------------------------------------------------------
  // Lo unico que se puede tocar ahora. Todo lo demas se apaga, y por eso no
  // hace falta saber la notacion para cargar.
  opciones(){
    if(this.cerrada) return [];
    const paso = this.paso;
    if(!paso) return [];
    const usados = new Set(this.pasos.filter(p => p.estado === this.estado).map(p => p.id));
    const salida = [];

    if(paso.pide === "jugador"){
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
      salida.push({id: extra.id, tipo:"boton", etiqueta: extra.etiqueta,
                   texto: extra.texto, siguiente: extra.siguiente || null,
                   cierra: !!extra.cierra, tono: extra.tono || null});
    });
    return salida;
  }

  _ficha(paso, id, tipo, etiqueta, valor){
    return {id, tipo, etiqueta, valor,
            texto: (paso.prefijo || "") + valor + (paso.sufijo || ""),
            siguiente: paso.siguiente || null, cierra: !!paso.cierra,
            lado: paso.lado};
  }

  // ------------------------------------------------------------------
  tocar(id, numero){
    const opcion = this.opciones().find(o => o.id === id);
    if(!opcion) return null;
    const texto = opcion.tipo === "numero"
      ? opcion.prefijo + numero + opcion.sufijo
      : opcion.texto;
    this.pasos.push({estado: this.estado, id, texto, cierra: opcion.cierra});
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
