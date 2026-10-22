'use strict';
(() => {
  const pass = document.querySelector('[data-live-pass]');
  if (!pass) return;
  const image = document.getElementById('live-qr');
  const status = document.getElementById('qr-status');
  const refresh = document.getElementById('refresh-pass');
  let expiresAt = Date.now() + 180000;
  let pending = false;
  let revoked = false;
  const update = async () => {
    if (pending || revoked) return;
    pending = true; refresh.disabled = true;
    try {
      const response = await fetch(pass.dataset.tokenUrl, {headers: {'Accept': 'application/json'}, cache: 'no-store', credentials: 'same-origin'});
      if (response.redirected) throw new Error('Your session expired. Sign in again to refresh your pass.');
      const result = await response.json().catch(() => { throw new Error('The pass service is unavailable. Try refreshing shortly.'); });
      if (!response.ok || !result.ok) {
        if (response.status === 403) { revoked = true; image.hidden = true; }
        throw new Error(result.message || 'Your pass could not be refreshed.');
      }
      image.src = result.qr_data; image.hidden = false;
      expiresAt = Date.now() + result.expires_in * 1000;
      status.textContent = 'Live QR · refreshed just now';
    } catch (error) {
      status.textContent = error instanceof TypeError ? 'Connection interrupted. Try refreshing your pass.' : error.message || 'Your pass could not be refreshed.';
      if (Date.now() >= expiresAt) image.hidden = true;
    } finally { pending = false; refresh.disabled = revoked; }
  };
  refresh.addEventListener('click', update);
  document.addEventListener('visibilitychange', () => { if (!document.hidden && !revoked) update(); });
  window.setInterval(() => {
    if (Date.now() >= expiresAt && !revoked) { image.hidden = true; status.textContent = 'QR expired. Refresh to display a valid pass.'; }
    if (!document.hidden && !revoked && expiresAt - Date.now() < 60000) update();
  }, 10000);
})();
