import { Suspense } from "react";
import { ChatApp } from "@/components/chat/ChatApp";
import { ChatAppWithAuth } from "@/components/chat/ChatAppWithAuth";
import { isClerkEnabled } from "@/lib/clerk-config";

export default function ChatPage() {
  return <Suspense fallback={null}>{isClerkEnabled() ? <ChatAppWithAuth /> : <ChatApp />}</Suspense>;
}
