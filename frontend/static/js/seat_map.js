/**
 * SeatLock — seat_map.js
 * End-to-end integration for real-time venue seat maps, interactive seat selection,
 * atomic 5-minute temporary holds, countdown timer, and booking confirmation.
 */

(function () {
  'use strict';

  /* ── Constants ─────────────────────────────────────────────── */
  const MAX_SEATS = 4;
  const HOLD_DURATION_SECONDS = 300; // 5 minutes

  /* ── DOM references ─────────────────────────────────────────── */
  const seatMap         = document.getElementById('seat-map');
  const holdBtn         = document.getElementById('hold-btn');
  const holdTimerEl     = document.getElementById('hold-timer');
  const holdCountdownEl = document.getElementById('hold-countdown');
  const holdTimerBar    = document.getElementById('hold-timer-bar');
  const confirmBtn      = document.getElementById('confirm-btn');
  const releaseBtn      = document.getElementById('release-btn');

  const sidebarEmpty    = document.getElementById('seat-sidebar-empty');
  const sidebarSelected = document.getElementById('seat-sidebar-selected');
  const selectedList    = document.getElementById('selected-seat-list');
  const summaryCount    = document.getElementById('summary-count');

  const bannerTitle     = document.querySelector('.seat-event-banner__title');
  const bannerMetaSpans = document.querySelectorAll('.seat-event-banner__meta span');

  if (!seatMap) return;

  /* ── State ──────────────────────────────────────────────────── */
  let eventId           = null;
  let selectedSeats     = []; // array of seat numbers, e.g. ["A1", "A2"]
  let activeHoldId      = null;
  let holdExpiresAt     = null;
  let holdTimerInterval = null;

  // Extract eventId from URL (/events/{id}/seats) or data attribute
  function getEventId() {
    const parts = window.location.pathname.split('/');
    // e.g. ["", "events", "097bfb66-...", "seats"]
    for (let i = 0; i < parts.length; i++) {
      if (parts[i] === 'events' && parts[i + 1]) {
        return parts[i + 1];
      }
    }
    return seatMap.dataset.eventId || null;
  }

  /* ── 1. Fetch Event Header & Seat Inventory ──────────────────── */
  async function loadEventData() {
    eventId = getEventId();
    if (!eventId) {
      console.error('Could not determine event ID from URL');
      return;
    }

    // Fetch Event Details
    const eventRes = await window.apiFetch(`/events/${eventId}`);
    if (eventRes.ok && eventRes.data) {
      const evt = eventRes.data;
      if (bannerTitle) bannerTitle.textContent = evt.title;
      const d = new Date(evt.start_time);
      const dateStr = d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
      const timeStr = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });

      if (bannerMetaSpans[0]) bannerMetaSpans[0].innerHTML = `📅 ${dateStr} · ${timeStr}`;
      if (bannerMetaSpans[1]) bannerMetaSpans[1].innerHTML = `📍 ${evt.location || 'Venue TBA'}`;
    }

    // Fetch Live Seat Map
    await refreshSeatMap();
  }

  async function refreshSeatMap() {
    seatMap.innerHTML = `
      <div style="text-align: center; padding: 40px; color: var(--color-text-secondary); width: 100%;">
        <p>Loading venue seating layout...</p>
      </div>
    `;

    const seatRes = await window.apiFetch(`/events/${eventId}/seats`);
    if (!seatRes.ok || !seatRes.data) {
      seatMap.innerHTML = `
        <div style="text-align: center; padding: 40px; color: var(--color-danger); width: 100%;">
          <p>Failed to load venue seats: ${seatRes.error || 'Server error'}</p>
        </div>
      `;
      return;
    }

    const { seats, available_count, total_seats } = seatRes.data;
    if (bannerMetaSpans[2]) {
      bannerMetaSpans[2].innerHTML = `💺 ${available_count} of ${total_seats} seats available`;
    }

    renderSeatsGrid(seats);
  }

  /* ── 2. Render Live Dynamic Seat Layout ──────────────────────── */
  function renderSeatsGrid(seats) {
    seatMap.innerHTML = '';

    if (!seats || seats.length === 0) {
      seatMap.innerHTML = '<p class="text-muted text-center" style="padding: 20px;">No seats configured for this event.</p>';
      return;
    }

    // Group seats by Row letter
    const rowMap = new Map();
    seats.forEach((s) => {
      // Split "A10" -> row "A", col "10"
      const match = s.seat_number.match(/^([A-Za-z]+)(\d+)$/);
      const rowLabel = match ? match[1] : s.seat_number.charAt(0);
      const colNum = match ? parseInt(match[2], 10) : parseInt(s.seat_number.slice(1), 10) || 1;

      if (!rowMap.has(rowLabel)) {
        rowMap.set(rowLabel, []);
      }
      rowMap.get(rowLabel).push({ ...s, colNum });
    });

    // Sort rows alphabetically and seats within rows by col number
    const sortedRowLabels = Array.from(rowMap.keys()).sort();

    sortedRowLabels.forEach((rowLabel) => {
      const rowSeats = rowMap.get(rowLabel).sort((a, b) => a.colNum - b.colNum);

      const rowDiv = document.createElement('div');
      rowDiv.className = 'seat-row';
      rowDiv.setAttribute('role', 'row');
      rowDiv.dataset.row = rowLabel;

      rowDiv.innerHTML = `
        <span class="seat-row__label" aria-hidden="true">${rowLabel}</span>
        <div class="seat-row__seats" role="rowgroup"></div>
        <span class="seat-row__label" aria-hidden="true">${rowLabel}</span>
      `;

      const seatsContainer = rowDiv.querySelector('.seat-row__seats');

      rowSeats.forEach((seat) => {
        const btn = document.createElement('button');
        const num = seat.seat_number;
        const isSelected = selectedSeats.includes(num);

        if (seat.status === 'booked') {
          btn.className = 'seat seat--booked';
          btn.disabled = true;
          btn.setAttribute('aria-label', `Seat ${num} — booked`);
          btn.title = `Seat ${num} (Booked)`;
        } else if (seat.status === 'held') {
          if (seat.is_held_by_me || isSelected) {
            btn.className = 'seat seat--selected';
            btn.dataset.seatId = num;
            btn.setAttribute('aria-label', `Seat ${num} — selected by you`);
            btn.title = `Seat ${num} (Selected)`;
          } else {
            btn.className = 'seat seat--held';
            btn.disabled = true;
            btn.setAttribute('aria-label', `Seat ${num} — held by another user`);
            btn.title = `Seat ${num} (Held)`;
          }
        } else {
          // Available
          btn.className = `seat ${isSelected ? 'seat--selected' : 'seat--available'}`;
          btn.dataset.seatId = num;
          btn.setAttribute('aria-label', `Seat ${num} — available`);
          btn.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
          btn.title = `Seat ${num} (Available)`;
        }

        btn.textContent = seat.colNum || num;
        seatsContainer.appendChild(btn);
      });

      seatMap.appendChild(rowDiv);
    });
  }

  /* ── 3. Seat Click Handler (Toggle Selection) ────────────────── */
  seatMap.addEventListener('click', (e) => {
    const seatBtn = e.target.closest('.seat--available, .seat--selected');
    if (!seatBtn || activeHoldId) return; // Locked while active hold exists

    const seatId = seatBtn.dataset.seatId;
    if (!seatId) return;

    const idx = selectedSeats.indexOf(seatId);

    if (idx > -1) {
      // Deselect
      selectedSeats.splice(idx, 1);
      seatBtn.classList.remove('seat--selected');
      seatBtn.classList.add('seat--available');
      seatBtn.setAttribute('aria-pressed', 'false');
    } else {
      // Select
      if (selectedSeats.length >= MAX_SEATS) {
        shakeElement(seatBtn);
        window.showNotification(`Maximum ${MAX_SEATS} seats allowed per reservation.`, 'warning');
        return;
      }
      selectedSeats.push(seatId);
      seatBtn.classList.remove('seat--available');
      seatBtn.classList.add('seat--selected');
      seatBtn.setAttribute('aria-pressed', 'true');
    }

    updateSidebar();
    updateHoldButton();
  });

  /* ── 4. Sidebar State Synchronization ────────────────────────── */
  function updateSidebar() {
    const hasSeats = selectedSeats.length > 0;

    if (sidebarEmpty) sidebarEmpty.hidden = hasSeats;
    if (sidebarSelected) sidebarSelected.hidden = !hasSeats;

    if (!hasSeats) {
      if (selectedList) selectedList.replaceChildren();
      if (summaryCount) summaryCount.textContent = '0';
      return;
    }
    if (!selectedList) return;

    selectedList.innerHTML = '';
    selectedSeats.forEach((seatNum, idx) => {
      const li = document.createElement('li');
      li.className = 'selected-seat-item';
      li.innerHTML = `
        <span class="selected-seat-item__id">Seat ${seatNum}</span>
        ${!activeHoldId ? `
          <button class="selected-seat-item__remove" data-index="${idx}" aria-label="Remove seat ${seatNum}">✕</button>
        ` : ''}
      `;
      selectedList.appendChild(li);
    });

    if (summaryCount) summaryCount.textContent = String(selectedSeats.length);
  }

  // Remove from sidebar
  selectedList && selectedList.addEventListener('click', (e) => {
    if (activeHoldId) return;
    const btn = e.target.closest('[data-index]');
    if (!btn) return;
    const idx = parseInt(btn.dataset.index, 10);
    const removedId = selectedSeats[idx];
    selectedSeats.splice(idx, 1);

    // Update button in grid
    const gridBtn = seatMap.querySelector(`[data-seat-id="${removedId}"]`);
    if (gridBtn) {
      gridBtn.classList.remove('seat--selected');
      gridBtn.classList.add('seat--available');
      gridBtn.setAttribute('aria-pressed', 'false');
    }

    updateSidebar();
    updateHoldButton();
  });

  function updateHoldButton() {
    if (holdBtn) {
      holdBtn.disabled = selectedSeats.length === 0 || !!activeHoldId;
    }
  }

  /* ── 5. Acquire 5-Minute Seat Hold (API POST) ─────────────────── */
  holdBtn && holdBtn.addEventListener('click', async () => {
    if (selectedSeats.length === 0) return;

    // Check login
    if (!window.CURRENT_USER) {
      window.showNotification('Please sign in to place a seat hold.', 'warning');
      setTimeout(() => { window.location.href = '/login'; }, 800);
      return;
    }

    holdBtn.disabled = true;
    holdBtn.textContent = 'Acquiring hold...';

    const res = await window.apiFetch(`/events/${eventId}/hold`, {
      method: 'POST',
      body: { seat_numbers: selectedSeats },
    });

    if (res.ok && res.data) {
      activeHoldId = res.data.id;
      holdExpiresAt = new Date(res.data.expires_at);

      window.showNotification('Seats successfully locked for 5 minutes!', 'success');

      holdBtn.textContent = 'Seats Locked';
      holdBtn.disabled = true;

      if (holdTimerEl) holdTimerEl.hidden = false;
      startCountdownTimer();
    } else {
      holdBtn.disabled = false;
      holdBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect width="11" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
        </svg>
        Hold seats
      `;

      if (res.status === 409) {
        window.showNotification(res.error || 'Conflict: Some selected seats are no longer available. Refreshing...', 'error');
        selectedSeats = [];
        updateSidebar();
        await refreshSeatMap();
      } else {
        window.showNotification(res.error || 'Failed to place seat hold.', 'error');
      }
    }
  });

  /* ── 6. Countdown Timer & Auto-Release ───────────────────────── */
  function startCountdownTimer() {
    if (holdTimerInterval) clearInterval(holdTimerInterval);

    function tick() {
      const now = new Date();
      const diffSecs = Math.max(0, Math.floor((holdExpiresAt - now) / 1000));

      const mins = String(Math.floor(diffSecs / 60)).padStart(2, '0');
      const secs = String(diffSecs % 60).padStart(2, '0');
      if (holdCountdownEl) holdCountdownEl.textContent = `${mins}:${secs}`;

      const pct = Math.min(100, Math.max(0, (diffSecs / HOLD_DURATION_SECONDS) * 100));
      if (holdTimerBar) holdTimerBar.style.width = `${pct}%`;

      if (diffSecs <= 0) {
        clearInterval(holdTimerInterval);
        holdTimerInterval = null;
        expireHold();
      }
    }

    tick();
    holdTimerInterval = setInterval(tick, 1000);
  }

  function expireHold() {
    activeHoldId = null;
    holdExpiresAt = null;
    if (holdTimerEl) holdTimerEl.hidden = true;
    selectedSeats = [];
    updateSidebar();
    updateHoldButton();
    window.showNotification('Your 5-minute seat hold has expired. Please select seats again.', 'warning');
    refreshSeatMap();
  }

  /* ── 7. Confirm Hold into Permanent Booking (API POST) ────────── */
  confirmBtn && confirmBtn.addEventListener('click', async () => {
    if (!activeHoldId) return;

    confirmBtn.disabled = true;
    confirmBtn.textContent = 'Confirming reservation...';

    const res = await window.apiFetch(`/holds/${activeHoldId}/confirm`, {
      method: 'POST',
    });

    if (res.ok && res.data) {
      clearInterval(holdTimerInterval);
      holdTimerInterval = null;
      activeHoldId = null;

      window.showNotification('Booking confirmed! Redirecting to your tickets...', 'success');

      setTimeout(() => {
        window.location.href = '/bookings';
      }, 1000);
    } else {
      confirmBtn.disabled = false;
      confirmBtn.textContent = 'Confirm booking';

      if (res.status === 409) {
        window.showNotification('Your hold expired before confirmation could be processed.', 'error');
        expireHold();
      } else {
        window.showNotification(res.error || 'Failed to confirm booking.', 'error');
      }
    }
  });

  /* ── 8. Manual Release Seats ─────────────────────────────────── */
  releaseBtn && releaseBtn.addEventListener('click', async () => {
    if (holdTimerInterval) clearInterval(holdTimerInterval);
    activeHoldId = null;
    holdExpiresAt = null;
    if (holdTimerEl) holdTimerEl.hidden = true;
    selectedSeats = [];
    updateSidebar();
    updateHoldButton();
    window.showNotification('Seats released.', 'info');
    await refreshSeatMap();
  });

  /* ── Helpers ────────────────────────────────────────────────── */
  function shakeElement(el) {
    el.style.animation = 'none';
    el.getBoundingClientRect(); // reflow
    el.style.animation = 'shake 300ms ease';
    el.addEventListener('animationend', () => { el.style.animation = ''; }, { once: true });
  }

  if (!document.getElementById('sl-keyframes')) {
    const style = document.createElement('style');
    style.id = 'sl-keyframes';
    style.textContent = `
      @keyframes shake {
        0%,100%{transform:translateX(0)}
        25%{transform:translateX(-4px)}
        75%{transform:translateX(4px)}
      }
    `;
    document.head.appendChild(style);
  }

  // Auto-load on page load
  loadEventData();
})();
