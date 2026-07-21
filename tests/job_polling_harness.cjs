/* job_polling_harness.cjs — Suite determinista del motor REAL `static/job_polling.js` (H2).
 *
 * Ejercita el poller con fetch, timers, reloj y AbortController INYECTABLES (sin red, sin
 * setTimeout real). Cada test valida un contrato del motor (done/error/404/500/red/timeout/
 * cancel/dedupe/no-overlap/cleanup/abort/reset). Imprime JSON {ok, total, passed, results} y
 * sale con código != 0 si algún test falla (el test Python lo ejecuta y exige returncode 0).
 *
 * Uso:  node job_polling_harness.cjs [ruta_job_polling.js]
 */
"use strict";
const path = require("path");
const modPath = process.argv[2] || path.join(__dirname, "..", "static", "job_polling.js");
const CJP = require(modPath);

// ── Reloj + scheduler falso ──────────────────────────────────────────────────
function makeClock() {
  let nowMs = 0;
  let seq = 1;
  const timers = new Map(); // id -> {fireAt, fn}
  return {
    now: () => nowMs,
    setTimer: (fn, ms) => {
      const id = seq++;
      timers.set(id, { fireAt: nowMs + (ms || 0), fn: fn });
      return id;
    },
    clearTimer: (id) => timers.delete(id),
    pending: () => timers.size,
    // Avanza el reloj `ms` disparando los timers vencidos EN ORDEN, drenando microtasks entre
    // cada disparo para que las cadenas de promesas de fetch se resuelvan de forma determinista.
    advance: async (ms) => {
      const target = nowMs + ms;
      // eslint-disable-next-line no-constant-condition
      while (true) {
        let next = null;
        for (const [id, t] of timers) {
          if (t.fireAt <= target && (next === null || t.fireAt < next.fireAt)) {
            next = { id, fireAt: t.fireAt, fn: t.fn };
          }
        }
        if (next === null) {
          nowMs = target;
          break;
        }
        nowMs = next.fireAt;
        timers.delete(next.id);
        next.fn();
        await flush();
      }
    },
  };
}

async function flush() {
  for (let i = 0; i < 40; i++) await Promise.resolve();
}

// ── AbortController falso (registra creaciones + aborts) ──────────────────────
function makeAbortFactory(log) {
  return function () {
    const signal = { aborted: false };
    const c = {
      aborted: false,
      signal: signal,
      abort: function () {
        c.aborted = true;
        signal.aborted = true;
        log.aborts++;
        if (signal._onabort) signal._onabort(); // despierta a un fetch colgado -> rechazo
      },
    };
    log.created++;
    log.controllers.push(c);
    return c;
  };
}

// ── fetch scriptado ───────────────────────────────────────────────────────────
// steps: array de descriptores consumidos por llamada; el último se repite si se agota.
//   {ok, status, json}          -> respuesta HTTP con JSON
//   {ok:true, status:200, bad:true} -> 200 con JSON inválido (r.json() lanza)
//   {net:true}                  -> fetch rechaza (error de red)
function makeFetch(steps, log) {
  let i = 0;
  return function (url, init) {
    log.calls++;
    log.concurrent++;
    if (log.concurrent > log.maxConcurrent) log.maxConcurrent = log.concurrent;
    log.lastInit = init;
    const step = steps[Math.min(i, steps.length - 1)];
    i++;
    // Fetch COLGADO: nunca resuelve por su cuenta; solo se rechaza cuando el signal se aborta
    // (timeout del request). Simula un backend que acepta la conexión pero no responde.
    if (step.hang) {
      const sig = init && init.signal;
      return new Promise((_resolve, reject) => {
        if (sig) sig._onabort = () => { log.concurrent--; reject(new Error("aborted")); };
      });
    }
    // BODY colgado: los headers llegan (fetch resuelve ok) pero r.json() se cuelga leyendo el
    // cuerpo hasta que el signal se aborta. Verifica que el timeout siga activo tras los headers.
    if (step.bodyHang) {
      const sig = init && init.signal;
      log.concurrent--;
      return Promise.resolve({
        ok: true,
        status: 200,
        json: function () {
          return new Promise((_res, rej) => {
            if (sig) sig._onabort = () => rej(new Error("body aborted"));
          });
        },
      });
    }
    return new Promise((resolve, reject) => {
      // resuelve en microtask para simular I/O sin timers reales
      Promise.resolve().then(() => {
        log.concurrent--;
        if (step.net) return reject(new Error("network down"));
        const r = {
          ok: step.ok,
          status: step.status,
          json: function () {
            if (step.bad) return Promise.reject(new Error("bad json"));
            return Promise.resolve(step.json);
          },
        };
        resolve(r);
      });
    });
  };
}

