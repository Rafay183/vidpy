/* vidpy Studio — browser editor. Plain JS, no build step. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (tag, attrs = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") e.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(k));
  return e;
};
const api = async (url, opts = {}) => {
  const o = { ...opts };
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers = { "Content-Type": "application/json" }; delete o.json; }
  const r = await fetch(url, o);
  const ct = r.headers.get("content-type") || "";
  const data = ct.includes("json") ? await r.json() : await r.blob();
  if (!r.ok) throw new Error((data && data.error) || r.statusText);
  return data;
};
const uid = () => Math.random().toString(16).slice(2, 10);
const clone = (x) => JSON.parse(JSON.stringify(x));
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const fmtT = (t) => {
  t = Math.max(0, t || 0);
  const hh = Math.floor(t / 3600), mm = Math.floor((t % 3600) / 60), ss = Math.floor(t % 60), cs = Math.floor((t % 1) * 100);
  return [hh, mm, ss].map((v) => String(v).padStart(2, "0")).join(":") + "." + String(cs).padStart(2, "0");
};
const r3 = (v) => Math.round(v * 1000) / 1000;
function toast(msg, ms = 2600) {
  const t = h("div", { class: "toast" }, msg);
  document.body.append(t);
  setTimeout(() => t.remove(), ms);
}

/* ------------------------------------------------------------------ state */
const S = {
  project: null, media: [], byPath: {}, catalog: null, sel: null, t: 0, zoom: 60,
  undo: [], redo: [], dirty: false, savedName: null,
  preview: { url: null, start: 0, end: 0, valid: false, job: null },
};

function newProject(name = "Untitled") {
  return { name, width: 1920, height: 1080, fps: 30, background: "#000000", clips: [], overlays: [], texts: [], audio: [],
           effects: [], audio_effects: [], subtitles: null, version: 1 };
}
const D = {
  clip: () => ({ id: uid(), src: "", kind: "auto", in_point: 0, out_point: null, duration: null, color: "#000000", speed: 1,
                 reverse: false, volume: 1, mute: false, fit: "fit", effects: [], audio_effects: [], transition: null, name: "",
                 t_offset: 0, full_duration: null }),
  overlay: () => ({ id: uid(), src: "", start: 0, duration: null, in_point: 0, x: 0.5, y: 0.5, scale: 0.3, opacity: 1, rotation: 0,
                    fade_in: 0, fade_out: 0, chroma_key: null, use_audio: false, volume: 1, effects: [], layer: 1, name: "", t_offset: 0, full_duration: null }),
  text: () => ({ id: uid(), text: "Title", start: 0, duration: 3, preset: "center", x: 0.5, y: 0.5, size: 72, color: "#ffffff", font: "",
                 box: false, box_color: "#000000", box_opacity: 0.55, outline: 0, outline_color: "#000000", shadow: 2, align: "center",
                 fade_in: 0.3, fade_out: 0.3, animation: "fade", name: "" }),
  audio: () => ({ id: uid(), src: "", start: 0, in_point: 0, out_point: null, volume: 1, speed: 1, fade_in: 0, fade_out: 0,
                  loop: false, duck: false, effects: [], name: "" }),
};

/* ------------------------------------------------------------------ timing (mirrors project.py) */
const P = () => S.project;
const mediaOf = (src) => S.byPath[src];
const nameOf = (src) => (mediaOf(src) || {}).name || (src || "").split(/[\\/]/).pop();
function clipKind(c) {
  if (c.kind && c.kind !== "auto") return c.kind;
  if (!c.src) return "color";
  const m = mediaOf(c.src);
  return m ? m.kind : "video";
}
function clipSpan(c) {
  const k = clipKind(c);
  if (k === "image" || k === "color") return [0, +(c.duration || 5)];
  const total = (mediaOf(c.src) || {}).duration || 0;
  const a = clamp(c.in_point || 0, 0, Math.max(total - 0.04, 0));
  const b = c.out_point == null ? total : clamp(c.out_point, a + 0.04, total);
  return [a, b];
}
function clipLen(c) {
  const [a, b] = clipSpan(c);
  const k = clipKind(c);
  return k === "image" || k === "color" ? b - a : (b - a) / Math.max(c.speed || 1, 0.01);
}
function transDur(i) {
  const cs = P().clips, c = cs[i];
  if (!c || !c.transition || i >= cs.length - 1) return 0;
  return Math.max(0, Math.min(+c.transition.duration || 1, clipLen(c) - 0.05, clipLen(cs[i + 1]) - 0.05));
}
function layout() {
  const out = []; let t = 0;
  P().clips.forEach((c, i) => {
    const L = clipLen(c);
    out.push({ c, start: t, len: L, i });
    t += L;
    if (i < P().clips.length - 1) t -= transDur(i);
  });
  return out;
}
function ovLen(o) {
  if (o.duration != null) return +o.duration;
  const m = mediaOf(o.src) || {};
  return m.kind === "image" ? 5 : Math.max((m.duration || 5) - (o.in_point || 0), 0.04);
}
function audLen(a, T) {
  if (a.loop && T) return Math.max(T - a.start, 0.04);
  const m = mediaOf(a.src) || {};
  const b = a.out_point == null ? (m.duration || 0) : Math.min(a.out_point, m.duration || a.out_point);
  return Math.max(b - (a.in_point || 0), 0.04) / Math.max(a.speed || 1, 0.01);
}
function mainLen() { const l = layout(); return l.length ? l[l.length - 1].start + l[l.length - 1].len : 0; }
function duration() {
  const p = P();
  let ends = [mainLen()];
  p.overlays.forEach((o) => ends.push(o.start + ovLen(o)));
  p.texts.forEach((t) => ends.push(t.start + t.duration));
  p.audio.forEach((a) => { if (!a.loop) ends.push(a.start + audLen(a)); });
  return Math.max(0, ...ends);
}

/* ------------------------------------------------------------------ history */
let lastCommitKey = null, lastCommitAt = 0;
function commit(key = null) {
  const now = Date.now();
  if (!(key && key === lastCommitKey && now - lastCommitAt < 700)) {
    S.undo.push(JSON.stringify(S.project));
    if (S.undo.length > 150) S.undo.shift();
    S.redo = [];
  }
  lastCommitKey = key; lastCommitAt = now;
}
function changed(opts = {}) {
  S.dirty = true; S.preview.valid = false;
  $("#saveState").textContent = "● unsaved";
  if (!opts.noTimeline) renderTimeline();
  if (!opts.noInspector) renderInspector();
  refreshFrame();
}
function undo() { if (!S.undo.length) return; S.redo.push(JSON.stringify(S.project)); S.project = JSON.parse(S.undo.pop()); afterLoad(); }
function redo() { if (!S.redo.length) return; S.undo.push(JSON.stringify(S.project)); S.project = JSON.parse(S.redo.pop()); afterLoad(); }
function afterLoad() { $("#projName").value = S.project.name; syncCanvasSel(); changed(); }

/* ------------------------------------------------------------------ selection helpers */
function findSel() {
  if (!S.sel) return null;
  const p = P(), coll = { clip: p.clips, overlay: p.overlays, text: p.texts, audio: p.audio }[S.sel.type];
  return coll ? coll.find((x) => x.id === S.sel.id) : null;
}
function select(type, id) { S.sel = type ? { type, id } : null; renderTimeline(); renderInspector(); }

/* ------------------------------------------------------------------ boot */
async function boot() {
  const [cat, info] = await Promise.all([api("/api/catalog"), api("/api/info")]);
  S.catalog = cat; S.info = info;
  await loadMedia();
  const qp = new URLSearchParams(location.search).get("project");
  const last = qp || localStorage.getItem("vidpy:last");
  S.project = newProject();
  if (last) {
    try { S.project = Object.assign(newProject(), await api("/api/projects/" + encodeURIComponent(last))); S.savedName = last; } catch (e) { /* ignore */ }
    if (qp) { localStorage.setItem("vidpy:last", qp); history.replaceState(null, "", "/"); }
  }
  buildCanvasSel(); buildLibraries(); bindUI();
  afterLoad();
  S.dirty = false; $("#saveState").textContent = S.savedName ? "saved" : "";
  setInterval(() => { if (S.dirty && S.savedName) save(true); }, 15000);
  setInterval(pollJobs, 800);
}

async function loadMedia() {
  const r = await api("/api/media");
  S.media = r.media; S.byPath = {};
  for (const m of S.media) S.byPath[m.path] = m;
  renderMedia();
}

