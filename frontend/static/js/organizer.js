/**
 * SeatLock — organizer.js
 * Comprehensive integration for Organizer Dashboard:
 * - Real-time event inventory & stats
 * - Event creation & OCC updates (Optimistic Concurrency Control with versioning)
 * - Live Attendee Manifest querying
 * - Gate Check-in via Booking UUID or Scanned QR Ticket Token
 */

(function () {
  'use strict';

  /* ── DOM Elements ────────────────────────────────────────────── */
  const eventsTableBody    = document.getElementById('events-table-body');
  const attendeesTableBody = document.getElementById('attendees-table-body');
  const attendeeEventSelect= document.getElementById('attendee-event-select');
  const attendeeSearchInput= document.getElementById('attendee-search-input');
  const gateEventSelect    = document.getElementById('gate-event-select');
  const gateTokenInput     = document.getElementById('gate-token-input');
  const gateCheckinBtn     = document.getElementById('gate-checkin-btn');
  const gateResultBox      = document.getElementById('gate-result-box');

  const statTotalEvents    = document.getElementById('stat-total-events');
  const statTotalBookings  = document.getElementById('stat-total-bookings');
  const statSeatsAvailable = document.getElementById('stat-seats-available');
  const statCheckedIn      = document.getElementById('stat-checked-in');

  // Modals
  const createModal        = document.getElementById('create-event-modal');
  const openCreateBtn      = document.getElementById('open-create-event-btn');
  const closeCreateBtn     = document.getElementById('close-create-modal');
  const createForm         = document.getElementById('create-event-form');

  const editModal          = document.getElementById('edit-event-modal');
  const closeEditBtn       = document.getElementById('close-edit-modal');
  const editForm           = document.getElementById('edit-event-form');

  /* ── State ──────────────────────────────────────────────────── */
  let myEvents = [];
  let currentAttendees = [];

  /* ── 1. Load Organizer Events & Global Stats ─────────────────── */
  async function loadOrganizerEvents() {
    if (!eventsTableBody) return;

    eventsTableBody.innerHTML = `
      <tr>
        <td colspan="6" class="text-center text-muted" style="padding: var(--space-6);">
          Loading organizer events...
        </td>
      </tr>
    `;

    const res = await window.apiFetch('/events/organizer/mine');
    if (!res.ok || !res.data) {
      eventsTableBody.innerHTML = `
        <tr>
          <td colspan="6" class="text-center text-danger" style="padding: var(--space-6);">
            ${res.error || 'Failed to load organizer events.'}
          </td>
        </tr>
      `;
      return;
    }

    myEvents = res.data;

    // Update stats
    if (statTotalEvents) statTotalEvents.textContent = myEvents.length;

    // Update dropdowns
    populateEventSelects(myEvents);

    if (myEvents.length === 0) {
      eventsTableBody.innerHTML = `
        <tr>
          <td colspan="6" class="text-center text-muted" style="padding: var(--space-6);">
            No events found. Click "Create event" above to publish your first event!
          </td>
        </tr>
      `;
      return;
    }

    // Render Event Rows
    let totalCap = 0;
    eventsTableBody.innerHTML = myEvents.map((evt) => {
      totalCap += evt.total_seats || 0;
      const startStr = evt.start_time ? new Date(evt.start_time).toLocaleString() : 'TBA';
      const isPast = evt.booking_close_time && new Date(evt.booking_close_time) < new Date();

      return `
        <tr data-id="${evt.id}">
          <td>
            <div class="font-medium">${escapeHtml(evt.title)}</div>
            <div class="text-xs text-muted">ID: ${evt.id.substring(0, 8)}... (v${evt.version})</div>
          </td>
          <td class="text-muted text-sm">${startStr}</td>
          <td class="text-muted text-sm">${escapeHtml(evt.location)}</td>
          <td>
            <span class="font-medium">${evt.total_seats}</span>
            <span class="text-xs text-muted">seats</span>
          </td>
          <td>
            <span class="badge ${isPast ? 'badge--default' : 'badge--success badge--dot'}">
              ${isPast ? 'Closed' : 'Active'}
            </span>
          </td>
          <td>
            <div class="flex gap-2" style="flex-wrap: wrap;">
              <button class="btn btn-secondary btn-sm edit-evt-btn" data-id="${evt.id}">
                Edit
              </button>
              <a href="/events/${evt.id}/seats" class="btn btn-ghost btn-sm" target="_blank">
                Seat map
              </a>
              <button class="btn btn-ghost btn-sm view-manifest-btn" data-id="${evt.id}">
                Attendees
              </button>
            </div>
          </td>
        </tr>
      `;
    }).join('');

    if (statSeatsAvailable) statSeatsAvailable.textContent = totalCap;

    // Attach Event Listeners
    document.querySelectorAll('.edit-evt-btn').forEach((btn) => {
      btn.addEventListener('click', () => openEditModal(btn.dataset.id));
    });

    document.querySelectorAll('.view-manifest-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        if (attendeeEventSelect) {
          attendeeEventSelect.value = btn.dataset.id;
          attendeeEventSelect.dispatchEvent(new Event('change'));
          document.getElementById('attendees-heading')?.scrollIntoView({ behavior: 'smooth' });
        }
      });
    });

    // Automatically load manifest for first event if available
    if (myEvents.length > 0 && attendeeEventSelect && !attendeeEventSelect.value) {
      attendeeEventSelect.value = myEvents[0].id;
      loadAttendees(myEvents[0].id);
    }
  }

  function populateEventSelects(events) {
    const optionsHtml = '<option value="">Select an event...</option>' +
      events.map(e => `<option value="${e.id}">${escapeHtml(e.title)}</option>`).join('');

    if (attendeeEventSelect) {
      const currentVal = attendeeEventSelect.value;
      attendeeEventSelect.innerHTML = optionsHtml;
      if (currentVal && events.some(e => e.id === currentVal)) {
        attendeeEventSelect.value = currentVal;
      }
    }

    if (gateEventSelect) {
      const currentVal = gateEventSelect.value;
      gateEventSelect.innerHTML = optionsHtml;
      if (currentVal && events.some(e => e.id === currentVal)) {
        gateEventSelect.value = currentVal;
      } else if (events.length > 0) {
        gateEventSelect.value = events[0].id;
      }
    }
  }

  /* ── 2. Load Attendee Manifest ───────────────────────────────── */
  async function loadAttendees(eventId) {
    if (!attendeesTableBody) return;

    if (!eventId) {
      attendeesTableBody.innerHTML = `
        <tr>
          <td colspan="6" class="text-center text-muted" style="padding: var(--space-6);">
            Select an event above to view attendee manifest.
          </td>
        </tr>
      `;
      return;
    }

    attendeesTableBody.innerHTML = `
      <tr>
        <td colspan="6" class="text-center text-muted" style="padding: var(--space-6);">
          Fetching attendee manifest...
        </td>
      </tr>
    `;

    const res = await window.apiFetch(`/events/${eventId}/attendees`);
    if (!res.ok || !res.data) {
      attendeesTableBody.innerHTML = `
        <tr>
          <td colspan="6" class="text-center text-danger" style="padding: var(--space-6);">
            ${res.error || 'Failed to load attendee manifest.'}
          </td>
        </tr>
      `;
      return;
    }

    const resData = res.data;
    currentAttendees = resData.attendees || (Array.isArray(resData) ? resData : []);

    // Update checked in stats from manifest aggregate
    const checkedInCount = resData.total_checked_in !== undefined
      ? resData.total_checked_in
      : currentAttendees.filter(a => a.status === 'CHECKED_IN' || !!a.checked_in_at).length;

    if (statCheckedIn) statCheckedIn.textContent = checkedInCount;
    if (statTotalBookings) statTotalBookings.textContent = resData.total_bookings !== undefined ? resData.total_bookings : currentAttendees.length;

    renderAttendeeTable();
  }

  function renderAttendeeTable() {
    if (!attendeesTableBody) return;

    const query = (attendeeSearchInput?.value || '').trim().toLowerCase();
    const filtered = currentAttendees.filter((a) => {
      if (!query) return true;
      return (
        (a.username || '').toLowerCase().includes(query) ||
        (a.booking_id || '').toLowerCase().includes(query) ||
        (a.seat_numbers || []).some(s => s.toLowerCase().includes(query))
      );
    });

    if (filtered.length === 0) {
      attendeesTableBody.innerHTML = `
        <tr>
          <td colspan="6" class="text-center text-muted" style="padding: var(--space-6);">
            ${currentAttendees.length === 0 ? 'No attendees booked for this event yet.' : 'No attendees match your search filter.'}
          </td>
        </tr>
      `;
      return;
    }

    attendeesTableBody.innerHTML = filtered.map((a) => {
      const isCheckedIn = a.status === 'CHECKED_IN' || !!a.checked_in_at;
      const checkinTime = a.checked_in_at ? new Date(a.checked_in_at).toLocaleTimeString() : '—';
      const seatsHtml = (a.seat_numbers || []).map(s => `<span class="booking-seat-tag">${escapeHtml(s)}</span>`).join(' ');

      return `
        <tr>
          <td>
            <div class="attendee-cell">
              <div class="attendee-avatar">${(a.username[0] || 'U').toUpperCase()}</div>
              <div>
                <div class="font-medium text-sm">${escapeHtml(a.username)}</div>
                <div class="text-xs text-muted">User: ${a.user_id.substring(0, 8)}...</div>
              </div>
            </div>
          </td>
          <td>
            <div class="flex gap-1" style="flex-wrap: wrap;">${seatsHtml}</div>
          </td>
          <td>
            <code style="font-size: var(--text-xs); color: var(--color-text-secondary);">${a.booking_id.substring(0, 8)}...</code>
          </td>
          <td>
            <span class="badge ${isCheckedIn ? 'badge--success badge--dot' : 'badge--warning badge--dot'}">
              ${isCheckedIn ? 'Checked in' : 'Confirmed'}
            </span>
          </td>
          <td class="text-xs text-muted">${checkinTime}</td>
          <td>
            ${
              isCheckedIn
                ? `<span class="badge badge--success">✓ Verified</span>`
                : `<button class="btn btn-ghost btn-sm row-checkin-btn" data-booking-id="${a.booking_id}">Check in</button>`
            }
          </td>
        </tr>
      `;
    }).join('');

    // Attach row check-in listeners
    document.querySelectorAll('.row-checkin-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const bookingId = btn.dataset.bookingId;
        const currentEventId = attendeeEventSelect.value;
        if (!currentEventId || !bookingId) return;

        btn.disabled = true;
        btn.textContent = 'Processing...';

        const res = await window.apiFetch(`/events/${currentEventId}/check-in`, {
          method: 'POST',
          body: { booking_id: bookingId },
        });

        if (res.ok) {
          window.showNotification('Attendee checked in successfully!', 'success');
          loadAttendees(currentEventId);
        } else {
          window.showNotification(res.error || 'Check-in failed.', 'error');
          btn.disabled = false;
          btn.textContent = 'Check in';
        }
      });
    });
  }

  /* ── 3. Gate QR Check-In Tool ────────────────────────────────── */
  async function handleGateCheckin() {
    if (!gateTokenInput || !gateResultBox) return;

    const rawInput = gateTokenInput.value.trim();
    const eventId  = gateEventSelect ? gateEventSelect.value : null;

    if (!rawInput) {
      window.showNotification('Please enter or scan a ticket token or booking ID.', 'warning');
      return;
    }

    gateResultBox.style.display = 'block';
    gateResultBox.innerHTML = `
      <div style="padding: 12px; background: var(--color-surface-raised); border-radius: 8px;" class="text-sm text-muted">
        Validating ticket and gate pass...
      </div>
    `;

    // Is it a UUID format?
    const isUUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(rawInput);

    let res;
    if (isUUID && (!eventId || eventId === '')) {
      // Direct booking check-in
      res = await window.apiFetch(`/bookings/${rawInput}/check-in`, { method: 'POST' });
    } else {
      if (!eventId) {
        gateResultBox.innerHTML = `
          <div style="padding: 12px; background: rgba(239,68,68,0.1); border: 1px solid var(--color-danger); border-radius: 8px; color: var(--color-danger);" class="text-sm">
            <strong>Check-in Error:</strong> Please select the target event from the dropdown above.
          </div>
        `;
        return;
      }

      const payload = isUUID ? { booking_id: rawInput } : { qr_token: rawInput };
      res = await window.apiFetch(`/events/${eventId}/check-in`, {
        method: 'POST',
        body: payload,
      });
    }

    if (res.ok && res.data) {
      const data = res.data;
      gateResultBox.innerHTML = `
        <div style="padding: 16px; background: rgba(16,185,129,0.1); border: 1px solid var(--color-success); border-radius: 8px;">
          <div class="flex items-center gap-2" style="margin-bottom: 6px;">
            <span style="color: var(--color-success); font-size: 1.25rem;">✓</span>
            <strong style="color: var(--color-success); font-size: 1rem;">Entry Approved — Checked In</strong>
          </div>
          <div class="text-sm" style="color: var(--color-text-primary);">
            <strong>Attendee:</strong> ${escapeHtml(data.username || 'Verified')} ·
            <strong>Seats:</strong> ${(data.seat_numbers || []).join(', ') || 'N/A'} ·
            <strong>Booking:</strong> <code>${(data.booking_id || '').substring(0, 8)}...</code>
          </div>
          <div class="text-xs text-muted" style="margin-top: 4px;">
            Check-in recorded at: ${data.checked_in_at ? new Date(data.checked_in_at).toLocaleTimeString() : new Date().toLocaleTimeString()}
          </div>
        </div>
      `;
      gateTokenInput.value = '';
      window.showNotification('Gate check-in confirmed!', 'success');

      // Refresh attendee manifest if viewing this event
      if (attendeeEventSelect && attendeeEventSelect.value === eventId) {
        loadAttendees(eventId);
      }
    } else {
      gateResultBox.innerHTML = `
        <div style="padding: 16px; background: rgba(239,68,68,0.1); border: 1px solid var(--color-danger); border-radius: 8px;">
          <div class="flex items-center gap-2" style="margin-bottom: 6px;">
            <span style="color: var(--color-danger); font-size: 1.25rem;">✕</span>
            <strong style="color: var(--color-danger); font-size: 1rem;">Gate Check-In Rejected</strong>
          </div>
          <p class="text-sm" style="color: var(--color-danger); margin: 0;">
            ${escapeHtml(res.error || 'Invalid or already-used ticket.')}
          </p>
        </div>
      `;
      window.showNotification(res.error || 'Check-in rejected.', 'error');
    }
  }

  /* ── 4. Create Event Modal ───────────────────────────────────── */
  function openCreateModal() {
    if (!createModal) return;
    createForm.reset();

    // Default dates: tomorrow at 18:00 UTC, close 1 hour before
    const now = new Date();
    const tomorrow = new Date(now.getTime() + 24 * 3600 * 1000);
    tomorrow.setMinutes(0, 0, 0);

    const closeTime = new Date(tomorrow.getTime() - 2 * 3600 * 1000);

    const pad = (n) => String(n).padStart(2, '0');
    const toLocalISO = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

    document.getElementById('ce-start-time').value = toLocalISO(tomorrow);
    document.getElementById('ce-close-time').value = toLocalISO(closeTime);

    createModal.style.display = 'flex';
  }

  function closeCreateModal() {
    if (createModal) createModal.style.display = 'none';
  }

  async function handleCreateEvent(e) {
    e.preventDefault();
    const title = document.getElementById('ce-title').value.trim();
    const location = document.getElementById('ce-location').value.trim();
    const startTimeVal = document.getElementById('ce-start-time').value;
    const closeTimeVal = document.getElementById('ce-close-time').value;
    const seatsVal = parseInt(document.getElementById('ce-seats').value, 10);

    if (!title || !location || !startTimeVal || !closeTimeVal || isNaN(seatsVal)) {
      window.showNotification('Please fill in all required fields.', 'warning');
      return;
    }

    const startTime = new Date(startTimeVal).toISOString();
    const closeTime = new Date(closeTimeVal).toISOString();

    const submitBtn = document.getElementById('ce-submit-btn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Creating & Initializing Seats...';

    const res = await window.apiFetch('/events', {
      method: 'POST',
      body: {
        title,
        location,
        start_time: startTime,
        booking_close_time: closeTime,
        total_seats: seatsVal,
      },
    });

    submitBtn.disabled = false;
    submitBtn.textContent = 'Create Event & Initialize Seats';

    if (res.ok) {
      window.showNotification('Event created successfully!', 'success');
      closeCreateModal();
      loadOrganizerEvents();
    } else {
      window.showNotification(res.error || 'Failed to create event.', 'error');
    }
  }

  /* ── 5. Edit Event Modal (Optimistic Concurrency Control) ─────── */
  function openEditModal(eventId) {
    if (!editModal) return;
    const evt = myEvents.find(e => e.id === eventId);
    if (!evt) return;

    document.getElementById('ee-id').value = evt.id;
    document.getElementById('ee-version').value = evt.version;
    document.getElementById('ee-title').value = evt.title;
    document.getElementById('ee-location').value = evt.location;
    document.getElementById('ee-seats').value = evt.total_seats;

    const pad = (n) => String(n).padStart(2, '0');
    const toLocalISO = (isoStr) => {
      if (!isoStr) return '';
      const d = new Date(isoStr);
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
    };

    document.getElementById('ee-start-time').value = toLocalISO(evt.start_time);
    document.getElementById('ee-close-time').value = toLocalISO(evt.booking_close_time);

    editModal.style.display = 'flex';
  }

  function closeEditModal() {
    if (editModal) editModal.style.display = 'none';
  }

  async function handleEditEvent(e) {
    e.preventDefault();
    const id = document.getElementById('ee-id').value;
    const version = parseInt(document.getElementById('ee-version').value, 10);
    const title = document.getElementById('ee-title').value.trim();
    const location = document.getElementById('ee-location').value.trim();
    const startTimeVal = document.getElementById('ee-start-time').value;
    const closeTimeVal = document.getElementById('ee-close-time').value;
    const seatsVal = parseInt(document.getElementById('ee-seats').value, 10);

    const startTime = new Date(startTimeVal).toISOString();
    const closeTime = new Date(closeTimeVal).toISOString();

    const submitBtn = document.getElementById('ee-submit-btn');
    submitBtn.disabled = true;
    submitBtn.textContent = 'Saving (Checking Version)...';

    const res = await window.apiFetch(`/events/${id}`, {
      method: 'PUT',
      body: {
        title,
        location,
        start_time: startTime,
        booking_close_time: closeTime,
        total_seats: seatsVal,
        version,
      },
    });

    submitBtn.disabled = false;
    submitBtn.textContent = 'Save Changes (Version Check)';

    if (res.ok) {
      window.showNotification('Event updated successfully (Version bumped)!', 'success');
      closeEditModal();
      loadOrganizerEvents();
    } else {
      if (res.status === 409) {
        window.showNotification('OCC Conflict: Event was updated by another request. Reloading...', 'error');
        closeEditModal();
        loadOrganizerEvents();
      } else {
        window.showNotification(res.error || 'Failed to update event.', 'error');
      }
    }
  }

  /* ── Utilities ───────────────────────────────────────────────── */
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
    loadOrganizerEvents();

    // Event Listeners for modals
    openCreateBtn?.addEventListener('click', openCreateModal);
    closeCreateBtn?.addEventListener('click', closeCreateModal);
    createForm?.addEventListener('submit', handleCreateEvent);

    closeEditBtn?.addEventListener('click', closeEditModal);
    editForm?.addEventListener('submit', handleEditEvent);

    // Close modals on background click
    window.addEventListener('click', (e) => {
      if (e.target === createModal) closeCreateModal();
      if (e.target === editModal) closeEditModal();
    });

    // Attendee selection & search
    attendeeEventSelect?.addEventListener('change', () => {
      loadAttendees(attendeeEventSelect.value);
    });

    attendeeSearchInput?.addEventListener('input', () => {
      renderAttendeeTable();
    });

    // Gate Check-in
    gateCheckinBtn?.addEventListener('click', handleGateCheckin);
    gateTokenInput?.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        e.preventDefault();
        handleGateCheckin();
      }
    });
  });

})();
