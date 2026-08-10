"use client";

import { useEffect, useRef, useState } from "react";
import { createSpeechRecognizer, isSpeechRecognitionSupported } from "@/lib/speech";

export function VoiceMicButton({ onResult }: { onResult: (text: string) => void }) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const recognizerRef = useRef<ReturnType<typeof createSpeechRecognizer>>(null);

  useEffect(() => {
    setSupported(isSpeechRecognitionSupported());
  }, []);

  if (!supported) return null;

  function start() {
    const recognizer = createSpeechRecognizer({
      onFinal: (text) => onResult(text),
      onEnd: () => setListening(false),
      onError: () => setListening(false),
    });
    if (!recognizer) return;
    recognizerRef.current = recognizer;
    setListening(true);
    recognizer.start();
  }

  function stop() {
    recognizerRef.current?.stop();
    setListening(false);
  }

  return (
    <button
      type="button"
      onClick={listening ? stop : start}
      aria-label={listening ? "Stop voice input" : "Start voice input"}
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full border transition ${
        listening ? "animate-pulse border-red-300 bg-red-50 text-red-600" : "border-slate-200 text-slate-500 hover:bg-slate-50"
      }`}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3Z" />
        <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
        <line x1="12" y1="19" x2="12" y2="23" />
        <line x1="8" y1="23" x2="16" y2="23" />
      </svg>
    </button>
  );
}
