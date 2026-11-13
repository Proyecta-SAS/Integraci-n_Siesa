(() => {
  const form = document.querySelector('#historyFilters');
  const body = document.querySelector('#historyBody');
  const message = document.querySelector('#historyMessage');
  const previous = document.querySelector('#historyPrevious');
  const next = document.querySelector('#historyNext');
  const filter = document.querySelector('#historyFilterButton');
  let page = 1, pages = 1, ticket = 0;
  const statusNames = { confirmed: ['Confirmado', 'ok'], unconfirmed: ['Sin confirmar', 'pendiente'], rejected: ['Rechazado', 'novedad'], review: ['Por verificar', 'pendiente'] };
  function cell(row, value, className = '') {
    const item = document.createElement('td');
    item.textContent = value || '—';
    item.className = className;
    row.append(item);
    return item;
  }
  function badge(target, label, variant) {
    target.textContent = '';
    const span = document.createElement('span');
    span.className = 'pildora pildora--' + variant;
    span.textContent = label;
    target.append(span);
    return span;
  }
  function amount(value) {
    if (!value) return '—';
    const [whole, fraction] = value.split('.');
    return '$ ' + whole.replace(/\B(?=(\d{3})+(?!\d))/g, '.') + (fraction ? ',' + fraction : '');
  }
  async function load() {
    const current = ++ticket;
    previous.disabled = next.disabled = filter.disabled = true;
    message.textContent = 'Consultando el histórico…';
    try {
      const query = new URLSearchParams({ page, source: form.elements.source.value, search: form.elements.search.value, status: form.elements.status.value, duplicates: form.elements.duplicates.checked ? '1' : '0' });
      const data = await api('/api/history?' + query);
      if (current !== ticket) return;
      document.querySelector('#historyConfirmed').textContent = data.summary.confirmed || 0;
      document.querySelector('#historyUnconfirmed').textContent = data.summary.unconfirmed || 0;
      document.querySelector('#historyDuplicates').textContent = data.summary.possible_duplicates || 0;
      document.querySelector('#historyWithoutNumber').textContent = data.summary.without_receipt_number || 0;
      const selectedSource = form.elements.source.value;
      form.elements.source.replaceChildren(new Option('Todas las fuentes', 'all'), ...data.sources.map(source => new Option(source, source)));
      form.elements.source.value = selectedSource;
      body.replaceChildren();
      for (const record of data.rows) {
        const row = document.createElement('tr');
        cell(row, record.payment_date);
        cell(row, record.activator);
        cell(row, record.identity_number);
        cell(row, record.customer || 'Sin dato histórico');
        cell(row, amount(record.amount), 'tabla__num');
        badge(cell(row, ''), ...(statusNames[record.status] || statusNames.review));
        cell(row, record.receipt_number || 'No devuelto');
        cell(row, record.note, 'detail-cell');
        const warning = cell(row, 'Sin coincidencia detectada');
        if (record.possible_duplicate) badge(warning, 'Posible duplicado', 'pendiente').title = record.duplicate_reason;
        body.append(row);
      }
      if (!data.rows.length) {
        const row = document.createElement('tr');
        const empty = cell(row, 'No hay registros para estos filtros.', 'tabla__vacio');
        empty.colSpan = 9;
        body.append(row);
      }
      pages = Math.max(1, Math.ceil(data.total / data.page_size));
      document.querySelector('#historyPage').textContent = `Página ${page} de ${pages} · ${data.total} registros`;
      message.textContent = `${data.avoided_resends} reenvíos evitados registrados.` +
        (data.last_synced_at ? ` Actualizado: ${new Date(data.last_synced_at).toLocaleString('es-CO')}.` : ' Preparando importación.') +
        (data.sync_error ? ' No se pudo actualizar el índice; se muestran los datos conservados.' : '') +
        (data.import_issues ? ` ${data.import_issues} registros de origen requieren revisión; las copias originales se conservaron.` : '');
    } catch (error) {
      if (current === ticket) message.textContent = error.message || 'No se pudo actualizar el histórico.';
    } finally {
      if (current === ticket) {
        filter.disabled = false;
        previous.disabled = page <= 1;
        next.disabled = page >= pages;
      }
    }
  }
  form.addEventListener('submit', event => { event.preventDefault(); page = 1; load(); });
  previous.addEventListener('click', () => { if (page > 1) { page--; load(); } });
  next.addEventListener('click', () => { if (page < pages) { page++; load(); } });
  window.addEventListener('siesa:history', load);
})();
