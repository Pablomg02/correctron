// Anonymize page (Anonimizar): an Alpine component that edits the rectangles of one PDF
// and exports flattened copies. Loaded without defer, before Alpine starts, so
// `anonimizar` exists when Alpine initialises the x-data of the page.
(function () {
  "use strict";

  // Smallest drag, as a fraction of the page, that creates a rectangle (D15).
  const MINIMO = 0.005;

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
  function canonico(recuadros) {
    return JSON.stringify(
      recuadros.map((r) => ({
        pagina: r.pagina,
        x: r.x,
        y: r.y,
        ancho: r.ancho,
        alto: r.alto,
        color: r.color,
      }))
    );
  }

  function acotar(valor) {
    return Math.min(1, Math.max(0, valor));
  }

  // Fractions are stored with four decimals, so the sidecar stays readable.
  function redondear(valor) {
    return Math.round(valor * 10000) / 10000;
  }

  // Keys typed in a field belong to the field, not to the page.
  function esCampo(elemento) {
    return (
      elemento instanceof HTMLElement &&
      (elemento.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(elemento.tagName))
    );
  }

  window.anonimizar = function () {
    const estado = JSON.parse(document.getElementById("estado").textContent);
    const enc = encodeURIComponent(estado.pdf);
    const urlRecuadros = "/api/recuadros?pdf=" + enc;
    const urlAnonimizar = "/api/anonimizar?pdf=" + enc + "&todos=";

    // Kept out of Alpine's reactive data: a Promise behind the proxy cannot be chained.
    let version = estado.version; // version token of the sidecar on disk
    let confirmado = canonico(estado.recuadros); // last state the server accepted
    let cola = Promise.resolve(); // saves and exports run one at a time, in order

    return {
      total: estado.paginas,
      numeros: Array.from({ length: estado.paginas }, (_, i) => i + 1),
      recuadros: JSON.parse(JSON.stringify(estado.recuadros)),
      actual: 1, // page shown in the large view
      color: "#ffffff", // colour for new rectangles
      seleccion: null, // index in `recuadros` of the selected rectangle, or null
      arrastre: null, // { x0, y0, x1, y1 } as fractions while drawing, or null
      pipeta: false, // eyedropper mode: the next click on the page takes its colour
      ocupado: false, // an export is running
      exportados: [],

      // --- reading the state ---

      urlPagina(p, ancho) {
        return "/pagina?pdf=" + enc + "&n=" + p + "&ancho=" + ancho;
      },

      urlArchivo(ruta) {
        return "/archivo/" + ruta.split("/").map(encodeURIComponent).join("/");
      },

      // Indices of the rectangles drawn on the current page: its own and the "todas" ones (D13).
      visibles() {
        const indices = [];
        this.recuadros.forEach((r, i) => {
          if (r.pagina === this.actual || r.pagina === "todas") indices.push(i);
        });
        return indices;
      },

      // Thumbnail badge: rectangles that apply to page p, own and "todas".
      cuantos(p) {
        return this.recuadros.filter((r) => r.pagina === p || r.pagina === "todas").length;
      },

      estilo(r) {
        return {
          left: r.x * 100 + "%",
          top: r.y * 100 + "%",
          width: r.ancho * 100 + "%",
          height: r.alto * 100 + "%",
          background: r.color,
        };
      },

      estiloArrastre() {
        const a = this.arrastre;
        if (a === null) return {};
        return {
          left: Math.min(a.x0, a.x1) * 100 + "%",
          top: Math.min(a.y0, a.y1) * 100 + "%",
          width: Math.abs(a.x1 - a.x0) * 100 + "%",
          height: Math.abs(a.y1 - a.y0) * 100 + "%",
        };
      },

      textoExportadas() {
        const n = this.exportados.length;
        if (n === 0) return ""; // x-text evaluates this even while the panel is hidden
        const carpeta = this.exportados[0].split("/").slice(0, -1).join("/") + "/";
        const cuenta = n === 1 ? "Anonimizado 1 PDF" : "Anonimizados " + n + " PDFs";
        return cuenta + " en " + carpeta;
      },

      // Position of a pointer as fractions of the large page, clamped to [0, 1] (D15).
      fraccion(ev) {
        const caja = this.$refs.lienzo.getBoundingClientRect();
        if (caja.width === 0 || caja.height === 0) return { x: 0, y: 0 };
        return {
          x: acotar((ev.clientX - caja.left) / caja.width),
          y: acotar((ev.clientY - caja.top) / caja.height),
        };
      },

      // --- pages ---

      irA(p) {
        if (p < 1 || p > this.total || p === this.actual) return;
        this.actual = p;
        this.seleccion = null;
        this.arrastre = null;
        this.$nextTick(() => {
          const miniatura = document.getElementById("miniatura-" + p);
          if (miniatura) miniatura.scrollIntoView({ block: "nearest" });
        });
      },

      // --- drawing and selecting (D15) ---

      pulsarLienzo(ev) {
        if (ev.button !== 0) return;
        if (this.pipeta) {
          this.muestrear(ev);
          return;
        }
        const p = this.fraccion(ev);
        this.seleccion = null;
        this.arrastre = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
        this.$refs.lienzo.setPointerCapture(ev.pointerId);
      },

      pulsarRecuadro(i, ev) {
        if (ev.button !== 0) return;
        if (this.pipeta) {
          this.muestrear(ev);
          return;
        }
        this.seleccion = i;
      },

      moverArrastre(ev) {
        if (this.arrastre === null) return;
        const p = this.fraccion(ev);
        this.arrastre.x1 = p.x;
        this.arrastre.y1 = p.y;
      },

      soltarArrastre(ev) {
        if (this.arrastre === null) return;
        this.moverArrastre(ev);
        const a = this.arrastre;
        this.arrastre = null;
        if (Math.abs(a.x1 - a.x0) < MINIMO || Math.abs(a.y1 - a.y0) < MINIMO) return;
        // Edges are rounded first and the size is taken from them, so x + ancho never exceeds 1.
        const x0 = redondear(Math.min(a.x0, a.x1));
        const x1 = redondear(Math.max(a.x0, a.x1));
        const y0 = redondear(Math.min(a.y0, a.y1));
        const y1 = redondear(Math.max(a.y0, a.y1));
        this.recuadros.push({
          pagina: this.actual,
          x: x0,
          y: y0,
          ancho: redondear(x1 - x0),
          alto: redondear(y1 - y0),
          color: this.color,
        });
        this.seleccion = this.recuadros.length - 1;
        this.guardar();
      },

      cancelarArrastre() {
        this.arrastre = null;
      },

      puedeCopiar() {
        return this.seleccion !== null && this.recuadros[this.seleccion].pagina !== "todas";
      },

      copiarATodas() {
        if (!this.puedeCopiar()) return;
        this.recuadros[this.seleccion].pagina = "todas";
        this.guardar();
      },

      quitarSeleccionado() {
        if (this.seleccion === null) return;
        this.recuadros.splice(this.seleccion, 1);
        this.seleccion = null;
        this.guardar();
      },

      // --- colour and eyedropper (D14) ---

      alternarPipeta() {
        this.pipeta = !this.pipeta;
        this.arrastre = null;
      },

      // Average of the 5x5 pixels around the click, read from the page image at its natural size.
      muestrear(ev) {
        this.pipeta = false;
        const img = this.$refs.lienzo.querySelector("img");
        if (!img || !img.complete || img.naturalWidth === 0) {
          aviso("aviso", "La página todavía se está cargando. Vuelve a intentarlo.", false);
          return;
        }
        const p = this.fraccion(ev);
        const ancho = img.naturalWidth;
        const alto = img.naturalHeight;
        const cx = Math.min(ancho - 1, Math.floor(p.x * ancho));
        const cy = Math.min(alto - 1, Math.floor(p.y * alto));
        const canvas = document.createElement("canvas");
        canvas.width = ancho;
        canvas.height = alto;
        const ctx = canvas.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(img, 0, 0, ancho, alto);
        const x0 = Math.max(0, cx - 2);
        const y0 = Math.max(0, cy - 2);
        const x1 = Math.min(ancho - 1, cx + 2);
        const y1 = Math.min(alto - 1, cy + 2);
        const datos = ctx.getImageData(x0, y0, x1 - x0 + 1, y1 - y0 + 1).data;
        let rojo = 0;
        let verde = 0;
        let azul = 0;
        let n = 0;
        for (let i = 0; i < datos.length; i += 4) {
          rojo += datos[i];
          verde += datos[i + 1];
          azul += datos[i + 2];
          n += 1;
        }
        const hex = [rojo, verde, azul]
          .map((v) => Math.round(v / n).toString(16).padStart(2, "0"))
          .join("");
        this.fijarColor("#" + hex);
      },

      // The colour for new rectangles, and for the selected one.
      fijarColor(hex) {
        this.color = hex;
        if (this.seleccion !== null) {
          this.recuadros[this.seleccion].color = hex;
          this.guardar();
        }
      },

      // --- keys ---

      teclas(ev) {
        if (esCampo(ev.target)) return;
        if (ev.key === "Escape") {
          this.arrastre = null;
          this.pipeta = false;
          this.seleccion = null;
        } else if (ev.key === "Delete") {
          ev.preventDefault();
          this.quitarSeleccionado();
        } else if (ev.key === "ArrowLeft") {
          ev.preventDefault();
          this.irA(this.actual - 1);
        } else if (ev.key === "ArrowRight") {
          ev.preventDefault();
          this.irA(this.actual + 1);
        }
      },

      // --- saving and exporting ---

      guardar() {
        cola = cola.then(() => this.enviar());
        return cola;
      },

      async enviar() {
        const actual = canonico(this.recuadros);
        if (actual === confirmado) return;
        const r = await peticion(urlRecuadros, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ version: version, recuadros: this.recuadros }),
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
        this.recuadros = JSON.parse(confirmado);
        this.seleccion = null;
      },

      exportar(todos) {
        this.ocupado = true;
        cola = cola.then(() => this.enviarExportacion(todos));
        return cola;
      },

      async enviarExportacion(todos) {
        this.exportados = [];
        try {
          const r = await peticion(urlAnonimizar + (todos ? "1" : "0"), { method: "POST" });
          if (r === null) return;
          if (!r.ok) {
            aviso("error", r.body.error || "No se ha podido anonimizar el PDF.", false);
            return;
          }
          this.exportados = r.body.archivos;
          r.body.avisos.forEach((texto) => aviso("aviso", texto, false));
        } finally {
          this.ocupado = false;
        }
      },
    };
  };
})();
