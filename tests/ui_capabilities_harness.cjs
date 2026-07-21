/* ui_capabilities_harness.cjs — Ejecuta el modulo REAL static/system_capabilities.js con un DOM
 * minimo para testear el modo degradado (H3) sin navegador. Fixture JSON por stdin:
 *   { caps: {<cap>: {available, message}}, elements: [{data-cap: "render"}, ...] }
 * Salida (stdout): JSON { elements: [{cap, disabled, title, ariaDisabled}], banner: {hidden, role, text} }
 */
const fs = require("fs");
const path = require("path");
const cap = require(path.join(__dirname, "..", "static", "system_capabilities.js"));

const fixture = JSON.parse(fs.readFileSync(0, "utf8"));

function makeEl(attrs) {
  const a = Object.assign({}, attrs);
  return {
    disabled: false,
    _a: a,
    getAttribute: (k) => (k in a ? a[k] : null),
    setAttribute: (k, v) => { a[k] = String(v); },
    removeAttribute: (k) => { delete a[k]; },
  };
}

const elements = (fixture.elements || []).map((e) => makeEl(e));
const bannerAttrs = {};
const banner = {
  hidden: true,
  textContent: "",
  setAttribute: (k, v) => { bannerAttrs[k] = String(v); },
  removeAttribute: (k) => { delete bannerAttrs[k]; },
};
const doc = {
  querySelectorAll: () => elements,
  getElementById: (id) => (id === "system-banner" ? banner : null),
};

// caps=null debe ser tolerado (fallo al consultar capabilities no rompe la UI)
cap.applyCapabilities(fixture.caps === undefined ? null : fixture.caps, doc);

const out = {
  elements: elements.map((el) => ({
    cap: el.getAttribute("data-cap"),
    disabled: el.disabled,
    title: el.getAttribute("title"),
    ariaDisabled: el.getAttribute("aria-disabled"),
  })),
  banner: { hidden: banner.hidden, role: bannerAttrs.role || null, text: banner.textContent },
};
process.stdout.write(JSON.stringify(out));
