# I-RICE Exhibition Portal

A responsive Flask application for the **Project Exhibition Booth Registration and Participant Verification Management System** described in the Chapter One proposal. Built for Southern University College's I-RICE event with Flask, MySQL, SQLAlchemy, Bootstrap 5, and html5-qrcode.

## What works

- **Exhibitors:** register, manage a team, submit a project abstract/category/poster/booth requirements, track review comments and booth allocation, and download an admission pass and booth certificate.
- **Attendees and evaluators:** register for complimentary admission, receive organizer approval, and access their own digital ticket. Evaluator registration grants no organizer privileges.
- **Organizers:** review and reopen applications, allocate category-compatible booths, add categories and booths, approve attendee registrations, view dashboard metrics/activity, export CSV reports, and check in registered people through camera scanning or manual QR token entry.
- **Verification:** short-lived signed live QR codes, expiring PDF passes, immediate approval-revocation checks, and exactly one attendance record per registered person.

## Setup with MySQL (recommended)

Requirements: Python 3.12+ and Docker. Run from the existing checkout; a separate Git worktree is unnecessary.

```bash
cd /workspace/FYP
bash scripts/setup.sh
bash scripts/mysql.sh
.venv/bin/python -m flask --app irice init-db
.venv/bin/python -m flask --app irice create-admin
bash scripts/run.sh
```

`create-admin` prompts for an organizer name, email, and password. There is no default administrator password and public registration cannot create an organizer. The web server uses port 5000 by default. Use `IRICE_PORT` and `IRICE_HOST` to change the development listener.

The local MySQL script generates unique credentials in ignored `instance/mysql.env` and `instance/.env`, binds MySQL only to `127.0.0.1:3307`, and persists database files in `instance/mysql-data`. Keep those files together when backing up the local development database. The script starts an existing `irice-mysql` container on subsequent runs. Stop it with `docker stop irice-mysql`; do not delete its data directory to restart it.

`init-db` is repeatable: it creates missing tables and adds missing default categories/booths without erasing submissions. It is an initial schema creator, not a migration tool for future schema changes.

For an existing MySQL service, create a UTF-8 database, put a URL-encoded `DATABASE_URL` and a random `SECRET_KEY` in `instance/.env` using `.env.example` as a guide, and skip `scripts/mysql.sh`. Environment variables override that file. Never commit credentials.

## SQLite quickstart

For a lightweight local demo without Docker:

```bash
bash scripts/setup.sh
DATABASE_URL=sqlite:///irice.db .venv/bin/python -m flask --app irice init-db
DATABASE_URL=sqlite:///irice.db .venv/bin/python -m flask --app irice create-admin
DATABASE_URL=sqlite:///irice.db bash scripts/run.sh
```

SQLite supports the main development workflow. MySQL is the proposal's intended database and is used for the database integration and concurrent booth allocation tests.

Optional fictional projects for demonstration:

```bash
.venv/bin/python -m flask --app irice seed-demo
```

These teams are marked `[DEMO]`. Their passwords are random and undisclosed; they are not login accounts for a demonstration. Create your own participant through registration. This command does not run automatically during setup.

## Try the complete workflow

1. Register an exhibitor, complete the team profile, and submit a project. Posters accept valid PNG/JPEG images under the 8 MB request limit.
2. In a separate browser session, sign in as an organizer and open **Applications**. Review the abstract/poster, approve the application, and assign an available booth.
3. Return to the exhibitor's dashboard and **My digital pass**. Display the live QR or download the 24-hour admission PDF. A booth certificate becomes available once a booth is allocated.
4. Open **Event check-in** as an organizer. Scan the pass with a camera, or paste its signed token into the manual field. The first scan records attendance; repeats show the original check-in without increasing the count.
5. Check dashboard totals and download the CSV report. Reopen/reject an approved application to revoke its passes and release its booth; the participant can revise and resubmit.

Team members listed in a team profile are informational. An admission pass is for the **named registered account**, and each additional attendee needs their own approved registration. Attendance metrics count registered people, while submission and booth metrics count projects.

## Run tests

```bash
.venv/bin/python -m pytest -q           # isolated temporary SQLite databases
bash scripts/test-mysql.sh             # isolated irice_test MySQL database
```

Tests cover registration, role/ownership boundaries, CSRF, poster validation, reviews/resubmission, booth allocation/reassignment, signed QR tampering/expiry/revocation, PDF generation, CSV export, and repeat/concurrent check-ins. The MySQL run additionally exercises simultaneous booth allocation requests. Test databases are recreated; `IRICE_TEST_DATABASE_URL` must point to a disposable database with a name ending in `_test`. The application database is not a test target.

## Runtime and security notes

- Camera access requires HTTPS or browser-trusted localhost and explicit camera permission. The manual token field uses the same authenticated server validation. Physical mobile camera behavior should be checked on the event's devices.
- Live tokens expire after 180 seconds and refresh on the pass page. PDF tokens expire after 24 hours; issue a fresh PDF for a later day. Both require current approval and are invalidated by revocation.
- All state changes use POST with CSRF protection. Passwords are hashed, organizer routes enforce roles, poster downloads enforce ownership, and uploaded images are decoded/re-encoded with generated filenames.
- Keep the secret key stable across workers and restarts. Changing it invalidates sessions and passes. When no environment key is configured, a local random key is retained at `instance/secret.key`.
- For deployment, use a production WSGI server and HTTPS, set `COOKIE_SECURE=1`, configure backups and appropriate account recovery/rate limiting, and restrict database access. `scripts/run.sh` is a development server.
- This is a single-event academic prototype. No native app, offline verification, live payment gateway, password-recovery email service, or judging/scoring module is included. Admission is complimentary; registration plus approval is the ticket reservation. No payments are collected or simulated charges presented as real transactions.

See [architecture and workflow](docs/architecture.md) for the model and verification design.
