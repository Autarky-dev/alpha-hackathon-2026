/**
 * SeatLock — main.js
 * Global behaviours: mobile nav toggle, flash message auto-dismiss.
 * No framework dependencies.
 */

(function () {
  'use strict';

  /* ── Mobile nav toggle ─────────────────────────────────────── */
  const hamburgerBtn = document.getElementById('hamburger-btn');
  const mainNav      = document.getElementById('main-nav');

  if (hamburgerBtn && mainNav) {
    hamburgerBtn.addEventListener('click', () => {
      const isOpen = mainNav.classList.toggle('mobile-open');
      hamburgerBtn.setAttribute('aria-expanded', String(isOpen));
    });

    // Close on outside click
    document.addEventListener('click', (e) => {
      if (!hamburgerBtn.contains(e.target) && !mainNav.contains(e.target)) {
        mainNav.classList.remove('mobile-open');
        hamburgerBtn.setAttribute('aria-expanded', 'false');
      }
    });

    // Close on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && mainNav.classList.contains('mobile-open')) {
        mainNav.classList.remove('mobile-open');
        hamburgerBtn.setAttribute('aria-expanded', 'false');
        hamburgerBtn.focus();
      }
    });
  }

  /* ── Auto-dismiss flash messages ───────────────────────────── */
  const alerts = document.querySelectorAll('.flash-container .alert');
  alerts.forEach((alert) => {
    setTimeout(() => {
      alert.style.transition = 'opacity 400ms ease, margin-top 400ms ease';
      alert.style.opacity    = '0';
      alert.style.marginTop  = '-' + alert.offsetHeight + 'px';
      setTimeout(() => alert.remove(), 400);
    }, 5000);
  });

})();
