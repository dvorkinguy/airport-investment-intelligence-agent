/**
 * Single source of truth for whether Clerk auth is wired up. Both keys must
 * be present together; with either missing the app runs exactly as before -
 * landing and /chat both public, no Clerk code path ever executes.
 *
 * Checked from server contexts only (middleware, layout, chat/page) - never
 * call this from a client component: CLERK_SECRET_KEY is never in the
 * browser bundle, so it would always read false there.
 */
export function isClerkEnabled(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY && process.env.CLERK_SECRET_KEY);
}
