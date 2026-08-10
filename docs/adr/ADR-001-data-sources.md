# ADR-001: Data sources

Status: accepted | Date: 2026-08-10

**Plain language:** we rank airports using the US government's own numbers - the
Bureau of Transportation Statistics for how many people fly and how full planes
are, and the FAA for airport facts and live congestion. Commercial flight APIs
were evaluated and rejected for the core: license limits, tiny free quotas, or
explicit "not for operational use" disclaimers.

## Decision

| Source | Role | Tier |
|---|---|---|
| BTS T-100 segments (passengers, seats, departures, distance, by airport/route/month) | Demand + capacity history - the scoring foundation | Core |
| BTS on-time performance | Congestion/delay signal over time | Core |
| FAA airport/runway metadata (NASR) + OurAirports reference | Airport identity, location, state/region, infrastructure | Core |
| FAA NAS Status API (live XML) | Current operational congestion color | Tier 2 |
| OpenSky, NOAA METAR/TAF, PreflightAPI, AviationAPI | Validation / weather / convenience wrappers | Stretch |
| AviationStack | Rejected: 100 req/mo free tier, personal-only license - incompatible with a public demo | - |

Full evaluation matrix: [../research/api-comparison.html](../research/api-comparison.html)

## Key mitigations

1. **Snapshot-first ingestion.** Scripts call the real public sources once and
   persist snapshots into the repo (`data/`, all public domain). The agent runs
   off snapshots - the demo never depends on a third-party endpoint being up.
   Refresh is re-running the script.
2. **Trend vs snapshot.** Investment signal comes from multi-year BTS history;
   live FAA status is current-color only and never treated as long-term evidence.
3. **Estimated, not observed.** No public source reports unmet demand directly.
   We compute `max(0, demand pressure - available capacity)` from load factor,
   passenger vs seat growth, and persistent delays - always labeled an estimate.
4. Licensing: BTS/FAA data is US-government public domain (CC0-class) - safe for
   a public repository.
