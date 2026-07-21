/* job_polling.js — Motor ÚNICO de polling de jobs de Centrito Studio (H2).
 *
 * Reemplaza la lógica duplicada de pollJob / pollJobP / _pollReframe. Una sola sesión por
 * job con: setTimeout recursivo (nunca setInterval), a lo más UNA request activa por job,
 * AbortController, cleanup garantizado, dedupe por job ID, deadline y límite de errores
 * consecutivos configurables, reset del contador tras éxito, cancelación local, reinicio
 * explícito del seguimiento y resultado terminal ESTRUCTURADO.
 *
 * Cierra P1-POLL-1..4 y P2-POLL-5/6/7. NO cancela el worker real en backend (sólo el
 * seguimiento local del navegador): un `cancelled`/`timeout`/`lost` jamás afirma que se
 * detuvo FFmpeg.
 *
 * Doble entorno, sin bundler ni dependencias externas:
 *   - navegador:  window.CentritoJobPolling
 *   - Node (CJS): module.exports  (para el harness de tests con fetch/timers inyectables)
 *
 * Estados terminales:
 *   done · job_error · lost · unavailable · timeout · cancelled · invalid_response
 */
(function (root, factory) {
  "use strict";
  var api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  if (typeof root !== "undefined" && root) root.CentritoJobPolling = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  var TERMINALS = [
    "done",
    "job_error",
    "lost",
    "unavailable",
    "timeout",
    "cancelled",
    "invalid_response",
  ];

  // Mensajes por defecto (español, accionables, sin filtrar rutas ni comandos).
  var MESSAGES = {
    lost: "El servidor se reinició o el trabajo ya no existe.",
    unavailable: "Se perdió la conexión con el Studio.",
    timeout: "El trabajo está tardando más de lo esperado.",
    invalid_response: "El servidor devolvió una respuesta inesperada.",
    cancelled: "Seguimiento cancelado.",
  };

  var DEFAULTS = {
    intervalMs: 900,
    deadlineMs: 30 * 60 * 1000, // 30 min: cubre renders largos sin colgarse para siempre
    maxConsecutiveErrors: 5,
    requestTimeoutMs: 20 * 1000, // aborta un GET /api/jobs colgado (backend mudo) para no colgar
    jobUrl: function (jobId) {
      return "/api/jobs/" + jobId;
    },
  };

  function isTerminal(reason) {
    return TERMINALS.indexOf(reason) !== -1;
  }

  // Clasifica un fallo REINTENTABLE por su tipo, para elegir el terminal correcto al llegar al
  // límite: 5xx/red -> unavailable; JSON inválido/estado desconocido/4xx raro -> invalid_response.
  function terminalForKind(kind) {
    return kind === "invalid" ? "invalid_response" : "unavailable";
  }

  function Session(poller, jobId, opts) {
    this.poller = poller;
    this.jobId = String(jobId);
    this.onTick = typeof opts.onTick === "function" ? opts.onTick : null;
    this.onTerminal = typeof opts.onTerminal === "function" ? opts.onTerminal : null;
    this.intervalMs = opts.intervalMs != null ? opts.intervalMs : poller.intervalMs;
    this.deadlineMs = opts.deadlineMs != null ? opts.deadlineMs : poller.deadlineMs;
    this.maxConsecutiveErrors =
      opts.maxConsecutiveErrors != null
        ? opts.maxConsecutiveErrors
        : poller.maxConsecutiveErrors;
    this.requestTimeoutMs =
      opts.requestTimeoutMs != null ? opts.requestTimeoutMs : poller.requestTimeoutMs;
    this.consecutiveErrors = 0;
    this.lastErrorKind = "network";
    this.timer = null;
    this.reqTimer = null;
    this.controller = null;
    this.finished = false;
    this.inFlight = false;
    this.startedAt = poller.now();
  }

  Session.prototype._clearTimer = function () {
    if (this.timer !== null) {
      this.poller.clearTimer(this.timer);
      this.timer = null;
    }
  };

  // Timer POR REQUEST: si un fetch queda pendiente para siempre (backend acepta la conexión pero
  // nunca responde), sin esto la sesión jamás vuelve a hacer tick y la UI gira sin fin. Al vencer
  // aborta el controlador -> el fetch se rechaza -> se trata como error de red reintentable.
  Session.prototype._clearReqTimer = function () {
    if (this.reqTimer !== null) {
      this.poller.clearTimer(this.reqTimer);
      this.reqTimer = null;
    }
  };

  Session.prototype._abort = function () {
    if (this.controller) {
      try {
        this.controller.abort();
      } catch (e) {
        /* AbortController.abort() nunca debe tumbar el cleanup */
      }
      this.controller = null;
    }
  };

  // Cierre único: limpia timer + controlador + entrada del mapa y entrega el resultado terminal
  // estructurado exactamente UNA vez. Reentrante-seguro (finished actúa de latch).
  Session.prototype._finish = function (reason, extra) {
    if (this.finished) return;
    this.finished = true;
    this._clearTimer();
    this._clearReqTimer();
    this._abort();
    this.poller._remove(this.jobId, this);
    if (this.onTerminal) {
      var result = { reason: reason, jobId: this.jobId };
      if (extra && extra.job !== undefined) result.job = extra.job;
      result.message =
        (extra && extra.message) || MESSAGES[reason] || (extra && extra.job && extra.job.message) || "";
      this.onTerminal(result);
    }
  };

  Session.prototype.cancel = function () {
    // Sólo detiene el seguimiento LOCAL: aborta el fetch en curso y limpia el timer. No toca el
    // worker de backend. terminal = cancelled.
    this._finish("cancelled", {});
  };

  Session.prototype._scheduleNext = function () {
    if (this.finished) return;
    var self = this;
    this.timer = this.poller.setTimer(function () {
      self.timer = null;
      self._tick();
    }, this.intervalMs);
  };

  Session.prototype._retryable = function (kind) {
    // Contrato ÚNICO de errores consecutivos (5xx, red, JSON inválido, estado desconocido, 4xx
    // no-404). Al alcanzar el límite -> terminal según el ÚLTIMO tipo. Antes del límite reintenta.
    this.lastErrorKind = kind;
    this.consecutiveErrors += 1;
    if (this.consecutiveErrors >= this.maxConsecutiveErrors) {
      this._finish(terminalForKind(kind), {});
      return;
    }
    this._scheduleNext();
  };

  Session.prototype._tick = function () {
    if (this.finished) return;
    // Deadline: si ya se excedió, terminal timeout (NO se declara que el worker fue cancelado).
    if (this.poller.now() - this.startedAt >= this.deadlineMs) {
      this._finish("timeout", {});
      return;
    }
    if (this.inFlight) return; // invariante: nunca dos requests solapadas
    this.inFlight = true;
    this.controller = this.poller.makeAbortController();
    var self = this;
    var signal = this.controller ? this.controller.signal : undefined;
    var url = this.poller.jobUrl(this.jobId);

    // Arma el timeout del request en vuelo (P1-POLL-3: fetch colgado != spinner eterno).
    if (this.requestTimeoutMs > 0) {
      this.reqTimer = this.poller.setTimer(function () {
        self.reqTimer = null;
        if (!self.finished && self.inFlight && self.controller) self.controller.abort();
      }, this.requestTimeoutMs);
    }

    this.poller
      .fetch(url, signal ? { signal: signal } : {})
      .then(function (r) {
        self._clearReqTimer();
        return self._handleResponse(r);
      })
      .catch(function (err) {
        self._clearReqTimer();
        if (self.finished) return; // abortado por cancel(): ya se entregó cancelled
        // Error de red o abort por timeout del request: mismo contrato de errores consecutivos
        // (no se confunde con 404 ni con cancel).
        self.inFlight = false;
        self._retryable("network");
      });
  };

  Session.prototype._handleResponse = function (r) {
    this.inFlight = false;
    if (this.finished) return; // cancelado mientras la respuesta estaba en vuelo
    var status = r && typeof r.status === "number" ? r.status : 0;
    var ok = r && r.ok;
    if (!ok) {
      if (status === 404) {
        // Servidor reiniciado / job inexistente: terminal, NO se reintenta indefinidamente.
        this._finish("lost", {});
        return;
      }
      if (status >= 500) {
        this._retryable("network"); // 5xx: reintenta hasta el límite -> unavailable
        return;
      }
      this._retryable("invalid"); // otro 4xx raro: contador controlado -> invalid_response
      return;
    }
    var self = this;
    return Promise.resolve()
      .then(function () {
        return r.json();
      })
      .then(function (job) {
        if (self.finished) return;
        self._handleJob(job);
      })
      .catch(function () {
        if (self.finished) return;
        self._retryable("invalid"); // 200 con JSON inválido: contador controlado
      });
  };

  Session.prototype._handleJob = function (job) {
    if (!job || typeof job !== "object" || typeof job.status !== "string") {
      this._retryable("invalid");
      return;
    }
    var status = job.status;
    if (status === "done") {
      if (this.onTick) this.onTick(job);
      this.consecutiveErrors = 0;
      this._finish("done", { job: job, message: job.message });
      return;
    }
    if (status === "error") {
      if (this.onTick) this.onTick(job);
      this.consecutiveErrors = 0;
      // Conserva el mensaje saneado del job (POLL-7: la causa exacta no se pierde).
      this._finish("job_error", { job: job, message: job.message });
      return;
    }
    if (status === "running" || status === "pending") {
      this.consecutiveErrors = 0; // respuesta exitosa reinicia el contador de fallos
      if (this.onTick) this.onTick(job);
      this._scheduleNext();
      return;
    }
    // Estado desconocido: nunca quedar colgado -> contador controlado -> invalid_response.
    this._retryable("invalid");
  };

  Session.prototype.start = function () {
    this._tick();
    return this;
  };

  function Poller(deps) {
    deps = deps || {};
    var g = typeof globalThis !== "undefined" ? globalThis : {};
    this.fetch = deps.fetch || (typeof g.fetch === "function" ? g.fetch.bind(g) : null);
    this.setTimer =
      deps.setTimer ||
      (typeof g.setTimeout === "function"
        ? function (fn, ms) {
            return g.setTimeout(fn, ms);
          }
        : function () {
            return 0;
          });
    this.clearTimer =
      deps.clearTimer ||
      (typeof g.clearTimeout === "function"
        ? function (h) {
            g.clearTimeout(h);
          }
        : function () {});
    this.now = deps.now || (typeof Date.now === "function" ? Date.now.bind(Date) : function () { return 0; });
    var AC = deps.AbortController || (typeof g.AbortController === "function" ? g.AbortController : null);
    this.makeAbortController = deps.makeAbortController || (AC ? function () { return new AC(); } : function () { return null; });
    this.jobUrl = deps.jobUrl || DEFAULTS.jobUrl;
    this.intervalMs = deps.intervalMs != null ? deps.intervalMs : DEFAULTS.intervalMs;
    this.deadlineMs = deps.deadlineMs != null ? deps.deadlineMs : DEFAULTS.deadlineMs;
    this.maxConsecutiveErrors =
      deps.maxConsecutiveErrors != null ? deps.maxConsecutiveErrors : DEFAULTS.maxConsecutiveErrors;
    this.requestTimeoutMs =
      deps.requestTimeoutMs != null ? deps.requestTimeoutMs : DEFAULTS.requestTimeoutMs;
    this._sessions = {}; // jobId -> Session activa (dedupe)
  }

  Poller.prototype._remove = function (jobId, session) {
    if (this._sessions[jobId] === session) delete this._sessions[jobId];
  };

  // track(jobId, opts): inicia (o REINICIA) el seguimiento de un job. Dedupe: si ya hay una
  // sesión activa para ese jobId, se cancela antes (iniciar una acción nueva cancela la anterior).
  Poller.prototype.track = function (jobId, opts) {
    jobId = String(jobId);
    this.cancel(jobId);
    var session = new Session(this, jobId, opts || {});
    this._sessions[jobId] = session;
    session.start();
    return session;
  };

  // retry(jobId, opts): vuelve a consultar el MISMO job con deadline y contador NUEVOS. No crea
  // otro job ni relanza el POST original. Igual que track() (dedupe garantiza sesión única).
  Poller.prototype.retry = function (jobId, opts) {
    return this.track(jobId, opts);
  };

  Poller.prototype.cancel = function (jobId) {
    var s = this._sessions[String(jobId)];
    if (s) s.cancel();
  };

  Poller.prototype.cancelAll = function () {
    var ids = Object.keys(this._sessions);
    for (var i = 0; i < ids.length; i++) this.cancel(ids[i]);
  };

  Poller.prototype.active = function (jobId) {
    return Object.prototype.hasOwnProperty.call(this._sessions, String(jobId));
  };

  Poller.prototype.activeCount = function () {
    return Object.keys(this._sessions).length;
  };

  return {
    Poller: Poller,
    createPoller: function (deps) {
      return new Poller(deps);
    },
    TERMINALS: TERMINALS.slice(),
    MESSAGES: MESSAGES,
    DEFAULTS: DEFAULTS,
    isTerminal: isTerminal,
  };
});
