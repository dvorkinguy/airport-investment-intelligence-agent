import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { ClerkProvider, Show, SignInButton, UserButton } from "@clerk/nextjs";
import { BrandMark } from "@/components/BrandMark";
import { isClerkEnabled } from "@/lib/clerk-config";
import "./globals.css";

export const metadata: Metadata = {
  title: "Airport Investment Intelligence Agent",
  description:
    "Ask investment questions about US airport modernization and expansion. Every number traces to public aviation data.",
  icons: {
    // SVG first (sizes="any" is the documented trick that gets browsers
    // supporting vector favicons to prefer it); PNG is the fallback for
    // Safari and other browsers that only understand raster favicons.
    icon: [
      { url: "/icon.svg", type: "image/svg+xml", sizes: "any" },
      { url: "/icon.png", type: "image/png", sizes: "64x64" },
    ],
  },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  interactiveWidget: "resizes-content",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const clerkEnabled = isClerkEnabled();

  const content = (
    <>
      <header className="sticky top-0 z-50 flex h-14 items-center justify-between border-b border-slate-200 bg-white/85 pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))] backdrop-blur supports-[backdrop-filter]:bg-white/70 md:pl-[max(2rem,env(safe-area-inset-left))] md:pr-[max(2rem,env(safe-area-inset-right))]">
        <Link
          href="/"
          className="flex min-w-0 items-center gap-2 text-sm font-semibold tracking-tight text-slate-900"
        >
          <BrandMark className="h-5 w-5 shrink-0" />
          <span className="truncate">
            <span className="sm:hidden">Airport Intelligence</span>
            <span className="hidden sm:inline">Airport Investment Intelligence Agent</span>
          </span>
        </Link>
        <nav className="flex items-center gap-3 text-sm sm:gap-5">
          <Link href="/chat" className="text-slate-600 hover:text-slate-900">
            Chat
          </Link>
          <a
            href="/3d"
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-600 hover:text-slate-900"
          >
            3D map
          </a>
          <a
            href="https://github.com/dvorkinguy/airport-investment-intelligence-agent"
            target="_blank"
            rel="noopener noreferrer"
            className="hidden text-slate-600 hover:text-slate-900 md:inline"
          >
            GitHub
          </a>
          {clerkEnabled && (
            <>
              <Show when="signed-in">
                <UserButton />
              </Show>
              <Show when="signed-out">
                <SignInButton mode="modal">
                  <button
                    type="button"
                    className="shrink-0 whitespace-nowrap rounded-lg bg-slate-900 px-3 py-1.5 text-xs font-medium text-white hover:bg-slate-800"
                  >
                    Sign in
                  </button>
                </SignInButton>
              </Show>
            </>
          )}
        </nav>
      </header>
      {children}
    </>
  );

  // ClerkProvider is a child of <body> (Clerk's current documented
  // placement - not a wrapper around <html>), and only exists in the tree
  // at all when both keys are set: when disabled, `content` renders
  // standalone with no Clerk component ever instantiated.
  return (
    <html lang="en">
      <body className="bg-white text-slate-900 antialiased">
        {clerkEnabled ? (
          <ClerkProvider
            signInUrl="/sign-in"
            signUpUrl="/sign-up"
            signInFallbackRedirectUrl="/chat"
            signUpFallbackRedirectUrl="/chat"
          >
            {content}
          </ClerkProvider>
        ) : (
          content
        )}
      </body>
    </html>
  );
}
