import { Suspense } from "react";
import { ChatApp } from "@/components/chat/ChatApp";

export default function ChatPage() {
  return (
    <Suspense fallback={null}>
      <ChatApp />
    </Suspense>
  );
}