/* ------------------------------------------------------------------ media library */
function renderMedia() {
  const list = $("#mediaList");
  list.innerHTML = "";
  if (!S.media.length) list.append(h("p", { class: "hint", style: { gridColumn: "1/-1" } }, "No media yet."));
  for (const m of S.media) {
    const card = h("div", { class: "mcard", draggable: "true", title: `${m.name}\n${m.width ? m.width + "×" + m.height + " · " : ""}${m.duration ? m.duration.toFixed(2) + "s" : ""}` },
      h("img", { src: `/media/${m.id}/thumb`, loading: "lazy" }),
      h("span", { class: "badge" }, m.kind === "video" ? "🎬 " + fmtT(m.duration).slice(3, 8) : m.kind === "audio" ? "🎵 " + fmtT(m.duration).slice(3, 8) : "🖼"),
      h("div", { class: "acts" },
        m.kind !== "audio" && h("button", { title: "Add to main track", onclick: (e) => { e.stopPropagation(); addMedia(m, "main"); } }, "+"),
        m.kind !== "audio" && h("button", { title: "Add as overlay / PiP at playhead", onclick: (e) => { e.stopPropagation(); addMedia(m, "overlay", S.t); } }, "⧉"),
        m.has_audio && h("button", { title: "Add to audio track at playhead", onclick: (e) => { e.stopPropagation(); addMedia(m, "audio", S.t); } }, "♪"),
        h("button", { title: "Remove from library", onclick: async (e) => { e.stopPropagation(); await api(`/api/media/${m.id}`, { method: "DELETE" }); loadMedia(); } }, "×")),
      h("div", { class: "meta" }, h("div", {}, m.name), h("div", { class: "muted" }, m.width ? `${m.width}×${m.height}` + (m.fps ? ` · ${Math.round(m.fps * 100) / 100}fps` : "") : (m.acodec || ""))));
    card.addEventListener("dragstart", (e) => { e.dataTransfer.setData("vidpy/media", m.id); e.dataTransfer.effectAllowed = "copy"; });
    card.addEventListener("dblclick", () => addMedia(m, m.kind === "audio" ? "audio" : "main"));
    list.append(card);
  }
}

async function uploadFiles(files) {
  for (const f of files) {
    const j = { label: "Uploading " + f.name, status: "running", progress: 0, kind: "upload", id: "up" + uid() };
    localJobs[j.id] = j; renderJobs();
    try {
      await new Promise((res, rej) => {
        const x = new XMLHttpRequest();
        x.open("POST", "/api/upload?name=" + encodeURIComponent(f.name));
        x.upload.onprogress = (e) => { j.progress = e.loaded / e.total; renderJobs(); };
        x.onload = () => (x.status < 300 ? res() : rej(new Error(JSON.parse(x.responseText).error)));
        x.onerror = () => rej(new Error("upload failed"));
        x.send(f);
      });
      j.status = "done"; j.progress = 1;
    } catch (e) { j.status = "error"; j.error = e.message; }
    renderJobs();
    setTimeout(() => { delete localJobs[j.id]; renderJobs(); }, 2500);
  }
  await loadMedia();
}

function addMedia(m, where, at = null) {
  commit();
  const p = P();
  if (where === "main") {
    const c = Object.assign(D.clip(), { src: m.path, name: m.name });
    if (m.kind === "image") c.duration = 5;
    if (p.clips.length === 0 && m.width && m.height && m.kind === "video") {
      // first clip defines the canvas (like Premiere's "new sequence from clip")
      p.width = m.width - (m.width % 2); p.height = m.height - (m.height % 2);
      if (m.fps) p.fps = Math.round(m.fps * 1000) / 1000;
      syncCanvasSel();
    }
    p.clips.push(c); select("clip", c.id);
  } else if (where === "overlay") {
    const o = Object.assign(D.overlay(), { src: m.path, name: m.name, start: r3(at ?? S.t) });
    if (m.kind === "image") o.duration = 5;
    p.overlays.push(o); select("overlay", o.id);
  } else {
    const a = Object.assign(D.audio(), { src: m.path, name: m.name, start: r3(at ?? S.t) });
    p.audio.push(a); select("audio", a.id);
  }
  changed();
}

/* ------------------------------------------------------------------ libraries (effects, transitions, text, smart) */
function buildLibraries() {
  const fxList = (kind, el, q = "") => {
    el.innerHTML = "";
    const items = S.catalog[kind === "video" ? "video_effects" : "audio_effects"].filter((e) =>
      !q || (e.name + " " + e.category + " " + e.id + " " + e.description).toLowerCase().includes(q.toLowerCase()));
    const cats = [...new Set(items.map((e) => e.category))];
    for (const cat of cats) {
      el.append(h("div", { class: "fxcat" }, cat));
      const grid = h("div", { class: "fxgrid" });
      for (const e of items.filter((x) => x.category === cat)) {
        const d = h("div", { class: "fx" + (e.available ? "" : " na"), draggable: e.available ? "true" : "false",
          title: (e.description || e.name) + (e.available ? "\n\nDrag onto a clip, or click to add to the selection." : "\n\nNot available in your FFmpeg build."),
          onclick: () => e.available && addEffectToSelection(kind, e.id) }, e.name);
        d.addEventListener("dragstart", (ev) => ev.dataTransfer.setData("vidpy/" + (kind === "video" ? "vfx" : "afx"), e.id));
        grid.append(d);
      }
      el.append(grid);
    }
  };
  fxList("video", $("#vfxList"));
  fxList("audio", $("#afxList"));
  $$(".search").forEach((inp) => inp.addEventListener("input", () =>
    fxList(inp.dataset.search === "vfx" ? "video" : "audio", inp.dataset.search === "vfx" ? $("#vfxList") : $("#afxList"), inp.value)));

  const tl = $("#transList");
  const cats = [...new Set(S.catalog.transitions.map((t) => t.category))];
  for (const cat of cats) {
    tl.append(h("div", { class: "fxcat" }, cat));
    const grid = h("div", { class: "fxgrid" });
    for (const t of S.catalog.transitions.filter((x) => x.category === cat && x.available)) {
      const d = h("div", { class: "fx", draggable: "true", onclick: () => {
        const c = S.sel && S.sel.type === "clip" ? findSel() : null;
        if (!c) return toast("Select a clip on the main track first");
        setTransition(c, t.id);
      } }, t.name);
      d.addEventListener("dragstart", (ev) => ev.dataTransfer.setData("vidpy/trans", t.id));
      grid.append(d);
    }
    tl.append(grid);
  }

  const T = $("#textTemplates");
  const tpls = [
    ["Big Title", { size: 120, animation: "zoom_pop", shadow: 4, outline: 2 }, "big"],
    ["Subtitle / caption", { preset: "bottom", size: 54, box: true, animation: "fade" }],
    ["Lower third", { preset: "lower_third", size: 56, box: true, box_color: "#7c5cff", box_opacity: 0.85, animation: "slide_left", duration: 4 }],
    ["Typewriter", { size: 72, animation: "typewriter", duration: 4 }],
    ["Slide-up headline", { preset: "top", size: 84, animation: "slide_up", outline: 3 }],
    ["Corner tag", { preset: "top_right", size: 40, box: true, box_opacity: 0.4, animation: "fade", duration: 5 }],
  ];
  for (const [name, props, cls] of tpls) {
    T.append(h("button", { onclick: () => {
      commit();
      const t = Object.assign(D.text(), props, { text: name === "Big Title" ? "BIG TITLE" : name, start: r3(S.t) });
      P().texts.push(t); select("text", t.id); changed();
    } }, h("div", { class: cls || "" }, name), h("div", { class: "muted small" }, `${props.animation} · ${props.preset || "center"}`)));
  }
  renderSmart();
}

