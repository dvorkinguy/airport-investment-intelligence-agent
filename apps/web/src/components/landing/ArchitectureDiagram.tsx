import { Fragment, type SVGProps } from "react";

const STEPS = [
  { label: "You", detail: "Ask in plain English", Icon: IconChat },
  { label: "Chat UI", detail: "Next.js, streaming", Icon: IconWindow },
  { label: "Agent", detail: "FastAPI + LangGraph", Icon: IconCpu },
  { label: "SQL views", detail: "Neon Postgres, deterministic", Icon: IconDatabase },
  { label: "Public data", detail: "BTS T-100, on-time, FAA", Icon: IconGlobe },
];

// Flat card/connector/card/... sequence so CSS grid does the axis switch:
// one column on mobile (each item its own row, connector rotated to point
// down) and 5 stretch-height card columns + 4 auto connector columns on
// desktop (connector sits in the row, never below it).
export function ArchitectureDiagram() {
  return (
    <div className="grid grid-cols-1 items-stretch gap-2 md:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr_auto_1fr] md:gap-0">
      {STEPS.map((step, i) => (
        <Fragment key={step.label}>
          <StepCard step={step} />
          {i < STEPS.length - 1 && <StepConnector />}
        </Fragment>
      ))}
    </div>
  );
}

function StepCard({ step }: { step: (typeof STEPS)[number] }) {
  return (
    <div className="flex flex-row items-center gap-3 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-left shadow-sm transition hover:border-emerald-300 hover:shadow-md md:flex-col md:gap-2 md:px-4 md:py-4 md:text-center">
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100 md:h-9 md:w-9">
        <step.Icon className="h-5 w-5 text-slate-500" />
      </span>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-800">{step.label}</p>
        <p className="mt-0.5 text-xs text-slate-500">{step.detail}</p>
      </div>
    </div>
  );
}

function StepConnector() {
  return (
    <div className="flex items-center justify-center md:px-2">
      <svg
        viewBox="0 0 16 16"
        fill="none"
        aria-hidden="true"
        className="h-2.5 w-2.5 shrink-0 rotate-90 text-slate-300 md:h-3.5 md:w-3.5 md:rotate-0"
      >
        <path d="M6 4l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
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
