# ADR-000: Guiding principles

Status: accepted | Date: 2026-08-10

**Plain language:** we optimize for a working, verifiable demo over an impressive
diagram. Features earn their place by helping answer the four target questions;
everything else is designed on paper and deferred.

## Principles

1. **No overengineering.** Fastest path to a visible, correct result; iterate from
   there. Every component must justify itself against the deliverable.
2. **Deterministic core, AI shell.** Scoring and ranking are SQL - auditable and
   reproducible. The LLM orchestrates tools and explains; it never invents numbers.
3. **Production-grade by design.** The structure, security, and observability follow
   production standards (see the 8-gate table in docs/design.md). Anything not
   implemented inside the time window is explicitly stubbed and documented -
   never silently missing.
4. **Assumptions stated, always.** Estimated metrics are labeled estimated; data
   vintage and scope are cited in answers.
5. **Local-first.** The full stack runs locally end-to-end before any cloud deploy.
   Cloud is the demo layer, not the only path.

## Consequences

- A pre-agreed drop order exists for scope under time pressure; the submission is
  complete at every tier boundary.
- Deferred items appear in docs/design.md as "designed, not implemented" with their
  production path - deliberate scope decisions, not gaps.
