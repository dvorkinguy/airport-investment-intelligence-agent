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
      className="flex items-start gap-2 rounded-2xl border border-slate-200 bg-white p-2.5 shadow-sm transition-all focus-within:border-emerald-300 focus-within:shadow-sm focus-within:ring-2 focus-within:ring-emerald-200/60 sm:items-end sm:p-3.5 sm:shadow-md sm:shadow-slate-200/60 sm:transition-shadow sm:focus-within:border-slate-300 sm:focus-within:shadow-lg sm:focus-within:ring-0"
    >
      <VoiceMicButton onResult={(text) => setValue((v) => (v ? `${v} ${text}` : text))} />
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        rows={1}
        placeholder="Ask about an airport, a region, or a comparison..."
        disabled={disabled}
        className="max-h-32 min-h-16 flex-1 resize-none border-0 bg-transparent px-2 py-2.5 text-sm outline-none disabled:opacity-60 sm:min-h-[2.5rem]"
      />
      <button
        type="submit"
        disabled={disabled || !value.trim()}
        className="flex h-9 shrink-0 items-center justify-center rounded-full bg-slate-900 px-4 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40 sm:h-auto sm:rounded-xl sm:py-2.5"
      >
        Send
      </button>
    </form>
  );
}