function makeHarness(steps, opts) {
  opts = opts || {};
  const clock = makeClock();
  const flog = { calls: 0, concurrent: 0, maxConcurrent: 0, lastInit: null };
  const alog = { created: 0, aborts: 0, controllers: [] };
  const poller = CJP.createPoller({
    fetch: makeFetch(steps, flog),
    setTimer: clock.setTimer,
    clearTimer: clock.clearTimer,
    now: clock.now,
    makeAbortController: makeAbortFactory(alog),
    intervalMs: opts.intervalMs != null ? opts.intervalMs : 900,
    deadlineMs: opts.deadlineMs != null ? opts.deadlineMs : 30 * 60 * 1000,
    maxConsecutiveErrors: opts.maxConsecutiveErrors != null ? opts.maxConsecutiveErrors : 5,
  });
  return { clock, flog, alog, poller };
}

// track + drive: flush inicial y luego advance(interval) hasta terminal o maxSteps.
async function drive(h, jobId, handlers, maxSteps) {
  const ticks = [];
  let terminal = null;
  const session = h.poller.track(jobId, {
    onTick: (j) => {
      ticks.push(j);
      if (handlers && handlers.onTick) handlers.onTick(j, session);
    },
    onTerminal: (r) => {
      terminal = r;
    },
    intervalMs: handlers && handlers.intervalMs,
    deadlineMs: handlers && handlers.deadlineMs,
    maxConsecutiveErrors: handlers && handlers.maxConsecutiveErrors,
  });
  await flush();
  let steps = maxSteps || 20;
  const interval = (handlers && handlers.intervalMs) || 900;
  while (terminal === null && steps-- > 0) {
    if (handlers && handlers.beforeAdvance) {
      const stop = await handlers.beforeAdvance(session, h);
      if (stop) break;
    }
    await h.clock.advance(interval);
  }
  return { session, ticks, terminal };
}

// ── Tests ─────────────────────────────────────────────────────────────────────
const tests = [];
function test(name, fn) {
  tests.push({ name, fn });
}
function assert(cond, msg) {
  if (!cond) throw new Error(msg || "assertion failed");
}

test("1_done", async () => {
  const h = makeHarness([{ ok: true, status: 200, json: { status: "done", message: "listo" } }]);
  const { ticks, terminal } = await drive(h, "j");
  assert(terminal && terminal.reason === "done", "reason=" + (terminal && terminal.reason));
  assert(terminal.job && terminal.job.status === "done", "job.done");
  assert(terminal.message === "listo", "msg=" + terminal.message);
  assert(ticks.length === 1 && ticks[0].status === "done", "tick done");
});

test("2_job_error", async () => {
  const h = makeHarness([{ ok: true, status: 200, json: { status: "error", message: "falló X" } }]);
  const { terminal } = await drive(h, "j");
  assert(terminal.reason === "job_error", "reason=" + terminal.reason);
  assert(terminal.message === "falló X", "msg conserva la causa exacta: " + terminal.message);
  assert(terminal.job && terminal.job.status === "error", "job.error");
});

test("3_pending_running_done", async () => {
  const h = makeHarness([
    { ok: true, status: 200, json: { status: "pending", progress: 0 } },
    { ok: true, status: 200, json: { status: "running", progress: 50 } },
    { ok: true, status: 200, json: { status: "done", message: "ok" } },
  ]);
  const { ticks, terminal } = await drive(h, "j");
  assert(terminal.reason === "done", "reason=" + terminal.reason);
  assert(ticks.length === 3, "3 ticks, got " + ticks.length);
  assert(ticks[0].status === "pending" && ticks[1].status === "running", "orden");
});

