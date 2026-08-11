import type { ThreadRecord } from "./types";

// Pre-fix, every browser shared this one unnamespaced key - a second Clerk
// user signing in on the same browser saw the first user's threads. Every
// read/write below is namespaced by userId (the caller passes Clerk's
// userId, or the literal "anonymous" in authless/signed-out mode); this
// legacy key is only ever touched once, by migrateLegacyOnce, to fold
// whatever it holds into the first user who loads post-fix and then delete
// it - so it can never leak to a second user again.
const LEGACY_KEY = "aiia.threads.v1";

function storageKey(userId: string): string {
  return `aiia.threads.v1:${userId}`;
}

function migrateLegacyOnce(userId: string): void {
  const legacy = window.localStorage.getItem(LEGACY_KEY);
  if (legacy === null) return;
  const key = storageKey(userId);
  if (window.localStorage.getItem(key) === null) {
    window.localStorage.setItem(key, legacy);
  }
  window.localStorage.removeItem(LEGACY_KEY);
}

function readAll(userId: string): ThreadRecord[] {
  if (typeof window === "undefined") return [];
  migrateLegacyOnce(userId);
  try {
    const raw = window.localStorage.getItem(storageKey(userId));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ThreadRecord[]) : [];
  } catch {
    return [];
  }
}

function writeAll(userId: string, threads: ThreadRecord[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(storageKey(userId), JSON.stringify(threads));
}

export function listThreads(userId: string): ThreadRecord[] {
  return readAll(userId).sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
}

export function getThread(userId: string, id: string): ThreadRecord | undefined {
  return readAll(userId).find((t) => t.id === id);
}

export function upsertThread(userId: string, thread: ThreadRecord): void {
  const all = readAll(userId);
  const idx = all.findIndex((t) => t.id === thread.id);
  if (idx === -1) all.push(thread);
  else all[idx] = thread;
  writeAll(userId, all);
}
