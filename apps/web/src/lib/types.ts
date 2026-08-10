// Wire format mirrors services/agent/main.py: the SSE event union emitted by POST /chat.
export type ChatEvent =
  | { type: "start"; thread_id: string }
  | { type: "token"; content: string }
  | { type: "tool_call"; name: string; args: Record<string, unknown> }
  | { type: "tool_result"; name: string | null; ok: boolean; error?: string | null }
  | { type: "assumptions"; items: string[] }
  | {
      type: "done";
      thread_id: string;
      tools_used: string[];
      answer: string;
      assumptions: string[];
    }
  | { type: "error"; message: string };

export interface ToolActivityEntry {
  name: string;
  status: "called" | "ok" | "error";
  error?: string | null;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  streaming?: boolean;
  errored?: boolean;
  toolActivity?: ToolActivityEntry[];
  assumptions?: string[];
  followUps?: string[];
}

export interface ThreadRecord {
  id: string;
  firstQuestion: string;
  createdAt: string;
  messages: ChatMessage[];
}
