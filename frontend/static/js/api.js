/**
 * SeatLock — api.js
 * Centralized API client, session manager, and dynamic UI state.
 */

(function () {
  'use strict';

  // Resolve base URL for the FastAPI backend service:
  // 1. If window.API_BASE was already set by caller, honor it.
  // 2. If window.BACKEND_URL was injected from backend_url template context / env var, use it.
  // 3. If running locally on port 3000 (localhost or 127.0.0.1), fallback to http://localhost:8000.
  // 4. Otherwise (e.g. production same-origin or reverse-proxy), use "" (relative requests).
  if (typeof window.API_BASE === 'undefined' || window.API_BASE === null || window.API_BASE === '') {
    if (typeof window.BACKEND_URL === 'string' && window.BACKEND_URL.trim() !== '') {
      window.API_BASE = window.BACKEND_URL.trim().replace(/\/+$/, '');
    } else if (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') {
      window.API_BASE = window.location.port === '3000' ? 'http://localhost:8000' : '';
    } else {
      window.API_BASE = '';
    }
  }
  window.CURRENT_USER = null;

  /**
   * Universal fetch wrapper for SeatLock backend.
   * Enforces credentials: "include" for HttpOnly JWT cookie persistence.
   */
  async function apiFetch(path, options = {}) {
    const url = path.startsWith('http')
      ? path
      : window.API_BASE + (path.startsWith('/') ? path : '/' + path);

    const headers = { ...(options.headers || {}) };
    let body = options.body;

    if (body && typeof body === 'object' && !(body instanceof FormData)) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(body);
    }

    const fetchOptions = {
      ...options,
      headers,
      body,
      credentials: 'include', // Essential for cookie-based auth
    };

    try {
      const res = await fetch(url, fetchOptions);
      let data = null;
      const contentType = res.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        data = await res.json();
      } else {
        data = await res.text();
      }

      return {
        ok: res.ok,
        status: res.status,
        data,
        error: !res.ok ? (data && data.detail ? data.detail : 'Request failed') : null,
      };
    } catch (err) {
      console.error(`[apiFetch error] ${options.method || 'GET'} ${url}:`, err);
      return {
        ok: false,
        status: 0,
        data: null,
        error: 'Unable to connect to SeatLock backend service' + (window.API_BASE ? ' at ' + window.API_BASE : ''),
      };
    }
  }

  /**
   * Floating notification banner / toast.
   */
  function showNotification(message, type = 'info') {
    let container = document.getElementById('sl-notifications');
    if (!container) {
      container = document.createElement('div');
      container.id = 'sl-notifications';
      container.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        z-index: 99999;
        display: flex;
        flex-direction: column;
        gap: 10px;
        max-width: 420px;
      `;
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    const bg = type === 'success' ? '#059669' : type === 'error' ? '#dc2626' : type === 'warning' ? '#d97706' : '#4f46e5';
    toast.style.cssText = `
      background: ${bg};
      color: #ffffff;
      padding: 12px 18px;
      border-radius: 8px;
      font-size: 14px;
      font-weight: 500;
      box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      transition: opacity 300ms ease, transform 300ms ease;
      opacity: 0;
      transform: translateY(-8px);
    `;

    toast.innerHTML = `
      <span>${message}</span>
      <button style="background:none;border:none;color:#fff;cursor:pointer;font-size:16px;line-height:1;">✕</button>
    `;

    container.appendChild(toast);
    requestAnimationFrame(() => {
      toast.style.opacity = '1';
      toast.style.transform = 'translateY(0)';
    });

    const close = () => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(-8px)';
      setTimeout(() => toast.remove(), 300);
    };

    toast.querySelector('button').addEventListener('click', close);
    setTimeout(close, 4500);
  }

  /**
   * Authentication service.
   */
  const SeatLockAuth = {
    async getCurrentUser() {
      const res = await apiFetch('/auth/me');
      if (res.ok && res.data) {
        window.CURRENT_USER = res.data;
        return res.data;
      }
      window.CURRENT_USER = null;
      return null;
    },

    async login(username, password) {
      const res = await apiFetch('/auth/login', {
        method: 'POST',
        body: { username, password },
      });
      if (res.ok && res.data) {
        window.CURRENT_USER = res.data.user;
      }
      return res;
    },

    async logout() {
      const res = await apiFetch('/auth/logout', { method: 'POST' });
      window.CURRENT_USER = null;
      window.location.href = '/login';
      return res;
    },

    async initNavbar() {
      const user = await this.getCurrentUser();
      const mainNav = document.getElementById('main-nav');
      const navbarActions = document.querySelector('.navbar__actions');

      const currentPath = window.location.pathname;

      // Protected route guard:
      if (!user) {
        if (currentPath.startsWith('/bookings') || currentPath.startsWith('/organizer') || currentPath.startsWith('/admin')) {
          showNotification('Please sign in to view this page.', 'warning');
          setTimeout(() => { window.location.href = '/login'; }, 600);
          return;
        }
      } else {
        // Enforce role-based access
        if (currentPath.startsWith('/organizer') && user.role !== 'organizer' && user.role !== 'admin') {
          showNotification('Access restricted: Organizer role required.', 'error');
          setTimeout(() => { window.location.href = '/events'; }, 800);
          return;
        }
        if (currentPath.startsWith('/admin') && user.role !== 'admin') {
          showNotification('Access restricted: Admin role required.', 'error');
          setTimeout(() => { window.location.href = '/events'; }, 800);
          return;
        }
      }

      // Update Nav Links
      if (mainNav) {
        let navHtml = `
          <li><a href="/events" class="navbar__nav-link ${currentPath === '/' || currentPath.startsWith('/events') ? 'active' : ''}">Events</a></li>
        `;
        if (user) {
          navHtml += `
            <li><a href="/bookings" class="navbar__nav-link ${currentPath.startsWith('/bookings') ? 'active' : ''}">My Bookings</a></li>
          `;
          if (user.role === 'organizer' || user.role === 'admin') {
            navHtml += `
              <li><a href="/organizer" class="navbar__nav-link ${currentPath.startsWith('/organizer') ? 'active' : ''}">Dashboard</a></li>
            `;
          }
          if (user.role === 'admin') {
            navHtml += `
              <li><a href="/admin" class="navbar__nav-link ${currentPath.startsWith('/admin') ? 'active' : ''}">Admin</a></li>
            `;
          }
        }
        mainNav.innerHTML = navHtml;
      }

      // Update Navbar Actions (Profile / Sign in / Sign out)
      if (navbarActions) {
        const hamburger = document.getElementById('hamburger-btn');
        if (user) {
          navbarActions.innerHTML = `
            <div class="navbar__user" aria-label="User menu" style="display:flex;align-items:center;gap:8px;">
              <div class="navbar__avatar" aria-hidden="true" style="background:var(--color-accent);color:#fff;font-weight:700;">
                ${(user.username[0] || 'U').toUpperCase()}
              </div>
              <span class="navbar__user-name" style="font-weight:600;">${user.username}</span>
              <span class="badge badge--accent" style="font-size:11px;text-transform:capitalize;">${user.role}</span>
            </div>
            <button id="nav-signout-btn" class="btn btn-ghost btn-sm">Sign out</button>
          `;
          document.getElementById('nav-signout-btn')?.addEventListener('click', () => {
            SeatLockAuth.logout();
          });
        } else {
          navbarActions.innerHTML = `
            <a href="/login" class="btn btn-primary btn-sm">Sign in</a>
          `;
        }
        if (hamburger) navbarActions.appendChild(hamburger);
      }
    },
  };

  window.apiFetch = apiFetch;
  window.showNotification = showNotification;
  window.SeatLockAuth = SeatLockAuth;

  // Auto-init navbar on DOM load
  document.addEventListener('DOMContentLoaded', () => {
    SeatLockAuth.initNavbar();
  });
})();
