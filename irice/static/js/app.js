'use strict';
(() => {
  if (document.body.dataset.refresh) { window.setInterval(() => { if (!document.hidden && !document.body.classList.contains('nav-open')) window.location.reload(); }, Number(document.body.dataset.refresh)); }
  const toggle = document.querySelector('[data-toggle-nav]');
  const closeNav = () => { document.body.classList.remove('nav-open'); toggle?.setAttribute('aria-expanded', 'false'); };
  toggle?.addEventListener('click', () => { const opened = document.body.classList.toggle('nav-open'); toggle.setAttribute('aria-expanded', String(opened)); });
  document.querySelector('[data-close-nav]')?.addEventListener('click', closeNav);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') closeNav(); });
  document.querySelectorAll('[data-dismiss-alert]').forEach(button => button.addEventListener('click', () => button.closest('.alert').remove()));
  document.querySelectorAll('[data-confirm]').forEach(form => form.addEventListener('submit', event => { if (!window.confirm(form.dataset.confirm)) event.preventDefault(); }));
  document.querySelector('[data-poster-input]')?.addEventListener('change', event => {
    const file = event.target.files[0];
    const preview = document.querySelector('[data-poster-preview]');
    if (!file || !preview) return;
    if (!['image/png', 'image/jpeg'].includes(file.type) || file.size > 8 * 1024 * 1024) {
      event.target.setCustomValidity('Choose a PNG or JPEG image no larger than 8 MB.'); event.target.reportValidity(); return;
    }
    event.target.setCustomValidity(''); preview.src = URL.createObjectURL(file); preview.hidden = false;
    preview.onload = () => URL.revokeObjectURL(preview.src);
  });
})();
