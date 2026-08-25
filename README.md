# Solstice Events Co. — Event Check-In Kiosk Service

A Django + DRF + Celery/RabbitMQ + PostgreSQL service that lets kiosk staff
scan an attendee's QR code, asynchronously prints their badge, and checks
them in only once printing is confirmed.

## Day 4 Scope Delta

**Before (deprecated):**
```
QR Scan → Django → Synchronous Printer REST API → Wait → Success → Checked In
```
The kiosk made a blocking HTTP call to a printer vendor's REST API and held
the HTTP connection open until the printer replied. That API has been
**decommissioned** and is not used anywhere in this codebase — there is no
synchronous printer client, and no code path can reach it.

**Now (this build):**
```
QR Scan
  ↓
Django API (POST /api/checkin/scan/)
  ↓
Create PrintJob (status=QUEUED) + validate/lock attendee, all in one DB transaction
  ↓
On commit: publish badge.print.requested → RabbitMQ
  ↓
Django responds 202 Accepted immediately (attendee is PENDING) — kiosk UI polls, never blocks
  ↓
Printer Worker (separate process) consumes the RabbitMQ message
  ↓
Simulated badge printing (time delay + configurable failure rate)
  ↓
Worker POSTs badge.print.completed webhook to Django, signed with HMAC-SHA256
 ↓
Django verifies signature → looks up PrintJob by job_id → idempotency check by event_id  ↓
PrintJob → COMPLETED/FAILED, and only on COMPLETED does Attendee → CHECKED_IN
```

The kiosk **never waits on the printer**. It shows `PENDING` immediately
after scanning and polls `GET /api/checkin/<attendee_id>/` until the webhook
has moved the attendee to `CHECKED_IN` (or the job fails, in which case the
attendee is rolled back to `NOT_CHECKED_IN` so they can be rescanned).

## Architecture

```
solstice_checkin/
├── config/                 # Django project settings, URLs, Celery app definition
│   ├── settings.py
│   ├── celery.py           # Celery app bound to the RabbitMQ broker
│   └── urls.py
├── checkin/                 # Core domain app
│   ├── models.py            # Attendee, PrintJob, WebhookEvent
│   ├── serializers.py       # DRF serializers
│   ├── views.py              # ScanView, AttendeeStatusView, PrinterWebhookView
│   ├── services.py           # Business logic: scan_attendee(), process_print_completed_webhook()
│   ├── publisher.py          # The ONLY place that publishes to RabbitMQ
│   ├── tasks.py               # The printer worker (Celery consumer + webhook sender)
│   ├── security.py            # HMAC sign/verify helpers
│   ├── urls.py / webhook_urls.py
│   ├── management/commands/seed_attendees.py
│   └── tests/                 # Unit + end-to-end tests
├── kiosk/                    # Kiosk-facing UI (server-rendered page + vanilla JS)
│   ├── templates/kiosk/index.html
│   └── static/kiosk/{kiosk.js,kiosk.css}
├── requirements.txt
├── .env.example
├── Dockerfile
└── docker-compose.yml
```

Each concern is isolated on purpose:

* **`views.py`** only does HTTP request/response translation.
* **`services.py`** owns all business rules (validation, locking, state
  transitions) and is fully unit-testable without touching HTTP or Celery.
* **`publisher.py`** is the single choke point for outbound RabbitMQ traffic
  from the Django API process.
* **`tasks.py`** is the printer worker — it runs in its **own process**
  (`printer_worker` in docker-compose), consumes off RabbitMQ, and talks
  back to Django only over the signed HTTP webhook, exactly as an external
  printer vendor integration would.
* **`security.py`** centralizes the HMAC scheme so both the signer (worker)
  and verifier (Django view) share one implementation and can't drift.

## RabbitMQ Flow

RabbitMQ transport is implemented via **Celery**, using RabbitMQ as the
broker (`CELERY_BROKER_URL=amqp://...`). This gives a real AMQP queue you
can inspect in the RabbitMQ management UI (`http://localhost:15672`,
default `guest`/`guest`) while avoiding hand-rolled `pika` boilerplate:

* `checkin/publisher.py` calls `handle_print_requested.delay(message)`,
  which Celery serializes and publishes onto the
  `badge_print_requested` queue (`CELERY_TASK_DEFAULT_QUEUE` in
  `config/settings.py`).
* The `printer_worker` service runs:
  `celery -A config worker -Q badge_print_requested -l info`
  and is the sole consumer of that queue.
* If the worker crashes mid-message, Celery/RabbitMQ redelivers on restart
  (`acks_late`-style at-least-once delivery) — this is exactly why the
  webhook side is built to be idempotent (see below), since a retried
  message can result in the worker sending the completion webhook twice.

## Webhook Security (HMAC)

`POST /api/webhooks/printer/` is the only endpoint that can move an
attendee to `CHECKED_IN`, so it is authenticated with HMAC-SHA256:

```
signature = hex( HMAC_SHA256( PRINTER_WEBHOOK_SECRET, raw_request_body_bytes ) )
```

* The worker (`checkin/tasks.py::send_completion_webhook`) computes this
  signature over the **exact raw bytes** it sends, and puts it in the
  `X-Signature` header.
