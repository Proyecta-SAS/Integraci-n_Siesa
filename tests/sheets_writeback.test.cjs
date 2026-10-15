const {test} = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const path = require("node:path");
const source = fs.readFileSync(path.join(__dirname, "../scripts/sheets_writeback.gs"), "utf8");

function fixture() {
  const operational = ["Banco", "15/10/2026", "Cliente", "Ingreso", "Transferencia", "", "Concepto", "1", "1000", "Nota", ""];
  const grid = [
    Array.from({length: 15}, (_, index) => index < 11 ? `Campo ${index}` : `Alegra ${index}`),
    [...operational, "dato historico", "", "", ""],
  ];
  let maxColumns = 15;
  let acquired = false;
  let released = false;
  const sheet = {
    getSheetId: () => 17,
    getLastRow: () => grid.length,
    getLastColumn: () => grid[0].length,
    getMaxColumns: () => maxColumns,
    insertColumnsAfter: (after, count) => { maxColumns += count; },
    getRange: (row, column, height = 1, width = 1) => ({
      getDisplayValue: () => String(grid[row - 1]?.[column - 1] || ""),
      getDisplayValues: () => Array.from({length: height}, (_, i) =>
        Array.from({length: width}, (_, j) => String(grid[row + i - 1]?.[column + j - 1] || ""))),
      setValue: value => { grid[row - 1][column - 1] = value; },
    }),
  };
  const context = vm.createContext({
    PropertiesService: {getScriptProperties: () => ({getProperty: name => ({
      SIESA_WEBHOOK_TOKEN: "secret", SIESA_ALLOWED_SPREADSHEETS: "book, other-book",
    })[name]})},
    SpreadsheetApp: {openById: id => ({getSheets: () => [sheet]}), flush: () => {}},
    LockService: {getScriptLock: () => ({
      waitLock: () => { acquired = true; }, hasLock: () => acquired,
      releaseLock: () => { released = true; },
    })},
    ContentService: {MimeType: {JSON: "json"}, createTextOutput: text => ({setMimeType: () => text})},
  });
  vm.runInContext(source, context);
  const post = overrides => JSON.parse(context.doPost({postData: {contents: JSON.stringify({
    token: "secret", spreadsheet_id: "book", sheet_id: 17, source_row: 2,
    source_cells: operational, status: "Pendiente", ...overrides,
  })}}));
  const value = title => grid[1][grid[0].indexOf(title)];
  return {grid, operational, sheet, context, post, value, released: () => released};
}

test("appends result columns without changing operational or Alegra values", () => {
  const f = fixture();
  const before = f.grid.map(row => row.slice());
  assert.equal(f.post().ok, true);
  assert.deepEqual(f.grid[0].slice(0, 15), before[0]);
  assert.deepEqual(f.grid[1].slice(0, 15), before[1]);
  assert.equal(f.value("Estado Siesa"), "Pendiente");
  assert.equal(f.grid[0].length, 20);
  assert.equal(f.released(), true);
  f.post({status: "Pendiente por corregir", error: "Tercero no existe", response: {codigo: 1}});
  assert.equal(f.value("Error Siesa"), "Tercero no existe");
  f.post({status: "Cargado", receipt: "RC-17", sent_at: "2026-10-15T15:00:00Z", response: {codigo: 0}});
  assert.equal(f.value("Estado Siesa"), "Cargado");
  assert.equal(f.value("Recibo Siesa"), "RC-17");
  assert.equal(f.value("Error Siesa"), "");
  assert.equal(f.grid[0].length, 20);
});

test("rejects bad credentials, destinations, row numbers and state without mutations", () => {
  for (const override of [
    {token: "bad"}, {spreadsheet_id: "unknown"}, {sheet_id: 0},
    {source_row: 1}, {source_row: 50}, {source_cells: []}, {status: "Enviado"},
  ]) {
    const f = fixture();
    const before = JSON.stringify(f.grid);
    assert.equal(f.post(override).ok, false);
    assert.equal(JSON.stringify(f.grid), before);
  }
});

test("rejects a moved or edited source row", () => {
  const f = fixture();
  f.grid[1][8] = "2000";
  const before = JSON.stringify(f.grid);
  const result = f.post();
  assert.equal(result.ok, false);
  assert.match(result.error, /cambio o se movio/);
  assert.equal(JSON.stringify(f.grid), before);
  assert.equal(f.released(), true);
});

test("reuses noncontiguous columns and rejects duplicate traceability headers", () => {
  const f = fixture();
  f.grid[0][12] = "Estado Siesa";
  f.grid[0][14] = "Error Siesa";
  assert.equal(f.post({status: "Pendiente por corregir", error: "Datos incompletos"}).ok, true);
  assert.equal(f.grid[1][12], "Pendiente por corregir");
  assert.equal(f.grid[1][14], "Datos incompletos");
  assert.equal(f.grid[0].length, 18);
  for (const position of [1, 12]) {
    const duplicate = fixture();
    duplicate.grid[0][position] = "Estado Siesa";
    duplicate.grid[0][14] = "Estado Siesa";
    assert.equal(duplicate.post().ok, false);
    assert.equal(duplicate.grid[0].length, 15);
  }
});

test("keeps confirmed status and legacy receipt details on a duplicate repair", () => {
  const f = fixture();
  f.post({status: "Cargado", receipt: "RC-20", sent_at: "2026-10-15", response: {documento: "RC-20"}});
  const before = JSON.stringify(f.grid);
  assert.equal(f.post().ok, false);
  assert.equal(JSON.stringify(f.grid), before);
  assert.equal(f.post({status: "Cargado"}).ok, true);
  assert.equal(f.value("Recibo Siesa"), "RC-20");
  assert.equal(f.value("Fecha envio"), "2026-10-15");
  assert.equal(f.value("Respuesta Siesa"), '{"documento":"RC-20"}');
});

test("treats returned text as literals and limits Google cell lengths", () => {
  const f = fixture();
  f.post({status: "Pendiente por corregir", error: '=IMPORTXML("https://example.com")'});
  assert.equal(f.value("Error Siesa")[0], "'");
  assert.equal(f.context.siesaLiteral_("a".repeat(50000)).length, 40000);
});
