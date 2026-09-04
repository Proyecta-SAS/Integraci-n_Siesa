const companyCards = document.querySelectorAll(".company-card");
const navItems = document.querySelectorAll(".nav-item");
const statusFilter = document.querySelector("#statusFilter");
const searchInput = document.querySelector("#searchInput");
const paymentRows = document.querySelectorAll("#paymentRows tr");
const timeline = document.querySelector("#timeline");
const validateBtn = document.querySelector("#validateBtn");
const syncBtn = document.querySelector("#syncBtn");

function addTimelineEvent(text) {
  const now = new Date();
  const time = now.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" });
  const item = document.createElement("li");
  item.innerHTML = `<time>${time}</time><span>${text}</span>`;
  timeline.prepend(item);
}

companyCards.forEach((card) => {
  card.addEventListener("click", () => {
    companyCards.forEach((item) => item.classList.remove("active"));
    card.classList.add("active");
    addTimelineEvent(`Compania activa: ${card.dataset.company}`);
  });
});

navItems.forEach((item) => {
  item.addEventListener("click", () => {
    navItems.forEach((nav) => nav.classList.remove("active"));
    item.classList.add("active");
  });
});

function applyFilters() {
  const status = statusFilter.value;
  const query = searchInput.value.trim().toLowerCase();

  paymentRows.forEach((row) => {
    const matchesStatus = status === "all" || row.dataset.status === status;
    const matchesQuery = !query || row.innerText.toLowerCase().includes(query);
    row.hidden = !(matchesStatus && matchesQuery);
  });
}

statusFilter.addEventListener("change", applyFilters);
searchInput.addEventListener("input", applyFilters);

validateBtn.addEventListener("click", () => {
  addTimelineEvent("Validacion de filas ejecutada en modo visual");
});

syncBtn.addEventListener("click", () => {
  addTimelineEvent("Sincronizacion QA preparada; faltan credenciales API");
});
