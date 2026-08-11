"use client";

import { useState, type FormEvent, type KeyboardEvent } from "react";
import { VoiceMicButton } from "./VoiceMicButton";

export function ChatInput({ onSend, disabled }: { onSend: (text: string) => void; disabled?: boolean }) {
  const [value, setValue] = useState("");

  function submit(e?: FormEvent) {
    e?.preventDefault();
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  function handleKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  }

  return (
    <form
      onSubmit={submit}
      className="flex items-end gap-2 rounded-2xl border border-slate-200 bg-white p-3.5 shadow-md shadow-slate-200/60 transition-shadow focus-within:border-slate-300 focus-within:shadow-lg"
    >
      <VoiceMicButton onResult={(text) => setValue((v) => (v ? `${v} ${text}` : text))} />
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        rows={1}
        placeholder="Ask about an airport, a region, or a comparison..."
        disabled={disabled}
        className="max-h-32 min-h-[2.5rem] flex-1 resize-none border-0 bg-transparent px-2 py-2.5 text-sm outline-none disabled:opacity-60"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="shrink-0 rounded-xl bg-slate-900 px-4 py-2.5 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
      >
        Send
      </button>
    </form>
  );
}
