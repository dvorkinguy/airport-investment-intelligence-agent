"use client";

import { useUser } from "@clerk/nextjs";
import { ChatApp } from "./ChatApp";

/**
 * Only ever mounted when Clerk is enabled (see src/app/chat/page.tsx), so a
 * <ClerkProvider> ancestor is guaranteed - useUser() is safe to call
 * unconditionally here even though it would throw outside that context.
 */
export function ChatAppWithAuth() {
  const { user } = useUser();
  return <ChatApp userId={user?.id} userEmail={user?.primaryEmailAddress?.emailAddress} />;
}
