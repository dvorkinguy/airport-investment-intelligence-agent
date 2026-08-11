import Link from "next/link";

export function QuestionCard({ question }: { question: string }) {
  return (
    <Link
      href={`/chat?q=${encodeURIComponent(question)}`}
      className="group flex items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white px-4 py-3.5 text-left text-sm text-slate-700 shadow-sm transition hover:border-emerald-300 hover:shadow-md"
    >
      <span>{question}</span>
      <svg
        viewBox="0 0 16 16"
        width="16"
        height="16"
        fill="none"
        aria-hidden="true"
        className="shrink-0 text-slate-300 transition group-hover:translate-x-0.5 group-hover:text-emerald-500"
      >
        <path d="M4 8h8M9 4.5 12.5 8 9 11.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </Link>
  );
}
