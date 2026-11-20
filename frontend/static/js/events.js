/**
 * SeatLock — events.js
 * Live event catalog fetching, real-time seat availability calculation,
 * and client-side filtering/sorting.
 */
(function () {
  'use strict';

  const searchInput = document.getElementById('event-search');
  const selects = document.querySelectorAll('.events-filter-select');
  const categorySelect = selects[0] || null;
  const sortSelect = selects[1] || null;
  const grid = document.querySelector('.events-grid');
  const metaCount = document.querySelector('.events-meta strong');

  if (!grid) return;

  let loadedEvents = [];

  function formatDateTime(isoStr) {
    if (!isoStr) return { date: 'TBA', time: '' };
    const d = new Date(isoStr);
    return {
      date: d.toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' }),
      time: d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }),
    };
  }

  function getCardDate(event) {
    const parsed = Date.parse(event.start_time);
    return Number.isNaN(parsed) ? 0 : parsed;
  }

  function renderCard(event) {
    const dt = formatDateTime(event.start_time);
    const total = event.total_seats || 0;
    const avail = typeof event.available_seats === 'number' ? event.available_seats : total;
    const pct = total > 0 ? Math.round(((total - avail) / total) * 100) : 100;
    const isSoldOut = avail === 0;
    const isAlmostFull = avail > 0 && avail < Math.max(5, Math.round(total * 0.15));

    let availBadge = '';
    if (isSoldOut) {
      availBadge = '<span class="badge badge--danger">Sold out</span>';
    } else if (isAlmostFull) {
      availBadge = '<span class="badge badge--warning badge--dot">Almost full</span>';
    } else {
      availBadge = '<span class="badge badge--success badge--dot">Available</span>';
    }

    const card = document.createElement('article');
    card.className = 'event-card card card--interactive';
    card.dataset.eventId = event.id;
    card.dataset.eventDate = event.start_time;
    card.dataset.availableSeats = avail;

    card.innerHTML = `
      <div class="event-card__visual" style="background-color: #1a162b;" aria-hidden="true">
        <span class="event-card__category badge badge--accent">${event.category || 'Tech & Event'}</span>
        ${isSoldOut ? '<span class="event-card__sold-out-banner">Sold out</span>' : ''}
        ${isAlmostFull ? `<span class="event-card__urgency">${avail} left</span>` : ''}
      </div>

      <div class="card__body event-card__body">
        <h2 class="event-card__title">${escapeHtml(event.title)}</h2>

        <div class="event-card__meta">
          <div class="event-card__meta-row">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <rect width="18" height="18" x="3" y="4" rx="2" ry="2"/>
              <line x1="16" x2="16" y1="2" y2="6"/>
              <line x1="8" x2="8" y1="2" y2="6"/>
              <line x1="3" x2="21" y1="10" y2="10"/>
            </svg>
            <span>${dt.date} · ${dt.time}</span>
          </div>
          <div class="event-card__meta-row">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z"/>
              <circle cx="12" cy="10" r="3"/>
            </svg>
            <span>${escapeHtml(event.location || 'Venue TBA')}</span>
          </div>
        </div>

        <div class="event-card__availability">
          <div class="event-card__avail-label">
            <span class="text-xs text-muted">${avail} of ${total} remaining</span>
            ${availBadge}
          </div>
          <div class="avail-bar" role="progressbar" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100">
            <div class="avail-bar__fill ${pct >= 95 ? 'avail-bar__fill--danger' : pct >= 75 ? 'avail-bar__fill--warning' : ''}" style="width: ${Math.min(pct, 100)}%;"></div>
          </div>
        </div>
      </div>

      <div class="card__footer event-card__footer">
        ${isSoldOut ? `
          <button class="btn btn-secondary btn-sm" disabled>Sold Out</button>
        ` : `
          <a href="/events/${event.id}/seats" class="btn btn-primary btn-sm">
            Select seats
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M5 12h14M12 5l7 7-7 7"/>
            </svg>
          </a>
        `}
      </div>
    `;

    return card;
  }

  function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function renderEvents(eventsToDisplay) {
    grid.innerHTML = '';
    if (!eventsToDisplay || eventsToDisplay.length === 0) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1; padding: var(--space-12) 0;">
          <div class="empty-state__icon">🎟️</div>
          <h2 class="empty-state__title">No events found</h2>
          <p class="empty-state__text">Try adjusting your search criteria or check back soon.</p>
        </div>
      `;
      if (metaCount) metaCount.textContent = '0';
      return;
    }

    eventsToDisplay.forEach((evt) => {
      grid.appendChild(renderCard(evt));
    });

    if (metaCount) metaCount.textContent = String(eventsToDisplay.length);
  }

  function applyFilters() {
    const query = searchInput ? searchInput.value.trim().toLowerCase() : '';
    const category = categorySelect ? categorySelect.value.trim().toLowerCase() : '';

    let filtered = loadedEvents.filter((event) => {
      const title = (event.title || '').toLowerCase();
      const loc = (event.location || '').toLowerCase();
      const cat = (event.category || '').toLowerCase();
      const matchesQuery = !query || title.includes(query) || loc.includes(query);
      const matchesCategory = !category || cat.includes(category);
      return matchesQuery && matchesCategory;
    });

    const sort = sortSelect ? sortSelect.value : 'date_asc';
    filtered.sort((a, b) => {
      if (sort === 'availability') return (b.available_seats || 0) - (a.available_seats || 0);
      const aDate = getCardDate(a);
      const bDate = getCardDate(b);
      return sort === 'date_desc' ? bDate - aDate : aDate - bDate;
    });

    renderEvents(filtered);
  }

  async function loadLiveEvents() {
    grid.innerHTML = `
      <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: var(--color-text-secondary);">
        <p>Loading active events from SeatLock backend...</p>
      </div>
    `;

    const res = await window.apiFetch('/events?limit=50');
    if (!res.ok || !res.data) {
      console.warn('Could not fetch events from backend, falling back to sample data:', res.error);
      return; // Leave template fallback
    }

    const eventsList = res.data;
    if (eventsList.length === 0) {
      renderEvents([]);
      return;
    }

    // Fetch live seat availability for each event concurrently
    const populated = await Promise.all(
      eventsList.map(async (evt) => {
        const seatRes = await window.apiFetch(`/events/${evt.id}/seats`);
        if (seatRes.ok && seatRes.data) {
          evt.available_seats = seatRes.data.available_count;
          evt.total_seats = seatRes.data.total_seats;
        } else {
          evt.available_seats = evt.total_seats;
        }
        return evt;
      })
    );

    loadedEvents = populated;
    applyFilters();
  }

  if (searchInput) searchInput.addEventListener('input', applyFilters);
  if (categorySelect) categorySelect.addEventListener('change', applyFilters);
  if (sortSelect) sortSelect.addEventListener('change', applyFilters);

  // Initialize
  loadLiveEvents();
})();
