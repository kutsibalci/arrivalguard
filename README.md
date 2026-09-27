# ArrivalGuard

**Arrival protection for medical tourists, driven by mobile-network signals — without location history.**

[![ci](https://github.com/kutsibalci/arrivalguard/actions/workflows/ci.yml/badge.svg)](https://github.com/kutsibalci/arrivalguard/actions/workflows/ci.yml)
· Python 3.11+ · FastAPI · Nokia Network as Code (CAMARA) · MIT · [Türkçe](README.tr.md)

> *Same signal, opposite meaning.*
> A patient who goes silent **before** meeting their driver is an alarm. The same silence **after** first contact
> is almost always a local SIM card. ArrivalGuard is an event-driven case agent that knows the difference.

## Status at a glance

| | |
|---|---|
| ✅ **Built** | Full case agent, API, coordinator console, consent page (TR/EN/AR), driver verification page, local Nokia simulator, Docker, CI. 152 tests, 90% coverage |
| ✅ **Verified on the live Nokia API** (27.09.2026) | Network queries, consent check, subscriptions, and **a full case driven only by live Nokia events**: arrival → SIM-swap gate → reachability → airport, corridor and clinic areas → case closed |
| ⏸ **Where we stopped** | Two checks need more than Nokia's free *Simulator* plan offers: **driver verification on a real phone** (needs a real SIM on a supported operator network) and **journey logic with a real moving device** (Nokia's simulated area events do not reflect a real position) |

Details: [Project status](#project-status).

---

## The problem

A medical-tourism patient lands in a foreign country: foreign network, foreign language, a driver they have never met.
The clinic only knows a flight number. Airports have an ecosystem aimed at exactly this moment: fake "clinic drivers",
unlicensed taxis and scam messages. Today's defence is a printed name sign, and anyone can print one.

Turkey alone served 1.5M+ foreign patients in 2024 (USHAŞ). Since April 2025, licensed intermediaries must run a
24/7 multilingual call centre ([sources](docs/sources.md)). ArrivalGuard is a tool for that operation.

## How it works

The mobile network already knows the moment the patient becomes reachable in the country. ArrivalGuard listens to
events instead of tracking position:

| Stage | Network signal (CAMARA) | Decision |
|---|---|---|
| Consent | Consent Info + patient's explicit opt-in | No consent → no monitoring, no subscriptions |
| Landing | Device Roaming Status subscription (`roaming-on`) | Compared with the itinerary: **arrival or layover?** No driver details on a layover |
| Integrity gate | SIM Swap (24 h window) | Line changed hands recently → **pickup details withheld**, coordinator alerted |
| Driver | Number Verification on the **driver's own device** (3-legged OIDC) | Verified device → one-time **meeting code** to patient and driver |
| First call | Registry + fresh driver attestation | Unregistered caller → "do not answer"; driver's number without attestation → spoofing warning |
| Silence | Device Reachability subscription | **Before** first contact → alarm. **After** → de-escalate (local SIM) |
| Journey | Geofencing (corridor) + scheduler | Off-corridor + stationary + unreachable → confidence-scored escalation, with a budget |
| Closure | Geofencing (clinic) | Case closed, family informed in their language, subscriptions deleted, raw numbers erased |

Deciding when to stay quiet is the hard part. Every decision is a pure function that returns `explain[]`
(signal, value, weight, source). An escalation budget and a re-escalation interval keep the coordinator from getting alarm fatigue.

## Quick start

```bash
pip install -e ".[dev]"
pytest                                   # 152 tests
./run.sh simulator                       # Windows: $env:PYTHON="py"; .\run.ps1 -Mode simulator
```

| URL | What |
|---|---|
| http://127.0.0.1:8000/demo | One-click demo (7 scenarios) |
| http://127.0.0.1:8000/console | Coordinator console: cases, alerts, actions, new case form |
| http://127.0.0.1:8000/docs | OpenAPI |

`./run.sh fixture` runs fully in memory (no network). `docker compose up --build` starts API + simulator.
For the live Nokia API, see [docs/deployment.md](docs/deployment.md).

## Demo scenarios

| Button | Endpoint | Shows |
|---|---|---|
| Full chain | `POST /v1/demo/happy-path` | Layover → arrival → spoofed call warning → foreign device rejected → driver verified (meeting code) → impostor rejected → real driver → clinic → family message → cleanup |
| **Same signal, opposite meaning** | `POST /v1/demo/local-sim` | Two patients, identical `reachable=false`: one alarm, one de-escalation |
| SIM swapped on arrival | `POST /v1/demo/sim-swap` | Pickup details and meeting code withheld; driver's call is not counted as contact |
| Traffic or trouble? | `POST /v1/demo/trouble` | Confidence 25% → 60% → 85%, then the escalation budget runs out |
| Nokia API down | `POST /v1/demo/api-down` | Circuit breaker opens, flow continues, decisions flagged `error(server)` |
| Arrival signal missing | `POST /v1/demo/no-signal` | Scheduler polls roaming after the window, coordinator confirms arrival |
| Consent | `POST /v1/demo/consent` | No processing before consent; withdrawal deletes subscriptions and raw numbers |

Script for presenting: [docs/demo-script.md](docs/demo-script.md).

## Architecture

```
src/arrivalguard/
  nac_client/   single gateway to Nokia NaC: auth, timeout, retry, circuit breaker, masking,
                Number Verification OIDC flow; fixture | simulator | live
  rules/        pure decision functions → Decision(explain[]); all thresholds in config (AG_* env)
  agent/        deterministic case state machine, TR/EN/AR message templates, optional LLM summary
  api/          FastAPI app: cases, webhooks, consent & driver links, coordinator actions, scheduler,
                notifications (log | signed webhook | Twilio), storage (memory | SQLite), API-key tenancy
  simulator/    local Nokia mock with the real paths, OIDC endpoints and CloudEvents delivery
  tools/        arrivalguard-probe: tests every Nokia API we use and writes a masked report
  web/          demo, coordinator console, consent page, driver page (vanilla HTML/JS, no CDN)
```

State machine: `pending_consent → waiting → arrived → frozen | released → contacted → in_transit → closed`,
with `escalated` from any active state and the terminal states `expired | declined | withdrawn`.
Details: [docs/architecture.md](docs/architecture.md).

## Privacy by design

- **No location history.** Area events only (`stored_locations_count: 0`). Location *Verification* (a TRUE/FALSE
  verdict at pickup), never Location Retrieval.
- **Consent first.** Nothing is processed and no subscription exists until the patient agrees. Withdrawal takes
  effect immediately.
- **No raw phone numbers** in any response, log or audit: masked (`+44770***0001`) + HMAC-SHA256 hash. Raw numbers
  are erased once a case ends. Meeting codes and link tokens are masked, even in the coordinator view.
- **Retention:** closed cases are deleted after 30 days (configurable).

See [docs/privacy.md](docs/privacy.md).

## Project status

### How we got here

1. **August 2026 — hackathon idea and prototype.** Built for MENA Ignite Hackathon 2026 (GSMA × Nokia). A working
   prototype with 59 tests, running against fixtures.
2. **25.09.2026 — rebuilt as a maintainable project (v0.2.0).** Package layout, consent flow, coordinator console,
   persistence, scheduler, notification channels, per-clinic API keys, production config guard, CI and Docker.
   Driver verification was redesigned around what Number Verification can actually prove.
3. **27.09.2026 — driver OIDC flow and live verification.** The driver page now gets its device token through
   Number Verification's 3-legged OIDC flow. Then everything that the free plan allows was tested against the live Nokia API.

### Verified on the live Nokia API

Nokia Network as Code, free *Simulator* plan, simulated device `+99999991000`. Reports: [`docs/live-probe/`](docs/live-probe/).

| Capability | Result |
|---|---|
| Roaming status, reachability status (instant queries) | ✅ 200 |
| SIM Swap check and date | ✅ 200 |
| Location Verification (meeting point verdict) | ✅ 200 |
| Consent Info (operator-side consent check) | ✅ 200 |
| Number Verification OIDC discovery (the driver page's redirect to the operator) | ✅ 200 |
| All 7 subscriptions a case opens (2 roaming, 2 reachability, 3 geofence) | ✅ ACTIVE |
| **Event delivery:** Nokia → public HTTPS tunnel → `/webhooks/*` with the sink Bearer token → case agent | ✅ roaming, reachability and geofence (area-entered) events delivered and processed |
| **End-to-end case on live events:** roaming-on (Hungary) → arrival → SIM Swap gate withheld pickup (Nokia reports a recent SIM change for this device) → reachability → airport, corridor, clinic → case closed | ✅ every decision matched the rules |
| Cleanup: every subscription deleted when the case ends | ✅ no leftovers |

Live testing found bugs that neither the simulator nor the unit tests could have shown. All are fixed, each has a regression
test, and the simulator now enforces Nokia's rules:

- Device-status subscriptions accept exactly **one event type** each (422).
- Consent Info needs a W3C DPV `purpose` and the `requestCaptureUrl` field (422).
- The webhook credential needs an **expiry** (`accessTokenExpiresUtc`); without it Nokia rejected every subscription (422).
- **Country codes differ between Nokia's own endpoints.** The instant roaming query returns the phone calling code
  (Hungary = 36), but roaming events carry the mobile country code (Hungary = 216). A real arrival was read as
  "unexpected country". The country is now taken from the ISO code (`countryName: ["HU"]`) that both carry.
- **In-flight silence raised alarms.** A patient's phone is off during the flight, but "unreachable" before arrival counted as
  "vanished before first contact" and escalated after 5 minutes. Silence before arrival is now expected and the timer starts at landing.
- `subscription-ends` events for deleted cases were answered with 404, which invites retries; they are now acknowledged.

### Where we stopped, and why

The code for both remaining checks is written and tested locally. What is missing is access that the free plan does not give.

| Not yet verified | Why we stopped | What would unblock it |
|---|---|---|
| **Journey logic with a real moving device** (off-corridor, stationary, "traffic or trouble?") | Geofence events are delivered live, but they are synthetic: Nokia sent "entered" for our Istanbul areas while the simulated device sits in Budapest. That proves delivery and handling, not that journey decisions are right for a patient who is really moving. | A real SIM on a network Nokia supports, travelling a real route |
| **Driver verification on a real phone** | Number Verification recognises the line through the phone's own mobile-data session. The free plan covers only simulated numbers, so the full redirect → code → token → verify chain cannot run on a real handset. The server side (OIDC discovery) already works live. | A real SIM on a supported operator network, beyond the free plan |

### What it would take to go to production

This is a working, tested prototype, not a certified medical or safety system. Before real patients:

- Operator access beyond the free plan (see above) and a registered OIDC redirect URI.
- A real notification provider (`NOTIFY_CHANNEL=webhook` or `twilio`); the default only logs messages.
- A legal review of the consent text and data processing (KVKK / GDPR).
- A single-node deployment behind TLS with rate limiting. The scheduler is single-process and SQLite suits one node.

Full history: [CHANGELOG.md](CHANGELOG.md) · API-by-API results: [docs/api-availability.md](docs/api-availability.md).

## Documentation

[Architecture](docs/architecture.md) · [API availability & live results](docs/api-availability.md) ·
[Live feasibility](docs/live-feasibility.md) · [Deployment](docs/deployment.md) · [Privacy](docs/privacy.md) ·
[Concept (TR, non-technical)](docs/concept.tr.md) · [Sources](docs/sources.md) · [Contributing](CONTRIBUTING.md) ·
[Security](SECURITY.md)

Originally built for **MENA Ignite Hackathon 2026** (GSMA × Nokia), Theme 3: Tourism, Pilgrimage & Cultural Experience.

## License

[MIT](LICENSE)
