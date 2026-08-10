import type { ToolActivityEntry } from "@/lib/types";

export function ToolActivity({ entries }: { entries: ToolActivityEntry[] }) {
  if (entries.length === 0) return null;
  return (
    <div className="mb-2 flex flex-wrap gap-1.5">
      {entries.map((entry, i) => {
        const style =
          entry.status === "error"
            ? "border-red-200 bg-red-50 text-red-600"
            : entry.status === "ok"
              ? "border-emerald-200 bg-emerald-50 text-emerald-700"
              : "border-slate-200 bg-slate-50 text-slate-500";
        const prefix = entry.status === "called" ? "Running " : entry.status === "error" ? "Failed " : "";
        return (
          <span
            key={`${entry.name}-${i}`}
            className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${style}`}
          >
            {prefix}
            {entry.name}
          </span>
        );
      })}
    </div>
  );
}
