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
        className="rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
      >
        {copied ? "Copied" : "Copy"}
      </button>
      <button
        type="button"
        onClick={handleDownload}
        className="rounded-md border border-slate-200 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
      >
        CSV
      </button>
    </div>
  );
}
