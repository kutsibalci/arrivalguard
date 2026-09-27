# Contributing

## Setup

```bash
pip install -e ".[dev,llm]"
pytest                 # all tests, no network needed (NAC fixture mode)
ruff check src tests   # lint (CI runs both on Python 3.11–3.13)
```

## Design rules (please keep them)

1. **Nokia calls only through `arrivalguard.nac_client`.** Nothing else talks to Nokia over HTTP. In the API layer,
   calls go through `ctx.facade.call(...)`, which marks failures as `error(<kind>)` instead of inventing data.
2. **Every decision is a pure function** in `rules/decisions.py`: inputs plus `Config` in, `Decision(explain[])` out.
   No network, no clock (time is a parameter), no side effects. Add a unit test in `tests/test_rules.py`.
3. **No hard-coded thresholds.** New thresholds go in `rules/config.py`. They get an `AG_*` env override
   automatically, and each one needs a line in `.env.example`.
4. **The state machine is the only place that changes a case** (`agent/case_machine.py`). Side effects outside
   the case (subscriptions, notifications, PII purge, persistence) belong to `api/context.py`.
5. **Privacy invariants are tested.** No raw phone number, meeting code or link token may appear in `Case.to_dict()`,
   the audit report, logs or debug output. There are no location coordinates anywhere in a case.
6. **Endpoints must exist in the spec.** Do not assume an API that CAMARA/Nokia does not document. Simulator-only
   helpers live under `/_sim/*`.
7. Code comments and user-facing texts are Turkish (the project's working language). Patient messages exist in TR/EN/AR.
   A new template must be added in all three languages.

## Pull requests

- Keep the test suite green and lint clean.
- If you change behaviour, update the relevant document in `docs/` and add a line to `CHANGELOG.md`.
- Never commit `.env`, real phone numbers or API keys. Fixture numbers use fictional ranges
  (UK `07700 900xxx`, Nokia's `+999999910xx` simulated devices).
