const activatorButtons = document.querySelectorAll(".activator-button");
const selectedCompany = document.querySelector("#selectedCompany");
const launcherPanel = document.querySelector("#launcherPanel");
const modulePanel = document.querySelector("#modulePanel");
const backButton = document.querySelector("#backButton");
const loadRowsButton = document.querySelector("#loadRowsButton");
const preflightButton = document.querySelector("#preflightButton");
const dryRunButton = document.querySelector("#dryRunButton");
const sendButton = document.querySelector("#sendButton");
const statusOutput = document.querySelector("#statusOutput");
const resultOutput = document.querySelector("#resultOutput");
const rowsBody = document.querySelector("#rowsBody");
const rowCount = document.querySelector("#rowCount");
const connectionStatus = document.querySelector("#connectionStatus");
const connectionHint = document.querySelector("#connectionHint");
const readyRowsMetric = document.querySelector("#readyRowsMetric");
const rowsHint = document.querySelector("#rowsHint");
const amountMetric = document.querySelector("#amountMetric");
const amountHint = document.querySelector("#amountHint");
const sendStatusMetric = document.querySelector("#sendStatusMetric");
const sendHint = document.querySelector("#sendHint");
const resultTitle = document.querySelector("#resultTitle");
const resultMessage = document.querySelector("#resultMessage");
const resultList = document.querySelector("#resultList");
const envPill = document.querySelector("#envPill");
const crossHeader = document.querySelector("#crossHeader");

let currentApplicationMode = "cartera";

const moneyFormatter = new Intl.NumberFormat("es-CO", {
  style: "currency",
  currency: "COP",
  maximumFractionDigits: 0,
});

function showModule() {
  launcherPanel.classList.add("hidden");
  modulePanel.classList.remove("hidden");
  loadStatus();
  loadRows();
}

function showLauncher() {
  modulePanel.classList.add("hidden");
  launcherPanel.classList.remove("hidden");
}

function writeJson(element, data) {
  element.textContent = JSON.stringify(data, null, 2);
}

function formatMoney(value) {
  const number = Number(String(value || "0").replace(/,/g, ""));
  return moneyFormatter.format(Number.isFinite(number) ? number : 0);
}

function formatCooldown(seconds) {
  if (!seconds || seconds <= 0) {
    return "Disponible";
  }
  const minutes = Math.ceil(seconds / 60);
  return `Espere ${minutes} min`;
}

