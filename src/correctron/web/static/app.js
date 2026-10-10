// Correctron: small client behaviours on top of htmx.
(function () {
  "use strict";

  const AUTO_HIDE_MS = 6000;

  // htmx copies the old element's classes onto its replacement while it "settles". When a
  // swap replaces the very field that sent the request (a rejected edit puts the stored
  // value back), the replacement could keep the "busy" class htmx-request for good.
  // No transition here relies on settling classes, so only settle size and style.
  if (window.htmx) htmx.config.attributesToSettle = ["style", "width", "height"];

  function noticesBox() {
    return document.getElementById("avisos");
  }

  // Every notice gets a close button; "ok" and "info" notices fade out on their own.
  function decorate(notice) {
    if (!(notice instanceof HTMLElement) || notice.dataset.listo) return;
    notice.dataset.listo = "1";
    const close = document.createElement("button");
    close.type = "button";
    close.className = "cerrar-aviso";
    close.setAttribute("aria-label", "Cerrar aviso");
    close.textContent = "×";
    close.addEventListener("click", () => notice.remove());
    notice.prepend(close);
    if (notice.matches(".aviso-ok, .aviso-info")) {
      setTimeout(() => notice.remove(), AUTO_HIDE_MS);
    }
  }

  function addNotice(level, html, withReload) {
    const notice = document.createElement("article");
    notice.className = "aviso-" + level;
    notice.innerHTML = html;
    if (withReload && !notice.querySelector("button")) {
      const reload = document.createElement("button");
      reload.type = "button";
      reload.className = "outline";
      reload.textContent = "Recargar";
      reload.addEventListener("click", () => location.reload());
      notice.append(" ", reload);
    }
    noticesBox().append(notice);
  }

  document.addEventListener("DOMContentLoaded", () => {
    // A notice that came with a redirect (?ok=…) is shown once: drop it from the address bar.
    const url = new URL(location.href);
    if (url.searchParams.has("ok")) {
      url.searchParams.delete("ok");
      history.replaceState(null, "", url);
    }
    const box = noticesBox();
    box.querySelectorAll("article").forEach(decorate);
    new MutationObserver((mutations) => {
      mutations.forEach((m) => m.addedNodes.forEach(decorate));
    }).observe(box, { childList: true });
  });

  // Errors (400, 404, 409…) go to the notices; a 409 offers to reload.
  document.addEventListener("htmx:responseError", (ev) => {
    const xhr = ev.detail.xhr;
    const body = xhr.responseText || "Error " + xhr.status;
    addNotice("error", body, xhr.status === 409);
  });

  document.addEventListener("htmx:sendError", () => {
    addNotice("error", "No se puede conectar con Correctron. ¿Sigue en marcha el servidor?", false);
  });

  // After a successful inline save: clear the invalid marks of the row and flash the field.
  document.addEventListener("htmx:afterRequest", (ev) => {
    const xhr = ev.detail.xhr;
    if (!ev.detail.successful || !xhr || xhr.getResponseHeader("HX-Retarget")) return;
    const elt = ev.detail.elt;
    const row = elt.closest && elt.closest("table.rejilla tr");
    if (row) {
      row.querySelectorAll("[aria-invalid]").forEach((el) => el.removeAttribute("aria-invalid"));
    }
    if (elt.matches && elt.matches("input, select")) {
      elt.classList.add("guardado");
      setTimeout(() => elt.classList.remove("guardado"), 900);
    }
  });

  // Grid navigation: Enter / ArrowDown go to the same column in the next row,
  // Shift+Enter / ArrowUp to the previous one. Disabled cells (NP rows) are skipped.
  document.addEventListener("keydown", (ev) => {
    const input = ev.target;
    if (!(input instanceof HTMLInputElement) || !input.closest("table.rejilla")) return;
    let step = 0;
    if (ev.key === "Enter") step = ev.shiftKey ? -1 : 1;
    else if (ev.key === "ArrowDown") step = 1;
    else if (ev.key === "ArrowUp") step = -1;
    if (!step || ev.altKey || ev.ctrlKey || ev.metaKey) return;
    const cell = input.closest("td");
    const row = cell && cell.parentElement;
    if (!row) return;
    ev.preventDefault();
    const column = cell.cellIndex;
    let next = step > 0 ? row.nextElementSibling : row.previousElementSibling;
    while (next) {
      const target = next.cells[column] && next.cells[column].querySelector("input:not([disabled])");
      if (target) {
        target.focus();
        target.select();
        return;
      }
      next = step > 0 ? next.nextElementSibling : next.previousElementSibling;
    }
    // Last row: leave the cell so its value is saved.
    if (ev.key === "Enter") input.blur();
  });

  // Long feedback dialog: open after its content arrives, close when the server says so.
  document.addEventListener("htmx:afterSwap", (ev) => {
    if (ev.detail.target && ev.detail.target.id === "feedback-contenido") {
      const dialog = document.getElementById("feedback");
      if (!dialog.open) dialog.showModal();
      const area = dialog.querySelector("textarea");
      if (area) area.focus();
    }
  });

  document.addEventListener("cerrar-feedback", () => {
    const dialog = document.getElementById("feedback");
    if (dialog && dialog.open) dialog.close();
  });
})();
