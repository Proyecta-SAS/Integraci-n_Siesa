(() => {
  const redirect = () => location.assign('/login?next=' + encodeURIComponent(location.pathname));
  const auth = { csrf: '', redirect };
  auth.ready = fetch('/api/auth/me', { credentials: 'same-origin', cache: 'no-store' }).then(async response => {
    if (response.status === 401) { redirect(); throw new Error('Debes iniciar sesión.'); }
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'No se pudo verificar la sesión.');
    auth.csrf = data.csrf_token;
    if (data.preview) document.querySelector('#portalPreviewNotice').hidden = false;
    document.querySelector('#authUserEmail').textContent = data.user.email;
    document.querySelector('#authAvatar').textContent = data.user.email[0].toUpperCase();
    return data;
  });
  // The operational requests await this same promise, so no POST races session initialization.
  auth.ready.catch(() => {});
  window.siesaAuth = auth;
  document.querySelector('#logoutButton').addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await auth.ready;
      const response = await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': auth.csrf } });
      if (response.ok || response.status === 401) location.assign('/login');
      else throw new Error('No se pudo cerrar la sesión.');
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Reintentar salida';
    }
  });
})();