* The Django view (`PrinterWebhookView`) recomputes the signature over
  `request.body` (the raw bytes actually received) using
  `hmac.compare_digest` for constant-time comparison, **before** parsing
  the JSON or touching the database. An invalid or missing signature is
  rejected with `401` and no state changes ever happen.
* `PRINTER_WEBHOOK_SECRET` must be identical on both the `web` and
  `printer_worker` containers — it's supplied via `.env` and shared through
  `env_file:` in `docker-compose.yml`.

## Idempotency & Duplicate Protection

Three independent layers guard against duplicate badges / double check-ins:

1. **Scan-time locking (`services.scan_attendee`)** — runs inside
   `transaction.atomic()` with `select_for_update()` on both the `Attendee`
   and any existing active `PrintJob`. An attendee who is already
   `CHECKED_IN` is rejected (`already_checked_in`, 409). An attendee with an
   `QUEUED`/`PRINTING` job is rejected (`print_already_in_progress`, 409) —
   this is what makes "duplicate scan while pending" impossible even under
   concurrent kiosk requests.
2. **Database constraint** — `PrintJob` has a partial `UniqueConstraint` on
   `(attendee, status='QUEUED')`, so even a bug that bypassed the
   application-level lock would be rejected at the database level.
3. **Webhook idempotency (`services.process_print_completed_webhook`)** —
   every inbound webhook is first recorded in `WebhookEvent` keyed by the
   spec's `event_id`. If that `event_id` was already `processed=True`, the
   handler returns `duplicate_ignored` immediately without touching
   `PrintJob`/`Attendee` again — this handles at-least-once delivery
   retries from the worker cleanly.
4. **Out-of-order webhooks by `job_id`** — completion webhooks are looked up
   and applied strictly by `job_id`, not by assumed arrival order. Once a
   `PrintJob` reaches a terminal state (`COMPLETED` or `FAILED`), any
   further webhook for that `job_id` is recorded but produces a `no_op`
   result — it can never flip a finished job's state backwards or check in
   an attendee whose job already failed.
5. **Attendee → CHECKED_IN happens in exactly one place**: inside
   `process_print_completed_webhook`, only on a verified, successfully
   processed `status: "success"` webhook. Nothing else in the codebase sets
   that status.

## API

### `POST /api/checkin/scan/`
Staff scans an attendee's QR code.

Request:
```json
{ "qr_code": "QR-ADA-001" }
```

Response `202 Accepted` (printing is async — the kiosk does not block):
```json
{
  "attendee": { "id": "...", "name": "Ada Lovelace", "status": "PENDING", "...": "..." },
  "print_job": { "job_id": "...", "event_id": "...", "status": "QUEUED", "...": "..." }
}
```

Errors: `404 attendee_not_found`, `409 already_checked_in`,
`409 print_already_in_progress`.

### `GET /api/checkin/<attendee_id>/`
Polled by the kiosk UI while a badge prints.

```json
{ "id": "...", "name": "Ada Lovelace", "status": "CHECKED_IN", "qr_code": "...", "latest_print_job": { "...": "..." } }
```

### `POST /api/webhooks/printer/`
Called by the printer worker only. Requires header `X-Signature: <hmac-sha256-hex>`.

```json
{
  "event": "badge.print.completed",
  "event_id": "evt-789",
  "job_id": "job-456",
  "attendee_id": "attendee-001",
  "status": "success",
  "timestamp": "2026-08-21T12:00:00Z"
}
```

Response: `200` with `{"status": "checked_in" | "print_failed" | "duplicate_ignored" | "no_op_terminal_job", ...}`.
Errors: `401 invalid_signature`, `400 invalid_payload`, `404 unknown_job_id`,
`409 attendee_job_mismatch`.

## Setup

### With Docker (recommended)

```bash
cp .env.example .env
docker compose up --build
```

This starts PostgreSQL, RabbitMQ, the Django web app, and the `printer_worker` Celery consumer.

Seed the 3 demo attendees:
```bash
docker compose exec web python manage.py seed_attendees
```

Open the kiosk UI at `http://localhost:8000/` 

### Without Docker (local dev / running tests)

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
export TEST_SQLITE=1   # run against sqlite instead of Postgres
python manage.py test checkin -v 2
```

## Tests

`checkin/tests/` covers every item in the spec's required test list:

| File | Covers |
|---|---|
| `test_scan.py` | successful scan, invalid QR, print-job creation, duplicate scan while pending, duplicate scan after check-in |
| `test_publisher.py` | RabbitMQ publishing (Celery producer call) |
| `test_printer_worker.py` | simulated printing success/failure, webhook payload building & signing |
| `test_webhook.py` | successful webhook, failed printing, duplicate webhook, invalid signature, unknown job ID, attendee/job mismatch, out-of-order webhooks |
| `test_e2e.py` | full 3-attendee end-to-end flow (including a printer failure + rescan) plus the duplicate-scan case, wired together in-process |

Run everything:
```bash
TEST_SQLITE=1 python manage.py test checkin -v 2
```
(23 tests, all passing.)
