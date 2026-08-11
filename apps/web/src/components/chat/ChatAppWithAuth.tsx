"use client";

import { useAuth } from "@clerk/nextjs";
import { ChatApp } from "./ChatApp";

/**
 * Only ever mounted when Clerk is enabled (see src/app/chat/page.tsx), so a
 * <ClerkProvider> ancestor is guaranteed - useAuth() is safe to call
 * unconditionally here even though it would throw outside that context.
 *
 * Gated on isLoaded: middleware already confirmed a valid session before
 * this page ever shipped to the browser, but useAuth() still needs its own
 * client-side hydration pass, and userId reads null during it. Mounting
 * ChatApp before isLoaded would namespace that first render's localStorage
 * reads/writes under "anonymous" instead of the real user - the same class
 * of cross-account leak this component exists to prevent, just triggered
 * by a race instead of a missing namespace.
 */
export function ChatAppWithAuth() {
  const { isLoaded, userId, getToken } = useAuth();
  if (!isLoaded || !userId) return null;
  return <ChatApp userId={userId} getAuthToken={getToken} />;
}