test("4_404_lost", async () => {
  const h = makeHarness([{ ok: false, status: 404 }]);
  const { terminal } = await drive(h, "j");
  assert(terminal.reason === "lost", "reason=" + terminal.reason);
  assert(/reinici|ya no existe/i.test(terminal.message), "msg lost: " + terminal.message);
  assert(h.flog.calls === 1, "404 no reintenta: calls=" + h.flog.calls);
});

test("5_500_temporal_recupera", async () => {
  const h = makeHarness([
    { ok: false, status: 500 },
    { ok: true, status: 200, json: { status: "done", message: "ok" } },
  ]);
  const { terminal } = await drive(h, "j");
  assert(terminal.reason === "done", "reason=" + terminal.reason);
  assert(h.flog.calls === 2, "reintentó 1 vez: " + h.flog.calls);
});

test("6_500_hasta_limite_unavailable", async () => {
  const h = makeHarness([{ ok: false, status: 500 }], { maxConsecutiveErrors: 3 });
  const { terminal } = await drive(h, "j");
  assert(terminal.reason === "unavailable", "reason=" + terminal.reason);
  assert(h.flog.calls === 3, "3 intentos hasta límite: " + h.flog.calls);
});

test("7_red_temporal_recupera", async () => {
  const h = makeHarness([
    { net: true },
    { ok: true, status: 200, json: { status: "done", message: "ok" } },
  ]);
  const { terminal } = await drive(h, "j");
  assert(terminal.reason === "done", "reason=" + terminal.reason);
  assert(h.flog.calls === 2, "calls=" + h.flog.calls);
});

test("8_red_hasta_limite_unavailable", async () => {
  const h = makeHarness([{ net: true }], { maxConsecutiveErrors: 4 });
  const { terminal } = await drive(h, "j");
  assert(terminal.reason === "unavailable", "reason=" + terminal.reason);
  assert(h.flog.calls === 4, "calls=" + h.flog.calls);
});

test("9a_json_invalido_recupera", async () => {
  const h = makeHarness([
    { ok: true, status: 200, bad: true },
    { ok: true, status: 200, json: { status: "done", message: "ok" } },
  ]);
  const { terminal } = await drive(h, "j");
  assert(terminal.reason === "done", "reason=" + terminal.reason);
});

test("9b_json_invalido_hasta_limite_invalid_response", async () => {
  const h = makeHarness([{ ok: true, status: 200, bad: true }], { maxConsecutiveErrors: 2 });
  const { terminal } = await drive(h, "j");
  assert(terminal.reason === "invalid_response", "reason=" + terminal.reason);
});

test("10a_status_desconocido_recupera", async () => {
  const h = makeHarness([
    { ok: true, status: 200, json: { status: "wat" } },
    { ok: true, status: 200, json: { status: "done", message: "ok" } },
  ]);
  const { terminal } = await drive(h, "j");
  assert(terminal.reason === "done", "reason=" + terminal.reason);
});

test("10b_status_desconocido_hasta_limite_invalid_response", async () => {
  const h = makeHarness([{ ok: true, status: 200, json: { status: "???" } }], {
    maxConsecutiveErrors: 2,
  });
  const { terminal } = await drive(h, "j");
  assert(terminal.reason === "invalid_response", "reason=" + terminal.reason);
});

test("11_deadline_timeout", async () => {
  // running perpetuo; deadline corto -> timeout (nunca declara worker cancelado).
  const h = makeHarness([{ ok: true, status: 200, json: { status: "running", progress: 10 } }], {
    deadlineMs: 2000,
    intervalMs: 500,
  });
  const { terminal } = await drive(h, "j", { intervalMs: 500 }, 40);
  assert(terminal.reason === "timeout", "reason=" + terminal.reason);
  assert(/tardando/i.test(terminal.message), "msg timeout: " + terminal.message);
});

test("12_cancel", async () => {
  const h = makeHarness([{ ok: true, status: 200, json: { status: "running", progress: 10 } }]);
  let terminal = null;
  const s = h.poller.track("j", { onTerminal: (r) => (terminal = r) });
  await flush();
  s.cancel();
  await flush();
  assert(terminal && terminal.reason === "cancelled", "reason=" + (terminal && terminal.reason));
  assert(h.clock.pending() === 0, "timers limpios tras cancel");
  assert(h.poller.activeCount() === 0, "sesión removida del mapa");
});

