/* ui_render_harness.cjs — Ejecuta el JS REAL del static/index.html en un sandbox `vm` con un
 * DOM mínimo, para testear (sin Playwright) el comportamiento de la UI de Auto/SRT.
 *
 * Uso:  node ui_render_harness.cjs <ruta_index.html>   (fixture JSON por stdin)
 * Modos (fixture.fn):
 *   - 'clip'          -> ret = JSON({html}) de renderAutoClip(clip, i, pkgId, v2)
 *   - 'result'        -> renderAutoResult(result); clips/resume = innerHTML capturados
 *   - 'controls'      -> aplica srtPanel.onSource('render') por cada step y devuelve el estado
 *                        (disabled/checked/value/hidden/clase) de los controles del render
 *   - 'render_params' -> configura fuente + video, captura la URL del POST /render de startRender
 *
 * El JS se invoca concatenado al MISMO script (no en un 2º runInContext) porque `srtPanel` y
 * varias vars son `const/let` del scope léxico del bundle, no propiedades del objeto global.
 * Salida (stdout): JSON { ret, out, err, initerr, clips, resume, resumen }.
 */
const fs = require("fs");
const vm = require("vm");

// Statements top-level del bundle disparan cargas async (loadVideos, etc.); con el DOM stub
// esas promesas se rechazan y se silencian para no tumbar el proceso (no afectan lo probado).
process.on("unhandledRejection", () => {});

const htmlPath = process.argv[2];
const fixture = JSON.parse(fs.readFileSync(0, "utf8"));
const html = fs.readFileSync(htmlPath, "utf8");

const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const code = scripts.join("\n;\n").replace(/_rutaInicial\(\);/, "");

function makeClassList() {
  const s = new Set();
  return {
    add: (c) => s.add(c),
    remove: (c) => s.delete(c),
    contains: (c) => s.has(c),
    toggle: (c, f) => {
      const on = f === undefined ? !s.has(c) : !!f;
      if (on) s.add(c); else s.delete(c);
      return on;
    },
  };
}
const store = {};
function fakeEl(id) {
  if (!store[id]) {
    store[id] = {
      id, innerHTML: "", textContent: "", value: "", disabled: false, checked: false,
      hidden: false, style: {}, classList: makeClassList(),
      setAttribute() {}, getAttribute() { return null; }, appendChild() {},
      addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
      scrollIntoView() {}, focus() {}, remove() {}, closest() { return null; },
    };
  }
  return store[id];
}
const documentStub = {
  getElementById: (id) => fakeEl(id),
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: () => fakeEl("_el" + Math.random()),
  addEventListener: () => {},
  readyState: "complete", title: "", body: fakeEl("body"), documentElement: fakeEl("html"),
};
const base = {
  document: documentStub, console, location: { hash: "", href: "" }, navigator: {},
  setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
  fetch: () => Promise.resolve({ ok: false, status: 0, json: () => Promise.resolve([]), text: () => Promise.resolve("") }),
  URL, URLSearchParams,
  FormData: function () { this.append = () => {}; this.set = () => {}; }, Response: function () {},
  Date, Math, JSON, Number, String, Boolean, Array, Object,
  encodeURIComponent, decodeURIComponent, parseInt, parseFloat, isNaN, isFinite,
};
base.window = base;
base.globalThis = base;
const sandbox = new Proxy(base, {
  has: () => true,
  get: (t, k) => (k in t ? t[k] : undefined),
  set: (t, k, v) => { t[k] = v; return true; },
});
const ctx = vm.createContext(sandbox);

