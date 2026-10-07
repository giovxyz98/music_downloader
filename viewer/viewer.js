"use strict";
// Il testo del log (titoli, canali, percorsi) e' dato di terzi: viene scritto SOLO con
// textContent, mai con innerHTML. Sono cliccabili solo i link youtube.com/watch?v=<id>.

const data = window.LOG_DATA || { source: "(nessun dato: esegui prepara_log.py)", cut: 0, records: [] };
const LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"];
const on = new Set(["INFO", "WARNING", "ERROR"]);
const MAX_SHOWN = 4000;
const YT_G = /https:\/\/www\.youtube\.com\/watch\?v=[\w-]{11}/g;
const $ = (id) => document.getElementById(id);

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function appendText(parent, text) {
  let last = 0;
  for (const m of text.matchAll(YT_G)) {
    parent.append(text.slice(last, m.index));
    const a = el("a", m[0]);
    a.href = m[0];
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    parent.append(a);
    last = m.index + m[0].length;
  }
  parent.append(text.slice(last));
}

function render() {
  const q = $("q").value.trim().toLowerCase();
  const counts = {};
  const shown = [];
  for (const r of data.records) {
    counts[r[2]] = (counts[r[2]] || 0) + 1;
    if (on.has(r[2]) && (!q || r[3].toLowerCase().includes(q))) shown.push(r);
  }
  const out = $("out");
  out.replaceChildren();
  const skipped = Math.max(0, shown.length - MAX_SHOWN);
  if (data.cut) out.append(el("div", `(${data.cut} righe più vecchie non incluse)`, "note"));
  if (skipped) out.append(el("div", `Mostro le ultime ${MAX_SHOWN} righe su ${shown.length}: restringi con ricerca o livelli.`, "note"));
  if (!shown.length)
    out.append(el("div", "Nessuna riga. Le righe DEBUG ci sono solo con LOG_LEVEL = DEBUG in config.json.", "note"));
  for (const [d, t, lv, text] of shown.slice(skipped)) {
    const row = el("div", undefined, "l " + lv);
    row.append(el("span", `${d} ${t}  ${lv.padEnd(7)} `, "meta"));
    appendText(row, text);
    out.append(row);
  }
  const bar = $("levels");
  bar.replaceChildren();
  for (const lv of LEVELS) {
    const chip = el("span", `${lv} ${counts[lv] || 0}`, "chip " + lv + (on.has(lv) ? " on" : ""));
    chip.addEventListener("click", () => { on.has(lv) ? on.delete(lv) : on.add(lv); render(); });
    bar.append(chip);
  }
}

$("src").textContent = data.source;
$("q").addEventListener("input", render);
render();