test("13_retry_misma_sesion", async () => {
  // Primer intento cae a lost (404). retry() re-consulta el MISMO job (ahora responde done).
  const steps = [{ ok: false, status: 404 }, { ok: true, status: 200, json: { status: "done", message: "ok" } }];
  const h = makeHarness(steps);
  let t1 = null;
  h.poller.track("j", { onTerminal: (r) => (t1 = r) });
  await flush();
  assert(t1.reason === "lost", "primer terminal lost");
  let t2 = null;
  h.poller.retry("j", { onTerminal: (r) => (t2 = r) });
  await flush();
  assert(t2 && t2.reason === "done", "retry done: " + (t2 && t2.reason));
  assert(h.flog.calls === 2, "retry no crea job nuevo, sólo reconsulta: " + h.flog.calls);
});

test("14_dedupe_mismo_job", async () => {
  const h = makeHarness([{ ok: true, status: 200, json: { status: "running", progress: 1 } }]);
  h.poller.track("j", {});
  h.poller.track("j", {});
  await flush();
  assert(h.poller.activeCount() === 1, "una sola sesión activa: " + h.poller.activeCount());
});

test("15_nueva_sesion_cancela_anterior", async () => {
  const h = makeHarness([{ ok: true, status: 200, json: { status: "running", progress: 1 } }]);
  let firstTerminal = null;
  h.poller.track("j", { onTerminal: (r) => (firstTerminal = r) });
  await flush();
  h.poller.track("j", {}); // reinicio explícito
  await flush();
  assert(firstTerminal && firstTerminal.reason === "cancelled", "la anterior recibió cancelled");
  assert(h.poller.activeCount() === 1, "una activa");
});

test("16_no_requests_superpuestas", async () => {
  const h = makeHarness([
    { ok: true, status: 200, json: { status: "running", progress: 10 } },
    { ok: true, status: 200, json: { status: "running", progress: 20 } },
    { ok: true, status: 200, json: { status: "done", message: "ok" } },
  ]);
  await drive(h, "j");
  assert(h.flog.maxConcurrent <= 1, "maxConcurrent=" + h.flog.maxConcurrent);
});

test("17_timer_limpio_tras_done", async () => {
  const h = makeHarness([{ ok: true, status: 200, json: { status: "done", message: "ok" } }]);
  await drive(h, "j");
  assert(h.clock.pending() === 0, "timers pendientes=" + h.clock.pending());
  assert(h.poller.activeCount() === 0, "sin sesiones activas");
});

test("18_timer_limpio_tras_error", async () => {
  const h = makeHarness([{ ok: true, status: 200, json: { status: "error", message: "x" } }]);
  await drive(h, "j");
  assert(h.clock.pending() === 0, "timers pendientes=" + h.clock.pending());
});

test("19_abortcontroller_usado", async () => {
  const h = makeHarness([{ ok: true, status: 200, json: { status: "running", progress: 1 } }]);
  const s = h.poller.track("j", {});
  await flush();
  assert(h.alog.created >= 1, "se creó AbortController: " + h.alog.created);
  s.cancel();
  await flush();
  assert(h.alog.aborts >= 1, "abort() invocado en cancel: " + h.alog.aborts);
});

test("20_contador_reinicia_tras_exito", async () => {
  // 500, running (éxito: reinicia), 500, running, 500, done. Con límite 2 NUNCA debe caer a
  // unavailable porque cada éxito reinicia el contador.
  const h = makeHarness(
    [
      { ok: false, status: 500 },
      { ok: true, status: 200, json: { status: "running", progress: 10 } },
      { ok: false, status: 500 },
      { ok: true, status: 200, json: { status: "running", progress: 20 } },
      { ok: false, status: 500 },
      { ok: true, status: 200, json: { status: "done", message: "ok" } },
    ],
    { maxConsecutiveErrors: 2 }
  );
  const { terminal } = await drive(h, "j", null, 30);
  assert(terminal.reason === "done", "reason=" + terminal.reason);
});

