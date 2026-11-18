// The browser first receives a same-origin, CSRF-protected form from the backend.
// Authentication always leaves the portal iframe and uses the main window.
if (window.self === window.top) document.querySelector('form[action="/sso/iniciar"]')?.requestSubmit();
