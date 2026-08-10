"use client";

import { useAuth } from "@clerk/nextjs";
import { ChatApp } from "./ChatApp";

/**
 * Only ever mounted when Clerk is enabled (see src/app/chat/page.tsx), so a
 * <ClerkProvider> ancestor is guaranteed - useAuth() is safe to call
 * unconditionally here even though it would throw outside that context.
 */
export function ChatAppWithAuth() {
  const { getToken } = useAuth();
  return <ChatApp getAuthToken={getToken} />;
}
