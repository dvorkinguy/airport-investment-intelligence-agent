# Security Policy

## Scope

A demonstration system built as a technical exercise. It handles only public US
government aviation data (DOT/BTS, FAA) and open OurAirports data: no personal
data, no customer data, no payment data. Sign-in exists to gate the chat
interface, and the only identity stored is the subject claim from a verified
session token.

## Controls in place

- Secrets live in managed stores - GCP Secret Manager, GitHub Actions secrets,
  platform environment variables - never in the repository.
- `gitleaks` runs as a local pre-commit hook (`.pre-commit-config.yaml`) and
  again in CI across the full history on every push and pull request.
- Dependabot alerts are enabled.
- The Cloud Run service runs as a dedicated service account scoped to
  `secretAccessor` on its own secrets, never the default compute account.
- Agent database access is read-only and bounded by a statement timeout.
- Identity comes only from a signature: Clerk session tokens are verified
  against Clerk's JWKS, and caller-supplied user headers are ignored.

Not yet enabled: GitHub secret scanning and push protection, which become
available on this repository once it is public.

## Reporting

Email dvorkin.guy@gmail.com. Expect an acknowledgement within 72 hours. Please
do not open a public issue for a security report.