function isOtherIncomeMode(mode = currentApplicationMode) {
  return ["otros_ingresos", "otro_ingreso", "anticipo", "anticipo_por_identificar"].includes(mode);
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function setResult(title, message, items = [], tone = "info") {
  resultTitle.textContent = title;
  resultMessage.textContent = message;
  resultTitle.dataset.tone = tone;
  resultList.innerHTML = items.length
    ? items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")
    : "<li>Sin detalle adicional.</li>";
}

function shortValue(value, maxLength = 260) {
  const text = String(value ?? "").trim();
  if (!text) {
    return "";
  }
  return text.length > maxLength ? `${text.slice(0, maxLength - 3)}...` : text;
}

function readableSiesaResponse(value) {
  if (!value) {
    return "Siesa no retorno detalle.";
  }
  if (typeof value === "string") {
    return shortValue(value);
  }
  if (Array.isArray(value)) {
    return shortValue(value.map(readableSiesaResponse).filter(Boolean).join(" | "));
  }

  const keys = [
    "mensaje",
    "message",
    "error",
    "descripcion",
    "description",
    "detalle",
    "detail",
    "resultado",
    "codigo",
    "transaccion",
  ];
  const parts = keys
    .filter((key) => value[key] !== undefined && value[key] !== null && value[key] !== "")
    .map((key) => `${key}: ${typeof value[key] === "object" ? JSON.stringify(value[key]) : value[key]}`);

  return shortValue(parts.length ? parts.join(" | ") : JSON.stringify(value));
}

async function latestFailureItems() {
  const data = await api("/api/audit?event=failed&limit=10");
  return (data.events || []).map((event) => {
    const row = event.source_row ? `Fila ${event.source_row}` : "Fila sin numero";
    const status = event.siesa_status_code ? `HTTP ${event.siesa_status_code}` : "Siesa";
    const amount = event.amount ? formatMoney(event.amount) : "valor sin dato";
    return `${row} - ${amount} - ${status}: ${readableSiesaResponse(event.siesa_response)}`;
  });
}

function updateStatusSummary(runtime) {
  const missingCount = (runtime.missing_send_env || []).length;
  const cooldown = runtime.cooldown || {};
  currentApplicationMode = runtime.application_mode || "cartera";
  const otherIncome = isOtherIncomeMode();
  envPill.textContent = otherIncome
    ? `${String(runtime.environment || "QA").toUpperCase()} · 28050505`
    : String(runtime.environment || "QA").toUpperCase();
  crossHeader.textContent = otherIncome ? "Otros ingresos" : "Cruce";

  connectionStatus.textContent = runtime.ready_to_send ? "Configurado" : "Incompleto";
  connectionStatus.dataset.tone = runtime.ready_to_send ? "ok" : "warn";
  connectionHint.textContent = runtime.ready_to_send
    ? otherIncome
      ? "QA tiene datos base. Flujo: otros ingresos 28050505."
      : "QA tiene URL, credenciales y datos base."
    : `Faltan ${missingCount} dato(s) para enviar.`;

  if (runtime.send_unlocked && !cooldown.cooldown_active) {
    sendStatusMetric.textContent = "Permitido";
    sendStatusMetric.dataset.tone = "warn";
    sendHint.textContent = otherIncome
      ? "Enviar QA creara recibos por otros ingresos."
      : "Enviar QA creara recibos reales en pruebas.";
    return;
  }

  sendStatusMetric.textContent = "Bloqueado";
  sendStatusMetric.dataset.tone = "safe";
  sendHint.textContent = cooldown.cooldown_active
    ? formatCooldown(cooldown.retry_after_seconds)
    : "Requiere SIESA_ALLOW_SEND=true.";
}

function updateRowsSummary(rows = []) {
  const readyRows = rows.filter((row) => row.ready || (row.valid && row.cross_ready));
  const invalidRows = rows.length - readyRows.length;
  const total = readyRows.reduce((sum, row) => sum + Number(String(row.amount || "0").replace(/,/g, "")), 0);

  readyRowsMetric.textContent = `${readyRows.length}/${rows.length}`;
  readyRowsMetric.dataset.tone = invalidRows ? "warn" : "ok";
  rowsHint.textContent = rows.length
    ? invalidRows
      ? `${invalidRows} fila(s) requieren revision.`
      : "Todas las filas pueden procesarse."
    : "No hay filas cargadas.";

  amountMetric.textContent = formatMoney(total);
  amountHint.textContent = readyRows.length
    ? "Total de filas listas."
    : "Sin pagos listos.";
}

async function summarizeSyncResult(data, mode) {
  const result = data.result || data;
  const failed = Number(result.failed || 0);
  const invalid = Number(result.invalid || 0);
  const sent = Number(result.sent || 0);
  const dryRun = Number(result.dry_run || 0);
  const skipped = Number(result.skipped_duplicates || 0);
  const processed = Number(result.processed || 0);

  if (mode === "send" && sent > 0 && failed === 0 && invalid === 0) {
    setResult(
      "Envio QA exitoso",
      `Siesa recibio ${sent} recibo(s) de caja. Ahora valida el consecutivo en Siesa QA.`,
      [
        `Filas procesadas: ${processed}`,
        `Recibos enviados: ${sent}`,
        `Duplicados omitidos: ${skipped}`,
        "Despues de validar, vuelve a bloquear el envio real.",
      ],
      "ok",
    );
    return;
  }

  if (mode === "dry-run" && dryRun > 0 && failed === 0 && invalid === 0) {
    setResult(
      "Prueba QA correcta",
      `El sistema puede armar ${dryRun} recibo(s) sin crear nada en Siesa.`,
      [
        `Filas procesadas: ${processed}`,
        `Filas listas para enviar: ${dryRun}`,
        `Duplicados detectados: ${skipped}`,
      ],
      "ok",
    );
    return;
  }

  if (mode === "send" && failed > 0) {
    let items = [
      `Procesadas: ${processed}`,
      `Enviadas: ${sent}`,
      `Fallidas: ${failed}`,
      `Invalidas antes de enviar: ${invalid}`,
      `Duplicadas: ${skipped}`,
    ];
    try {
      const failureItems = await latestFailureItems();
      if (failureItems.length) {
        items = items.concat(failureItems);
      }
    } catch (error) {
      items.push(`No se pudo leer el detalle del log: ${error.message}`);
    }
    setResult(
      "Siesa rechazo el envio",
      `${failed} fila(s) llegaron al conector, pero Siesa no creo el recibo.`,
      items,
      "warn",
    );
    return;
  }

  setResult(
    failed || invalid ? "Hay filas por revisar" : "Proceso finalizado",
    "Revisa el detalle de la tabla antes de volver a intentar.",
    [
      `Procesadas: ${processed}`,
      `Enviadas: ${sent}`,
      `Probadas sin enviar: ${dryRun}`,
      `Invalidas: ${invalid}`,
      `Fallidas: ${failed}`,
      `Duplicadas: ${skipped}`,
    ],
    failed || invalid ? "warn" : "info",
  );
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Accept": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || `Error HTTP ${response.status}`);
  }
  return data;
}

