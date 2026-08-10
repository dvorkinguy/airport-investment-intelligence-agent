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
          <button
            key={t.id}
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
        ))}
      </nav>
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