// Cuerpo de la invocación bajo prueba (se concatena al bundle; corre en su mismo scope léxico).
let body;
if (fixture.fn === "clip") {
  body = `__ret__ = JSON.stringify({html: renderAutoClip(${JSON.stringify(fixture.clip)}, ${fixture.i | 0}, ${JSON.stringify(fixture.pkgId || "")}, ${!!fixture.v2})});`;
} else if (fixture.fn === "result") {
  body = `renderAutoResult(${JSON.stringify(fixture.result)});`;
} else if (fixture.fn === "controls") {
  const pre = fixture.pre || {};
  body = `
    const g = (id) => document.getElementById(id);
    g('use-emphasis').checked = ${!!pre.emphasis};
    g('use-caption-qa').checked = ${!!pre.qa};
    g('render-wpg').value = ${JSON.stringify(pre.wpg || "")};
    const src = g('render-caption-source');
    for (const step of ${JSON.stringify(fixture.steps || [])}) { src.value = step; srtPanel.onSource('render'); }
    __out__ = JSON.stringify({
      wpg_disabled: !!g('render-wpg').disabled, wpg_value: g('render-wpg').value,
      emph_disabled: !!g('use-emphasis').disabled, emph_checked: !!g('use-emphasis').checked,
      qa_disabled: !!g('use-caption-qa').disabled, qa_checked: !!g('use-caption-qa').checked,
      field_wpg_dis: g('field-wpg').classList.contains('control-disabled'),
      row_emph_dis: g('row-emphasis').classList.contains('control-disabled'),
      row_qa_dis: g('row-caption-qa').classList.contains('control-disabled'),
      note_hidden: !!g('render-srt-incompat').hidden,
      style_disabled: !!g('render-style').disabled,
      preset_disabled: !!g('render-preset').disabled,
      intensidad_disabled: !!g('render-intensidad').disabled,
      emojis_disabled: !!g('use-emojis').disabled,
    });`;
} else if (fixture.fn === "preset_defaults") {
  // Inyecta cvePresets (metadatos con position_default/avoid_faces_default), selecciona un
  // preset y corre onPresetChange(); reporta cómo quedan los controles CVE F6 inicializados.
  const pre = fixture.pre || {};
  body = `
    const g = (id) => document.getElementById(id);
    cvePresets = ${JSON.stringify(pre.cvePresets || [])};
    g('render-preset').value = ${JSON.stringify(pre.preset || "")};
    onPresetChange();
    __out__ = JSON.stringify({
      position: g('render-position').value,
      avoid_faces: !!g('use-avoid-faces').checked,
    });`;
} else if (fixture.fn === "render_params") {
  const pre = fixture.pre || {};
  body = `
    const g = (id) => document.getElementById(id);
    g('render-caption-source').value = ${JSON.stringify(fixture.source)};
    srtPanel.onSource('render');
    videos = [{name: 'v1', stages: {transcrito: true}}];
    g('render-video-select').value = 'v1';
    g('render-preset').value = ${JSON.stringify(pre.preset || "")};
    onPresetChange();
    g('render-densidad').value = ${JSON.stringify(pre.densidad || "")};
    g('render-position').value = ${JSON.stringify(pre.position || "")};
    g('use-avoid-faces').checked = ${pre.avoidFaces === undefined ? true : !!pre.avoidFaces};
    g('use-emphasis').checked = ${!!pre.emphasis};
    g('use-caption-qa').checked = ${!!pre.qa};
    g('caption-qa-mode').value = 'alertas';
    g('render-wpg').value = ${JSON.stringify(pre.wpg || "")};
    let __captured = '';
    fetch = (url) => { __captured = String(url); return Promise.resolve({ok: true, json: () => Promise.resolve({job_id: 'j'})}); };
    startRender();
    __out__ = JSON.stringify({url: __captured, f6_hidden: !!g('field-cve-f6').style.display && g('field-cve-f6').style.display === 'none'});`;
}

const wrapped = `${code}\n;try {\n${body}\n} catch (e) { __err__ = String((e && e.stack) || e); }`;
try { vm.runInContext(wrapped, ctx, { timeout: 8000 }); } catch (e) { base.__initerr__ = String((e && e.stack) || e); }

process.stdout.write(
  JSON.stringify({
    ret: base.__ret__ || "",
    out: base.__out__ || "",
    err: base.__err__ || "",
    initerr: base.__initerr__ || "",
    clips: (store["auto-clips"] || {}).innerHTML || "",
    resume: (store["auto-resume"] || {}).innerHTML || "",
    resumen: (store["auto-resumen"] || {}).textContent || "",
  })
);
