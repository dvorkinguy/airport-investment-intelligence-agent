import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Airport Investment Intelligence Agent",
  description:
    "Ask investment questions about US airport modernization and expansion. Every number traces to public aviation data.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-white text-slate-900 antialiased">
        <header className="flex h-14 items-center justify-between border-b border-slate-200 px-4 md:px-8">
          <Link href="/" className="text-sm font-semibold tracking-tight text-slate-900">
            Airport Investment Intelligence Agent
          </Link>
          <nav className="flex items-center gap-4 text-sm">
            <Link href="/chat" className="text-slate-600 hover:text-slate-900">
              Chat
            </Link>
            {/* Tier 2: Clerk <UserButton /> slot - auth not wired in this window */}
          </nav>
        </header>
        {children}
      </body>
    </html>
  );
}