function renderSmart() {
  const el = $("#smartPane");
  el.innerHTML = "";
  const mediaSel = h("select", { style: { width: "100%", marginBottom: "6px" } },
    ...S.media.filter((m) => m.kind !== "image").map((m) => h("option", { value: m.id }, m.name)));
  const mid = () => mediaSel.value;
  const run = async (tool, params = {}) => {
    if (!mid()) return toast("Import a video or audio file first");
    const busy = toast("Analysing… ✦", 1500);
    const r = await api("/api/smart/" + tool, { method: "POST", json: { media_id: mid(), params } }).catch((e) => toast("✖ " + e.message, 5000));
    return r;
  };
  const sec = (title, desc, ...btns) => h("div", { class: "smart-sec" }, h("h4", {}, title), h("p", {}, desc), h("div", { class: "bs" }, ...btns));
  el.append(
    h("div", { class: "smart-sec" }, h("h4", {}, "Source media"), mediaSel, h("p", {}, "Pick the file the analysis tools below should work on.")),
    sec("Auto jump-cut", "Removes silences / dead air and puts the talking parts on the timeline.",
      h("button", { onclick: async () => { const r = await run("cut_silences"); if (r) appendClips(r.clips, "Jump-cut"); } }, "✂ Cut silences")),
    sec("Scene detection", "Splits a long video into its individual shots.",
      h("button", { onclick: async () => { const r = await run("split_scenes"); if (r) appendClips(r.clips, "Scenes"); } }, "🎬 Split into shots")),
    sec("Highlight reel", "Finds the most energetic moments and cuts a reel with transitions.",
      h("button", { onclick: async () => { const r = await run("highlights", { clips: 5, clip_length: 3 }); if (r) appendClips(r.clips, "Highlights"); } }, "⚡ 5 × 3s"),
      h("button", { onclick: async () => { const r = await run("highlights", { clips: 8, clip_length: 1.5, transition: "fadewhite" }); if (r) appendClips(r.clips, "Highlights"); } }, "⚡ 8 × 1.5s")),
    sec("Loudness meter", "EBU R128 integrated loudness and true peak.",
      h("button", { onclick: async () => { const r = await run("loudness"); if (r) modal("Loudness", h("pre", {}, JSON.stringify(r, null, 2)), h("p", { class: "muted" }, "YouTube/Spotify target ≈ −14 LUFS, podcasts ≈ −16 LUFS. Use the 'Loudness Normalize' audio effect to hit a target.")); } }, "📈 Analyse")),
    sec("Stabilize & compress", "Creates a new file in your library.",
      h("button", { onclick: async () => { const r = await run("stabilize"); if (r) watchJob(r, true); } }, "🎯 Stabilize"),
      h("button", { onclick: async () => { const mb = prompt("Target size in MB", "25"); if (mb) { const r = await run("compress", { target_mb: +mb }); if (r) watchJob(r, true); } } }, "🗜 Compress to size")),
    sec("Whole project", "One-click polish and re-framing for social platforms.",
      h("button", { onclick: autoEnhance }, "✨ Auto-enhance"),
      h("button", { onclick: () => reframe(1080, 1920) }, "📱 9:16"),
      h("button", { onclick: () => reframe(1080, 1080) }, "◻ 1:1"),
      h("button", { onclick: () => reframe(1920, 1080) }, "🖥 16:9")),
  );
}
function appendClips(clips, label) {
  if (!clips || !clips.length) return toast("Nothing found");
  commit();
  for (const c of clips) P().clips.push(Object.assign(D.clip(), c, { id: uid() }));
  changed(); toast(`${label}: added ${clips.length} clips`);
}
function autoEnhance() {
  commit();
  const p = P();
  p.effects.push({ id: "auto_levels", params: { strength: 0.5 }, enabled: true }, { id: "vibrance", params: { intensity: 0.25 }, enabled: true },
    { id: "denoise", params: { strength: 2 }, enabled: true }, { id: "sharpen", params: { amount: 0.5, size: "5" }, enabled: true });
  p.audio_effects.push({ id: "highpass", params: { freq: 70 }, enabled: true }, { id: "normalize", params: { target_lufs: -14, true_peak: -1.5 }, enabled: true });
  changed(); toast("✨ Auto-enhance added to the project grade & master bus");
}
function reframe(w, hgt) { commit(); P().width = w; P().height = hgt; P().clips.forEach((c) => (c.fit = "fill")); syncCanvasSel(); changed(); }

function addEffectToSelection(kind, id, target = null) {
  const sel = target || (S.sel ? { type: S.sel.type, obj: findSel() } : { type: "project", obj: P() });
  const obj = sel.obj || P();
  const type = sel.obj ? sel.type : "project";
  const eff = { id, params: {}, enabled: true };
  commit();
  if (kind === "video") {
    if (type === "text" || type === "audio") return toast("Video effects apply to clips, overlays or the whole project");
    obj.effects.push(eff);
  } else {
    if (type === "clip") obj.audio_effects.push(eff);
    else if (type === "audio") obj.effects.push(eff);
    else if (type === "project") obj.audio_effects.push(eff);
    else return toast("Audio effects apply to clips, audio tracks or the master bus");
  }
  changed();
  toast(`Added ${id.replace(/_/g, " ")} → ${type === "project" ? "whole project" : obj.name || type}`);
}
function setTransition(c, type) {
  const idx = P().clips.indexOf(c);
  if (idx === P().clips.length - 1) return toast("Transitions blend into the NEXT clip — add another clip after this one");
  commit(); c.transition = { type, duration: (c.transition && c.transition.duration) || 1 }; changed();
}

/* ------------------------------------------------------------------ canvas */
function buildCanvasSel() {
  const sel = $("#canvasSel");
  sel.innerHTML = "";
  for (const [k, v] of Object.entries(S.catalog.canvas_presets)) sel.append(h("option", { value: k }, v.label));
  sel.append(h("option", { value: "custom" }, "Custom…"));
  sel.onchange = () => {
    if (sel.value === "custom") return select(null);
    const v = S.catalog.canvas_presets[sel.value];
    commit(); Object.assign(P(), { width: v.width, height: v.height, fps: v.fps }); changed();
  };
}
function syncCanvasSel() {
  const p = P();
  const k = Object.entries(S.catalog.canvas_presets).find(([, v]) => v.width === p.width && v.height === p.height);
  if (!k) {
    let o = $("#canvasSel option[value=custom]");
    o.textContent = `Custom ${p.width}×${p.height}`;
  }
  $("#canvasSel").value = k ? k[0] : "custom";
  $("#stage").style.aspectRatio = `${p.width}/${p.height}`;
}

/* ------------------------------------------------------------------ viewer */
let frameTimer = null, frameSeq = 0, lastFrameErr = null;
function refreshFrame() {
  clearTimeout(frameTimer);
  frameTimer = setTimeout(async () => {
    const T = duration();
    $("#durcode").textContent = fmtT(T);
    $("#emptyHint").classList.toggle("hidden", T > 0);
    if (T <= 0) { $("#frameImg").removeAttribute("src"); return; }
    const seq = ++frameSeq;
    try {
      const blob = await api("/api/frame", { method: "POST", json: { project: P(), t: Math.min(S.t, T), height: Math.min(720, +$("#pvQual").value * 1.5) } });
      if (seq !== frameSeq) return;
      lastFrameErr = null;
      const old = $("#frameImg").src;
      $("#frameImg").src = URL.createObjectURL(blob);
      if (old && old.startsWith("blob:")) URL.revokeObjectURL(old);
    } catch (e) {
      if (seq !== frameSeq) return;
      console.warn(e);
      if (e.message !== lastFrameErr) { lastFrameErr = e.message; toast("✖ Preview frame failed: " + e.message.split("\n").slice(-3).join(" "), 6000); }
    }
  }, 90);
}
function setTime(t, { frame = true } = {}) {
  S.t = clamp(t, 0, Math.max(duration(), 0));
  $("#timecode").textContent = fmtT(S.t);
  $("#playhead").style.left = S.t * S.zoom + "px";
  if (frame) { stopPlayback(); refreshFrame(); }
}
let playRAF = null;
async function togglePlay() {
  const vid = $("#previewVid");
  if ($("#stage").classList.contains("playing") && !vid.paused) return stopPlayback();
  const T = duration();
  if (T <= 0) return;
  if (S.t >= T - 0.05) setTime(0, { frame: false });
  const start = S.t, end = Math.min(T, start + 60);
  const pv = S.preview;
  if (!(pv.valid && pv.url && start >= pv.start && start < pv.end - 0.1)) {
    $("#busy").classList.remove("hidden");
    try {
      const job = await api("/api/preview", { method: "POST", json: { project: P(), start, end, height: +$("#pvQual").value } });
      const done = await waitJob(job.id, (j) => ($("#busy span").textContent = `Rendering preview… ${Math.round(j.progress * 100)}%`));
      Object.assign(pv, { url: done.url + "?v=" + uid(), start, end, valid: true });
    } catch (e) { $("#busy").classList.add("hidden"); return toast("✖ Preview failed: " + e.message.slice(-400), 7000); }
    $("#busy").classList.add("hidden"); $("#busy span").textContent = "Rendering preview…";
  }
  if (vid.dataset.url !== pv.url) { vid.src = pv.url; vid.dataset.url = pv.url; await new Promise((r) => (vid.onloadedmetadata = r)); }
  vid.currentTime = S.t - pv.start;
  $("#stage").classList.add("playing");
  $("#btnPlay").textContent = "❚❚";
  await vid.play().catch(() => {});
  const tick = () => {
    if (vid.paused) return stopPlayback(false);
    S.t = pv.start + vid.currentTime;
    $("#timecode").textContent = fmtT(S.t);
    $("#playhead").style.left = S.t * S.zoom + "px";
    const sc = $("#tlScroll"), x = S.t * S.zoom;
    if (x > sc.scrollLeft + sc.clientWidth - 40) sc.scrollLeft = x - 80;
    playRAF = requestAnimationFrame(tick);
  };
  vid.onended = () => stopPlayback();
  tick();
}
function stopPlayback(refresh = true) {
  const vid = $("#previewVid");
  if (!vid.paused) vid.pause();
  cancelAnimationFrame(playRAF);
  $("#btnPlay").textContent = "▶";
  if ($("#stage").classList.contains("playing")) {
    $("#stage").classList.remove("playing");
    if (refresh) refreshFrame();
  }
}
async function waitJob(id, onTick) {
  for (;;) {
    const j = await api("/api/jobs/" + id);
    if (onTick) onTick(j);
    if (j.status === "done") return j;
    if (j.status === "error" || j.status === "cancelled") throw new Error(j.error || j.status);
    await new Promise((r) => setTimeout(r, 300));
  }
}

