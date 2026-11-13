/* Navigation between pages while retaining the active operational state.
   Payment operations and their permission checks remain in app.js. */
(() => {
  const sidebar = document.querySelector("#sidebar");
  const workspace = document.querySelector("#workspace");
  const group = document.querySelector("#alianzaMenuGroup");
  const groupButton = document.querySelector("#alianzaMenuButton");
  const submenu = document.querySelector("#alianzaSubmenu");
  const home = document.querySelector("#backButton");
  const openButton = document.querySelector("#openSidebarButton");
  const closeButton = document.querySelector("#closeSidebarButton");
  const collapseButton = document.querySelector("#collapseSidebarButton");
  const backdrop = document.querySelector("#sidebarBackdrop");
  const actions = [...submenu.querySelectorAll(".action-button")];
  const pageLinks = [...document.querySelectorAll("a[data-page]")];
  const pages = [...document.querySelectorAll(".workspace-page")];
  const pageTitle = document.querySelector("#pageTitle");
  const pageDescription = document.querySelector("#pageDescription");
  const routes = {
    "/resumen": { id: "resumen", title: "Resumen operativo", description: "Estado de la conexión, pagos pendientes y pasos del proceso." },
    "/resultados": { id: "resultados", title: "Resultados", description: "Consulta la respuesta y los avisos de la última acción ejecutada." },
    "/pagos": { id: "filas", title: "Pagos y validación", description: "Revisa las filas de Sheets, sus referencias y el estado de cada pago." },
    "/integracion": { id: "integracion", title: "Datos de integración", description: "Origen, destino y detalle técnico de la conexión contable." },
    "/historico": { id: "historico", title: "Histórico de recibos", description: "Consulta los envíos recuperados, sus confirmaciones y las coincidencias por revisar." },
  };
  const mobile = window.matchMedia("(max-width: 900px)");
  let expanded = true;
  let drawerOpen = false;
  let previousOverflow = null;

  function syncGroup() {
    const collapsed = !mobile.matches && document.body.classList.contains("lateral-colapsado");
    const visible = expanded && !collapsed;
    submenu.hidden = !visible;
    group.classList.toggle("grupo-lateral--abierto", visible);
    groupButton.setAttribute("aria-expanded", String(visible));
  }

  function syncDrawer() {
    const open = mobile.matches && drawerOpen;
    sidebar.classList.toggle("abierta", open);
    backdrop.classList.toggle("activo", open);
    sidebar.inert = mobile.matches && !open;
    workspace.inert = open;
    openButton.setAttribute("aria-expanded", String(open));
    if (open) {
      sidebar.setAttribute("role", "dialog");
      sidebar.setAttribute("aria-modal", "true");
      if (previousOverflow === null) previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    } else {
      sidebar.removeAttribute("role");
      sidebar.removeAttribute("aria-modal");
      if (previousOverflow !== null) {
        document.body.style.overflow = previousOverflow;
        previousOverflow = null;
      }
    }
  }

  function closeDrawer(restoreFocus = true) {
    const wasOpen = drawerOpen;
    drawerOpen = false;
    syncDrawer();
    if (wasOpen && restoreFocus && mobile.matches) openButton.focus();
  }

  openButton.addEventListener("click", () => {
    drawerOpen = true;
    syncDrawer();
    closeButton.focus();
  });
  closeButton.addEventListener("click", () => closeDrawer());
  backdrop.addEventListener("click", () => closeDrawer());

  groupButton.addEventListener("click", () => {
    if (!mobile.matches && document.body.classList.contains("lateral-colapsado")) {
      document.body.classList.remove("lateral-colapsado");
      updateCollapseLabel();
      expanded = true;
    } else {
      expanded = !expanded;
    }
    syncGroup();
  });

  function updateCollapseLabel() {
    const collapsed = document.body.classList.contains("lateral-colapsado");
    const label = collapsed ? "Expandir menú" : "Contraer menú";
    collapseButton.setAttribute("aria-label", label);
    collapseButton.title = label;
  }

  collapseButton.addEventListener("click", () => {
    document.body.classList.toggle("lateral-colapsado");
    updateCollapseLabel();
    syncGroup();
  });

  function renderPage(focusHeading = false) {
    const route = routes[window.location.pathname] || routes["/resumen"];
    for (const page of pages) page.hidden = page.id !== route.id;
    pageTitle.textContent = route.title;
    pageDescription.textContent = route.description;
    document.title = `${route.title} | Siesa Alianza`;
    if (route.id === "historico") window.dispatchEvent(new Event("siesa:history"));
    home.classList.toggle("item-lateral--activo", route.id === "resumen");
    groupButton.classList.toggle("item-lateral--activo", route.id !== "resumen");
    for (const link of pageLinks) {
      const current = link.dataset.page === route.id;
      link.classList.toggle("subitem-lateral--activo", current && link !== home);
      if (current) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    }
    window.scrollTo({ top: 0, behavior: "instant" });
    if (focusHeading) pageTitle.focus({ preventScroll: true });
  }

  function navigate(path, focusHeading = true) {
    if (window.location.pathname !== path) window.history.pushState({}, "", path);
    closeDrawer(false);
    renderPage(focusHeading);
  }

  for (const link of pageLinks) {
    link.addEventListener("click", event => {
      if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      navigate(link.getAttribute("href"));
    });
  }

  window.addEventListener("popstate", () => {
    closeDrawer(false);
    renderPage(true);
  });

  for (const action of actions) {
    action.addEventListener("click", () => {
      for (const item of actions) item.classList.toggle("subitem-lateral--activo", item === action);
      navigate("/resultados", false);
      const result = document.querySelector("#resultTitle");
      result.tabIndex = -1;
      if (mobile.matches) result.focus({ preventScroll: true });
    });
  }

  document.addEventListener("keydown", event => {
    if (!mobile.matches || !drawerOpen) return;
    if (event.key === "Escape") {
      event.preventDefault();
      closeDrawer();
    } else if (event.key === "Tab") {
      const focusable = [...sidebar.querySelectorAll("button:not(:disabled), a[href], [tabindex='0']")]
        .filter(element => element.getClientRects().length && !element.closest("[hidden]"));
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  mobile.addEventListener("change", () => {
    const focusWasInSidebar = sidebar.contains(document.activeElement);
    drawerOpen = false;
    syncDrawer();
    syncGroup();
    if (mobile.matches && focusWasInSidebar) openButton.focus();
  });

  syncDrawer();
  syncGroup();
  if (window.location.pathname === "/" || window.location.pathname === "/index.html") {
    window.history.replaceState({}, "", "/resumen" + window.location.search);
  }
  renderPage();
  // A page refresh resumes the original read sequence. Moving between pages
  // retains in-memory results and never repeats a payment operation.
  showModule().catch(error => {
    setResult("No se pudo consultar el estado", error.message, ["Revisa la conexión y vuelve a consultar Sheets."], "warn");
  });
})();
