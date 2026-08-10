import type { ChatEvent } from "./types";

const DEFAULT_API_URL = "http://localhost:8000";

export function getApiUrl(): string {
  return process.env.NEXT_PUBLIC_AGENT_API_URL || DEFAULT_API_URL;
}

export interface HealthStatus {
  ok: boolean;
  status?: string;
  model?: string;
  data_backend?: string;
  data_vintage?: Record<string, unknown>;
}

export async function checkHealth(signal?: AbortSignal): Promise<HealthStatus> {
  try {
    const res = await fetch(`${getApiUrl()}/health`, { signal, cache: "no-store" });
    const body = (await res.json().catch(() => ({}))) as Partial<HealthStatus>;
    return { ...body, ok: res.ok };
  } catch {
    return { ok: false };
  }
}

export interface StreamChatOptions {
  signal?: AbortSignal;
  /** Clerk session JWT (Clerk enabled + signed in). Sent as `Authorization: Bearer <token>`; the backend verifies it via JWKS. Absent when signed out or Clerk is disabled - no auth header is sent, matching the authless mode. */
  token?: string;
}

/**
 * Consumes the POST /chat SSE stream. Uses fetch + a manual reader because the
 * backend needs a POST body - the browser EventSource API is GET-only.
 */
export async function streamChat(
  threadId: string,
  message: string,
  onEvent: (event: ChatEvent) => void,
  options?: StreamChatOptions,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (options?.token) headers["Authorization"] = `Bearer ${options.token}`;

  const res = await fetch(`${getApiUrl()}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({ thread_id: threadId, message, stream: true }),
    signal: options?.signal,
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    onEvent({ type: "error", message: text || `request failed (${res.status})` });
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sepIndex = buffer.indexOf("\n\n");
    while (sepIndex !== -1) {
      const rawEvent = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);
      const dataLine = rawEvent.split("\n").find((line) => line.startsWith("data: "));
      if (dataLine) {
        const jsonStr = dataLine.slice("data: ".length);
        try {
          onEvent(JSON.parse(jsonStr) as ChatEvent);
        } catch {
          // malformed chunk - skip rather than break the whole stream
        }
      }
      sepIndex = buffer.indexOf("\n\n");
    }
  }
}
