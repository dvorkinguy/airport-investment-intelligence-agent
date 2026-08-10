# Web UI

Next.js 15 (App Router) chat client for the Airport Investment Intelligence Agent.

## Run it

```bash
npm install
cp .env.example .env.local     # NEXT_PUBLIC_AGENT_API_URL, defaults to http://localhost:8000
npm run dev                    # http://localhost:3000
```

The agent backend (`services/agent`) must be running separately - see its README.

## Routes

| Route | What it is |
|---|---|
| `/` | Public landing page: value prop, the 4 exam questions as click-to-ask cards, architecture diagram, privacy line |
| `/chat` | Chat UI: SSE-streamed answers, markdown with GFM tables, per-table Copy/CSV + auto bar chart, assumptions footnote, follow-up chips, thread sidebar, voice input/read-aloud |

## Notes

- Thread list lives in `localStorage` (id, first question, date, and a local copy of the
  rendered messages for instant re-open); actual conversational memory lives in the backend's
  Postgres checkpointer, keyed by the same `thread_id`. There is no `GET` history endpoint, so a
  thread's local cache is what lets switching back to it show a transcript instantly.
- Voice (mic input via `SpeechRecognition`, read-aloud via `speechSynthesis`) is feature-detected
  and hidden entirely in browsers that don't support it (e.g. Firefox has no `SpeechRecognition`).
- Deps beyond the brief's "add only recharts": `react-markdown` + `remark-gfm` (GFM table
  rendering is a hard requirement; hand-rolling a markdown/table parser would be more code and
  more risk than a maintained library) and `uuid` (thread/message ids). No UI kit, no state
  library, no animation library.
- Pinned to Next.js 15 per the brief, not the currently-latest 16.x that `create-next-app@latest`
  installs by default.

## Stubbed (Tier 2, not this window)

- Clerk auth - slot comment in `src/app/layout.tsx` header, chat currently public
- PostHog analytics
- Deployed backend URL (currently points at `localhost:8000` by default)
