const activatorButtons = document.querySelectorAll(".activator-button");
const selectedCompany = document.querySelector("#selectedCompany");
const launcherPanel = document.querySelector("#launcherPanel");
const modulePanel = document.querySelector("#modulePanel");
const backButton = document.querySelector("#backButton");
const loadRowsButton = document.querySelector("#loadRowsButton");
const dryRunButton = document.querySelector("#dryRunButton");
const sendButton = document.querySelector("#sendButton");
const statusOutput = document.querySelector("#statusOutput");
const resultOutput = document.querySelector("#resultOutput");
const rowsBody = document.querySelector("#rowsBody");
const rowCount = document.querySelector("#rowCount");

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
  } finally {
    button.disabled = false;
    button.firstChild.textContent = original;
  }
}

async function loadStatus() {
  const data = await api("/api/status");
  writeJson(statusOutput, data.runtime);
  if (!data.runtime.connector_url_configured) {
    resultOutput.textContent = "Pendiente: copia la Request URL del conector en SIESA_CONNECTOR_URL. El path generico respondio 405 en QA.";
    return;
  }
  if (data.runtime.missing_send_env?.length) {
    resultOutput.textContent = `Pendiente: completa ${data.runtime.missing_send_env.join(", ")} antes de enviar QA.`;
  }
}

function renderRows(rows) {
  rowCount.textContent = `${rows.length} filas`;
  if (!rows.length) {
    rowsBody.innerHTML = '<tr><td colspan="8">No hay filas de pago para procesar.</td></tr>';
    return;
  }
  rowsBody.innerHTML = rows.map((row) => `
    <tr>
      <td>${row.source_row}</td>
      <td>${row.customer || "-"}</td>
      <td>${row.identity_number || "-"}</td>
      <td>${row.payment_date}</td>
      <td>${row.method || "-"}</td>
      <td>${row.amount}</td>
      <td>${row.flow}</td>
      <td class="${row.valid ? "state-ok" : "state-warn"}">${row.valid ? "Valida" : "Revisar"}</td>
    </tr>
  `).join("");
}

async function loadRows() {
  await withBusy(loadRowsButton, "Leyendo...", async () => {
    const data = await api("/api/payments?limit=50");
    renderRows(data.rows);
    writeJson(resultOutput, { ok: true, action: "payments", count: data.count });
  });
}

async function dryRun() {
  await withBusy(dryRunButton, "Probando...", async () => {
    const data = await api("/api/sync/dry-run", { method: "POST" });
    writeJson(resultOutput, data);
    await loadRows();
  });
}

async function sendQa() {
  await withBusy(sendButton, "Enviando...", async () => {
    const status = await api("/api/status");
    if (!status.runtime.connector_url_configured) {
      writeJson(resultOutput, {
        ok: false,
        error: "Falta SIESA_CONNECTOR_URL. Copia la Request URL exacta desde Ver Guia > Copiar URL en el conector 142888.",
      });
      return;
    }
    if (!status.runtime.ready_to_send) {
      writeJson(resultOutput, {
        ok: false,
        error: "Faltan datos operativos antes de enviar QA.",
        missing: status.runtime.missing_send_env,
      });
      return;
    }
    const data = await api("/api/sync/send", { method: "POST" });
    writeJson(resultOutput, data);
    await loadRows();
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
dryRunButton.addEventListener("click", dryRun);
sendButton.addEventListener("click", sendQa);
