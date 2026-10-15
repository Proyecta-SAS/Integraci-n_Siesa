/** Configure SIESA_WEBHOOK_TOKEN and SIESA_ALLOWED_SPREADSHEETS in Script Properties.
 * Deploy as a web app executing as the owner, accessible to Anyone.
 * See docs/estados_sheets.md. No receipt creation happens in this script.
 */
const SIESA_HEADERS = [
  "Estado Siesa", "Recibo Siesa", "Fecha envio", "Respuesta Siesa", "Error Siesa"
];
const SIESA_STATES = ["Pendiente", "Pendiente por corregir", "Cargado"];

function doPost(e) {
  let lock;
  try {
    const body = JSON.parse(e.postData.contents);
    const properties = PropertiesService.getScriptProperties();
    const token = properties.getProperty("SIESA_WEBHOOK_TOKEN");
    if (!token || body.token !== token) throw new Error("Acceso no autorizado");
    const allowed = (properties.getProperty("SIESA_ALLOWED_SPREADSHEETS") || "")
      .split(",").map(value => value.trim()).filter(Boolean);
    if (!allowed.includes(body.spreadsheet_id)) throw new Error("Spreadsheet no autorizado");
    if (!Number.isInteger(body.sheet_id) || body.sheet_id < 0 ||
        !Number.isInteger(body.source_row) || body.source_row < 2 ||
        !Array.isArray(body.source_cells) || body.source_cells.length !== 11 ||
        !body.source_cells.every(value => typeof value === "string") ||
        !SIESA_STATES.includes(body.status)) throw new Error("Fila o estado invalido");

    lock = LockService.getScriptLock();
    lock.waitLock(30000);
    const book = SpreadsheetApp.openById(body.spreadsheet_id);
    const sheet = book.getSheets().find(item => item.getSheetId() === body.sheet_id);
    if (!sheet) throw new Error("Pestana no encontrada");
    if (body.source_row > sheet.getLastRow()) throw new Error("Fila de origen no encontrada");
    const current = sheet.getRange(body.source_row, 1, 1, 11).getDisplayValues()[0];
    if (current.some((value, index) => value.trim() !== body.source_cells[index].trim())) {
      throw new Error("La fila cambio o se movio; vuelva a leer la hoja antes de procesarla");
    }

    // Append only missing traceability headers, after every existing column.
    // Never write into the operational A:K block or the historical Alegra fields.
    const headers = sheet.getRange(1, 1, 1, Math.max(11, sheet.getLastColumn())).getDisplayValues()[0];
    const columns = SIESA_HEADERS.map(title => {
      const positions = [];
      headers.forEach((header, index) => {
        if (header.trim() === title) positions.push(index + 1);
      });
      if (positions.length > 1 || (positions.length && positions[0] <= 11)) {
        throw new Error("Columna de trazabilidad duplicada o dentro de A:K: " + title);
      }
      return positions[0] || null;
    });
    columns.forEach((column, index) => {
      if (column) return;
      const next = headers.length + 1;
      if (next > sheet.getMaxColumns()) sheet.insertColumnsAfter(sheet.getMaxColumns(), next - sheet.getMaxColumns());
      sheet.getRange(1, next).setValue(SIESA_HEADERS[index]);
      headers.push(SIESA_HEADERS[index]);
      columns[index] = next;
    });

    const row = body.source_row;
    const oldStatus = sheet.getRange(row, columns[0]).getDisplayValue().trim();
    // Local state is authoritative for deduplication; never downgrade a row
    // previously confirmed by this webhook. A conflicting pending write must
    // stop the caller before it sends another receipt.
    if (oldStatus === "Cargado" && body.status !== "Cargado") {
      throw new Error("Fila ya marcada Cargado; concilie el estado local antes de reenviar");
    }
    const values = [
      body.status,
      body.receipt || "",
      body.sent_at || "",
      body.response == null ? "" : JSON.stringify(body.response),
      body.error || ""
    ];
    // Write confirmation last. If a previous update was interrupted, repeating
    // Cargado repairs its fields, while preserving legacy receipt/date values.
    for (let index = 1; index < values.length; index++) {
      if (body.status === "Cargado" && index <= 3 && !values[index]) continue;
      sheet.getRange(row, columns[index]).setValue(siesaLiteral_(values[index]));
    }
    sheet.getRange(row, columns[0]).setValue(body.status);
    SpreadsheetApp.flush();
    return siesaJson_({ok: true, source_row: row});
  } catch (error) {
    // Do not return request contents or credentials on errors.
    return siesaJson_({ok: false, error: String(error.message || error).slice(0, 500)});
  } finally {
    if (lock && lock.hasLock()) lock.releaseLock();
  }
}

function siesaLiteral_(value) {
  const text = String(value).slice(0, 40000);
  // Prevent an ERP response from being interpreted as a spreadsheet formula.
  return /^[=+@-]/.test(text) ? "'" + text : text;
}

function siesaJson_(body) {
  return ContentService.createTextOutput(JSON.stringify(body)).setMimeType(ContentService.MimeType.JSON);
}
