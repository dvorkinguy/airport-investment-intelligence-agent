"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { v4 as uuidv4 } from "uuid";
import type { ChatEvent, ChatMessage, ThreadRecord } from "@/lib/types";
import { checkHealth, streamChat } from "@/lib/api";
import { getThread, listThreads, upsertThread } from "@/lib/threads";
import { extractFollowUps, DEFAULT_FOLLOW_UPS } from "@/lib/followups";
import { ThreadSidebar } from "./ThreadSidebar";
import { MessageBubble } from "./MessageBubble";
import { ChatInput } from "./ChatInput";
import { BackendDownBanner } from "./BackendDownBanner";

export function ChatApp() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialQuestion = searchParams.get("q");

  const [threadId, setThreadId] = useState<string>(() => uuidv4());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [threads, setThreads] = useState<ThreadRecord[]>([]);
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  const [sending, setSending] = useState(false);
  const autoSentRef = useRef(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const refreshThreads = useCallback(() => setThreads(listThreads()), []);

  useEffect(() => {
    refreshThreads();
  }, [refreshThreads]);

  const probeHealth = useCallback(() => {
    const controller = new AbortController();
    void checkHealth(controller.signal).then((h) => setBackendOk(h.ok));
    return () => controller.abort();
  }, []);

  useEffect(() => probeHealth(), [probeHealth]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  const send = useCallback(
    async (text: string) => {
      const activeThreadId = threadId;
      const userMessage: ChatMessage = { id: uuidv4(), role: "user", content: text };
      const assistantId = uuidv4();
      const assistantPlaceholder: ChatMessage = {
        id: assistantId,
        role: "assistant",
        content: "",
        streaming: true,
        toolActivity: [],
      };

      function persist(msgs: ChatMessage[]) {
        const existing = getThread(activeThreadId);
        upsertThread({
          id: activeThreadId,
          firstQuestion: existing?.firstQuestion ?? text,
          createdAt: existing?.createdAt ?? new Date().toISOString(),
          messages: msgs,
        });
        refreshThreads();
      }

      setMessages((prev) => {
        const next = [...prev, userMessage, assistantPlaceholder];
        persist(next);
        return next;
      });
      setSending(true);

      const applyUpdate = (updater: (m: ChatMessage) => ChatMessage) => {
        setMessages((prev) => prev.map((m) => (m.id === assistantId ? updater(m) : m)));
      };

      const finalizeWith = (updater: (m: ChatMessage) => ChatMessage) => {
        setMessages((prev) => {
          const next = prev.map((m) => (m.id === assistantId ? updater(m) : m));
          persist(next);
          return next;
        });
      };

      const onEvent = (event: ChatEvent) => {
        switch (event.type) {
          case "token":
            applyUpdate((m) => ({ ...m, content: m.content + event.content }));
            break;
          case "tool_call":
            applyUpdate((m) => ({
              ...m,
              toolActivity: [...(m.toolActivity ?? []), { name: event.name, status: "called" }],
            }));
            break;
          case "tool_result":
            applyUpdate((m) => ({
              ...m,
              toolActivity: (m.toolActivity ?? []).map((t) =>
                t.name === event.name && t.status === "called"
                  ? { ...t, status: event.ok ? "ok" : "error", error: event.error }
                  : t,
              ),
            }));
            break;
          case "assumptions":
            applyUpdate((m) => ({ ...m, assumptions: event.items }));
            break;
          case "done": {
            const { body, followUps } = extractFollowUps(event.answer || "");
            finalizeWith((m) => ({
              ...m,
              content: body || m.content,
              streaming: false,
              assumptions: event.assumptions.length ? event.assumptions : m.assumptions,
              followUps: followUps.length ? followUps : DEFAULT_FOLLOW_UPS,
            }));
            break;
          }
          case "error":
            finalizeWith((m) => ({ ...m, streaming: false, errored: true, content: m.content || event.message }));
            break;
          case "start":
            break;
        }
      };

      try {
        await streamChat(activeThreadId, text, onEvent);
      } catch {
        finalizeWith((m) => ({
          ...m,
          streaming: false,
          errored: true,
          content: m.content || "Could not reach the agent backend.",
        }));
        setBackendOk(false);
      } finally {
        setSending(false);
      }
    },
    [threadId, refreshThreads],
  );

  useEffect(() => {
    if (initialQuestion && !autoSentRef.current) {
      autoSentRef.current = true;
      void send(initialQuestion);
      router.replace("/chat");
    }
    // Intentionally only re-running when the URL question changes, not on every `send` identity change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion]);

  function handleNewThread() {
    setThreadId(uuidv4());
    setMessages([]);
    router.replace("/chat");
  }

  function handleSelectThread(id: string) {
    const thread = getThread(id);
    if (!thread) return;
    setThreadId(id);
    setMessages(thread.messages);
  }

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <ThreadSidebar threads={threads} activeId={threadId} onSelect={handleSelectThread} onNew={handleNewThread} />
      <div className="flex min-w-0 flex-1 flex-col">
        {backendOk === false && <BackendDownBanner onRetry={probeHealth} />}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-6 md:px-8">
          {messages.length === 0 ? (
            <EmptyState onPick={(q) => void send(q)} />
          ) : (
            <div className="mx-auto flex max-w-3xl flex-col gap-4">
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} onFollowUp={(q) => void send(q)} />
              ))}
            </div>
          )}
        </div>
        <div className="mx-auto w-full max-w-3xl">
          <ChatInput onSend={(text) => void send(text)} disabled={sending || backendOk === false} />
        </div>
      </div>
    </div>
  );
}

function EmptyState({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="mx-auto flex h-full max-w-xl flex-col items-center justify-center text-center">
      <p className="text-lg font-medium text-slate-800">Ask an investment question about US airports.</p>
      <p className="mt-1 text-sm text-slate-500">
        Every number is pulled from a deterministic SQL view - never invented.
      </p>
      <div className="mt-6 flex flex-wrap justify-center gap-2">
        {DEFAULT_FOLLOW_UPS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            className="max-w-full break-words rounded-full border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-600 hover:border-emerald-300 hover:text-emerald-700"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