/* ------------------------------------------------------------------ timeline */
function lanes(items, startF, lenF) {
  const sorted = items.map((x) => ({ x, s: startF(x), e: startF(x) + lenF(x) })).sort((a, b) => a.s - b.s);
  const laneEnd = [], out = new Map();
  for (const it of sorted) {
    let l = laneEnd.findIndex((e) => e <= it.s + 1e-6);
    if (l < 0) { l = laneEnd.length; laneEnd.push(0); }
    laneEnd[l] = it.e; out.set(it.x, l);
  }
  return { map: out, count: Math.max(laneEnd.length, 1) };
}
function renderTimeline() {
  if (!S.project) return;
  const p = P(), T = duration(), Z = S.zoom;
  const width = Math.max((T + 20) * Z, $("#tlScroll").clientWidth);
  $("#tlInner").style.width = width + "px";
  // ruler
  const ruler = $("#ruler"); ruler.innerHTML = "";
  const steps = [0.1, 0.25, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300];
  const major = steps.find((s) => s * Z >= 70) || 600;
  const minor = major / 5;
  for (let t = 0; t * Z < width; t += minor) {
    const isMajor = Math.abs(t / major - Math.round(t / major)) < 1e-6;
    ruler.append(h("div", { class: "tick" + (isMajor ? "" : " minor"), style: { left: t * Z + "px" } }, isMajor ? fmtT(t).replace(/^00:/, "").slice(0, major < 1 ? 8 : 5) : ""));
  }
  const heads = $("#tlHeads"), tracks = $("#tracks");
  heads.innerHTML = ""; tracks.innerHTML = "";
  const isSel = (type, id) => S.sel && S.sel.type === type && S.sel.id === id;
  const fxBadge = (o) => (o.effects || []).length + ((o.audio_effects || []).length) ? h("span", { class: "fxdot" }, "fx " + ((o.effects || []).length + (o.audio_effects || []).length)) : null;

  // texts
  const tl = lanes(p.texts, (t) => t.start, (t) => t.duration);
  for (let l = tl.count - 1; l >= 0; l--) {
    heads.append(h("div", { class: "thead" }, "T  Text" + (tl.count > 1 ? " " + (l + 1) : "")));
    const tr = h("div", { class: "track", "data-kind": "text" });
    p.texts.filter((t) => tl.map.get(t) === l).forEach((t) => tr.append(block("txt", t, t.start, t.duration, ["✎ " + t.text.split("\n")[0], fxBadge(t)], isSel("text", t.id))));
    tracks.append(tr);
  }
  // overlays
  const ol = lanes(p.overlays, (o) => o.start, ovLen);
  for (let l = ol.count - 1; l >= 0; l--) {
    heads.append(h("div", { class: "thead" }, "⧉  Overlay" + (ol.count > 1 ? " " + (l + 1) : "")));
    const tr = h("div", { class: "track", "data-kind": "overlay" });
    p.overlays.filter((o) => ol.map.get(o) === l).forEach((o) => {
      const m = mediaOf(o.src);
      const b = block("ov", o, o.start, ovLen(o), [(o.chroma_key ? "🟩 " : "") + (o.name || nameOf(o.src)), fxBadge(o)], isSel("overlay", o.id));
      if (m) b.style.backgroundImage = `url(/media/${m.id}/${m.kind === "image" ? "thumb" : "strip"})`;
      tr.append(b);
    });
    tracks.append(tr);
  }
  // main
  heads.append(h("div", { class: "thead main" }, "🎬  Main video"));
  const mt = h("div", { class: "track main", "data-kind": "main" });
  for (const { c, start, len, i } of layout()) {
    const k = clipKind(c), m = mediaOf(c.src);
    const label = [k === "color" ? "▭ Color" : (c.name || nameOf(c.src))];
    if (c.speed !== 1) label.push(h("span", { class: "fxdot" }, c.speed + "×"));
    if (c.reverse) label.push(h("span", { class: "fxdot" }, "⇆"));
    label.push(fxBadge(c));
    const b = block("clip", c, start, len, label, isSel("clip", c.id));
    if (k === "color") b.style.backgroundColor = c.color;
    else if (m) b.style.backgroundImage = `url(/media/${m.id}/${k === "image" ? "thumb" : "strip"})`;
    mt.append(b);
    const d = transDur(i);
    if (d > 0) mt.append(h("div", { class: "trn", title: c.transition.type, style: { left: (start + len - d) * Z + "px", width: Math.max(d * Z, 6) + "px" } }));
  }
  tracks.append(mt);
  // audio
  const al = lanes(p.audio, (a) => a.start, (a) => audLen(a, T));
  for (let l = 0; l < al.count; l++) {
    heads.append(h("div", { class: "thead" }, "♪  Audio" + (al.count > 1 ? " " + (l + 1) : "")));
    const tr = h("div", { class: "track", "data-kind": "audio" });
    p.audio.filter((a) => al.map.get(a) === l).forEach((a) => {
      const m = mediaOf(a.src);
      const b = block("aud", a, a.start, audLen(a, T), [(a.duck ? "🦆 " : "") + (a.loop ? "🔁 " : "") + (a.name || nameOf(a.src)), fxBadge(a)], isSel("audio", a.id));
      if (m && m.has_audio) { b.style.backgroundImage = `url(/media/${m.id}/wave)`; b.style.backgroundSize = "100% 100%"; }
      tr.append(b);
    });
    tracks.append(tr);
  }
  $("#playhead").style.left = S.t * Z + "px";
  $("#durcode").textContent = fmtT(T);
  bindTrackDrops();
}

function block(cls, obj, start, len, label, selected) {
  const type = { clip: "clip", ov: "overlay", txt: "text", aud: "audio" }[cls];
  const b = h("div", { class: `blk ${cls}` + (selected ? " sel" : ""), style: { left: start * S.zoom + "px", width: Math.max(len * S.zoom, 4) + "px" } },
    h("div", { class: "shade" }), h("div", { class: "lbl" }, ...label), h("div", { class: "h l" }), h("div", { class: "h r" }));
  b.addEventListener("pointerdown", (e) => startDrag(e, type, obj, start, len));
  b.addEventListener("dragover", (e) => { if ([...e.dataTransfer.types].some((t) => /vidpy\/(vfx|afx|trans)/.test(t))) e.preventDefault(); });
  b.addEventListener("drop", (e) => {
    const v = e.dataTransfer.getData("vidpy/vfx"), a = e.dataTransfer.getData("vidpy/afx"), tr = e.dataTransfer.getData("vidpy/trans");
    if (!(v || a || tr)) return;
    e.preventDefault(); e.stopPropagation();
    S.sel = { type, id: obj.id };
    if (tr) { if (type === "clip") setTransition(obj, tr); else toast("Transitions go on main-track clips"); return; }
    addEffectToSelection(v ? "video" : "audio", v || a, { type, obj });
  });
  return b;
}

