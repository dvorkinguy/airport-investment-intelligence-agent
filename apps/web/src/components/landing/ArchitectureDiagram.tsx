const STEPS = [
  { label: "You", detail: "Ask in plain English" },
  { label: "Chat UI", detail: "Next.js, streaming" },
  { label: "Agent", detail: "FastAPI + LangGraph" },
  { label: "SQL views", detail: "Neon Postgres, deterministic" },
  { label: "Public data", detail: "BTS T-100, on-time, FAA" },
];

export function ArchitectureDiagram() {
  return (
    <div className="flex flex-col items-stretch gap-2 md:flex-row md:items-center md:justify-between">
      {STEPS.map((step, i) => (
        <div key={step.label} className="flex flex-1 items-center gap-2 md:flex-col md:gap-1">
          <div className="flex-1 rounded-xl border border-slate-200 bg-white px-4 py-3 text-center shadow-sm">
            <p className="text-sm font-semibold text-slate-800">{step.label}</p>
            <p className="mt-0.5 text-xs text-slate-500">{step.detail}</p>
          </div>
          {i < STEPS.length - 1 && (
            <span className="shrink-0 text-slate-300 md:rotate-90" aria-hidden>
              &rarr;
            </span>
          )}
        </div>
      ))}
    </div>
  );
}
