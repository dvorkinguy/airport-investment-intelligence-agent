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

## Auth (Clerk, env-gated)

`@clerk/nextjs@7.7.1` is wired but off unless both `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`
and `CLERK_SECRET_KEY` are set (`src/lib/clerk-config.ts` is the single check, used by
`src/middleware.ts`, `src/app/layout.tsx`, and `src/app/chat/page.tsx`). With either
missing the app runs exactly as before: landing and `/chat` both public, no Clerk
component ever mounts, and `src/middleware.ts`'s exported handler is a plain passthrough
(`NextResponse.next()`). The `matcher` itself can't be gated the same way - Next.js
statically parses `config.matcher` at build time and rejects a conditional expression
there - so it stays Clerk's standard pattern unconditionally; the middleware function
still runs on every request either way, it just does nothing when disabled.

With both set: landing stays public, `/chat` requires sign-in (whatever methods are
enabled in the Clerk dashboard - Google + email), `<Show when="signed-in">`/
`<Show when="signed-out">` render `UserButton`/`SignInButton` in the header (`ClerkProvider`
is a child of `<body>`, per Clerk's current layout convention - not a wrapper around
`<html>`), and the signed-in user's session token is attached to `POST /chat` as
`Authorization: Bearer <token>` (via `useAuth().getToken()`, called fresh per send since
session tokens are short-lived) for the backend to verify via JWKS. Signed out or Clerk
disabled -> no `Authorization` header at all.

Middleware uses Clerk's own standard matcher (skip `_next` and static files, always run
for `/api` and `/__clerk`) - never inverted into an allowlist of protected paths, since
that flips the app's only auth gate from default-deny to default-allow.

Filename is `middleware.ts`, not `proxy.ts` - Clerk names this file by the installed
Next.js major (`proxy.ts` on 16+, `middleware.ts` on 15 and below) and this app is on
15.5.23.

## E2E smoke tests

```bash
npm run test:e2e   # installs Chromium on first run, then builds+starts+tests
```

3 tests (`e2e/smoke.spec.ts`), one production build shared across all of them (backend
URL intentionally pointed at a dead port - see `playwright.config.ts`):

1. Landing renders the title, all 4 exam-question cards, and Start asking.
2. `/chat` renders the input, send button, and mic button.
3. Backend unreachable: the amber banner shows the production wording and nothing else
   breaks (input/send button still render, no uncaught page errors).

## Stubbed (Tier 2, not this window)

- PostHog analytics
- Deployed backend URL (currently points at `localhost:8000` by default)
- Custom Clerk sign-in/sign-up pages (uses Clerk's default hosted flow)