test("21_job_error_conserva_causa", async () => {
  const h = makeHarness([
    { ok: true, status: 200, json: { status: "error", message: "OOM en FFmpeg", error: "OOM" } },
  ]);
  const { terminal } = await drive(h, "j");
  assert(terminal.reason === "job_error", "reason");
  assert(terminal.job.error === "OOM" && terminal.message === "OOM en FFmpeg", "causa exacta");
});

test("22_fetch_colgado_se_aborta_por_timeout", async () => {
  // Backend mudo: cada fetch queda pendiente hasta que el timeout del request lo aborta -> error
  // de red reintentable -> al llegar al limite, terminal unavailable. NUNCA queda colgado.
  const h = makeHarness([{ hang: true }], {
    requestTimeoutMs: 500,
    intervalMs: 100,
    maxConsecutiveErrors: 3,
    deadlineMs: 10 * 60 * 1000,
  });
  let terminal = null;
  h.poller.track("j", {
    onTerminal: (r) => (terminal = r),
    requestTimeoutMs: 500,
    intervalMs: 100,
    maxConsecutiveErrors: 3,
    deadlineMs: 10 * 60 * 1000,
  });
  await flush();
  for (let i = 0; i < 10 && terminal === null; i++) await h.clock.advance(600);
  assert(terminal && terminal.reason === "unavailable", "reason=" + (terminal && terminal.reason));
  assert(h.alog.aborts >= 1, "el fetch colgado se aborto por timeout: " + h.alog.aborts);
  assert(h.clock.pending() === 0, "sin timers pendientes tras terminal");
});

test("24_body_colgado_se_aborta_por_timeout", async () => {
  // Headers llegan pero r.json() se cuelga: el timeout debe seguir activo y abortar el body,
  // tratandolo como error de red reintentable -> unavailable al limite. NUNCA queda colgado.
  const h = makeHarness([{ bodyHang: true }], {
    requestTimeoutMs: 500,
    intervalMs: 100,
    maxConsecutiveErrors: 3,
    deadlineMs: 10 * 60 * 1000,
  });
  let terminal = null;
  h.poller.track("j", {
    onTerminal: (r) => (terminal = r),
    requestTimeoutMs: 500,
    intervalMs: 100,
    maxConsecutiveErrors: 3,
    deadlineMs: 10 * 60 * 1000,
  });
  await flush();
  for (let i = 0; i < 12 && terminal === null; i++) await h.clock.advance(600);
  assert(terminal && terminal.reason === "unavailable", "reason=" + (terminal && terminal.reason));
  assert(h.alog.aborts >= 1, "el body colgado se aborto por timeout: " + h.alog.aborts);
  assert(h.clock.pending() === 0, "sin timers pendientes tras terminal");
});

test("23_fetch_colgado_se_recupera_si_responde", async () => {
  // Un fetch cuelga una vez (se aborta por timeout) y el siguiente responde done -> recupera.
  const h = makeHarness(
    [{ hang: true }, { ok: true, status: 200, json: { status: "done", message: "ok" } }],
    { requestTimeoutMs: 500, intervalMs: 100, maxConsecutiveErrors: 5, deadlineMs: 10 * 60 * 1000 }
  );
  let terminal = null;
  h.poller.track("j", {
    onTerminal: (r) => (terminal = r),
    requestTimeoutMs: 500,
    intervalMs: 100,
    maxConsecutiveErrors: 5,
    deadlineMs: 10 * 60 * 1000,
  });
  await flush();
  for (let i = 0; i < 10 && terminal === null; i++) await h.clock.advance(600);
  assert(terminal && terminal.reason === "done", "reason=" + (terminal && terminal.reason));
});

// ── Runner ────────────────────────────────────────────────────────────────────
(async () => {
  const results = [];
  let passed = 0;
  for (const t of tests) {
    try {
      await t.fn();
      results.push({ name: t.name, pass: true });
      passed++;
    } catch (e) {
      results.push({ name: t.name, pass: false, detail: String((e && e.message) || e) });
    }
  }
  const ok = passed === tests.length;
  process.stdout.write(JSON.stringify({ ok, total: tests.length, passed, results }, null, 2) + "\n");
  process.exit(ok ? 0 : 1);
})();
