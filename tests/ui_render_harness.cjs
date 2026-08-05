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
const path = require("path");
const vm = require("vm");
// El motor de polling H2 es un módulo aparte cargado por <script src>; el bundle inline lo espera
// como window.CentritoJobPolling. Lo inyectamos para que pollJob/pollJobP/trackJob sean reales.
const CentritoJobPolling = require(path.join(__dirname, "..", "static", "job_polling.js"));

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
function makeEl(id) {
  const attrs = {};
  const listeners = {};
  const el = {
    id, textContent: "", value: "", disabled: false, checked: false,
    hidden: false, style: {}, classList: makeClassList(), children: [], _attrs: attrs, _listeners: listeners,
    setAttribute(k, v) { attrs[k] = String(v); },
    getAttribute(k) { return k in attrs ? attrs[k] : null; },
    appendChild(child) { this.children.push(child); return child; },
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
    click() { (listeners.click || []).forEach((fn) => fn()); },
    querySelector() { return null; }, querySelectorAll() { return []; },
    scrollIntoView() {}, focus() {}, remove() {}, closest() { return null; },
  };
  // Reescribir el innerHTML de un <select> DESCARTA sus <option>, y con ellos la seleccion:
  // el navegador deja `value` en "". Sin modelarlo, el stub miente y un test puede pasar por
  // una razon que en el navegador no se cumple (paso justo con populateSelects, S41).
  let html = "";
  Object.defineProperty(el, "innerHTML", {
    get: () => html,
    set(v) {
      html = v;
      if (id.endsWith("-select")) el.value = "";
    },
    enumerable: true,
  });
  return el;
}
function fakeEl(id) {
  if (!store[id]) store[id] = makeEl(id);
  return store[id];
}
const documentStub = {
  getElementById: (id) => fakeEl(id),
  querySelector: () => null,
  querySelectorAll: () => [],
  createElement: () => makeEl("_el" + Math.random()),
  addEventListener: () => {},
  readyState: "complete", title: "", body: fakeEl("body"), documentElement: fakeEl("html"),
};
function FakeAbortController() { this.signal = {}; this.abort = () => {}; }
const base = {
  document: documentStub, console, location: { hash: "", href: "" }, navigator: {},
  setTimeout: () => 0, clearTimeout: () => {}, setInterval: () => 0, clearInterval: () => {},
  AbortController: FakeAbortController, CentritoJobPolling,
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
} else if (fixture.fn === "failui") {
  // Estado terminal ACCIONABLE: renderJobFailureUI(el, {reason,message}, {onRetry,onDismiss}).
  // Reporta role, mensaje, labels de botones y si Reintentar re-consulta (onRetry invocado).
  body = `
    const el = document.createElement('div');
    let retried = 0, dismissed = 0;
    renderJobFailureUI(el, ${JSON.stringify(fixture.res || {})}, {
      onRetry: () => { retried++; }, onDismiss: () => { dismissed++; },
    });
    // Recorre descendientes y toma sólo los que tienen listener de click (los botones de acción).
    const buttons = [];
    (function walk(n) {
      (n.children || []).forEach((c) => {
        if (c._listeners && c._listeners.click && c._listeners.click.length) buttons.push(c);
        walk(c);
      });
    })(el);
    const labels = buttons.map(b => b.textContent);
    if (${JSON.stringify(!!fixture.clickLabel)}) {
      const target = buttons.find(b => b.textContent === ${JSON.stringify(fixture.clickLabel || "")});
      if (target) target.click();
    }
    __out__ = JSON.stringify({
      role: el.getAttribute('role'),
      msg: (el.children[0] && el.children[0].textContent) || '',
      labels, retried, dismissed,
    });`;
} else if (fixture.fn === "trackaria") {
  // trackJob REAL: mientras corre, marca su contenedor como región viva (role=status/aria-live).
  // Es síncrono en start(), así que se puede afirmar sin manejar timers reales.
  body = `
    const statusEl = document.createElement('div');
    trackJob('j', { statusEl, reenable: () => {}, onTick: () => {}, onDone: () => {}, onJobError: () => {} });
    __out__ = JSON.stringify({
      role: statusEl.getAttribute('role'),
      ariaLive: statusEl.getAttribute('aria-live'),
      hasPoller: !!(window.CentritoJobPolling),
    });`;
} else if (fixture.fn === "offset_ciclo") {
  // S41: ejercita el ciclo REAL del offset (guardar propuesta / aplicar / descartar / cambiar
  // de video / abrir render por fuera del select / refresh que falla) y reporta el estado.
  body = `
    const g = (id) => document.getElementById(id);
    g('render-caption-source').value = 'srt';
    srtPanel.onSource('render');
    videos = [{name: 'v1', status: 'transcrito', stages: {}}, {name: 'v2', status: 'transcrito', stages: {}}];
    g('render-video-select').value = 'v1';
    for (const paso of ${JSON.stringify(fixture.pasos || [])}) {
      if (paso === 'aplicar') srtPanel.aplicarOffset('render');
      else if (paso === 'descartar') srtPanel.descartarOffset('render');
      else if (paso === 'cambiar_video') { g('render-video-select').value = 'v2'; srtPanel.onVideo('render'); }
      else if (paso === 'open_render') openRender('v2');
      // La funcion REAL: reescribe el <select> y deja la seleccion vacia sin pasar por el
      // onchange. Se llama tal cual para que el test no pueda pasar por una simulacion amable.
      else if (paso === 'repoblar_selector') populateSelects();
      else if (paso === 'refresh_falla') {
        fetch = () => Promise.resolve({ok: false, status: 500, json: () => Promise.resolve({})});
        srtPanel.refresh('render');
      } else if (paso && paso.guardar !== undefined) srtPanel._guardarOffset('render', paso.guardar);
    }
    const _p = srtPanel.offsetPropuesto.render, _a = srtPanel.offsetAceptado.render;
    const _box = g('render-srt-offset');
    __out__ = JSON.stringify({
      propuesto: _p && typeof _p === 'object' ? _p.ms : _p,
      aceptado: _a && typeof _a === 'object' ? _a.ms : _a,
      aceptado_video: _a && typeof _a === 'object' ? _a.video : null,
      tarjeta_visible: !_box.hidden,
      tarjeta_html: _box.innerHTML,
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
    // S41: el checkbox de alineado parcial nace marcado en el HTML; el DOM stub no lo lee, asi
    // que el fixture lo declara. offsetPropuesto/offsetAceptado simulan lo que dejo el view
    // model y lo que K acepto con un clic. (Sin backticks: esto vive dentro de un template.)
    g('render-srt-parcial').checked = ${pre.parcial === undefined ? true : !!pre.parcial};
    // El estado del offset lleva el video al que pertenece: 'v1' es el que se renderiza, asi
    // que un valor con otro nombre simula el residuo de un video anterior.
    srtPanel.offsetPropuesto.render = ${
      pre.offsetPropuesto === undefined
        ? "null"
        : `{video: 'v1', ms: ${Number(pre.offsetPropuesto)}, info: {n_anclas: 60, confianza: 0.99, aplicable: true}}`
    };
    srtPanel.offsetAceptado.render = ${
      pre.offsetAceptado === undefined
        ? "null"
        : `{video: ${JSON.stringify(pre.offsetAceptadoVideo || "v1")}, ms: ${Number(pre.offsetAceptado)}}`
    };
    let __captured = '';
    fetch = (url) => { __captured = String(url); return Promise.resolve({ok: true, json: () => Promise.resolve({job_id: 'j'})}); };
    startRender();
    __out__ = JSON.stringify({url: __captured, f6_hidden: !!g('field-cve-f6').style.display && g('field-cve-f6').style.display === 'none'});`;
} else if (fixture.fn === "auto_params") {
  // HF-4 Formato dual: captura la URL del POST /api/videos/{name}/auto que arma startAuto(),
  // igual que 'render_params' hace para el render manual.
  const pre = fixture.pre || {};
  body = `
    const g = (id) => document.getElementById(id);
    g('auto-video-select').value = 'v1';
    g('auto-objetivo').value = 'clips';
    g('auto-mode').value = ${JSON.stringify(pre.mode || "classic")};
    if (g('auto-formato')) g('auto-formato').value = ${JSON.stringify(pre.formato || "9:16")};
    g('auto-broll-enabled').checked = true;
    g('auto-fx-enabled').checked = true;
    g('auto-fx-preset').value = 'express';
    let __captured = '';
    fetch = (url) => { __captured = String(url); return Promise.resolve({ok: true, json: () => Promise.resolve({job_id: 'j'})}); };
    startAuto();
    __out__ = JSON.stringify({url: __captured});`;
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
