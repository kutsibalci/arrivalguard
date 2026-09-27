# Security policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
[private vulnerability reporting](https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability)
on this repository. Include the steps to reproduce and the affected version. You should get an acknowledgement within 7 days.

## Security model (summary)

| Surface | Protection |
|---|---|
| `/v1/*` API | `X-API-Key` per clinic (tenant isolation; other clinics' cases return 404) or `*` admin key |
| CAMARA webhooks | `Authorization: Bearer <WEBHOOK_TOKEN>` (sinkCredential), constant-time comparison, CloudEvent id de-duplication |
| Consent / driver pages | Unguessable per-case tokens (`secrets.token_urlsafe(24)`), stored hashed in the index column, erased when the case ends |
| Demo / debug / manual event feed | Disabled by default when `APP_ENV=prod` |
| Startup | With `APP_ENV=prod`, the app **refuses to start** with a default hash salt, a weak webhook token, no API keys, non-HTTPS public URL, in-memory storage or log-only notifications |
| Browser pages | CSP (`default-src 'self'`, no third-party scripts), `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` on token pages |
| Data | No location history. Raw phone numbers are kept only while monitoring and are masked in all output. Retention is 30 days by default |

## Known limitations

- API keys are static shared secrets from the environment. Rotating a key means a restart. There is no per-user identity inside a clinic;
  the audit shows a key fingerprint as the actor.
- No built-in rate limiting. Put the service behind a reverse proxy or API gateway that enforces rate limits and TLS.
- Link tokens are bearer secrets. Anyone holding a consent link can accept or withdraw for that case.
