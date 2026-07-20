/* ui_render_harness.cjs — Ejecuta las funciones REALES de render de clips de Auto del
 * static/index.html en un sandbox `vm` con un DOM mínimo, para testear (sin Playwright) la
 * política de tarjetas: un clip con status "error" NUNCA es publicable (ni v2 ni classic).
 *
 * Uso:  node ui_render_harness.cjs <ruta_index.html>   (fixture JSON por stdin)
 * Salida (stdout): JSON { ret, err, initerr, clips, resume, resumen }
 *   - fixture.fn === 'clip'  -> ret = JSON({html}) de renderAutoClip(clip, i, pkgId, v2)
 *   - fixture.fn === 'result'-> renderAutoResult(result); clips/resume = innerHTML capturados
 */
const fs = require("fs");
const vm = require("vm");

// Algún statement top-level del bundle dispara cargas async (loadVideos, etc.). Con un DOM
// stub esas promesas se rechazan; se silencian para no tumbar el proceso (no afectan el render).
process.on("unhandledRejection", () => {});

const htmlPath = process.argv[2];
const fixture = JSON.parse(fs.readFileSync(0, "utf8"));
const html = fs.readFileSync(htmlPath, "utf8");

const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
// Se elimina el auto-arranque por hash (necesita el DOM real); las funciones ya quedan definidas.
const code = scripts.join("\n;\n").replace(/_rutaInicial\(\);/, "");

const store = {};
function fakeEl(id) {
  if (!store[id]) {
    store[id] = {
      id, innerHTML: "", textContent: "", value: "", disabled: false, style: {},
      classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
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

// 1) Define funciones (los errores de statements top-level no impiden las declaraciones).
try { vm.runInContext(code, ctx, { timeout: 8000 }); } catch (e) { base.__initerr__ = String((e && e.stack) || e); }

// 2) Invoca la función bajo prueba en el mismo contexto (funciones persisten en el global).
const call =
  fixture.fn === "clip"
    ? `__ret__ = JSON.stringify({html: renderAutoClip(${JSON.stringify(fixture.clip)}, ${fixture.i | 0}, ${JSON.stringify(fixture.pkgId || "")}, ${!!fixture.v2})});`
    : `renderAutoResult(${JSON.stringify(fixture.result)});`;
try { vm.runInContext(call, ctx, { timeout: 8000 }); } catch (e) { base.__err__ = String((e && e.stack) || e); }

process.stdout.write(
  JSON.stringify({
    ret: base.__ret__ || "",
    err: base.__err__ || "",
    initerr: base.__initerr__ || "",
    clips: (store["auto-clips"] || {}).innerHTML || "",
    resume: (store["auto-resume"] || {}).innerHTML || "",
    resumen: (store["auto-resumen"] || {}).textContent || "",
  })
);
