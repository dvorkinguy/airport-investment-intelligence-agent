import type { NextConfig } from "next";

// The agent backend's own origin. Same source of truth as src/lib/api.ts, so
// the proxied route below and the client's direct calls can never disagree
// about which backend they mean.
const AGENT_API_URL =
  process.env.NEXT_PUBLIC_AGENT_API_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // public/3d/index.html has no directory-index resolution on its own -
  // Next only serves it at the literal /3d/index.html path. This rewrite
  // (not a redirect) keeps the clean /3d URL while serving that same file,
  // and runs independently of middleware.ts's matcher/auth gate.
  async rewrites() {
    return [
      { source: "/3d", destination: "/3d/index.html" },
      // /freshness is served by the FastAPI agent, not by Next. Without this
      // proxy the URL 404s on the site's own origin - which matters because
      // that is the URL we hand to a reviewer to check data currency for
      // themselves, and a dead link there is worse than no link.
      //
      // A rewrite rather than a redirect, so the endpoint stays same-origin.
      // That removes CORS from this path entirely: a CORS misconfiguration
      // would otherwise blank the freshness line in production for a reason
      // completely invisible in local development.
      //
      // middleware.ts runs ahead of this, but only guards /chat(.*), so
      // /freshness stays public and unauthenticated as intended.
      { source: "/freshness", destination: `${AGENT_API_URL}/freshness` },
    ];
  },
};

export default nextConfig;
