(() => {
  const form = document.querySelector('#loginForm');
  const button = document.querySelector('#loginButton');
  const error = document.querySelector('#loginError');
  form.addEventListener('submit', async event => {
    event.preventDefault();
    button.disabled = true;
    button.textContent = 'Ingresando…';
    error.hidden = true;
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ email: form.elements.email.value, password: form.elements.password.value }),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || 'No se pudo iniciar sesión.');
      form.elements.password.value = '';
      const next = new URLSearchParams(location.search).get('next');
      const allowed = ['/resumen', '/resultados', '/pagos', '/integracion', '/historico', '/alegra', '/configuracion'];
      location.assign(allowed.includes(next) ? next : '/resumen');
    } catch (failure) {
      error.textContent = failure.message || 'No se pudo conectar. Intenta nuevamente.';
      error.hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = 'Ingresar';
    }
  });
})();
