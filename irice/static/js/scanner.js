'use strict';
(() => {
  const container = document.querySelector('[data-scanner]');
  if (!container) return;
  const start = document.getElementById('start-camera');
  const stop = document.getElementById('stop-camera');
  const next = document.getElementById('scan-next');
  const placeholder = document.getElementById('camera-placeholder');
  const reader = document.getElementById('qr-reader');
  const cameraStatus = document.getElementById('camera-status');
  const form = document.getElementById('manual-scan');
  const tokenInput = document.getElementById('scan-token');
  const submit = document.getElementById('verify-token');
  const result = document.getElementById('scan-result');
  const title = document.getElementById('scan-result-title');
  const message = document.getElementById('scan-result-message');
  const time = document.getElementById('scan-result-time');
  let scanner = null;
  let scanning = false;
  let paused = false;
  let busy = false;
  const showResult = (state, heading, detail, stamp = '') => {
    result.hidden = false; result.dataset.state = state;
    title.textContent = heading; message.textContent = detail;
    time.textContent = stamp ? `Recorded: ${stamp}` : '';
    document.getElementById('scan-result-icon').textContent = state === 'error' ? '!' : state === 'duplicate' ? '↺' : '✓';
  };
  const verify = async token => {
    if (busy) return;
    busy = true; submit.disabled = true;
    try {
      if (scanning && scanner && !paused) { scanner.pause(true); paused = true; next.hidden = false; }
      const response = await fetch(container.dataset.checkinUrl, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content},
        body: JSON.stringify({token})
      });
      if (response.redirected) throw new Error('Your session expired. Refresh this page and sign in again.');
      const data = await response.json().catch(() => { throw new Error('The check-in service is unavailable. Try again shortly.'); });
      if (!response.ok || !data.ok) throw new Error(data.message || 'This pass could not be verified.');
      showResult(data.duplicate ? 'duplicate' : 'success', data.duplicate ? 'Already checked in' : 'Welcome to I-RICE!', `${data.name} · ${data.role}. ${data.message}`, data.time);
      tokenInput.value = '';
      if (paused) cameraStatus.textContent = 'Scan complete. Select “Scan next pass” when ready.';
    } catch (error) { showResult('error', 'Pass not accepted', error instanceof TypeError ? 'Connection interrupted. Try again.' : error.message || 'This pass could not be verified.'); }
    finally { busy = false; submit.disabled = false; }
  };
  form.addEventListener('submit', event => { event.preventDefault(); const token = tokenInput.value.trim(); if (token) verify(token); });
  start.addEventListener('click', async () => {
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      cameraStatus.textContent = 'Camera access requires HTTPS or a browser-trusted local connection. Use manual entry below.'; return;
    }
    start.disabled = true; cameraStatus.textContent = 'Waiting for camera permission…';
    try {
      reader.hidden = false; scanner = new Html5Qrcode('qr-reader');
      await scanner.start({facingMode: 'environment'}, {fps: 10, qrbox: {width: 220, height: 220}}, token => { if (!busy && !paused) verify(token); });
      scanning = true; paused = false; placeholder.hidden = true; stop.hidden = false;
      cameraStatus.textContent = 'Camera is on. Hold the admission QR inside the frame.';
    } catch (_error) {
      reader.hidden = true; placeholder.hidden = false;
      cameraStatus.textContent = 'Camera could not start. Check device permissions or use manual entry below.';
      scanner = null;
    } finally { start.disabled = false; }
  });
  stop.addEventListener('click', async () => {
    if (!scanner) return;
    stop.disabled = true;
    try { await scanner.stop(); scanner.clear(); }
    catch (_error) { /* Keep the manual workflow available if the camera disconnects. */ }
    finally { scanning = false; paused = false; scanner = null; reader.hidden = true; placeholder.hidden = false; stop.hidden = true; next.hidden = true; stop.disabled = false; cameraStatus.textContent = 'Camera is off. Manual entry is always available.'; }
  });
  next.addEventListener('click', () => { if (scanner && paused) { scanner.resume(); paused = false; next.hidden = true; result.hidden = true; cameraStatus.textContent = 'Ready for the next admission pass.'; } });
  window.addEventListener('pagehide', () => { if (scanner && scanning) scanner.stop().catch(() => {}); });
})();
