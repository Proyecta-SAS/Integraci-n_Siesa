const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

function app() {
  const elements = new Map();
  const document = {
    querySelectorAll: () => [],
    querySelector(selector) {
      if (!elements.has(selector)) elements.set(selector, {
        textContent: "", innerHTML: "", dataset: {}, addEventListener() {},
        firstChild: { textContent: "Activar" },
        classList: { add() {}, remove() {} },
        querySelector() { return { textContent: "" }; },
      });
      return elements.get(selector);
    },
  };
  const context = vm.createContext({ document, Intl });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../web/app.js"), "utf8"), context);
  return { context, elements };
}

test("possible duplicates remain ready and confirmed rows are excluded from pending totals", () => {
  const { context, elements } = app();
  const base = { customer: "Cliente", amount: "1250872", valid: true, cross_ready: true, issues: [] };
  context.renderRows([
    { ...base, source_row: 11, note: "Primero", already_sent: true, ready: false },
    { ...base, source_row: 12, note: "Primero", duplicate_of: 11, already_sent: false, ready: true },
  ]);
  assert.match(elements.get("#rowsBody").innerHTML, /Posible duplicado: coincide con la fila 11/);
  assert.match(elements.get("#rowsBody").innerHTML, /no bloquea el envio a Siesa/);
  assert.match(elements.get("#rowsBody").innerHTML, /Ya registrado/);
  assert.equal(elements.get("#readyRowsMetric").textContent, "1/2");
  assert.equal(elements.get("#amountMetric").textContent, context.formatMoney("1250872"));
  context.renderRows([
    { ...base, source_row: 11, note: "Primero", already_sent: true, ready: false },
    { ...base, source_row: 12, note: "Segundo pago <confirmado>", ready: true },
  ]);
  assert.equal(elements.get("#readyRowsMetric").textContent, "1/2");
  assert.equal(elements.get("#amountMetric").textContent, context.formatMoney("1250872"));
  assert.match(elements.get("#rowsBody").innerHTML, /Segundo pago &lt;confirmado&gt;/);
});

test("a successful send displays its possible duplicate warning", async () => {
  const { context, elements } = app();
  await context.summarizeSyncResult({ result: {
    sent: 2, processed: 2, possible_duplicates: 1,
    warnings: [{ source_row: 12, message: "Posible duplicado: coincide con la fila 11." }],
  } }, "send");
  assert.match(elements.get("#resultList").innerHTML, /Posible duplicado/);
  assert.match(elements.get("#resultMessage").textContent, /2 recibo/);
  assert.equal(elements.get("#resultTitle").dataset.tone, "warn");
});

test("a plain upstream error asks to check status before retrying", async () => {
  const { context } = app();
  context.fetch = async () => ({ status: 502, ok: false, text: async () => "upstream error" });
  await assert.rejects(context.api("/api/sync/send", { method: "POST" }), /el proceso puede haber continuado/);
});

test("monitoring continues beyond five minutes and recovers from a lost connection without another POST", async () => {
  const { context, elements } = app();
  let elapsed = 0;
  let polls = 0;
  const urls = [];
  context.setTimeout = (resolve, delay) => { elapsed += delay; queueMicrotask(resolve); };
  context.loadRows = async () => {};
  context.loadStatus = async () => {};
  context.fetch = async (url, options) => {
    urls.push(url);
    assert.equal(options.method, undefined);
    polls++;
    if (polls === 2) throw new Error("connection lost");
    const job = polls <= 160
      ? { status: "running", progress: { total: 109, completed: 40, sent: 40 } }
      : { status: "completed", outcome: { result: { sent: 109, processed: 109 } } };
    return { ok: true, text: async () => JSON.stringify({ ok: true, job }) };
  };
  vm.runInContext('sendJobs.set("alianza", { status: "running" });', context);
  await context.monitorSendJob("alianza");
  assert.ok(elapsed > 300000);
  assert.ok(urls.every(url => url === "/api/sync/job?activator=alianza"));
  assert.match(elements.get("#resultMessage").textContent, /109 recibo/);
  assert.equal(vm.runInContext('sendJobs.get("alianza").status', context), "completed");
});

test("reopening a page resumes the existing job and keeps sending disabled", async () => {
  const { context, elements } = app();
  let monitored;
  context.monitorSendJob = activator => { monitored = activator; };
  context.fetch = async url => ({ ok: true, text: async () => JSON.stringify(url.includes("/job")
    ? { job: { status: "running", progress: { total: 109, completed: 40, sent: 40 } } }
    : { runtime: { ready_to_send: true, connector_url_configured: true, send_unlocked: true,
      application_mode: "otros_ingresos", cooldown: {} } }) });
  await context.loadStatus();
  assert.equal(monitored, "alianza");
  assert.equal(elements.get("#sendButton").disabled, true);
  assert.match(elements.get("#resultMessage").textContent, /40 de 109/);
  assert.equal(elements.get("#sendStatusMetric").textContent, "En proceso");
});

test("losing the initial send acknowledgement only triggers status reads", async () => {
  const { context, elements } = app();
  let posts = 0;
  let jobReads = 0;
  context.window = { confirm: () => true };
  context.setTimeout = resolve => queueMicrotask(resolve);
  context.loadRows = async () => {};
  context.loadStatus = async () => {};
  context.fetch = async (url, options) => {
    if (options.method === "POST") { posts++; throw new Error("502"); }
    let data;
    if (url.includes("/job")) {
      jobReads++;
      data = { job: jobReads === 1 ? null : { status: "completed", outcome: { result: { sent: 2, processed: 2 } } } };
    } else if (url.includes("/status")) {
      data = { runtime: { connector_url_configured: true, ready_to_send: true, send_unlocked: true } };
    } else {
      data = { preflight: { ready: true, ready_rows: 2, total_ready_amount: "2000" } };
    }
    return { ok: true, text: async () => JSON.stringify(data) };
  };
  await context.activateSiesa();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(posts, 1);
  assert.equal(jobReads, 2);
  assert.match(elements.get("#resultMessage").textContent, /2 recibo/);
});

test("an interruption is displayed as requiring review rather than success", async () => {
  const { context, elements } = app();
  await context.showSendJob({ status: "interrupted", error: "El servidor se reinicio.", progress: { sent: 12 } });
  assert.equal(elements.get("#resultTitle").textContent, "Lote interrumpido");
  assert.equal(elements.get("#resultTitle").dataset.tone, "warn");
  assert.match(elements.get("#resultList").innerHTML, /12/);
});
