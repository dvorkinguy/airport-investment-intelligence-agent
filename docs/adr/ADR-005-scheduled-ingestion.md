# ADR-005: Scheduled ingestion

Status: accepted | Date: 2026-08-23 | **Post-submission.** The `submission-2026-08-11`
tag is unchanged and this decision is not part of it.

**Plain language:** the data now refreshes itself on a schedule instead of waiting for
someone to re-run a script. A weekly job checks whether the US government has actually
published anything new, and only rebuilds the database when it has. Everything the job
does is recorded in a table, and the last successful check is visible publicly on the
site so nobody has to take our word for it.

## Context

ADR-001 chose snapshot-first ingestion: build scripts fetch the real public sources once,
persist processed CSVs, and the running service never depends on a third-party endpoint
being up. That decision stands and is not revisited here.

What ADR-001 left open was *who re-runs the scripts*. The answer was "a person, on demand",
and `docs/design.md` section 11 listed scheduled data refresh among the items designed and
deliberately not built inside the window. That was an honest deferral, but a deferral is
still a gap: data currency depended entirely on someone remembering.

This ADR closes it.

## Decision

**A Cloud Run Job (`airport-ingest`), triggered weekly by Cloud Scheduler, running the
existing ingestion scripts through a new `ingestion/refresh.py` orchestrator, writing every
run to a `data_refresh_runs` table in Neon, and surfacing the last successful run on a
public `GET /freshness` endpoint and on the landing page.**

This **completes** ADR-002 rather than amending it. ADR-002 already assigned Cloud Run the
role of "Agent backend (FastAPI + LangGraph) **+ ingestion job**". The job was always the
declared home for this work. It simply had not been built.

## This upholds ADR-003's rejection of n8n

ADR-003 recorded:

> | n8n for ingestion scheduling | Rejected - a script run on demand beats a workflow runtime for a snapshot pipeline; production path (scheduled refresh) documented instead |

That rejection was correct and it still holds. Scheduling the pipeline does not create a
case for a workflow runtime:

| Option | Verdict |
|---|---|
| **Cloud Run Job + Cloud Scheduler** | **Chosen.** Retries, a 24h task ceiling, execution history and Cloud Monitoring alerting come with the platform, and the project already runs Cloud Run. No second control plane. |
| n8n calling a Cloud Run Job | Rejected. Adds a workflow runtime whose only responsibility would be calling a scheduler the platform already provides. Fails ADR-000 principle 1: every component must justify itself against the deliverable. It is also unverifiable to a reviewer, who can read this repository but cannot inspect a private automation host. |
| GitHub Actions on a cron | Rejected. Public run history is genuinely attractive, but it places `DATABASE_URL` as a secret on a public repository and makes the CI system perform production writes. |
| n8n re-implementing the builders | Rejected outright. Discards tested Python and asks a workflow engine to move hundreds of megabytes. |

## The job needs its own image

An earlier draft of this ADR assumed the job could simply reuse the agent's container,
on the reasoning that the Python environment was already proven. That was wrong, and the
repository says so plainly:

- `.dockerignore` excludes `apps/`, `data/`, `db/` and `ingestion/` under the comment
  "Not part of the backend image".
- The `Dockerfile` builder stage copies only `services/`.
- `pyproject.toml` wheels only `services/agent`.

So `ingestion/` is not in the agent image, and it is absent by decision rather than by
oversight. The agent serves questions; it has no reason to carry a data pipeline.

**Decision: a separate `Dockerfile.ingest`, pushed to the same Artifact Registry repository
under its own tag.** The shared `Dockerfile` and `.dockerignore` are not modified, so
building the ingest image cannot affect the running service.

Consequence worth stating because it is the easy mistake: `.dockerignore` strips those paths
from the build *context*, before any `COPY` executes. A second Dockerfile alone does not
recover them - the ingest build needs its own ignore scope. Verification is listing the files
inside the built image, not reading the Dockerfile and assuming.

**Identities.** The job runs as `airport-agent-run`, which already holds
`roles/secretmanager.secretAccessor` scoped to the `database-url` secret and nothing
project-wide. Cloud Scheduler triggers it as a separate, dedicated invoker service account
holding `roles/run.invoker` on that job alone. The thing that triggers a run and the thing
that performs it are not the same identity.

## Cadence: weekly poll, monthly effective refresh

BTS publishes T-100 monthly with a multi-month lag. FAA Form 127 is annual and lags its own
fiscal year - FY2024 filings were still arriving in February 2026 (ADR-004). OurAirports
changes continuously but slowly.

So the job runs weekly and *probes* first. When nothing new has published upstream it records
`no_change` and stops without touching the database. Re-downloading 21MB every week to
rebuild identical tables would be motion, not freshness.

A `no_change` result is a successful refresh check and is displayed as such. Only a `failed`
run is a failure.

## Safety: validate before load, because load destroys

This is the part that needed design rather than plumbing.

`ingestion/load.py` gets its idempotency from `schema.sql`, which is `DROP TABLE IF EXISTS`
followed by `CREATE TABLE`. Run by hand, watched, once, that is fine. Run unattended on a
schedule it is a live hazard: a truncated download or a half-failed builder would still reach
`load`, drop the populated tables, fail to repopulate them, and leave the public site
answering investment questions confidently from an empty database.

`refresh.py` therefore never lets a bad build reach `load`:

1. Open a `running` row and record current row counts.
2. Probe. Nothing new upstream: close `no_change`, exit 0, `load` is never called.
3. Build. Any builder failing: close `failed`, exit non-zero, `load` is never called.
4. Validate every output CSV against a floor derived from what Neon currently holds. New
   data should add rows, not remove them. Below floor: close `failed`, exit non-zero,
   `load` is never called.
5. Only now load.
6. Record final counts and the newest period. Close `success`.

An unhandled exception still closes the row as `failed`. A row left `running` forever would
make the freshness endpoint lie, which defeats the purpose of having one.

The BTS T-100 source is a scripted ASP.NET form flow (ADR-001 appendix). It will break
unattended at some point. The run table, the non-zero exit and the "last **successful**
refresh" wording exist so that when it does, the failure is visible rather than silent, and
the site keeps showing the true vintage of the data it actually holds.

## What this does not change

- `db/schema.sql` and `db/views.sql` are untouched. All new SQL is additive
  (`db/schema_refresh.sql`), per the ADR-004 freeze.
- **The 8-gate production-readiness table in `docs/design.md` is unchanged.** None of the
  eight gates concerns data ingestion, and moving a gate because an unrelated component
  shipped would inflate the table. The honest edit is to `docs/design.md` section 11, where
  scheduled refresh moves out of "designed, not built".
- ADR-001's snapshot-first decision, which this implements rather than replaces.

## Verification

Not "the schedule is configured" but "the schedule fired and something happened": the Cloud
Scheduler job is triggered manually once, and a corresponding new Cloud Run Job execution and
a new `data_refresh_runs` row are confirmed. A schedule that reports itself enabled and never
fires is a known failure mode and is not evidence of anything.
