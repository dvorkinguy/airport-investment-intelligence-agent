import { NextResponse } from "next/server";
import { clerkMiddleware, createRouteMatcher } from "@clerk/nextjs/server";

// Filename: Clerk's current docs name this file by the installed Next.js
// major - proxy.ts on Next 16+, middleware.ts on 15 and below. We're on
// 15.5.23, so middleware.ts is the documented name here, not a deviation.
//
// Env-gated: with no Clerk keys configured, clerkMiddleware() is never
// called - the exported handler is a plain passthrough, so the live
// authless site sees no behavior change from this file's presence.
//
// config.matcher below stays a static literal on purpose: Next.js parses it
// at build time via static analysis and rejects a conditional expression
// there ("Unsupported node type ConditionalExpression"), so the env gate
// has to live on the handler function, not the matcher.
const clerkEnabled = Boolean(
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY && process.env.CLERK_SECRET_KEY,
);

const isProtectedRoute = createRouteMatcher(["/chat(.*)"]);

export default clerkEnabled
  ? clerkMiddleware(async (auth, req) => {
      if (isProtectedRoute(req)) await auth.protect();
    })
  : function passthroughMiddleware() {
      return NextResponse.next();
    };

export const config = {
  matcher: [
    // Clerk's own standard matcher, unmodified: skip Next.js internals and
    // static files, always run for API routes. Never invert this into an
    // allowlist of protected paths - that flips the app's only auth gate
    // from default-deny to default-allow, and any future private route left
    // off the list ships silently public.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/(.*)",
  ],
};
