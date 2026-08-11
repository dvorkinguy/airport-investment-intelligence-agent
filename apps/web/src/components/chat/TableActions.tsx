"use client";

import { useState } from "react";
import { toCsv, toTsv } from "@/lib/table";

export function TableActions({
  headers,
  rows,
  filenameHint,
}: {
  headers: string[];
  rows: string[][];
  filenameHint: string;
}) {
  const [copied, setCopied] = useState(false);

  if (headers.length === 0) return null;

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(toTsv(headers, rows));
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard permission denied - nothing useful to do
    }
  }

  function handleDownload() {
    const blob = new Blob([toCsv(headers, rows)], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filenameHint}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mt-1.5 flex gap-2">
      <button
        type="button"
        onClick={() => void handleCopy()}
        className={
          copied
            ? "inline-flex items-center gap-1.5 rounded-md border border-emerald-300 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700"
            : "inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-600 transition-colors hover:border-slate-400 hover:bg-slate-50 active:bg-slate-100"
        }
      >
        {copied ? <CheckIcon /> : <CopyIcon />}
        {copied ? "Copied" : "Copy"}
      </button>
      <button
        type="button"
        onClick={handleDownload}
        className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-600 transition-colors hover:border-slate-400 hover:bg-slate-50 active:bg-slate-100"
      >
        <DownloadIcon />
        CSV
      </button>
    </div>
  );
}

function CopyIcon() {
  return (
    <svg viewBox="0 0 14 14" width="12" height="12" fill="none" aria-hidden="true">
      <rect x="4.5" y="4.5" width="8" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
      <path d="M2.5 9.5V3A1.5 1.5 0 0 1 4 1.5h6.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg viewBox="0 0 14 14" width="12" height="12" fill="none" aria-hidden="true">
      <path d="M3 7.5 6 10.5 11 4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 14 14" width="12" height="12" fill="none" aria-hidden="true">
      <path d="M7 1.5v7.5m0 0L4 6m3 3 3-3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M2 10.5v1A1.5 1.5 0 0 0 3.5 13h7a1.5 1.5 0 0 0 1.5-1.5v-1" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}
