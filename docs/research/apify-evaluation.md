# Apify Evaluation — Airport Investment Intelligence Agent

Research pass: 2026-08-10. Data core for this project is locked as BTS T-100 (demand/capacity
history), FAA NAS Status (live congestion), FAA NASR (airport metadata). This doc answers one
question: does Apify add anything on top of that core, and if so, where and at what cost.

## Verdict

| Tier | Use Apify? | Why |
|---|---|---|
| Tier 1 — airport identity/location metadata (IATA/ICAO, name, lat/lon, state, runway count/length) | **No** | OurAirports + FAA NASR cover every needed field, free, no scraping, verified with real row counts below |
| Tier 3 — passenger-sentiment signal (rating, review count) for ~50 major airports | **Yes, optional** | Genuine value-add (no other locked source has a sentiment signal), and trivially cheap (~$0.08–$0.21 total) |

Bottom line: don't build or budget for a scraper for Tier 1. Reserve Apify for the Tier 3
enrichment, and only if time remains after the deterministic scoring core is working — the client
brief itself says to prioritize clarity and reasoning over completeness.

## 1. Airport location coverage — no scraper needed

All three named candidate sources checked live on 2026-08-10:

| Source | Access | Download URL | Verified coverage |
|---|---|---|---|
| OurAirports `airports.csv` | Free, no auth, static CSV | https://davidmegginson.github.io/ourairports-data/airports.csv | 85,860 airports worldwide; 32,598 in the US (see breakdown below). Last-modified 2026-08-09 on the copy fetched. |
| OurAirports `runways.csv` | Free, no auth, static CSV | https://davidmegginson.github.io/ourairports-data/runways.csv | 48,148 runway rows worldwide; 26,558 joined to a US airport by `airport_ident` |
| FAA NASR 28-Day Subscription | Free, no registration | https://www.faa.gov/air_traffic/flight_info/aeronav/Aero_Data/NASR_Subscription/2026-08-06/ (current cycle as of this check) | Confirmed free/no-auth via NFDC README; includes `APT_BASE.csv` + `APT_RWY.csv` + `APT_RWY_END.csv`. Exact column list needs the separate "CSV DATA STRUCTURE" doc — the FAA site itself 403'd automated fetch, so field names weren't independently re-verified in this pass. Treat as the authoritative government cross-check, not the primary source. |
| aviationapi.com | **Unverified / likely dead API** | — | Main marketing site is up (`www.aviationapi.com` → HTTP 200, a SvelteKit single-page app with no server-rendered content). Both `api.aviationapi.com` and `docs.aviationapi.com` **fail DNS resolution** (checked via direct `curl`, not just WebFetch). Could not confirm this source is currently queryable. Not needed anyway — drop it. |

**OurAirports `airports.csv` fields (from the actual header row):**
`id, ident, type, name, latitude_deg, longitude_deg, elevation_ft, continent, iso_country, iso_region, municipality, scheduled_service, icao_code, iata_code, gps_code, local_code, home_link, wikipedia_link, keywords`

**US breakdown (computed by downloading and parsing the real files, not estimated):**

| Metric | Count |
|---|---|
| US rows total | 32,598 |
| ...with lat/lon populated | 32,598 (100%) |
| ...with `iso_region` (state, e.g. `US-CA`) populated | 32,598 (100%) |
| ...with IATA code | 2,036 |
| ...with ICAO code | 1,767 |
| ...`type = large_airport` | 95 |
| ...`type = medium_airport` | 822 |
| ...`type = small_airport` | 15,246 |
| ...`scheduled_service = yes` (the realistic commercial-passenger universe) | 699 |
| Runway rows joined to a US airport | 26,558 |
| ...of which `length_ft` populated | 26,545 |

Every airport named in the four target questions is covered: SFO, LAX, Santa Ana (SNA), Anchorage
(ANC), and the full New England set all carry IATA/ICAO codes, lat/lon, state, and joined runway
length data in this one free file pair.

**Verdict confirmed:** OurAirports alone satisfies every field item 1 asked about, for free, via a
single static download, refreshed roughly weekly. FAA NASR is the fallback/corroboration source if
OurAirports' community-maintained data is ever questioned in the design doc. No scraper of any kind
is needed for Tier 1.

