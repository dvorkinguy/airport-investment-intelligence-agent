import Link from "next/link";

export function QuestionCard({ question }: { question: string }) {
  return (
    <Link
      href={`/chat?q=${encodeURIComponent(question)}`}
      className="block rounded-xl border border-slate-200 bg-white px-4 py-3.5 text-left text-sm text-slate-700 shadow-sm transition hover:border-emerald-300 hover:shadow-md"
    >
      {question}
    </Link>
  );
}