function startDrag(e, type, obj, start, len) {
  if (e.button !== 0) return;
  e.preventDefault();
  const edge = e.target.classList.contains("h") ? (e.target.classList.contains("l") ? "l" : "r") : null;
  const x0 = e.clientX, Z = S.zoom, before = JSON.stringify(S.project);
  const orig = clone(obj);
  let moved = false;
  if (!(S.sel && S.sel.id === obj.id)) select(type, obj.id);
  const snapPts = () => {
    const pts = [0, S.t];
    layout().forEach(({ start, len }) => pts.push(start, start + len));
    P().texts.forEach((t) => pts.push(t.start, t.start + t.duration));
    P().overlays.forEach((o) => pts.push(o.start, o.start + ovLen(o)));
    return pts;
  };
  const pts = snapPts();
  const snap = (t) => { for (const p of pts) if (Math.abs(p - t) * Z < 8) return p; return t; };
  const onMove = (ev) => {
    const dt = (ev.clientX - x0) / Z;
    if (!moved && Math.abs(ev.clientX - x0) < 3) return;
    moved = true;
    const m = mediaOf(obj.src) || {};
    if (type === "clip") {
      const k = clipKind(obj);
      if (edge === "r") {
        if (k === "image" || k === "color") obj.duration = r3(Math.max(0.1, (orig.duration || 5) + dt));
        else { const [a, b] = clipSpan(orig); obj.out_point = r3(clamp(b + dt * (obj.speed || 1), a + 0.1, m.duration || b)); }
      } else if (edge === "l") {
        if (k === "video") { const [a, b] = clipSpan(orig); obj.in_point = r3(clamp(a + dt * (obj.speed || 1), 0, b - 0.1)); }
        else obj.duration = r3(Math.max(0.1, (orig.duration || 5) - dt));
      } else {
        // reorder on the magnetic track
        const centre = start + len / 2 + dt;
        const lay = layout().filter((l) => l.c !== obj);
        let idx = lay.findIndex((l) => centre < l.start + l.len / 2);
        if (idx < 0) idx = lay.length;
        const arr = P().clips.filter((c) => c !== obj);
        arr.splice(idx, 0, obj);
        if (arr.some((c, i) => c !== P().clips[i])) P().clips = arr;
      }
    } else if (type === "text") {
      if (edge === "r") obj.duration = r3(Math.max(0.2, snap(orig.start + orig.duration + dt) - orig.start));
      else if (edge === "l") { const ns = clamp(snap(orig.start + dt), 0, orig.start + orig.duration - 0.2); obj.duration = r3(orig.duration + orig.start - ns); obj.start = r3(ns); }
      else obj.start = r3(Math.max(0, snap(orig.start + dt)));
    } else if (type === "overlay") {
      const L = ovLen(orig);
      if (edge === "r") obj.duration = r3(Math.max(0.2, snap(orig.start + L + dt) - orig.start));
      else if (edge === "l") {
        const ns = clamp(snap(orig.start + dt), 0, orig.start + L - 0.2);
        obj.duration = r3(L - (ns - orig.start));
        if (m.kind !== "image") obj.in_point = r3(Math.max(0, (orig.in_point || 0) + (ns - orig.start)));
        obj.start = r3(ns);
      } else obj.start = r3(Math.max(0, snap(orig.start + dt)));
    } else if (type === "audio") {
      if (edge === "r" && !obj.loop) { const L = audLen(orig); obj.out_point = r3(clamp((orig.in_point || 0) + (L + dt) * (obj.speed || 1), (orig.in_point || 0) + 0.1, m.duration || 1e9)); }
      else if (edge === "l") { const ns = Math.max(0, orig.start + dt); obj.in_point = r3(Math.max(0, (orig.in_point || 0) + (ns - orig.start) * (obj.speed || 1))); obj.start = r3(ns); }
      else obj.start = r3(Math.max(0, snap(orig.start + dt)));
    }
    renderTimeline();
  };
  const onUp = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onUp);
    if (moved) { S.undo.push(before); S.redo = []; changed(); }
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onUp);
}

function bindTrackDrops() {
  $$("#tracks .track").forEach((tr) => {
    tr.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("vidpy/media")) { e.preventDefault(); tr.classList.add("drop-over"); } });
    tr.addEventListener("dragleave", () => tr.classList.remove("drop-over"));
    tr.addEventListener("drop", (e) => {
      tr.classList.remove("drop-over");
      const id = e.dataTransfer.getData("vidpy/media");
      if (!id) return;
      e.preventDefault();
      const m = S.media.find((x) => x.id === id);
      const t = (e.clientX - tr.getBoundingClientRect().left) / S.zoom;
      const kind = tr.dataset.kind;
      if (kind === "main") {
        if (m.kind === "audio") return addMedia(m, "audio", t);
        addMedia(m, "main");
        // insert at drop position
        const c = P().clips.pop();
        let idx = layout().findIndex((l) => t < l.start + l.len / 2);
        if (idx < 0) idx = P().clips.length;
        P().clips.splice(idx, 0, c); changed();
      } else if (kind === "audio" || m.kind === "audio") addMedia(m, "audio", t);
      else addMedia(m, "overlay", t);
    });
  });
}

/* ------------------------------------------------------------------ inspector */
function field(label, type, value, onChange, opt = {}) {
  const commitKey = opt.key || label + (S.sel ? S.sel.id : "");
  const fire = (v) => {
    if (opt.local) return onChange(v);
    commit(commitKey); onChange(v); changed({ noInspector: !opt.rerender });
  };
  let input, num = null;
  if (type === "range") {
    input = h("input", { type: "range", min: opt.min ?? 0, max: opt.max ?? 1, step: opt.step ?? 0.01, value: value ?? 0 });
    num = h("input", { class: "num", type: "number", step: opt.step ?? 0.01, value: value ?? 0 });
    input.addEventListener("input", () => { num.value = input.value; if (opt.local) onChange(+input.value); });
    input.addEventListener("change", () => fire(+input.value));
    num.addEventListener("change", () => { input.value = num.value; fire(+num.value); });
    return h("div", { class: "row" }, h("label", { title: label }, label), input, num);
  }
  if (type === "bool") input = h("input", { type: "checkbox", checked: !!value, onchange: (e) => fire(e.target.checked) });
  else if (type === "color") input = h("input", { type: "color", value: value || "#000000", onchange: (e) => fire(e.target.value) });
  else if (type === "choice") input = h("select", { onchange: (e) => fire(e.target.value) }, ...(opt.choices || []).map((c) => {
    const [v, l] = Array.isArray(c) ? c : [c, String(c).replace(/_/g, " ")];
    return h("option", { value: v, selected: String(v) === String(value) }, l);
  }));
  else if (type === "textarea") input = h("textarea", { onchange: (e) => fire(e.target.value) }, value ?? "");
  else if (type === "number") input = h("input", { type: "number", step: opt.step ?? 0.01, min: opt.min, max: opt.max, value: value ?? "", placeholder: opt.placeholder || "", onchange: (e) => fire(e.target.value === "" ? null : +e.target.value) });
  else input = h("input", { type: "text", value: value ?? "", placeholder: opt.placeholder || "", onchange: (e) => fire(e.target.value) });
  return h("div", { class: "row wide" }, h("label", { title: label }, label), input);
}
const group = (title, ...kids) => h("div", { class: "group" }, h("div", { class: "gt" }, title), ...kids);

function fxStack(list, kind, title) {
  const cat = S.catalog[kind === "video" ? "video_effects" : "audio_effects"];
  const byId = Object.fromEntries(cat.map((e) => [e.id, e]));
  const wrap = group(title);
  list.forEach((fx, i) => {
    const def = byId[fx.id];
    if (!def) { wrap.append(h("div", { class: "fxcard" }, "Unknown effect " + fx.id)); return; }
    const card = h("div", { class: "fxcard" + (fx.enabled === false ? " off" : "") },
      h("div", { class: "fxhead" },
        h("input", { type: "checkbox", checked: fx.enabled !== false, title: "Enable / bypass", onchange: (e) => { commit(); fx.enabled = e.target.checked; changed(); } }),
        h("span", { class: "t", title: def.description }, def.name),
        h("button", { title: "Move up", onclick: () => { if (i > 0) { commit(); [list[i - 1], list[i]] = [list[i], list[i - 1]]; changed(); } } }, "↑"),
        h("button", { title: "Reset", onclick: () => { commit(); fx.params = {}; changed(); } }, "⟲"),
        h("button", { class: "danger", title: "Remove", onclick: () => { commit(); list.splice(i, 1); changed(); } }, "✕")));
    for (const pdef of def.params) {
      const val = fx.params[pdef.name] ?? pdef.default;
      const set = (v) => (fx.params[pdef.name] = v);
      const key = fx.id + i + pdef.name;
      if (pdef.type === "float" || pdef.type === "int") card.append(field(pdef.label, "range", val, set, { min: pdef.min, max: pdef.max, step: pdef.step || (pdef.type === "int" ? 1 : 0.01), key }));
      else if (pdef.type === "choice") card.append(field(pdef.label, "choice", val, set, { choices: pdef.choices, key }));
      else if (pdef.type === "file") card.append(fileField(pdef.label, val, set));
      else card.append(field(pdef.label, pdef.type === "text" ? "text" : pdef.type, val, set, { key }));
    }
    wrap.append(card);
  });
  const sel = h("select", {}, h("option", { value: "" }, `+ Add ${kind} effect…`),
    ...[...new Set(cat.map((e) => e.category))].map((c) => h("optgroup", { label: c }, ...cat.filter((e) => e.category === c && e.available).map((e) => h("option", { value: e.id }, e.name)))));
  sel.onchange = () => { if (!sel.value) return; commit(); list.push({ id: sel.value, params: {}, enabled: true }); changed(); };
  wrap.append(h("div", { class: "addfx" }, sel));
  return wrap;
}
function fileField(label, val, set) {
  const sel = h("select", {}, h("option", { value: "" }, "— choose —"), ...S.media.map((m) => h("option", { value: m.path, selected: m.path === val }, m.name)),
    h("option", { value: "__path" }, "Type a path…"));
  sel.onchange = () => {
    let v = sel.value;
    if (v === "__path") v = prompt("Full path to the file (.cube LUT etc.)", val || "") || "";
    commit(); set(v); changed();
  };
  return h("div", { class: "row wide" }, h("label", {}, label), sel);
}

