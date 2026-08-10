import type { ThreadRecord } from "./types";

const STORAGE_KEY = "aiia.threads.v1";

function readAll(): ThreadRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as ThreadRecord[]) : [];
  } catch {
    return [];
  }
}

function writeAll(threads: ThreadRecord[]): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(threads));
}

export function listThreads(): ThreadRecord[] {
  return readAll().sort((a, b) => (a.createdAt < b.createdAt ? 1 : -1));
}

export function getThread(id: string): ThreadRecord | undefined {
  return readAll().find((t) => t.id === id);
}

export function upsertThread(thread: ThreadRecord): void {
  const all = readAll();
  const idx = all.findIndex((t) => t.id === thread.id);
  if (idx === -1) all.push(thread);
  else all[idx] = thread;
  writeAll(all);
}
