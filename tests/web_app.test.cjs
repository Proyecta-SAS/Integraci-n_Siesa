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
      });
      return elements.get(selector);
    },
  };
  const context = vm.createContext({ document, Intl });
  vm.runInContext(fs.readFileSync(path.join(__dirname, "../web/app.js"), "utf8"), context);
  return { context, elements };
}

test("matching notes are visible and confirmed rows are excluded from pending totals", () => {
  const { context, elements } = app();
  const base = { customer: "Cliente", amount: "1250872", valid: true, cross_ready: true, issues: [] };
  context.renderRows([
    { ...base, source_row: 11, note: "Primero", already_sent: true, ready: false },
    { ...base, source_row: 12, note: "Primero", duplicate_of: 11, already_sent: true, ready: false },
  ]);
  assert.match(elements.get("#rowsBody").innerHTML, /Coincide con la fila 11/);
  assert.match(elements.get("#rowsBody").innerHTML, /Ya registrado/);
  assert.equal(elements.get("#readyRowsMetric").textContent, "0/2");
  context.renderRows([
    { ...base, source_row: 11, note: "Primero", already_sent: true, ready: false },
    { ...base, source_row: 12, note: "Segundo pago <confirmado>", ready: true },
  ]);
  assert.equal(elements.get("#readyRowsMetric").textContent, "1/2");
  assert.equal(elements.get("#amountMetric").textContent, context.formatMoney("1250872"));
  assert.match(elements.get("#rowsBody").innerHTML, /Segundo pago &lt;confirmado&gt;/);
});

test("a plain upstream error asks to check status before retrying", async () => {
  const { context } = app();
  context.fetch = async () => ({ status: 502, ok: false, text: async () => "upstream error" });
  await assert.rejects(context.api("/api/sync/send", { method: "POST" }), /el proceso puede haber continuado/);
});