## 2. Tier 3: Google Maps rating/review-count enrichment

Actor: `compass/crawler-google-places` ("Google Maps Scraper"), 552,937 total users on the Apify
Store — this is the actor named in your brief, checked live via the public Apify Store page and its
`/pricing` sub-page.

**Published pricing (pay-per-event model):** headline rate **"from $1.50 / 1,000 scraped places"**
for the base "Place scraped" event. Separate paid events exist for "Reviews extracted" (full review
text/content), contact/email enrichment, and social-profile enrichment — none of which this use case
needs. Rating and aggregate review **count** are ordinary fields Google Maps shows on every place
card without opening individual reviews, so the working assumption is they ride along with the base
event at no extra charge. **This specific assumption is not confirmed against the actor's output
schema** — cheapest way to confirm before committing to the full batch: run the actor against a
single airport (cost: ~$0.0015) and inspect the output fields.

The pricing page does not publish a separate FREE-tier line price for the base event alone, but its
own worked example gives a real bounding ratio: a bundle (100 places + 100 reviews each + social
profiles) costs **$17.90 on the FREE plan vs $6.50 on SILVER** — FREE runs ~2.75x SILVER for
identical work.

**Estimate for ~50 major US airports, base event only:**

| Basis | Calculation | Cost |
|---|---|---|
| Headline rate | 50 / 1,000 × $1.50 | $0.075 |
| Conservative FREE-tier bound (headline × 2.75 observed ratio) | $0.075 × 2.75 | ~$0.21 |

Either way, under $0.25 total, one-time or refreshed periodically. See account finding below — the
account this would run under already carries $5/mo in free usage credit, which fully absorbs it.

This is a real, if minor, value-add: none of the three locked sources (BTS T-100, FAA NAS Status,
FAA NASR) carry a passenger-sentiment or service-quality signal. Recommend scoping this as a soft
modifier in the scoring model, not a primary KPI — it measures traveler sentiment, not investment
fundamentals — and as Tier 3 / build-it-only-if-time-remains, given the 24-hour clock.

## 3. Apify account ownership — HARD RULE check

Per standing rule: never use a customer's SaaS account for Guy's own work. Verified **live** on
2026-08-10 via `GET api.apify.com/v2/users/me`, using the token at `~/.config/apify/credentials.json`
(the account-info call only — no actor was run, no cost incurred):

| Field | Live value |
|---|---|
| username | `dvorkinguy` |
| email | `dvorkin.guy@gmail.com` |
| profile name | Guy Dvorkin |
| account created | 2025-03-31 |
| plan | **FREE** (tier: FREE, monthlyBasePriceUsd: $0) |
| isPaying | **false** |
| monthly free usage credit | $5 |

**Clean result: no sign of jennyartem billing on this account, right now.** This is Guy's own
account (his personal email), on Apify's free tier, paying nothing to anyone.

**Flag for the record — two stale/conflicting sources found during pre-check, now superseded by the
live result above:**

- The local `~/.config/apify/credentials.json` file itself still has `"plan":"STARTER"` hard-coded
  in it. That's wrong as of this check — the live API says FREE. Worth refreshing the file so it
  stops asserting a plan the account isn't on.
- A separate memory note (`project_apify_jennyartem_subscription.md`, dated ~2026-07-25, already
  flagged stale) describes a Starter plan billed to Jenny Artem's card, cancelled, ending June 14,
  2026. That's consistent with this same account having been on a paid Starter plan via that billing
  arrangement at some point and having since reverted to FREE after cancellation — or it describes a
  different Apify account browsed separately in-console during the jennyartem engagement. Either
  reading is consistent with today's clean result, but the discrepancy itself is the lesson: **don't
  trust either memory file for future Apify billing questions — re-verify live via `/v2/users/me`
  before any paid actor run**, exactly as this task's instructions required.

Given the account is FREE / not paying / shows no jennyartem billing signal, it's clear to use for
the ~$0.08–$0.21 Tier 3 run above, if and when you decide to build it.
