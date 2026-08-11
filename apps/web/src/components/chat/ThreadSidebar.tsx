import { downloadThreadExport } from "@/lib/export";
import { getThread } from "@/lib/threads";
import type { ThreadRecord } from "@/lib/types";

export function ThreadSidebar({
  threads,
  activeId,
  onSelect,
  onNew,
}: {
  threads: ThreadRecord[];
  activeId: string;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-slate-50/60 md:flex">
      <div className="p-3">
        <button
          type="button"
          onClick={onNew}
          className="w-full rounded-lg bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800"
        >
          + New thread
        </button>
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-2 pb-3">
        {threads.length === 0 && (
          <p className="px-2 py-4 text-center text-xs text-slate-400">No threads yet. Ask a question to start one.</p>
        )}
        {threads.map((t) => (
          <div key={t.id}>
            <button
              type="button"
              onClick={() => onSelect(t.id)}
              title={t.firstQuestion}
              className={`block w-full truncate rounded-lg px-3 py-2 text-left text-sm ${
                t.id === activeId ? "bg-white font-medium text-slate-900 shadow-sm" : "text-slate-600 hover:bg-white/70"
              }`}
            >
              <span className="block truncate">{t.firstQuestion}</span>
              <span className="block text-[11px] text-slate-400">{formatDate(t.createdAt)}</span>
            </button>
            {t.id === activeId && (
              <button
                type="button"
                onClick={() => {
                  // Read fresh from localStorage rather than trusting the
                  // `threads` prop - it's only as current as the last
                  // refreshThreads() call, and a click landing between the
                  // final SSE token and that state update would otherwise
                  // export a thread missing its just-finished answer.
                  const fresh = getThread(t.id) ?? t;
                  downloadThreadExport(fresh.firstQuestion, fresh.messages);
                }}
                className="mt-1 inline-flex w-full items-center justify-center gap-1.5 rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium text-slate-600 transition-colors hover:border-slate-400 hover:bg-slate-50 active:bg-slate-100"
              >
                <DownloadIcon />
                Export thread
              </button>
            )}
          </div>
        ))}
      </nav>
      <div className="border-t border-slate-200 p-3">
        <a
          href="/3d"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-slate-400 hover:text-slate-600"
        >
          3D system map
        </a>
      </div>
    </aside>
  );
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return "";
  }
}

function DownloadIcon() {
  return (
    <svg viewBox="0 0 14 14" width="12" height="12" fill="none" aria-hidden="true">
      <path d="M7 1.5v7.5m0 0L4 6m3 3 3-3" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M2 10.5v1A1.5 1.5 0 0 0 3.5 13h7a1.5 1.5 0 0 0 1.5-1.5v-1" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}
