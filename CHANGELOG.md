# Changelog

## 0.2.0 — 2026-09-25 · Hackathon prototype → maintainable project

### Correctness
- **Driver verification redesigned.** Number Verification only proves which line *the requesting device* is on. It
  cannot tell who is calling the patient. Verification now runs on the **driver's own device** (driver link page).
  A successful check issues a one-time **meeting code** to both sides. Calls are judged by registry match plus a fresh
  attestation. A call from the driver's number without an attestation is flagged as a possible caller-ID spoof (`unverified`).
- **Driver device check uses Number Verification's 3-legged OIDC flow.** The driver page redirects the phone to the
  operator (`/v1/driver/{token}/nv/start`). The operator recognises the line over mobile data and returns a code, which the
  server exchanges for a device token (`/driver/nv/callback`). State is single-use (10 min). The simulator serves the same
  `/.well-known/openid-configuration`, `oauth2/v1/auth/clientcredentials`, authorize and token endpoints.
- **Nokia device-status subscriptions accept exactly one event type** (live 422, 09.09.2026). Every type now gets its
  own subscription: roaming-on, roaming-change-country, reachability-disconnected, reachability-data, plus 3 geofences.
  The simulator enforces the same rule.
- **Consent Info `purpose` must be a DPV term** (`dpv:ServiceProvision`; live 422), and `requestCaptureUrl` is required
  (live 422, 27.09.2026; sent as `false`). The simulator enforces both.
- **Time-based rules actually run.** A background scheduler ticks open cases. Scheduler ticks are only written to the
  audit when something changes. A persisting problem re-wakes the coordinator after `AG_REESCALATE_AFTER_MIN` at the earliest (budgeted).
- **Missing arrival signal.** When the arrival window closes without a roaming event, the scheduler polls roaming once and
  warns the coordinator. The coordinator can confirm the arrival manually.
- **`roaming-on` without `countryCode`** is completed by an on-demand roaming query.
- **Known road closures lower journey-alarm confidence** (`AG_DISRUPTION_DISCOUNT`). Night hours appear in `explain[]`.
  The medium confidence (0.6) is now configurable.
- A genuine driver call on a **SIM-swap-frozen** case no longer counts as first contact. The meeting code is not sent to a suspicious line.
- An unknown reachability result (network error) no longer counts as "unreachable".
- Nokia `subscription-ends` while a case is active now raises an "izleme boşluğu" warning.
- Circuit breaker half-open state now admits a single trial call.
- Cases expire `AG_CASE_MAX_HOURS` after the destination ETA.

### Product
- **Consent flow.** Cases start in `pending_consent`. The patient gets a TR/EN/AR consent page, can accept or decline,
  and can withdraw at any time. Subscriptions exist only after consent and are deleted on withdrawal.
- **Coordinator console** (`/console`): case list, alerts with acknowledgement, manual release (reason required),
  arrival confirmation, driver reassignment, road-closure report, notes, closure, new-case form.
- **Clinic registry** with drivers and zones (`/v1/clinics`), seeded from `fixtures/clinics.json`.
- **Notifications:** outbox with retry. Channels: `log`, HMAC-signed `webhook`, `twilio`.
- **Persistence:** SQLite store (cases, subscription index, CloudEvent de-dupe, clinics). Memory store for dev/tests.
- **Optional LLM case summary** (Claude, `LLM_PROVIDER=anthropic`). It never makes decisions and only sees pseudonymised text.
  If the SDK is missing, the call fails or the request is refused, it falls back to the rule notes.
- Two new demo scenarios: `no-signal`, `consent`.
- Live probe CLI `arrivalguard-probe` (subscriptions are created and deleted again).

### Security & privacy
- API-key authentication with per-clinic tenant isolation. The admin key is `*`.
- `APP_ENV=prod` refuses insecure configuration. Demo, debug and manual-event endpoints are off by default in prod.
- Constant-time webhook token check. Security headers and CSP on all pages.
- Raw phone numbers are erased when a case ends. Meeting codes and link tokens are masked in every API view.
  Retention purge runs after `AG_RETENTION_DAYS`. Debug endpoints mask all numbers.

### Engineering
- `src/` package layout (`arrivalguard`), `pyproject.toml`, `uvicorn --factory`, no `sys.path` hacks.
- GitHub Actions: ruff + pytest on 3.11/3.12/3.13, Docker build smoke test. Dockerfile runs as non-root. docker-compose starts API + simulator.
- Tests: 59 → 134.

## 0.1.0 — 2026-08-17 · Hackathon prototype
- Event-driven case machine, 6 pure rules with `explain[]`, 5 one-click demos, fixture/simulator/live NaC client, 59 tests.