function renderInspector() {
  const el = $("#inspector");
  el.innerHTML = "";
  const o = findSel();
  const p = P();
  if (!o) {
    el.append(h("h3", {}, "Project"), h("div", { class: "sub" }, `${p.width}×${p.height} · ${p.fps} fps · ${fmtT(duration())}`),
      group("Canvas",
        field("Width", "number", p.width, (v) => (p.width = Math.round(v / 2) * 2), { step: 2, min: 16 }),
        field("Height", "number", p.height, (v) => (p.height = Math.round(v / 2) * 2), { step: 2, min: 16 }),
        field("Frame rate", "choice", String(p.fps), (v) => (p.fps = +v), { choices: ["23.976", "24", "25", "29.97", "30", "50", "60", "120"].concat(["23.976", "24", "25", "29.97", "30", "50", "60", "120"].includes(String(p.fps)) ? [] : [String(p.fps)]) }),
        field("Background", "color", p.background, (v) => (p.background = v))),
      fxStack(p.effects, "video", "Project grade (all clips)"),
      fxStack(p.audio_effects, "audio", "Master audio bus"),
      group("Subtitles (.srt burn-in)",
        fileField("SRT file", p.subtitles && p.subtitles.path, (v) => (p.subtitles = v ? { path: v, size: (p.subtitles && p.subtitles.size) || 24 } : null)),
        p.subtitles ? field("Font size", "range", p.subtitles.size || 24, (v) => (p.subtitles.size = v), { min: 10, max: 80, step: 1 }) : null),
      h("p", { class: "hint" }, "Tip: select something on the timeline to edit it. Drag effects from the left onto clips."),
      h("p", { class: "hint" }, `vidpy Studio ${S.info.version} · created by Muhammad Rafay Shaikh, from Pakistan · `,
        h("a", { class: "link", href: "https://github.com/rafay183/vidpy", target: "_blank" }, "GitHub")));
    return;
  }
  const m = mediaOf(o.src) || {};
  const head = (title) => el.append(h("h3", {}, title), h("div", { class: "sub" }, o.src ? o.src : ""));
  if (S.sel.type === "clip") {
    const k = clipKind(o);
    head(k === "color" ? "Color clip" : (o.name || nameOf(o.src)));
    el.append(group("Clip",
      field("Name", "text", o.name, (v) => (o.name = v)),
      k === "video" ? field("In (s)", "number", r3(clipSpan(o)[0]), (v) => (o.in_point = v || 0), { min: 0, max: m.duration }) : null,
      k === "video" ? field("Out (s)", "number", o.out_point, (v) => (o.out_point = v), { min: 0, max: m.duration, placeholder: "end · " + (m.duration || 0).toFixed(2) }) : null,
      k !== "video" ? field("Duration", "number", o.duration || 5, (v) => (o.duration = Math.max(v || 0.1, 0.1)), { min: 0.1 }) : null,
      k === "color" ? field("Color", "color", o.color, (v) => (o.color = v)) : null,
      k === "video" ? field("Speed", "range", o.speed, (v) => (o.speed = v), { min: 0.1, max: 8, step: 0.05 }) : null,
      k === "video" ? field("Reverse", "bool", o.reverse, (v) => (o.reverse = v)) : null,
      field("Fit", "choice", o.fit, (v) => (o.fit = v), { choices: [["fit", "Fit (letterbox)"], ["fill", "Fill (crop)"], ["stretch", "Stretch"]] }),
      h("div", { class: "muted small" }, `On timeline: ${clipLen(o).toFixed(2)}s`)));
    if (k === "video" && m.has_audio) el.append(group("Clip audio",
      field("Volume", "range", o.volume, (v) => (o.volume = v), { min: 0, max: 4, step: 0.01 }),
      field("Mute", "bool", o.mute, (v) => (o.mute = v))));
    const idx = p.clips.indexOf(o);
    if (idx < p.clips.length - 1) {
      const tr = o.transition || {};
      el.append(group("Transition → next clip",
        field("Type", "choice", tr.type || "", (v) => (o.transition = v ? { type: v, duration: tr.duration || 1 } : null),
          { choices: [["", "— cut —"], ...S.catalog.transitions.filter((t) => t.available).map((t) => [t.id, `${t.category}: ${t.name}`])] }),
        o.transition ? field("Duration", "range", tr.duration || 1, (v) => (o.transition.duration = v), { min: 0.1, max: 5, step: 0.05 }) : null));
    }
    el.append(fxStack(o.effects, "video", "Video effects"));
    if (k === "video" && m.has_audio) el.append(fxStack(o.audio_effects, "audio", "Audio effects"));
  } else if (S.sel.type === "overlay") {
    head(o.name || nameOf(o.src));
    const ck = o.chroma_key;
    el.append(group("Timing",
      field("Start", "number", o.start, (v) => (o.start = Math.max(v || 0, 0))),
      field("Duration", "number", o.duration, (v) => (o.duration = v), { placeholder: "auto · " + ovLen(o).toFixed(2) }),
      m.kind === "video" ? field("Source in", "number", o.in_point, (v) => (o.in_point = v || 0)) : null,
      field("Fade in", "range", o.fade_in, (v) => (o.fade_in = v), { min: 0, max: 5, step: 0.05 }),
      field("Fade out", "range", o.fade_out, (v) => (o.fade_out = v), { min: 0, max: 5, step: 0.05 })),
      group("Transform",
        field("X (centre)", "range", o.x, (v) => (o.x = v), { min: -0.5, max: 1.5, step: 0.005 }),
        field("Y (centre)", "range", o.y, (v) => (o.y = v), { min: -0.5, max: 1.5, step: 0.005 }),
        field("Scale", "range", o.scale, (v) => (o.scale = v), { min: 0.02, max: 2, step: 0.005 }),
        field("Rotation", "range", o.rotation, (v) => (o.rotation = v), { min: -180, max: 180, step: 0.5 }),
        field("Opacity", "range", o.opacity, (v) => (o.opacity = v), { min: 0, max: 1, step: 0.01 }),
        field("Layer", "number", o.layer, (v) => (o.layer = Math.round(v || 1)), { step: 1 }),
        h("div", { class: "bs", style: { display: "flex", gap: "4px", flexWrap: "wrap", marginTop: "6px" } },
          ...[["↖", 0.15, 0.15], ["↗", 0.85, 0.15], ["⊙", 0.5, 0.5], ["↙", 0.15, 0.85], ["↘", 0.85, 0.85], ["Full", 0.5, 0.5, 1]].map(([l, x, y, s]) =>
            h("button", { onclick: () => { commit(); o.x = x; o.y = y; if (s) o.scale = s; else if (o.scale > 0.5) o.scale = 0.3; changed(); } }, l)))),
      group("Green screen / chroma key",
        field("Enabled", "bool", !!ck, (v) => (o.chroma_key = v ? { color: "#00ff00", similarity: 0.15, blend: 0.08 } : null), { rerender: true }),
        ck ? field("Key color", "color", ck.color, (v) => (ck.color = v)) : null,
        ck ? field("Similarity", "range", ck.similarity, (v) => (ck.similarity = v), { min: 0.01, max: 0.6, step: 0.005 }) : null,
        ck ? field("Edge blend", "range", ck.blend, (v) => (ck.blend = v), { min: 0, max: 0.5, step: 0.005 }) : null),
      m.has_audio ? group("Overlay audio", field("Use audio", "bool", o.use_audio, (v) => (o.use_audio = v)), field("Volume", "range", o.volume, (v) => (o.volume = v), { min: 0, max: 4 })) : null,
      fxStack(o.effects, "video", "Effects"));
  } else if (S.sel.type === "text") {
    head("Text");
    el.append(group("Content",
      field("Text", "textarea", o.text, (v) => (o.text = v)),
      field("Start", "number", o.start, (v) => (o.start = Math.max(v || 0, 0))),
      field("Duration", "number", o.duration, (v) => (o.duration = Math.max(v || 0.1, 0.1)))),
      group("Style",
        field("Size", "range", o.size, (v) => (o.size = Math.round(v)), { min: 8, max: 300, step: 1 }),
        field("Color", "color", o.color, (v) => (o.color = v)),
        field("Font file", "text", o.font, (v) => (o.font = v), { placeholder: "default: " + ((S.info.font || "").split(/[\\/]/).pop()) }),
        field("Outline", "range", o.outline, (v) => (o.outline = Math.round(v)), { min: 0, max: 20, step: 1 }),
        field("Outline color", "color", o.outline_color, (v) => (o.outline_color = v)),
        field("Shadow", "range", o.shadow, (v) => (o.shadow = Math.round(v)), { min: 0, max: 20, step: 1 }),
        field("Box", "bool", o.box, (v) => (o.box = v)),
        field("Box color", "color", o.box_color, (v) => (o.box_color = v)),
        field("Box opacity", "range", o.box_opacity, (v) => (o.box_opacity = v), { min: 0, max: 1 })),
      group("Position & motion",
        field("Position", "choice", o.preset, (v) => (o.preset = v), { choices: ["center", "top", "bottom", "lower_third", "top_left", "top_right", "bottom_left", "bottom_right", "custom"], rerender: true }),
        o.preset === "custom" ? field("X", "range", o.x, (v) => (o.x = v), { min: 0, max: 1, step: 0.005 }) : null,
        o.preset === "custom" ? field("Y", "range", o.y, (v) => (o.y = v), { min: 0, max: 1, step: 0.005 }) : null,
        field("Animation", "choice", o.animation, (v) => (o.animation = v), { choices: ["none", "fade", "slide_up", "slide_left", "zoom_pop", "typewriter"] }),
        field("Fade in", "range", o.fade_in, (v) => (o.fade_in = v), { min: 0, max: 3, step: 0.05 }),
        field("Fade out", "range", o.fade_out, (v) => (o.fade_out = v), { min: 0, max: 3, step: 0.05 })));
  } else if (S.sel.type === "audio") {
    head(o.name || nameOf(o.src));
    el.append(group("Audio clip",
      field("Start", "number", o.start, (v) => (o.start = Math.max(v || 0, 0))),
      field("Source in", "number", o.in_point, (v) => (o.in_point = Math.max(v || 0, 0))),
      field("Source out", "number", o.out_point, (v) => (o.out_point = v), { placeholder: "end · " + (m.duration || 0).toFixed(2) }),
      field("Volume", "range", o.volume, (v) => (o.volume = v), { min: 0, max: 4 }),
      field("Speed", "range", o.speed, (v) => (o.speed = v), { min: 0.25, max: 4, step: 0.05 }),
      field("Fade in", "range", o.fade_in, (v) => (o.fade_in = v), { min: 0, max: 10, step: 0.1 }),
      field("Fade out", "range", o.fade_out, (v) => (o.fade_out = v), { min: 0, max: 10, step: 0.1 }),
      field("Loop to end", "bool", o.loop, (v) => (o.loop = v)),
      field("Auto-duck", "bool", o.duck, (v) => (o.duck = v)),
      h("p", { class: "hint" }, "Auto-duck lowers this track automatically whenever the main-track audio (dialogue) is speaking.")),
      fxStack(o.effects, "audio", "Audio effects"));
  }
}

