import type { SVGProps } from "react";

const STEPS = [
  { label: "You", detail: "Ask in plain English", Icon: IconChat },
  { label: "Chat UI", detail: "Next.js, streaming", Icon: IconWindow },
  { label: "Agent", detail: "FastAPI + LangGraph", Icon: IconCpu },
  { label: "SQL views", detail: "Neon Postgres, deterministic", Icon: IconDatabase },
  { label: "Public data", detail: "BTS T-100, on-time, FAA", Icon: IconGlobe },
];

export function ArchitectureDiagram() {
  return (
    <div className="flex flex-col items-stretch gap-2 md:flex-row md:items-start md:justify-between">
      {STEPS.map((step, i) => (
        <div key={step.label} className="flex flex-1 items-center gap-3 md:flex-col md:gap-0">
          <div className="flex flex-1 flex-col items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 py-4 text-center shadow-sm transition hover:border-slate-300 hover:shadow-md">
            <step.Icon className="h-5 w-5 text-slate-400" />
            <div>
              <p className="text-sm font-semibold text-slate-800">{step.label}</p>
              <p className="mt-0.5 text-xs text-slate-500">{step.detail}</p>
            </div>
          </div>
          {i < STEPS.length - 1 && (
            <span className="shrink-0 text-slate-300 md:rotate-90 md:py-1" aria-hidden>
              &rarr;
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function IconChat(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path
        d="M3 5.5A1.5 1.5 0 0 1 4.5 4h11A1.5 1.5 0 0 1 17 5.5v6a1.5 1.5 0 0 1-1.5 1.5H9l-3.5 3v-3H4.5A1.5 1.5 0 0 1 3 11.5v-6Z"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconWindow(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <rect x="3" y="4" width="14" height="12" rx="1.5" stroke="currentColor" strokeWidth="1.3" />
      <path d="M3 7.5h14" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

function IconCpu(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <rect x="6" y="6" width="8" height="8" rx="1.2" stroke="currentColor" strokeWidth="1.3" />
      <path
        d="M10 2.5v2M10 15.5v2M2.5 10h2M15.5 10h2M4.5 4.5l1.4 1.4M14.1 14.1l1.4 1.4M4.5 15.5l1.4-1.4M14.1 5.9l1.4-1.4"
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </svg>
  );
}

function IconDatabase(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <ellipse cx="10" cy="5" rx="6" ry="2.3" stroke="currentColor" strokeWidth="1.3" />
      <path d="M4 5v10c0 1.27 2.69 2.3 6 2.3s6-1.03 6-2.3V5" stroke="currentColor" strokeWidth="1.3" />
      <path d="M4 10c0 1.27 2.69 2.3 6 2.3s6-1.03 6-2.3" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}

function IconGlobe(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.3" />
      <path d="M3 10h14M10 3c2.2 2 2.2 12 0 14M10 3c-2.2 2-2.2 12 0 14" stroke="currentColor" strokeWidth="1.3" />
    </svg>
  );
}
