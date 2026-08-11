import Link from "next/link";
import { QuestionCard } from "@/components/landing/QuestionCard";
import { ArchitectureDiagram } from "@/components/landing/ArchitectureDiagram";

const EXAM_QUESTIONS = [
  "Which airports in New England are strong candidates for terminal expansion?",
  "Compare congestion at LAX and SNA.",
  "What percentage of flights out of Anchorage are long-haul?",
  "What is the estimated unmet flight demand at SFO, and why?",
];

export default function LandingPage() {
  return (
    <main className="mx-auto max-w-4xl px-4 py-16 md:px-8">
      <section className="text-center">
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900 md:text-4xl">
          Airport Investment Intelligence Agent
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-base text-slate-600 md:text-lg">
          Ask questions like &ldquo;which airports in New England are strong candidates for terminal
          expansion?&rdquo; and get ranked, explained, number-backed answers - every score traceable to
          public government data, every assumption stated.
        </p>
        <Link
          href="/chat"
          className="mt-8 inline-flex items-center justify-center rounded-xl bg-slate-900 px-6 py-3 text-sm font-medium text-white hover:bg-slate-800"
        >
          Start asking
        </Link>
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
        <p className="mt-4 text-center">
          <a
            href="/3d"
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-slate-500 underline underline-offset-2 hover:text-slate-700"
          >
            Explore the interactive 3D system map
          </a>
        </p>
      </section>

      <section className="mt-14 rounded-xl border border-slate-200 bg-slate-50 px-5 py-4 text-center text-xs text-slate-500">
        We log your account email and the questions you ask so we can improve answers. We never sell your data.
      </section>

      <footer className="mt-10 pb-6 text-center text-xs text-slate-400">
        Built as a 24-hour technical exercise.
      </footer>
    </main>
  );
}
