import type { Metadata } from "next";
import Link from "next/link";
import { ClerkProvider, SignedIn, SignedOut, SignInButton, UserButton } from "@clerk/nextjs";
import { isClerkEnabled } from "@/lib/clerk-config";
import "./globals.css";

export const metadata: Metadata = {
  title: "Airport Investment Intelligence Agent",
  description:
    "Ask investment questions about US airport modernization and expansion. Every number traces to public aviation data.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const clerkEnabled = isClerkEnabled();

  const page = (
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
            {clerkEnabled && (
              <>
                <SignedIn>
                  <UserButton afterSignOutUrl="/" />
                </SignedIn>
                <SignedOut>
                  <SignInButton mode="modal">
                    <button
                      type="button"
                      className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
                    >
                      Sign in
                    </button>
                  </SignInButton>
                </SignedOut>
              </>
            )}
          </nav>
        </header>
        {children}
      </body>
    </html>
  );

  // ClerkProvider wraps the whole <html> tree (Clerk's own documented
  // pattern), and only exists in the tree at all when both keys are set -
  // when disabled, `page` renders standalone with no Clerk component ever
  // instantiated.
  return clerkEnabled ? <ClerkProvider>{page}</ClerkProvider> : page;
}
