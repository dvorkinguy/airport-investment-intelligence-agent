import Link from "next/link";
import { QuestionCard } from "@/components/landing/QuestionCard";
import { ArchitectureDiagram } from "@/components/landing/ArchitectureDiagram";
import { AnswerPreviewCard } from "@/components/landing/AnswerPreviewCard";

const EXAM_QUESTIONS = [
  "Which airports in New England are strong candidates for terminal expansion?",
  "Compare congestion at LAX and SNA.",
  "What percentage of flights out of Anchorage are long-haul?",
  "What is the estimated unmet flight demand at SFO, and why?",
];

const BUILT_ON = ["Next.js", "FastAPI + LangGraph", "Neon Postgres", "Cloud Run", "Langfuse", "Clerk"];

export default function LandingPage() {
  return (
    <main className="mx-auto max-w-4xl px-4 md:px-8">
      <section className="relative -mx-4 overflow-hidden px-4 pt-16 text-center md:-mx-8 md:px-8 md:pt-20">
        <div className="hero-grid pointer-events-none absolute inset-0 -z-10" aria-hidden="true" />
        <h1 className="relative mx-auto max-w-2xl text-4xl font-semibold tracking-tight text-slate-900 sm:text-5xl md:text-6xl lg:text-7xl">
          Airport Investment
          <br />
          Intelligence Agent
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-base text-slate-600 md:text-lg">
          Ranked, explained, number-backed answers to airport investment questions - every score traceable to
          public data, every assumption stated.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link
            href="/chat"
            className="inline-flex items-center justify-center rounded-xl bg-slate-900 px-6 py-3 text-sm font-medium text-white transition hover:bg-slate-800"
          >
            Start asking
          </Link>
          <a
            href="/3d"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center justify-center rounded-xl border border-slate-300 px-6 py-3 text-sm font-medium text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
          >
            Explore the 3D system map
          </a>
        </div>

        <AnswerPreviewCard />
      </section>

      <section className="mt-14 flex flex-wrap items-center justify-center gap-x-6 gap-y-2 text-sm text-slate-500">
        <span className="text-slate-400">Built on</span>
        {BUILT_ON.map((name) => (
          <span key={name}>{name}</span>
        ))}
      </section>

      <section className="mt-14">
        <h2 className="text-center text-sm font-medium uppercase tracking-wide text-slate-400">
          Try one of the exam questions
        </h2>
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {EXAM_QUESTIONS.map((q) => (
            <QuestionCard key={q} question={q} />
          ))}
        </div>
      </section>

      <section className="mt-16">
        <h2 className="text-center text-sm font-medium uppercase tracking-wide text-slate-400">How it works</h2>
        <div className="mt-6">
          <ArchitectureDiagram />
        </div>
      </section>

      <section className="mt-14 rounded-xl border border-slate-200 bg-slate-50 px-5 py-4 text-center text-xs text-slate-500">
        We log your account email and the questions you ask so we can improve answers. We never sell your data.
      </section>

      <footer className="mt-10 flex flex-col items-center gap-3 pb-8 text-xs text-slate-400">
        <nav className="flex items-center gap-4">
          <Link href="/chat" className="hover:text-slate-600">
            Chat
          </Link>
          <a href="/3d" target="_blank" rel="noopener noreferrer" className="hover:text-slate-600">
            3D map
          </a>
          <a
            href="https://github.com/dvorkinguy/airport-investment-intelligence-agent"
            target="_blank"
            rel="noopener noreferrer"
            className="hover:text-slate-600"
          >
            GitHub
          </a>
        </nav>
        <p className="text-slate-300">&copy; 2026 Guy Dvorkin. All rights reserved.</p>
      </footer>
    </main>
  );
}
