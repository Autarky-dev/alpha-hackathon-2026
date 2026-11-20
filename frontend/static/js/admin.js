/**
 * SeatLock — admin.js
 * Admin dashboard integration:
 * - Real-time system stats (events, inventory, federated logs)
 * - 4-shard federated audit log viewer with filtering and live refresh
 * - Platform user search filter
 */

(function () {
  'use strict';

  /* ── DOM References ─────────────────────────────────────────── */
  const statTotalEvents    = document.getElementById('stat-total-events');
  const statTotalCapacity  = document.getElementById('stat-total-capacity');
  const statTotalAudits    = document.getElementById('stat-total-audits');

  const auditContainer     = document.getElementById('audit-entries-container');
  const auditActionFilter  = document.getElementById('audit-action-filter');
  const auditRefreshBtn    = document.getElementById('audit-refresh-btn');

  const userSearch         = document.querySelector('#users .search-bar input');
  const userTable          = document.querySelector('#users table tbody');

  /* ── 1. Fetch System Stats ───────────────────────────────────── */
  async function loadSystemStats() {
    // 1. Events stats
    const eventsRes = await window.apiFetch('/events');
    if (eventsRes.ok && Array.isArray(eventsRes.data)) {
      if (statTotalEvents) statTotalEvents.textContent = eventsRes.data.length;
      const totalSeats = eventsRes.data.reduce((acc, evt) => acc + (evt.total_seats || 0), 0);
      if (statTotalCapacity) statTotalCapacity.textContent = totalSeats.toLocaleString();
    }
  }

  /* ── 2. Fetch Federated 4-Shard Audit Logs ────────────────────── */
  async function loadAuditLogs() {
    if (!auditContainer) return;

    auditContainer.innerHTML = `
      <div style="padding: var(--space-6); text-align: center;" class="text-sm text-muted">
        Fetching entries from 4 audit shards (audit_logs_0..3)...
      </div>
    `;

    const selectedAction = auditActionFilter ? auditActionFilter.value : '';
    let queryUrl = '/audit-logs?limit=50';
    if (selectedAction) {
      queryUrl += `&action=${encodeURIComponent(selectedAction)}`;
    }

    const res = await window.apiFetch(queryUrl);
    if (!res.ok || !res.data) {
      auditContainer.innerHTML = `
        <div style="padding: var(--space-6); text-align: center;" class="text-sm text-danger">
          ${res.error || 'Failed to load federated audit logs.'}
        </div>
      `;
      return;
    }

    const { total, entries } = res.data;
    if (statTotalAudits) statTotalAudits.textContent = total.toLocaleString();

    if (!entries || entries.length === 0) {
      auditContainer.innerHTML = `
        <div style="padding: var(--space-6); text-align: center;" class="text-sm text-muted">
          No audit entries found matching current filter.
        </div>
      `;
      return;
    }

    auditContainer.innerHTML = entries.map((entry) => {
      const ts = entry.created_at ? new Date(entry.created_at).toLocaleTimeString() : '—';
      const actorRole = entry.actor_role || 'actor';
      const actorShort = entry.actor_id ? entry.actor_id.substring(0, 8) + '...' : 'System';

      // Level / badge styling
      let level = 'info';
      let badgeClass = 'badge--default';
      const act = (entry.action || '').toUpperCase();

      if (act.includes('LOGIN') || act.includes('CONFIRM') || act.includes('CHECKIN')) {
        level = 'info';
        badgeClass = 'badge--success';
      } else if (act.includes('CANCEL') || act.includes('EXPIRE') || act.includes('HOLD')) {
        level = 'warning';
        badgeClass = 'badge--warning';
      } else if (act.includes('FAIL') || act.includes('DENIED') || act.includes('ERROR')) {
        level = 'danger';
        badgeClass = 'badge--danger';
      }

      // Format details
      let detailStr = '';
      if (entry.details && typeof entry.details === 'object') {
        const parts = [];
        if (entry.details.seat_numbers) parts.push(`Seats: [${entry.details.seat_numbers.join(', ')}]`);
        if (entry.details.booking_id) parts.push(`Booking: ${entry.details.booking_id.substring(0, 8)}...`);
        if (entry.details.event_id) parts.push(`Event: ${entry.details.event_id.substring(0, 8)}...`);
        if (entry.details.method) parts.push(`Via: ${entry.details.method}`);
        if (entry.details.reason) parts.push(`Reason: ${entry.details.reason}`);
        detailStr = parts.length > 0 ? parts.join(' · ') : JSON.stringify(entry.details);
      } else if (entry.details) {
        detailStr = String(entry.details);
      } else {
        detailStr = 'No extra payload';
      }

      return `
        <div class="audit-entry audit-entry--${level}" style="display: flex; align-items: center; gap: 12px; padding: 12px 16px; border-bottom: 1px solid var(--color-border);">
          <code class="audit-entry__ts" style="font-size: 11px; color: var(--color-text-secondary); min-width: 65px;">${ts}</code>
          <span class="badge" style="font-size: 10px; background: rgba(99,102,241,0.15); color: #818cf8; border: 1px solid rgba(99,102,241,0.3);">
            Shard ${entry.shard_id}
          </span>
          <span class="audit-entry__actor" style="font-size: 13px; font-weight: 500; min-width: 130px;">
            <span style="opacity: 0.7; font-size: 11px;">[${actorRole}]</span> ${escapeHtml(actorShort)}
          </span>
          <span class="badge ${badgeClass} audit-entry__action" style="font-size: 11px;">
            ${escapeHtml(entry.action)}
          </span>
          <span class="audit-entry__detail text-sm text-muted" style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
            ${escapeHtml(detailStr)}
          </span>
        </div>
      `;
    }).join('');
  }

  /* ── 3. Utilities ────────────────────────────────────────────── */
  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ── Initialization ─────────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', () => {
    loadSystemStats();
    loadAuditLogs();

    auditRefreshBtn?.addEventListener('click', () => {
      loadAuditLogs();
      window.showNotification('Refreshed audit logs', 'info');
    });

    auditActionFilter?.addEventListener('change', () => {
      loadAuditLogs();
    });

    // User table live filter
    if (userSearch && userTable) {
      userSearch.addEventListener('input', () => {
        const q = userSearch.value.trim().toLowerCase();
        userTable.querySelectorAll('tr').forEach((row) => {
          const text = row.textContent.toLowerCase();
          row.style.display = text.includes(q) ? '' : 'none';
        });
      });
    }
  });

})();
