// Split page (Dividir): an Alpine component that edits the sections of one PDF.
// Loaded without defer, before Alpine starts, so `dividir` exists when Alpine
// initialises the x-data of the page.
(function () {
  "use strict";

  const COLORES = 6;

  // Notice in #avisos, same markup as the grading web. Text is set as text, never as HTML.
  function aviso(nivel, texto, recargar) {
    const article = document.createElement("article");
    article.className = "aviso-" + nivel;
    const cerrar = document.createElement("button");
    cerrar.type = "button";
    cerrar.className = "cerrar-aviso";
    cerrar.setAttribute("aria-label", "Cerrar aviso");
    cerrar.textContent = "×";
    cerrar.addEventListener("click", () => article.remove());
    const span = document.createElement("span");
    span.textContent = texto;
    article.append(cerrar, span);
    if (recargar) {
      const boton = document.createElement("button");
      boton.type = "button";
      boton.className = "outline";
      boton.textContent = "Recargar";
      boton.addEventListener("click", () => location.reload());
      article.append(" ", boton);
    }
    document.getElementById("avisos").append(article);
  }

  // Sends a request and resolves to { ok, status, body }; null when the server cannot be reached.
  async function peticion(url, opciones) {
    let respuesta;
    try {
      respuesta = await fetch(url, opciones);
    } catch (err) {
      aviso("error", "No se puede conectar con Correctron. ¿Sigue en marcha el servidor?", false);
      return null;
    }
    const body = await respuesta.json().catch(() => ({}));
    return { ok: respuesta.ok, status: respuesta.status, body: body };
  }

  // The part of the state that the sidecar stores, in a fixed shape, for comparisons.
  function canonico(secciones, girar) {
    return JSON.stringify({
      secciones: secciones.map((s) => ({ nombre: s.nombre, desde: s.desde, hasta: s.hasta })),
      girar: girar.slice(),
    });
  }

  function textoPaginas(desde, hasta) {
    return desde === hasta ? "Página " + desde : "Páginas " + desde + "–" + hasta;
  }

  window.dividir = function () {
    const estado = JSON.parse(document.getElementById("estado").textContent);
    const enc = encodeURIComponent(estado.pdf);
    const urlSecciones = "/api/secciones?pdf=" + enc;
    const urlExportar = "/api/secciones/exportar?pdf=" + enc;

    // Kept out of Alpine's reactive data: a Promise behind the proxy cannot be chained.
    let version = estado.version; // version token of the sidecar on disk
    let confirmado = canonico(estado.secciones, estado.girar); // last state the server accepted
    let cola = Promise.resolve(); // saves and exports run one at a time, in order

    return {
      paginas: Array.from({ length: estado.paginas }, (_, i) => i + 1),
      secciones: JSON.parse(JSON.stringify(estado.secciones)),
      girar: estado.girar.slice(),
      nombre: "",
      ancla: null, // first page of a range being picked, or null
      seleccion: null, // { desde, hasta } or null
      activa: -1, // section highlighted in the list, or -1
      ampliada: null, // page open in the zoom dialog
      exportados: [],

      // --- reading the state ---

      seccionDe(p) {
        return this.secciones.findIndex((s) => s.desde <= p && p <= s.hasta);
      },

      enSeleccion(p) {
        return this.seleccion !== null && this.seleccion.desde <= p && p <= this.seleccion.hasta;
      },

      girada(p) {
        return this.girar.includes(p);
      },

      claseDe(p) {
        const i = this.seccionDe(p);
        return i < 0 ? "" : "en-seccion color-" + (i % COLORES);
      },

      urlPagina(p, ancho) {
        return "/pagina?pdf=" + enc + "&n=" + p + "&ancho=" + ancho;
      },

      urlArchivo(ruta) {
        return "/archivo/" + ruta.split("/").map(encodeURIComponent).join("/");
      },

      rango(s) {
        return s.desde === s.hasta ? "pág. " + s.desde : "págs. " + s.desde + "–" + s.hasta;
      },

      textoSeleccion() {
        if (this.seleccion === null) return "Ninguna página seleccionada";
        return textoPaginas(this.seleccion.desde, this.seleccion.hasta);
      },

      textoExportadas() {
        const n = this.exportados.length;
        if (n === 0) return ""; // x-text evaluates this even while the panel is hidden
        const carpeta = this.exportados[0].split("/").slice(0, -1).join("/") + "/";
        const cuenta = n === 1 ? "Exportada 1 sección" : "Exportadas " + n + " secciones";
        return cuenta + " en " + carpeta;
      },

      // --- selecting pages (D10) ---

      pulsar(p) {
        const i = this.seccionDe(p);
        if (i >= 0) {
          this.ancla = null;
          this.seleccion = null;
          this.activa = i;
          this.$nextTick(() => {
            const fila = document.getElementById("seccion-" + i);
            if (fila) fila.scrollIntoView({ block: "nearest" });
          });
          return;
        }
        this.activa = -1;
        if (this.ancla === null) {
          this.ancla = p;
          this.seleccion = { desde: p, hasta: p };
        } else {
          this.seleccion = { desde: Math.min(this.ancla, p), hasta: Math.max(this.ancla, p) };
          this.ancla = null;
        }
      },

      limpiar() {
        this.ancla = null;
        this.seleccion = null;
        this.activa = -1;
      },

      solapa() {
        if (this.seleccion === null) return false;
        const sel = this.seleccion;
        return this.secciones.some((s) => s.desde <= sel.hasta && sel.desde <= s.hasta);
      },

      puedeSeccionar() {
        return this.seleccion !== null && !this.solapa();
      },

      // --- changing the sections ---

      seccionar() {
        if (!this.puedeSeccionar()) return;
        const nombre = this.nombre.trim();
        if (nombre === "") {
          aviso("aviso", "Escribe un nombre.", false);
          this.$refs.nombre.focus();
          return;
        }
        const repetida = this.secciones.some(
          (s) => s.nombre.trim().toLowerCase() === nombre.toLowerCase()
        );
        if (repetida) {
          aviso("error", "Ya hay una sección con el nombre «" + nombre + "».", false);
          return;
        }
        this.secciones.push({ nombre: nombre, desde: this.seleccion.desde, hasta: this.seleccion.hasta });
        this.secciones.sort((a, b) => a.desde - b.desde);
        this.nombre = "";
        this.limpiar();
        this.guardar();
        this.$nextTick(() => this.$refs.nombre.focus());
      },

      renombrar(i) {
        this.secciones[i].nombre = this.secciones[i].nombre.trim();
        this.guardar();
      },

      quitar(i) {
        this.secciones.splice(i, 1);
        this.activa = -1;
        this.guardar();
      },

      alternarGiro(p) {
        if (this.girar.includes(p)) {
          this.girar = this.girar.filter((x) => x !== p);
        } else {
          this.girar = [...this.girar, p].sort((a, b) => a - b);
        }
        this.guardar();
      },

      ampliar(p) {
        this.ancla = null;
        this.ampliada = p;
        this.$refs.zoom.showModal();
      },

      cerrarSiFondo(ev) {
        if (ev.target === ev.currentTarget) this.$refs.zoom.close();
      },

      // --- saving and exporting ---

      guardar() {
        cola = cola.then(() => this.enviar());
        return cola;
      },

      async enviar() {
        const actual = canonico(this.secciones, this.girar);
        if (actual === confirmado) return;
        const r = await peticion(urlSecciones, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ version: version, secciones: this.secciones, girar: this.girar }),
        });
        if (r === null) {
          this.restaurar();
        } else if (!r.ok) {
          this.restaurar();
          aviso("error", r.body.error || "No se han guardado los cambios.", r.status === 409);
        } else {
          version = r.body.version;
          confirmado = actual;
        }
      },

      restaurar() {
        const previo = JSON.parse(confirmado);
        this.secciones = previo.secciones;
        this.girar = previo.girar;
      },

      exportar() {
        cola = cola.then(() => this.enviarExportacion());
        return cola;
      },

      async enviarExportacion() {
        this.exportados = [];
        const r = await peticion(urlExportar, { method: "POST" });
        if (r === null) return;
        if (!r.ok) {
          aviso("error", r.body.error || "No se han podido exportar las secciones.", false);
          return;
        }
        this.exportados = r.body.archivos;
      },
    };
  };
})();
