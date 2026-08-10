"use client";

import { useEffect, useState } from "react";
import { isSpeechSynthesisSupported, speak, stopSpeaking } from "@/lib/speech";

export function ReadAloudToggle({ text }: { text: string }) {
  const [supported, setSupported] = useState(false);
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    setSupported(isSpeechSynthesisSupported());
  }, []);

  if (!supported) return null;

  function toggle() {
    if (speaking) {
      stopSpeaking();
      setSpeaking(false);
      return;
    }
    speak(text, () => setSpeaking(false));
    setSpeaking(true);
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-slate-400 hover:text-slate-600"
    >
      {speaking ? "Stop reading" : "Read aloud"}
    </button>
  );
}
