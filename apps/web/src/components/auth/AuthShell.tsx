import Link from "next/link";
import type { ReactNode } from "react";
import { BrandMark } from "@/components/BrandMark";

export function AuthShell({ children }: { children: ReactNode }) {
  return (
    <main className="mx-auto flex min-h-[calc(100vh-3.5rem)] max-w-md flex-col items-center justify-center px-4 py-12 md:px-8">
      <div className="flex flex-col items-center text-center">
        <Link href="/" className="flex items-center gap-2 text-base font-semibold tracking-tight text-slate-900">
          <BrandMark className="h-5 w-5 shrink-0" />
          Airport Investment Intelligence Agent
        </Link>
        <p className="mt-1.5 text-sm text-slate-500">Ranked, explained, number-backed airport analysis</p>
      </div>

      <div className="mt-8 w-full">{children}</div>

      <p className="mt-6 max-w-sm text-center text-xs text-slate-400">
        We log your account email and the questions you ask. We never sell your data.
      </p>
      <Link href="/" className="mt-3 text-xs text-slate-400 hover:text-slate-600">
        Back to the landing page
      </Link>
    </main>
  );
}