async function withBusy(button, label, action) {
  const original = button.firstChild.textContent.trim();
  button.disabled = true;
  button.firstChild.textContent = label;
  try {
    await action();
  } catch (error) {
    writeJson(resultOutput, { ok: false, error: error.message });
    setResult("No se pudo completar", error.message, ["Valida configuracion, fila de Sheets o disponibilidad de Siesa QA."], "warn");
  } finally {
    button.disabled = false;
    button.firstChild.textContent = original;
  }
}

async function loadStatus() {
  const data = await api("/api/status");
  writeJson(statusOutput, data.runtime);
  updateStatusSummary(data.runtime);
  const otherIncome = isOtherIncomeMode(data.runtime.application_mode);
  if (!data.runtime.connector_url_configured) {
    const message = "Pendiente: copia la Request URL del conector en SIESA_CONNECTOR_URL. El path generico respondio 405 en QA.";
    resultOutput.textContent = message;
    setResult("Configuracion pendiente", "Falta la URL exacta del conector de Siesa.", [message], "warn");
    return;
  }
  if (data.runtime.missing_send_env?.length) {
    const message = `Pendiente: completa ${data.runtime.missing_send_env.join(", ")} antes de enviar QA.`;
    resultOutput.textContent = message;
    setResult("Configuracion pendiente", "Faltan datos operativos para crear recibos.", data.runtime.missing_send_env, "warn");
    return;
  }
  if (!data.runtime.cross_fallback_configured) {
    resultOutput.textContent = "Cruce dinamico activo: cada fila debe traer Documento cruce o columnas separadas de CxC.";
  } else if (isOtherIncomeMode(data.runtime.application_mode)) {
    resultOutput.textContent = "Modo otros ingresos activo: no cruza FVE; envia auxiliar 28050505.";
  }
  const cooldownActive = data.runtime.cooldown?.cooldown_active;
  if (!data.runtime.send_unlocked || cooldownActive) {
    sendButton.disabled = true;
    sendButton.classList.add("locked");
    sendButton.querySelector("small").textContent = cooldownActive
      ? formatCooldown(data.runtime.cooldown.retry_after_seconds)
      : "Bloqueado hasta SIESA_ALLOW_SEND=true";
  } else {
    sendButton.disabled = false;
    sendButton.classList.remove("locked");
    sendButton.querySelector("small").textContent = otherIncome
      ? "Crea recibo por otros ingresos"
      : "Crea recibo en Siesa";
  }
}

function renderRows(rows) {
  rowCount.textContent = `${rows.length} filas`;
  updateRowsSummary(rows);
  if (!rows.length) {
    rowsBody.innerHTML = '<tr><td colspan="10">No hay filas de pago para procesar.</td></tr>';
    return;
  }
  rowsBody.innerHTML = rows.map((row) => `
    ${(() => {
      const details = row.issues?.length
        ? row.issues.map((issue) => `${issue.field}: ${issue.message}`).join(" | ")
        : row.cross_ready
          ? "Lista para enviar"
          : isOtherIncomeMode()
            ? "Faltan datos de otros ingresos"
            : "Falta documento cruce";
      const status = row.valid && row.cross_ready ? "Lista" : "Revisar";
      const statusClass = row.valid && row.cross_ready ? "state-ok" : "state-warn";
      return `
    <tr>
      <td>${escapeHtml(row.source_row)}</td>
      <td>${escapeHtml(row.customer || "-")}</td>
      <td>${escapeHtml(row.identity_number || "-")}</td>
      <td class="${row.cross_ready ? "state-ok" : "state-warn"}">${escapeHtml(row.cross_document || row.cross_source || "-")}</td>
      <td>${escapeHtml(row.payment_date)}</td>
      <td>${escapeHtml(row.method || "-")}</td>
      <td>${escapeHtml(row.amount)}</td>
      <td>${escapeHtml(row.flow)}</td>
      <td class="${statusClass}">${status}</td>
      <td class="detail-cell">${escapeHtml(details)}</td>
    </tr>
      `;
    })()}
  `).join("");
}

async function loadRows(announce = true) {
  await withBusy(loadRowsButton, "Leyendo...", async () => {
    const data = await api("/api/payments?limit=50");
    renderRows(data.rows);
    writeJson(resultOutput, { ok: true, action: "payments", count: data.count });
    if (!announce) {
      return;
    }
    const readyRows = data.rows.filter((row) => row.ready || (row.valid && row.cross_ready));
    setResult(
      "Sheets revisado",
      `${readyRows.length} de ${data.rows.length} fila(s) estan listas para procesar.`,
      readyRows.length === data.rows.length
        ? ["Puedes ejecutar Preflight para confirmar el total antes de enviar."]
        : ["Corrige las filas marcadas como Revisar en la tabla."],
      readyRows.length === data.rows.length ? "ok" : "warn",
    );
  });
}