/* ------------------------------------------------------------------ editing ops */
function del() {
  if (!S.sel) return;
  commit();
  const p = P(), k = { clip: "clips", overlay: "overlays", text: "texts", audio: "audio" }[S.sel.type];
  p[k] = p[k].filter((x) => x.id !== S.sel.id);
  S.sel = null; changed();
}
function dup() {
  const o = findSel(); if (!o) return;
  commit();
  const p = P(), c = Object.assign(clone(o), { id: uid() });
  if (S.sel.type === "clip") p.clips.splice(p.clips.indexOf(o) + 1, 0, c);
  else {
    const L = S.sel.type === "text" ? o.duration : S.sel.type === "overlay" ? ovLen(o) : audLen(o);
    c.start = r3(o.start + L);
    p[{ overlay: "overlays", text: "texts", audio: "audio" }[S.sel.type]].push(c);
  }
  S.sel.id = c.id; changed();
}
function split() {
  const t = S.t;
  let target = S.sel && findSel();
  const p = P();
  if (target && S.sel.type === "text" && t > target.start && t < target.start + target.duration) {
    commit(); const b = Object.assign(clone(target), { id: uid(), start: r3(t), duration: r3(target.start + target.duration - t) });
    target.duration = r3(t - target.start); p.texts.push(b); return changed();
  }
  if (target && S.sel.type === "overlay" && t > target.start && t < target.start + ovLen(target)) {
    commit(); const L = ovLen(target), off = t - target.start;
    const b = Object.assign(clone(target), { id: uid(), start: r3(t), duration: r3(L - off), in_point: r3((target.in_point || 0) + ((mediaOf(target.src) || {}).kind === "image" ? 0 : off)) });
    target.duration = r3(off); p.overlays.push(b); return changed();
  }
  if (target && S.sel.type === "audio" && t > target.start && t < target.start + audLen(target, duration())) {
    commit(); const off = (t - target.start) * (target.speed || 1);
    const b = Object.assign(clone(target), { id: uid(), start: r3(t), in_point: r3((target.in_point || 0) + off), loop: false });
    target.out_point = r3((target.in_point || 0) + off); target.loop = false; p.audio.push(b); return changed();
  }
  const hit = layout().find((l) => t > l.start + 0.02 && t < l.start + l.len - 0.02);
  if (!hit) return toast("Put the playhead over a clip to split it");
  commit();
  const c = hit.c, local = t - hit.start, k = clipKind(c);
  const b = Object.assign(clone(c), { id: uid() });
  if (k === "video") {
    const [a, e] = clipSpan(c);
    const cut = c.reverse ? e - local * c.speed : a + local * c.speed;
    if (c.reverse) { c.in_point = r3(cut); b.out_point = r3(cut); }
    else { c.out_point = r3(cut); b.in_point = r3(cut); }
  } else { b.duration = r3((c.duration || 5) - local); c.duration = r3(local); }
  c.transition = null;
  p.clips.splice(p.clips.indexOf(c) + 1, 0, b);
  select("clip", b.id); changed();
}

/* ------------------------------------------------------------------ save / open / export / code */
async function save(silent = false) {
  let name = S.savedName || P().name;
  if (!name || name === "Untitled") {
    if (silent) return;
    name = prompt("Project name", P().name || "My edit");
    if (!name) return;
    P().name = name; $("#projName").value = name;
  }
  const r = await api("/api/projects/" + encodeURIComponent(name), { method: "PUT", json: P() });
  S.savedName = r.name; S.dirty = false;
  localStorage.setItem("vidpy:last", r.name);
  $("#saveState").textContent = "saved " + new Date().toLocaleTimeString();
  if (!silent) toast("💾 Saved “" + r.name + "”");
}
function modal(title, ...body) {
  const card = $("#modalCard");
  card.innerHTML = "";
  card.append(h("h2", {}, title), ...body);
  $("#modal").classList.remove("hidden");
  $("#modal").onclick = (e) => { if (e.target.id === "modal") closeModal(); };
}
const closeModal = () => $("#modal").classList.add("hidden");

async function openDialog() {
  const r = await api("/api/projects");
  const list = h("div", { class: "plist" });
  if (!r.projects.length) list.append(h("p", { class: "muted" }, "No saved projects yet."));
  for (const pr of r.projects) list.append(h("button", { onclick: async () => {
    S.project = Object.assign(newProject(), await api("/api/projects/" + encodeURIComponent(pr.name)));
    S.savedName = pr.name; localStorage.setItem("vidpy:last", pr.name); S.undo = []; S.redo = []; S.sel = null;
    closeModal(); afterLoad(); S.dirty = false; $("#saveState").textContent = "saved";
  } }, h("span", {}, pr.name), h("span", { class: "muted" }, new Date(pr.modified * 1000).toLocaleString())));
  const fileIn = h("input", { type: "file", accept: ".json", hidden: true, onchange: async (e) => {
    const txt = await e.target.files[0].text();
    commit(); S.project = Object.assign(newProject(), JSON.parse(txt)); S.savedName = null; closeModal(); afterLoad();
  } });
  modal("Open project", list, h("div", { class: "btns" },
    h("label", { class: "link" }, "Import .json…", fileIn),
    h("button", { onclick: () => { const a = h("a", { href: URL.createObjectURL(new Blob([JSON.stringify(P(), null, 1)])), download: (P().name || "project") + ".vidpy.json" }); a.click(); } }, "Download current .json"),
    h("button", { onclick: closeModal }, "Close")));
}

function exportDialog() {
  if (duration() <= 0) return toast("Nothing to export yet");
  const st = { format: "mp4", quality: "high", resolution: "", hardware: false, filename: P().name || "export" };
  const body = h("div", {},
    field("Format", "choice", st.format, (v) => (st.format = v), { local: true, choices: S.catalog.formats.map((f) => [f.id, f.label]) }),
    field("Quality", "choice", st.quality, (v) => (st.quality = v), { local: true, choices: [["draft", "Draft (fastest)"], ["web", "Web (balanced)"], ["high", "High"], ["ultra", "Ultra"], ["lossless", "Lossless"]] }),
    field("Resolution", "choice", "", (v) => (st.resolution = v), { local: true, choices: [["", `Project (${P().width}×${P().height})`], ...S.catalog.resolutions.map((r) => [r, r])] }),
    field("GPU encoder", "bool", false, (v) => (st.hardware = v), { local: true }),
    field("File name", "text", st.filename, (v) => (st.filename = v), { local: true }),
    h("p", { class: "muted small" }, `Duration ${fmtT(duration())} · output goes to ${S.info.workspace}/exports`));
  modal("Export video", body, h("div", { class: "btns" },
    h("button", { onclick: closeModal }, "Cancel"),
    h("button", { class: "primary", onclick: async () => {
      closeModal();
      try { const j = await api("/api/export", { method: "POST", json: { project: P(), ...st } }); watchJob(j); }
      catch (e) { toast("✖ " + e.message, 6000); }
    } }, "Render ⤓")));
}
async function codeDialog() {
  if (duration() <= 0) return toast("Add something to the timeline first");
  const r = await api("/api/code", { method: "POST", json: { project: P() } });
  const pre = h("pre", {}, r.python);
  let cur = "python";
  const tabs = h("div", { class: "tabs" },
    h("button", { class: "on", onclick: (e) => { cur = "python"; pre.textContent = r.python; $$("button", tabs).forEach((b) => b.classList.remove("on")); e.target.classList.add("on"); } }, "Python"),
    h("button", { onclick: (e) => { cur = "ffmpeg"; pre.textContent = r.ffmpeg; $$("button", tabs).forEach((b) => b.classList.remove("on")); e.target.classList.add("on"); } }, "FFmpeg command"));
  modal("Your edit as code", h("p", { class: "muted" }, "Everything you do in the studio is reproducible in Python — automate it, batch it, version it."), tabs, pre,
    h("div", { class: "btns" }, h("button", { onclick: () => { navigator.clipboard.writeText(r[cur]); toast("Copied"); } }, "Copy"), h("button", { onclick: closeModal }, "Close")));
}

