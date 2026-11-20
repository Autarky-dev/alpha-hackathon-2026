# SeatLock — Frontend Preview

SeatLock is a server-rendered HTML/CSS/vanilla-JavaScript frontend for an event seat-booking application. FastAPI + Jinja2 are used only to preview the pages with sample data.

## Included pages

- `/` and `/events` — event discovery, search, category filter and sort
- `/login` — sign-in form presentation (authentication is not implemented)
- `/events/{event_id}/seats` — seat selection, visual hold countdown and release UI
- `/bookings` — booking list and status tabs
- `/organizer` — organizer dashboard preview
- `/admin` — admin dashboard preview

## Project structure

```text
seatlock-frontend/
├── templates/
│   ├── base.html
│   ├── login.html
│   ├── events.html
│   ├── seat_map.html
│   ├── my_bookings.html
│   ├── organizer_dashboard.html
│   └── admin_dashboard.html
├── static/
│   ├── css/
│   │   ├── style.css
│   │   ├── login.css
│   │   ├── events.css
│   │   ├── seat_map.css
│   │   ├── bookings.css
│   │   └── dashboard.css
│   ├── js/
│   │   ├── main.js
│   │   ├── events.js
│   │   ├── seat_map.js
│   │   ├── bookings.js
│   │   ├── organizer.js
│   │   └── admin.js
│   └── images/
├── preview.py
├── requirements.txt
├── .gitignore
└── README.md
```

## Run on Windows

Open PowerShell or the VS Code terminal in this folder:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
py -m uvicorn preview:app --reload --port 8000
```

If PowerShell blocks virtual-environment activation, run the install and server commands using `py -m pip ...` and `py -m uvicorn ...` without activating it.

Open **http://127.0.0.1:8000** in your browser. Stop the server with `Ctrl+C`.

## Important: preview vs. production

This ZIP is a **frontend foundation and visual preview**, not a complete booking backend. Sample event/booking/dashboard data is hard-coded in templates. The seat hold countdown is a browser-side demonstration only; it does not reserve seats for other users and it does not prevent two users from selecting the same seat.

Before production or a real-time hackathon demo, connect these UI actions to backend services:

1. Authentication and session management; validate credentials server-side.
2. Database models and migrations for users, events, venues, seat inventory, holds and bookings.
3. Atomic seat-hold creation with expiry (Redis or a database transaction/locking strategy).
4. Server-side availability refresh (WebSocket or polling) and conflict handling.
5. Booking confirmation/payment workflow and booking-reference generation.
6. Organizer event CRUD, attendee export and check-in API.
7. Admin user/event management with role-based authorization and audit logging.
8. CSRF protection, input validation, rate limiting, secure cookies and production error handling.

Do not use the preview login or visual seat-hold timer as real security or reservation logic.
