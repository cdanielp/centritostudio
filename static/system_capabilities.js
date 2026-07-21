/* system_capabilities.js — Modo degradado de la UI de Centrito Studio (H3, FASE 9).
 *
 * Modulo puro y aislado (mismo patron que job_polling.js): funciona en el navegador
 * (window.CentritoCapabilities) y en Node (module.exports) sin bundler ni dependencias.
 *
 * Consume /api/system/capabilities y:
 *   - deshabilita SOLO los controles cuya capacidad requerida no esta disponible
 *     (elementos con atributo data-cap="cap1,cap2"; se deshabilita si ALGUNA falta);
 *   - muestra un aviso discreto y accesible (role=status) explicando que falta y que hacer;
 *   - nunca expone rutas absolutas ni secretos (los mensajes vienen del preflight, ya saneados).
 *
 * No cambia layout, colores, navegacion ni el resultado audiovisual.
 */
(function (root) {
  "use strict";

  // Etiquetas legibles (es) por capacidad para el aviso.
  var LABELS = {
    ffmpeg: "FFmpeg",
    ffprobe: "ffprobe",
    render: "Render de captions",
    auto: "Modo Automatico",
    clips: "Generacion de clips",
    depurar: "Depuracion de silencios",
    reframe: "Reframe 9:16 con seguimiento facial",
    video_metadata: "Analisis de video",
    upload_validation: "Validacion de subidas",
    detector_yunet: "Detector YuNet",
    detector_blazeface: "Detector BlazeFace",
    audio_analysis: "Analisis de volumen",
    nvenc: "Codificacion NVIDIA NVENC",
  };

  // No se listan en el aviso: los detectores individuales ("reframe" ya resume su ausencia),
  // audio_analysis (el estado "volumen pendiente" se muestra por tarjeta) y nvenc (su ausencia
  // NO degrada la app: la CPU sigue siendo una ruta valida; solo el modo explicito nvenc se veta).
  var OCULTAS_EN_AVISO = {
    detector_yunet: true,
    detector_blazeface: true,
    audio_analysis: true,
    nvenc: true,
  };

  function unavailableList(caps) {
    caps = caps || {};
    return Object.keys(caps).filter(function (k) {
      return caps[k] && caps[k].available === false;
    });
  }

  function isDisabledByCaps(requires, caps) {
    caps = caps || {};
    return requires.some(function (k) {
      return caps[k] && caps[k].available === false;
    });
  }

  function _mensajePara(requires, caps) {
    for (var i = 0; i < requires.length; i++) {
      var k = requires[i];
      if (caps[k] && caps[k].available === false && caps[k].message) {
        return caps[k].message;
      }
    }
    return "Funcion no disponible en este entorno.";
  }

  function applyCapabilities(caps, doc) {
    caps = caps || {};
    var nodes = (doc && doc.querySelectorAll && doc.querySelectorAll("[data-cap]")) || [];
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var raw = el.getAttribute("data-cap") || "";
      var requires = raw
        .split(",")
        .map(function (s) { return s.trim(); })
        .filter(Boolean);
      var off = isDisabledByCaps(requires, caps);
      el.disabled = off;
      if (off) {
        el.setAttribute("title", _mensajePara(requires, caps));
        el.setAttribute("aria-disabled", "true");
      } else {
        el.removeAttribute("aria-disabled");
      }
    }
    updateBanner(caps, doc);
  }

  function updateBanner(caps, doc) {
    var banner = doc && doc.getElementById && doc.getElementById("system-banner");
    if (!banner) return;
    var off = unavailableList(caps).filter(function (k) {
      return !OCULTAS_EN_AVISO[k];
    });
    if (!off.length) {
      banner.hidden = true;
      banner.textContent = "";
      banner.removeAttribute("role");
      return;
    }
    var items = off.map(function (k) {
      var msg = (caps[k] && caps[k].message) || "no disponible";
      return (LABELS[k] || k) + ": " + msg;
    });
    banner.hidden = false;
    banner.setAttribute("role", "status");
    banner.setAttribute("aria-live", "polite");
    banner.textContent = "Modo degradado — " + items.join(" · ");
  }

  var api = {
    applyCapabilities: applyCapabilities,
    updateBanner: updateBanner,
    unavailableList: unavailableList,
    isDisabledByCaps: isDisabledByCaps,
  };

  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (root) root.CentritoCapabilities = api;
})(typeof window !== "undefined" ? window : null);
