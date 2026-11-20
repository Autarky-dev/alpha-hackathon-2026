/**
 * SeatLock — bookings.js
 * Real-time fetching of user bookings, status filtering,
 * ticket QR code generation, and booking cancellation.
 */

(function () {
  'use strict';

  const tabs         = document.querySelectorAll('.bookings-tab');
  const bookingList  = document.getElementById('bookings-list');
  const modal        = document.getElementById('ticket-modal');
  const closeModalBtn= document.getElementById('close-ticket-modal');
  const qrContainer  = document.getElementById('ticket-qr-container');
  const modalTitle   = document.getElementById('modal-event-title');
  const modalRef     = document.getElementById('modal-booking-ref');
  const modalSeats   = document.getElementById('modal-seats');
  const modalStatus  = document.getElementById('modal-checkin-status');
  const modalToken   = document.getElementById('modal-ticket-token');
  const copyTokenBtn = document.getElementById('copy-token-btn');

  let loadedBookings = [];
  let currentFilter  = 'all';

  /* ── 1. Load Real Bookings from Backend API ───────────────────── */
  async function loadBookings() {
    if (!bookingList) return;

    bookingList.innerHTML = `
      <div style="padding: 40px; text-align: center; color: var(--color-text-secondary); width: 100%;">
        <p>Loading your reservations...</p>
      </div>
    `;

    const res = await window.apiFetch('/bookings/me');
    if (!res.ok || !res.data) {
      bookingList.innerHTML = `
        <div class="empty-state">
          <div class="empty-state__icon">🎟️</div>
          <h2 class="empty-state__title">Unable to load bookings</h2>
          <p class="empty-state__text">${res.error || 'Please sign in to view your reservations.'}</p>
          <a href="/login" class="btn btn-primary">Sign in</a>
        </div>
      `;
      return;
    }

    loadedBookings = res.data;
    renderBookings();
  }

  /* ── 2. Render Booking Cards ─────────────────────────────────── */
  function renderBookings() {
    bookingList.innerHTML = '';

    const filtered = loadedBookings.filter((b) => {
      if (currentFilter === 'all') return true;
      if (currentFilter === 'upcoming') return b.status === 'confirmed' && !b.checked_in_at;
      if (currentFilter === 'completed') return b.checked_in_at !== null;
      if (currentFilter === 'cancelled') return b.status === 'cancelled';
      return true;
    });

    if (filtered.length === 0) {
      bookingList.innerHTML = `
        <div class="empty-state" style="width: 100%; padding: 40px 0;">
          <div class="empty-state__icon">🎟️</div>
          <h2 class="empty-state__title">No bookings found</h2>
          <p class="empty-state__text">You have no reservations matching this filter.</p>
          <a href="/events" class="btn btn-primary" style="margin-top: 12px;">Browse events</a>
        </div>
      `;
      return;
    }

    filtered.forEach((b) => {
      const card = document.createElement('article');
      card.className = 'booking-card card';
      card.dataset.status = b.status;
      card.dataset.bookingId = b.id;

      const createdDate = new Date(b.created_at).toLocaleString(undefined, {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });

      let statusBadge = '';
      if (b.status === 'confirmed') {
        if (b.checked_in_at) {
          statusBadge = '<span class="badge badge--success">✓ Checked In</span>';
        } else {
          statusBadge = '<span class="badge badge--success badge--dot">Confirmed</span>';
        }
      } else if (b.status === 'cancelled') {
        statusBadge = '<span class="badge badge--danger">Cancelled</span>';
      }

      const seatsHtml = (b.seat_numbers || []).map((s) => `<span class="booking-seat-tag">${s}</span>`).join(' ');
      const shortRef = `SL-${b.id.slice(0, 8).toUpperCase()}`;

      card.innerHTML = `
        <div class="booking-card__inner">
          <div class="booking-card__info">
            <div class="booking-card__top">
              <span class="badge badge--accent">Event Pass</span>
              ${statusBadge}
            </div>

            <h2 class="booking-card__title">${escapeHtml(b.event_title || 'SeatLock Event')}</h2>

            <div class="booking-card__meta">
              <span class="booking-card__meta-item">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <rect width="18" height="18" x="3" y="4" rx="2"/><line x1="16" x2="16" y1="2" y2="6"/>
                  <line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/>
                </svg>
                ID: ${b.id.slice(0, 18)}...
              </span>
            </div>

            <div class="booking-card__seats">
              <span class="text-xs text-muted">Seats:&nbsp;</span>
              ${seatsHtml}
            </div>
          </div>

          <div class="booking-card__divider" aria-hidden="true"></div>

          <div class="booking-card__actions">
            <div class="booking-card__ref">
              <span class="text-xs text-muted">Booking ref</span>
              <code class="booking-card__ref-code">${shortRef}</code>
            </div>
            <div class="booking-card__booked-at">
              <span class="text-xs text-muted">Booked on</span>
              <span class="text-sm text-secondary">${createdDate}</span>
            </div>

            <div class="booking-card__cta">
              <button class="btn btn-secondary btn-sm view-ticket-btn" data-id="${b.id}" data-title="${escapeHtml(b.event_title || 'Event')}" data-seats="${(b.seat_numbers || []).join(', ')}" data-status="${b.checked_in_at ? 'Checked In' : 'Valid'}">
                View ticket
              </button>
              ${b.status === 'confirmed' ? `
                <button class="btn btn-danger btn-sm cancel-booking-btn" data-id="${b.id}">
                  Cancel
                </button>
              ` : ''}
            </div>
          </div>
        </div>
      `;

      bookingList.appendChild(card);
    });
  }

  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /* ── 3. Tabs Filtering ───────────────────────────────────────── */
  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((t) => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');

      currentFilter = tab.dataset.filter || 'all';
      renderBookings();
    });
  });

  /* ── 4. Card Click Delegation (Ticket Modal & Cancellation) ──── */
  bookingList && bookingList.addEventListener('click', async (e) => {
    // View Ticket Click
    const ticketBtn = e.target.closest('.view-ticket-btn');
    if (ticketBtn) {
      const bookingId = ticketBtn.dataset.id;
      const title = ticketBtn.dataset.title;
      const seats = ticketBtn.dataset.seats;
      const statusText = ticketBtn.dataset.status;

      ticketBtn.disabled = true;
      ticketBtn.textContent = 'Loading...';

      const res = await window.apiFetch(`/bookings/${bookingId}/ticket`);
      ticketBtn.disabled = false;
      ticketBtn.textContent = 'View ticket';

      if (res.ok && res.data) {
        openTicketModal(res.data.booking_id, res.data.ticket_token, title, seats, statusText);
      } else {
        window.showNotification(res.error || 'Failed to retrieve ticket token.', 'error');
      }
      return;
    }

    // Cancel Click
    const cancelBtn = e.target.closest('.cancel-booking-btn');
    if (cancelBtn) {
      const bookingId = cancelBtn.dataset.id;
      if (!confirm('Are you sure you want to cancel this booking? All held seats will be released back to the event.')) {
        return;
      }

      cancelBtn.disabled = true;
      cancelBtn.textContent = 'Cancelling...';

      const res = await window.apiFetch(`/bookings/${bookingId}/cancel`, { method: 'POST' });
      if (res.ok) {
        window.showNotification('Booking successfully cancelled and seats released.', 'success');
        await loadBookings();
      } else {
        cancelBtn.disabled = false;
        cancelBtn.textContent = 'Cancel';
        window.showNotification(res.error || 'Could not cancel booking.', 'error');
      }
    }
  });

  /* ── 5. Modal Display & QR Code Rendering ────────────────────── */
  function openTicketModal(bookingId, ticketToken, title, seats, statusText) {
    if (!modal) return;

    modalTitle.textContent = title;
    modalRef.textContent = `Booking ID: ${bookingId}`;
    modalSeats.textContent = seats;
    modalStatus.textContent = statusText;
    modalStatus.className = statusText === 'Checked In' ? 'badge badge--default' : 'badge badge--success';
    modalToken.value = ticketToken;

    // Render QR Code
    qrContainer.innerHTML = '';
    if (typeof QRCode !== 'undefined') {
      new QRCode(qrContainer, {
        text: ticketToken,
        width: 180,
        height: 180,
        colorDark: '#0f172a',
        colorLight: '#ffffff',
        correctLevel: QRCode.CorrectLevel.M,
      });
    } else {
      qrContainer.innerHTML = '<p class="text-xs text-muted" style="padding: 20px;">[QR Display Ready]</p>';
    }

    modal.style.display = 'flex';
  }

  closeModalBtn && closeModalBtn.addEventListener('click', () => {
    if (modal) modal.style.display = 'none';
  });

  modal && modal.addEventListener('click', (e) => {
    if (e.target === modal) modal.style.display = 'none';
  });

  copyTokenBtn && copyTokenBtn.addEventListener('click', () => {
    modalToken.select();
    navigator.clipboard.writeText(modalToken.value).then(() => {
      window.showNotification('Ticket token copied to clipboard!', 'success');
    }).catch(() => {
      window.showNotification('Token selected. Copy with Ctrl+C.', 'info');
    });
  });

  // Load bookings on init
  loadBookings();
})();
