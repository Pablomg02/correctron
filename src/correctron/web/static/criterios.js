// Alpine component for the exam configuration tab (criteria with one level of
// sub-criteria). Loaded before Alpine so `editorCriterios` exists when Alpine starts.
(function () {
  "use strict";

  const KNOWN = ["nombre", "tipo", "fecha", "nota_maxima", "decimales", "calculo_total", "criterios"];
  const LETTERS = "abcdefghijklmnopqrstuvwxyz";
  let nextKey = 1;

  function blank(v) {
    return v === undefined || v === null || String(v).trim() === "";
  }

  // A number typed by the user ("7,5" is accepted); text that is not a number is
  // sent as it is so the server reports it.
  function toNumber(v) {
    if (blank(v)) return undefined;
    const n = Number(String(v).trim().replace(",", "."));
    return Number.isFinite(n) ? n : String(v);
  }

  function asText(v) {
    return blank(v) ? "" : String(v);
  }

  function leafFrom(raw) {
    const s = raw && typeof raw === "object" ? raw : {};
    return { _k: nextKey++, id: asText(s.id), nombre: asText(s.nombre), maximo: asText(s.maximo) };
  }

  function criterionFrom(raw) {
    const c = raw && typeof raw === "object" ? raw : {};
    const subs = Array.isArray(c.subcriterios) ? c.subcriterios.map(leafFrom) : [];
    return {
      _k: nextKey++,
      id: asText(c.id),
      nombre: asText(c.nombre),
      maximo: asText(c.maximo),
      peso: blank(c.peso) ? "1" : String(c.peso),
      subcriterios: subs,
    };
  }

  function move(list, index, delta) {
    const target = index + delta;
    if (target < 0 || target >= list.length) return;
    const [item] = list.splice(index, 1);
    list.splice(target, 0, item);
  }

  function fmt(n) {
    if (!Number.isFinite(n)) return "—";
    return String(Math.round(n * 10000) / 10000).replace(".", ",");
  }

  window.editorCriterios = function () {
    const source = JSON.parse(document.getElementById("config-datos").textContent) || {};
    const extra = {};
    Object.keys(source).forEach((key) => {
      if (!KNOWN.includes(key)) extra[key] = source[key];
    });
    return {
      nombre: asText(source.nombre),
      tipo: asText(source.tipo) || "examen",
      fecha: asText(source.fecha),
      nota_maxima: blank(source.nota_maxima) ? "10" : String(source.nota_maxima),
      decimales: blank(source.decimales) ? "2" : String(source.decimales),
      calculo_total: asText(source.calculo_total) || "suma",
      criterios: Array.isArray(source.criterios) ? source.criterios.map(criterionFrom) : [],
      extra: extra,
      explicaciones: {
        suma: "La nota es la suma de las notas de los apartados, sin escalar.",
        ponderada:
          "Cada criterio cuenta como la fracción obtenida de su máximo, ponderada por su peso, y el resultado se escala a la nota máxima.",
        manual: "La nota total se escribe a mano; el desglose por apartados es solo informativo.",
      },

      fmt: fmt,

      groupMax(c) {
        return c.subcriterios.reduce((acc, s) => acc + (Number(toNumber(s.maximo)) || 0), 0);
      },
      get sumaMaximos() {
        return this.criterios.reduce(
          (acc, c) =>
            acc + (c.subcriterios.length ? this.groupMax(c) : Number(toNumber(c.maximo)) || 0),
          0
        );
      },
      get sumaDistinta() {
        const top = Number(toNumber(this.nota_maxima));
        return (
          this.calculo_total === "suma" &&
          this.criterios.length > 0 &&
          Math.abs(this.sumaMaximos - top) > 1e-9
        );
      },

      freeId(base) {
        const taken = new Set();
        this.criterios.forEach((c) => {
          taken.add(c.id);
          c.subcriterios.forEach((s) => taken.add(s.id));
        });
        if (!taken.has(base)) return base;
        let n = 2;
        while (taken.has(base + "_" + n)) n++;
        return base + "_" + n;
      },
      // Put the cursor in the name of an item just added, ready to type over it.
      // `i` is the criterion; with `sub`, its last subcriterion.
      focusName(i, sub) {
        this.$nextTick(() => {
          const item = this.$root.querySelectorAll("li.criterio")[i];
          if (!item) return;
          const names = sub
            ? item.querySelectorAll("ol.subcriterios .c-nombre")
            : item.querySelectorAll(":scope > .criterio-fila > .c-nombre");
          if (names.length) names[names.length - 1].select();
        });
      },
      addCriterion() {
        const n = this.criterios.length + 1;
        this.criterios.push(
          criterionFrom({ id: this.freeId("ej" + n), nombre: "Ejercicio " + n, peso: 1 })
        );
        this.focusName(this.criterios.length - 1, false);
      },
      removeCriterion(i) {
        const c = this.criterios[i];
        const label = c.id || c.nombre || "este criterio";
        if (c.subcriterios.length && !confirm("¿Quitar «" + label + "» y sus subapartados?")) return;
        this.criterios.splice(i, 1);
      },
      moveCriterion(i, delta) {
        move(this.criterios, i, delta);
      },
      addSub(i) {
        const c = this.criterios[i];
        const n = c.subcriterios.length;
        const letter = LETTERS[n] || String(n + 1);
        const first = n === 0;
        c.subcriterios.push(
          leafFrom({
            id: this.freeId((c.id || "ej") + letter),
            nombre: "Apartado " + letter,
            maximo: first ? c.maximo : "",
          })
        );
        this.focusName(i, true);
      },
      removeSub(i, j) {
        const c = this.criterios[i];
        const [removed] = c.subcriterios.splice(j, 1);
        if (!c.subcriterios.length && blank(c.maximo)) c.maximo = removed.maximo;
      },
      moveSub(i, j, delta) {
        move(this.criterios[i].subcriterios, j, delta);
      },

      toConfig() {
        const config = {
          nombre: this.nombre.trim(),
          tipo: this.tipo,
          fecha: this.fecha,
          nota_maxima: toNumber(this.nota_maxima),
          decimales: toNumber(this.decimales),
          calculo_total: this.calculo_total,
          criterios: this.criterios.map((c) => {
            const item = { id: c.id.trim() };
            if (!blank(c.nombre)) item.nombre = c.nombre.trim();
            if (!blank(c.peso)) item.peso = toNumber(c.peso);
            if (c.subcriterios.length) {
              item.subcriterios = c.subcriterios.map((s) => {
                const leaf = { id: s.id.trim() };
                if (!blank(s.nombre)) leaf.nombre = s.nombre.trim();
                if (!blank(s.maximo)) leaf.maximo = toNumber(s.maximo);
                return leaf;
              });
            } else if (!blank(c.maximo)) {
              item.maximo = toNumber(c.maximo);
            }
            return item;
          }),
        };
        Object.keys(config).forEach((key) => {
          if (config[key] === undefined) delete config[key];
        });
        return Object.assign(config, this.extra);
      },
      serialize() {
        this.$refs.salida.value = JSON.stringify(this.toConfig(), null, 2);
      },
    };
  };
})();
