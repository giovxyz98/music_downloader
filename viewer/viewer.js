"use strict";
// Tutto il testo del log (titoli, canali, percorsi) e' dato di terzi: viene scritto
// SOLO con textContent, mai con innerHTML. Gli unici link sono youtube.com/watch?v=<id>.

const STATUS = {
  "OK":            { c: "var(--ok)",   label: "OK" },
  "OK*":           { c: "var(--warn)", label: "OK*" },
  "PRESENTE":      { c: "var(--pres)", label: "GIÀ" },
  "NON SCARICATA": { c: "var(--bad)",  label: "NO" },
  "FALLITA":       { c: "var(--bad)",  label: "FAIL" },
  "?":             { c: "var(--dim)",  label: "?" },
};
const YT = /^https:\/\/www\.youtube\.com\/watch\?v=[\w-]{11}$/;

const data = window.LOG_DATA || { source: "(nessun dato: esegui prepara_log.py)", runs: [] };
const $ = (id) => document.getElementById(id);
const active = new Set(Object.keys(STATUS));

function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text !== undefined) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}

function link(url) {
  if (!YT.test(url)) return el("span", url);
  const a = el("a", url);
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}

function kv(label, valueNode) {
  const d = el("div", undefined, "kv");
  d.append(el("i", label), valueNode);
  return d;
}

function candidates(song) {
  const t = el("table");
  const head = t.insertRow();
  ["#", "score", "views", "canale", "titolo", "id", ""].forEach((h) => head.append(el("th", h)));
  for (const c of song.candidates) {
    const tr = t.insertRow();
    const url = "https://www.youtube.com/watch?v=" + c.id;
    if (c.error) tr.className = "fail";
    else if (url === song.download) tr.className = "win";
    [c.rank, c.score, c.views, c.channel, c.title].forEach((v, i) => {
      const td = el("td", String(v));
      if (i === 4) td.className = "t";
      tr.append(td);
    });
    const idTd = el("td");
    idTd.append(YT.test(url) ? link(url) : el("span", c.id));
    tr.append(idTd, el("td", c.error ? "✗ " + c.error : url === song.download ? "✓ scaricato" : ""));
  }
  return t;
}

function songNode(song) {
  const st = STATUS[song.status] || STATUS["?"];
  const wrap = el("div", undefined, "song");
  wrap.style.setProperty("--c", st.c);
  const row = el("div", undefined, "row");
  row.append(el("span", st.label, "st"));
  const nm = el("span", song.name, "nm");
  const extra = [song.album && "(" + song.album + ")", song.detail && "· " + song.detail,
                 song.kbps && "· " + song.kbps + "k"].filter(Boolean).join(" ");
  if (extra) nm.append(" ", el("small", extra));
  row.append(nm);
  const det = el("div", undefined, "detail");
  if (song.candidates.length) det.append(candidates(song));
  else if (song.cached) det.append(el("div", "classifica non disponibile: link da cache", "note"));
  if (song.scoring) det.append(kv("scoring", link(song.scoring)));
  if (song.download) det.append(kv(song.status === "PRESENTE" ? "presente" : "download", link(song.download)));
  if (song.check) det.append(kv("file", el("span", song.check)));
  if (song.status !== "OK" && song.status !== "OK*" && song.status !== "PRESENTE" && song.detail)
    det.append(kv("motivo", el("span", song.detail)));
  for (const n of song.notes) det.append(el("div", n, "note"));
  det.append(kv("ora", el("span", song.date + " " + song.time)));
  row.append(det);
  row.addEventListener("click", (ev) => { if (ev.target.tagName !== "A") wrap.classList.toggle("open"); });
  wrap.append(row);
  return wrap;
}

function matches(song, q) {
  if (!active.has(song.status in STATUS ? song.status : "?")) return false;
  if (!q) return true;
  const hay = [song.name, song.album, song.detail, song.scoring, song.download,
               ...song.candidates.map((c) => c.channel + " " + c.title + " " + c.id)].join(" ").toLowerCase();
  return hay.includes(q);
}

function render() {
  const out = $("out");
  out.replaceChildren();
  const q = $("q").value.trim().toLowerCase();
  const idx = $("run").value;
  const runs = idx === "all" ? data.runs : [data.runs[Number(idx)]].filter(Boolean);
  if (!runs.length) out.append(el("div", "Nessun lancio nel log.", "empty"));
  const counts = {};
  for (const run of runs) {
    const box = el("div", undefined, "run");
    box.append(el("h2", `${run.date} ${run.start}${run.end ? " → " + run.end : ""} · ${run.total} tracce`));
    box.append(el("div", run.dest + (run.summary ? "  —  " + run.summary : ""), "meta"));
    const shown = run.songs.filter((s) => matches(s, q));
    for (const s of run.songs) counts[s.status] = (counts[s.status] || 0) + 1;
    if (!run.songs.length)
      box.append(el("div", "Nessun blocco canzone (lancio col formato di log precedente).", "empty"));
    else if (!shown.length) box.append(el("div", "Nessuna canzone con questi filtri.", "empty"));
    shown.forEach((s) => box.append(songNode(s)));
    if (run.events.length) {
      const d = el("details", undefined, "events");
      d.append(el("summary", `avvisi/errori fuori dai blocchi (${run.events.length})`));
      for (const e of run.events) d.append(el("div", `${e.time} [${e.level}] ${e.text}`, "ev " + e.level));
      box.append(d);
    }
    out.append(box);
  }
  renderChips(counts);
}

function renderChips(counts) {
  const bar = $("chips");
  bar.replaceChildren();
  for (const [key, st] of Object.entries(STATUS)) {
    if (key === "?" && !counts["?"]) continue;
    const chip = el("span", undefined, "chip" + (active.has(key) ? " on" : ""));
    chip.style.setProperty("--c", st.c);
    chip.append(el("b", st.label), " " + (counts[key] || 0));
    chip.addEventListener("click", () => { active.has(key) ? active.delete(key) : active.add(key); render(); });
    bar.append(chip);
  }
}

$("src").textContent = data.source;
const sel = $("run");
sel.append(new Option("tutti i lanci", "all"));
data.runs.forEach((r, i) => sel.append(new Option(`${r.date} ${r.start} · ${r.total} tracce · ${r.songs.length} blocchi`, String(i))));
const lastWithSongs = data.runs.map((r) => r.songs.length > 0).lastIndexOf(true);
sel.value = lastWithSongs >= 0 ? String(lastWithSongs) : "all";
sel.addEventListener("change", render);
$("q").addEventListener("input", render);
render();