/* ------------------------------------------------------------------ jobs */
const watched = {}, localJobs = {};
function watchJob(j, reloadMedia = false) { watched[j.id] = { ...j, reloadMedia }; renderJobs(); }
async function pollJobs() {
  const ids = Object.keys(watched).filter((id) => ["queued", "running"].includes(watched[id].status));
  for (const id of ids) {
    try {
      const j = await api("/api/jobs/" + id);
      const was = watched[id];
      watched[id] = { ...j, reloadMedia: was.reloadMedia };
      if (j.status === "done" && was.reloadMedia) loadMedia().then(renderSmart);
    } catch (e) { /* ignore */ }
  }
  if (ids.length) renderJobs();
}
function renderJobs() {
  const el = $("#jobs");
  el.innerHTML = "";
  for (const j of [...Object.values(localJobs), ...Object.values(watched)]) {
    const close = h("button", { onclick: () => { delete watched[j.id]; renderJobs(); } }, "✕");
    el.append(h("div", { class: "job" },
      h("div", { class: "jt" }, h("b", {}, (j.kind === "export" ? "⤓ " : "⚙ ") + j.label), h("span", { class: "muted small" }, j.status === "running" ? `${Math.round(j.progress * 100)}% ${j.speed || ""}` : j.status)),
      h("div", { class: "bar" }, h("i", { style: { width: Math.round((j.progress || 0) * 100) + "%" } })),
      j.error ? h("div", { class: "err" }, j.error.split("\n").slice(-8).join("\n")) : null,
      h("div", { class: "jt" },
        j.status === "running" && j.kind !== "upload" ? h("button", { onclick: () => api(`/api/jobs/${j.id}/cancel`, { method: "POST" }) }, "Cancel") : h("span"),
        j.status === "done" && j.url ? h("span", {}, h("a", { class: "link", href: j.url, target: "_blank" }, "Open"), " · ", h("a", { class: "link", href: j.url + "?dl=1" }, "Download")) : null,
        j.status === "done" && !j.url && j.output ? h("span", { class: "muted small" }, "Added to library") : null,
        j.kind !== "upload" && j.status !== "running" ? close : null)));
  }
}

/* ------------------------------------------------------------------ bindings */
function bindUI() {
  $$("#leftTabs button").forEach((b) => (b.onclick = () => {
    $$("#leftTabs button").forEach((x) => x.classList.toggle("on", x === b));
    $$(".pane").forEach((p) => p.classList.toggle("on", p.id === "pane-" + b.dataset.tab));
    if (b.dataset.tab === "smart") renderSmart();
  }));
  const acts = {
    new: () => { if (S.dirty && !confirm("Discard unsaved changes?")) return; S.project = newProject(); S.savedName = null; S.undo = []; S.redo = []; S.sel = null; localStorage.removeItem("vidpy:last"); afterLoad(); },
    open: openDialog, save: () => save(), undo, redo, export: exportDialog, code: codeDialog,
    split, dup, del,
    addColor: () => { commit(); const c = Object.assign(D.clip(), { kind: "color", color: "#111111", duration: 3, name: "Color" }); P().clips.push(c); select("clip", c.id); changed(); },
  };
  $$("[data-act]").forEach((b) => (b.onclick = () => acts[b.dataset.act]()));
  $("#projName").onchange = (e) => { commit(); P().name = e.target.value; S.dirty = true; };

  const drop = $("#drop");
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { if (e.dataTransfer.types.includes("Files")) { e.preventDefault(); drop.classList.add("over"); } }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, () => drop.classList.remove("over")));
  drop.addEventListener("drop", (e) => { e.preventDefault(); uploadFiles([...e.dataTransfer.files]); });
  document.addEventListener("dragover", (e) => { if (e.dataTransfer.types.includes("Files")) e.preventDefault(); });
  document.addEventListener("drop", (e) => { if (e.dataTransfer.types.includes("Files") && !drop.contains(e.target)) { e.preventDefault(); uploadFiles([...e.dataTransfer.files]); } });
  $("#fileIn").onchange = (e) => uploadFiles([...e.target.files]);
  $("#importPath").onclick = async () => {
    const pth = prompt("Full path to a file or a folder on this computer (imports without copying):");
    if (!pth) return;
    const r = await api("/api/import", { method: "POST", json: { path: pth } }).catch((e) => toast("✖ " + e.message));
    if (r) { toast(`Imported ${r.added.length} file(s)` + (r.errors.length ? `, ${r.errors.length} skipped` : "")); loadMedia().then(renderSmart); }
  };

  // ruler & playhead
  const ruler = $("#ruler");
  const seek = (e) => setTime((e.clientX - ruler.getBoundingClientRect().left) / S.zoom);
  ruler.addEventListener("pointerdown", (e) => {
    seek(e);
    const mv = (ev) => seek(ev), up = () => { window.removeEventListener("pointermove", mv); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", mv); window.addEventListener("pointerup", up);
  });
  $("#tracks").addEventListener("pointerdown", (e) => { if (e.target.classList.contains("track")) { select(null); seek(e); } });
  $("#zoom").oninput = (e) => {
    const sc = $("#tlScroll"), center = (sc.scrollLeft + sc.clientWidth / 2) / S.zoom;
    S.zoom = +e.target.value; renderTimeline(); sc.scrollLeft = center * S.zoom - sc.clientWidth / 2;
  };
  $("#tlScroll").addEventListener("wheel", (e) => {
    if (e.ctrlKey || e.metaKey) { e.preventDefault(); const z = $("#zoom"); z.value = clamp(+z.value * (e.deltaY < 0 ? 1.15 : 0.87), 8, 400); z.oninput({ target: z }); }
  }, { passive: false });
  $("#tlScroll").addEventListener("scroll", () => ($("#tlHeads").scrollTop = $("#tlScroll").scrollTop));

  $("#btnPlay").onclick = togglePlay;
  $("#btnStart").onclick = () => setTime(0);
  $("#btnEnd").onclick = () => setTime(duration());
  $("#btnBack").onclick = () => setTime(S.t - 1 / P().fps);
  $("#btnFwd").onclick = () => setTime(S.t + 1 / P().fps);
  $("#pvQual").onchange = () => { S.preview.valid = false; refreshFrame(); };

  window.addEventListener("keydown", (e) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName)) return;
    const mod = e.ctrlKey || e.metaKey;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    else if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); }
    else if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); }
    else if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
    else if (mod && e.key.toLowerCase() === "d") { e.preventDefault(); dup(); }
    else if (e.key === "Delete" || e.key === "Backspace") { e.preventDefault(); del(); }
    else if (e.key.toLowerCase() === "s") split();
    else if (e.key === "ArrowLeft") setTime(S.t - (e.shiftKey ? 1 : 1 / P().fps));
    else if (e.key === "ArrowRight") setTime(S.t + (e.shiftKey ? 1 : 1 / P().fps));
    else if (e.key === "Home") setTime(0);
    else if (e.key === "End") setTime(duration());
    else if (e.key === "Escape") { select(null); closeModal(); }
    else if (e.key === "+" || e.key === "=") { const z = $("#zoom"); z.value = +z.value * 1.25; z.oninput({ target: z }); }
    else if (e.key === "-") { const z = $("#zoom"); z.value = +z.value * 0.8; z.oninput({ target: z }); }
  });
  window.addEventListener("beforeunload", (e) => { if (S.dirty) { e.preventDefault(); e.returnValue = ""; } });
  window.addEventListener("resize", renderTimeline);
}

boot().catch((e) => { document.body.innerHTML = `<pre style="padding:20px;color:#f87171">vidpy Studio failed to start:\n${e.stack || e}</pre>`; });
