/* Módulo Alegra. Comparte sesión y CSRF; nunca utiliza los endpoints de Siesa. */
(() => {
  const feedback = document.querySelector('#alegraFeedback');
  const dialog = document.querySelector('#alegraConfirmDialog');
  const confirmButton = document.querySelector('#alegraConfirm');
  const cancelButton = document.querySelector('#alegraCancel');
  const buttons = [...document.querySelectorAll('[data-alegra]')];
  const locks = new Map();
  let selected = null, busy = false, loading = false;

  function showFeedback(message, error = false) {
    feedback.textContent = message;
    feedback.classList.toggle('alegra-feedback--error', error);
  }
  function renderLocks() {
    const now = Date.now();
    for (const button of buttons) {
      const state = locks.get(button.dataset.alegra);
      const remaining = state ? Math.max(0, Math.ceil((state.until - now) / 1000)) : 0;
      button.disabled = busy || !state || !state.configured || remaining > 0;
      button.textContent = remaining > 0
        ? `Disponible en ${String(Math.floor(remaining / 60)).padStart(2, '0')}:${String(remaining % 60).padStart(2, '0')}`
        : !state ? 'Consultando…' : !state.configured ? 'Conexión pendiente' : 'Ejecutar sistema →';
    }
  }
  async function request(path, options = {}) {
    const auth = window.siesaAuth;
    await auth.ready;
    const response = await fetch(path, { credentials: 'same-origin', cache: 'no-store', ...options,
      headers: { Accept: 'application/json', ...(options.method === 'POST' ? { 'Content-Type': 'application/json', 'X-CSRF-Token': auth.csrf } : {}) } });
    if (response.status === 401) { auth.redirect(); throw new Error('Debes iniciar sesión nuevamente.'); }
    const data = await response.json();
    return { response, data };
  }
  async function loadStatus() {
    if (loading) return;
    loading = true;
    try {
      const { response, data } = await request('/api/alegra/status');
      if (!response.ok || !data.ok) throw new Error(data.error || 'No se pudo consultar Alegra.');
      for (const account of data.accounts) locks.set(account.id, { configured: account.configured, until: Date.now() + account.retry_after_seconds * 1000 });
      showFeedback(data.preview ? 'Demostración local: puedes probar las cuentas sin enviar órdenes reales.' : 'Selecciona la cuenta contable que deseas activar.');
      renderLocks();
    } catch (error) { showFeedback(error.message, true); }
    finally { loading = false; }
  }
  for (const button of buttons) button.addEventListener('click', () => {
    if (busy || button.disabled) return;
    selected = button;
    const name = button.closest('.alegra-card').querySelector('h3').textContent;
    document.querySelector('#alegraConfirmMessage').textContent = `¿Deseas activar la cuenta ${name}?`;
    dialog.showModal();
    cancelButton.focus();
  });
  cancelButton.addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => { if (selected) selected.focus(); });
  confirmButton.addEventListener('click', async () => {
    if (busy || !selected) return;
    const key = selected.dataset.alegra;
    busy = true;
    confirmButton.disabled = cancelButton.disabled = true;
    confirmButton.textContent = 'Procesando…';
    renderLocks();
    try {
      const { response, data } = await request('/api/alegra/activate', { method: 'POST', body: JSON.stringify({ tipo: key, activador: 'ON' }) });
      if (data.retry_after_seconds) locks.set(key, { configured: true, until: Date.now() + data.retry_after_seconds * 1000 });
      if (!response.ok || !data.ok) throw new Error(data.error || 'No se pudo confirmar la activación.');
      showFeedback(data.preview ? 'Prueba completada: no se envió ninguna activación real.' : 'La orden de activación se envió correctamente a Alegra.');
    } catch (error) { showFeedback(error.message + ' Consulta el estado antes de volver a intentar.', true); }
    finally {
      busy = false;
      confirmButton.disabled = cancelButton.disabled = false;
      confirmButton.textContent = 'Sí, activar';
      dialog.close();
      renderLocks();
    }
  });
  function onPage() {
    if (location.pathname !== '/alegra') return;
    loadStatus();
    document.querySelectorAll('.alegra-card').forEach(card => card.classList.toggle('alegra-card--selected', '#' + card.id === location.hash));
    const card = document.querySelector('.alegra-card--selected');
    if (card) { card.scrollIntoView({ block: 'nearest' }); card.focus({ preventScroll: true }); }
  }
  window.addEventListener('portal:page', onPage);
  setInterval(renderLocks, 1000);
  setInterval(() => { if (location.pathname === '/alegra' && !document.hidden && !busy) loadStatus(); }, 30000);

  const themeButton = document.querySelector('#portalThemeButton');
  function setTheme(theme) {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem('tema', theme); } catch (_) {}
    themeButton.setAttribute('aria-label', theme === 'dark' ? 'Activar tema claro' : 'Activar tema oscuro');
    themeButton.setAttribute('aria-pressed', String(theme === 'dark'));
    document.querySelectorAll('[data-portal-theme]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.portalTheme === theme)));
  }
  let theme = 'light';
  try { theme = localStorage.getItem('tema') || localStorage.getItem('af-theme') || 'light'; } catch (_) {}
  setTheme(theme === 'dark' ? 'dark' : 'light');
  themeButton.addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
  document.querySelectorAll('[data-portal-theme]').forEach(button => button.addEventListener('click', () => setTheme(button.dataset.portalTheme)));
})();
