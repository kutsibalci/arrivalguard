# ArrivalGuard

**Arrival protection for medical tourists, driven by mobile-network signals — without location history.**

[![ci](https://github.com/kutsibalci/arrivalguard/actions/workflows/ci.yml/badge.svg)](https://github.com/kutsibalci/arrivalguard/actions/workflows/ci.yml)
· Python 3.11+ · FastAPI · Nokia Network as Code (CAMARA) · MIT · [Türkçe](README.tr.md)

> *Same signal, opposite meaning.*
> A patient who goes silent **before** meeting their driver is an alarm. The same silence **after** first contact
> is almost always a local SIM card. ArrivalGuard is an event-driven case agent that knows the difference.

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
| Driver | Number Verification on the **driver's own device** | Verified device → one-time **meeting code** to patient and driver |
| First call | Registry + fresh driver attestation | Unregistered caller → "do not answer"; driver's number without attestation → spoofing warning |
| Silence | Device Reachability subscription | **Before** first contact → alarm. **After** → de-escalate (local SIM) |
| Journey | Geofencing (corridor) + scheduler | Off-corridor + stationary + unreachable → confidence-scored escalation, with a budget |
| Closure | Geofencing (clinic) | Case closed, family informed in their language, subscriptions deleted, raw numbers erased |

Deciding when to stay quiet is the hard part. Every decision is a pure function that returns `explain[]`
(signal, value, weight, source). An escalation budget and a re-escalation interval keep the coordinator from getting alarm fatigue.

## Quick start

```bash
pip install -e ".[dev]"
pytest                                   # 134 tests
./run.sh simulator                       # Windows: .\run.ps1 -Mode simulator
```

| URL | What |
|---|---|
| http://127.0.0.1:8000/demo | One-click jury demo (7 scenarios) |
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
  nac_client/   single gateway to Nokia NaC: auth, timeout, retry, circuit breaker, masking; fixture | simulator | live
  rules/        pure decision functions → Decision(explain[]); all thresholds in config (AG_* env)
  agent/        deterministic case state machine, TR/EN/AR message templates, optional LLM summary
  api/          FastAPI app: cases, webhooks, consent & driver links, coordinator actions, scheduler,
                notifications (log | signed webhook | Twilio), storage (memory | SQLite), API-key tenancy
  simulator/    local Nokia mock with the real paths and CloudEvents delivery
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

## Status and known limits

This is a working prototype that passes its own tests. It is not a certified production system. Main gaps:
- **Driver OIDC flow (live):** the driver page runs Number Verification's 3-legged OIDC flow (operator redirect →
  code → device token). It is tested against the simulator and a mocked Nokia, but not yet on a real phone on mobile data.
- **Live event delivery:** geofencing events are not produced for Nokia's static simulated devices, and live
  roaming/reachability webhooks need a public HTTPS sink. Both are unverified end to end.
- **Single process:** one scheduler per deployment. SQLite suits a single node, not horizontal scaling.

Full list: [CHANGELOG.md](CHANGELOG.md) and [docs/api-availability.md](docs/api-availability.md).

## Documentation

[Architecture](docs/architecture.md) · [API availability & live results](docs/api-availability.md) ·
[Live feasibility](docs/live-feasibility.md) · [Deployment](docs/deployment.md) · [Privacy](docs/privacy.md) ·
[Concept (TR, non-technical)](docs/concept.tr.md) · [Sources](docs/sources.md) · [Contributing](CONTRIBUTING.md) ·
[Security](SECURITY.md)

Originally built for **MENA Ignite Hackathon 2026** (GSMA × Nokia), Theme 3: Tourism, Pilgrimage & Cultural Experience.

## License

[MIT](LICENSE)