async function dryRun() {
  await withBusy(dryRunButton, "Probando...", async () => {
    const data = await api("/api/sync/dry-run", { method: "POST" });
    writeJson(resultOutput, data);
    await summarizeSyncResult(data, "dry-run");
    await loadRows(false);
  });
}

async function preflight() {
  await withBusy(preflightButton, "Revisando...", async () => {
    const data = await api("/api/preflight?limit=100");
    renderRows(data.rows);
    writeJson(resultOutput, data.preflight);
    const preflight = data.preflight;
    setResult(
      preflight.ready ? "Preflight aprobado" : "Preflight con novedades",
      preflight.ready
        ? `${preflight.ready_rows} fila(s) listas por ${formatMoney(preflight.total_ready_amount)}.`
        : "Hay filas que deben corregirse antes de enviar.",
      [
        `Filas revisadas: ${preflight.rows_checked}`,
        `Filas listas: ${preflight.ready_rows}`,
        `Filas invalidas: ${preflight.invalid_rows.length}`,
        isOtherIncomeMode()
          ? "Cruce de cartera: no aplica"
          : `Sin documento cruce: ${preflight.missing_cross_rows.length}`,
      ],
      preflight.ready ? "ok" : "warn",
    );
  });
}

async function sendQa() {
  await withBusy(sendButton, "Enviando...", async () => {
    const status = await api("/api/status");
    if (!status.runtime.connector_url_configured) {
      const error = {
        ok: false,
        error: "Falta SIESA_CONNECTOR_URL. Copia la Request URL exacta desde Ver Guia > Copiar URL en el conector 142888.",
      };
      writeJson(resultOutput, error);
      setResult("Envio bloqueado", error.error, ["Completa la URL del conector y vuelve a revisar."], "warn");
      return;
    }
    if (!status.runtime.ready_to_send) {
      const error = {
        ok: false,
        error: "Faltan datos operativos antes de enviar QA.",
        missing: status.runtime.missing_send_env,
      };
      writeJson(resultOutput, error);
      setResult("Envio bloqueado", error.error, status.runtime.missing_send_env, "warn");
      return;
    }
    if (!status.runtime.send_unlocked) {
      const error = {
        ok: false,
        error: "Envio bloqueado por seguridad. Active SIESA_ALLOW_SEND=true solo cuando quiera crear recibos.",
      };
      writeJson(resultOutput, error);
      setResult("Envio bloqueado", "La proteccion de envio real esta activa.", ["Activa SIESA_ALLOW_SEND=true solo durante la prueba autorizada."], "warn");
      return;
    }
    if (status.runtime.cooldown?.cooldown_active) {
      const error = {
        ok: false,
        error: "Envio bloqueado por cooldown de 15 minutos.",
        retry_after_seconds: status.runtime.cooldown.retry_after_seconds,
        next_activation_at: status.runtime.cooldown.next_activation_at,
      };
      writeJson(resultOutput, error);
      setResult("Espere antes de reenviar", error.error, [formatCooldown(error.retry_after_seconds)], "warn");
      return;
    }
    const rowsData = await api("/api/payments?limit=50");
    const missingCrossRows = rowsData.rows.filter((row) => !row.cross_ready).map((row) => row.source_row);
    if (missingCrossRows.length && !isOtherIncomeMode(status.runtime.application_mode)) {
      const error = {
        ok: false,
        error: "Faltan datos de documento cruce en Sheets o variables SIESA_* de respaldo.",
        rows: missingCrossRows,
      };
      writeJson(resultOutput, error);
      setResult("Faltan cruces", "Completa el documento cruce de las filas marcadas.", [`Filas: ${missingCrossRows.join(", ")}`], "warn");
      renderRows(rowsData.rows);
      return;
    }
    const data = await api("/api/sync/send", { method: "POST" });
    writeJson(resultOutput, data);
    await summarizeSyncResult(data, "send");
    await loadRows(false);
  });
}

activatorButtons.forEach((button) => {
  button.addEventListener("click", () => {
    activatorButtons.forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    selectedCompany.textContent = button.dataset.company;
    if (button.dataset.enabled === "true") {
      showModule();
      return;
    }
    resultOutput.textContent = `${button.dataset.company} queda disponible cuando configuremos su Sheets y conector.`;
  });
});

backButton.addEventListener("click", showLauncher);
loadRowsButton.addEventListener("click", loadRows);
preflightButton.addEventListener("click", preflight);
dryRunButton.addEventListener("click", dryRun);
sendButton.addEventListener("click", sendQa);
