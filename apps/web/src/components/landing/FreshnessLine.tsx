"use client";

import { useEffect, useState } from "react";
import { checkFreshness, type FreshnessStatus } from "@/lib/api";

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return "";
  }
}

// latest_period stays "YYYY-MM" over the wire - that machine form is what
// a script or the next terminal checking this endpoint wants. This line's
// audience is a reviewer, not a script, so it gets the human phrasing;
// manual y/m parsing avoids relying on the non-standard "YYYY-MM" Date
// parse. Falls back to the raw string on anything unexpected rather than
// showing nothing - a slightly technical fallback beats a missing line.
function formatPeriod(period: string): string {
  const match = /^(\d{4})-(\d{2})$/.exec(period);
  if (!match) return period;
  const [, year, month] = match;
  try {
    return new Date(Number(year), Number(month) - 1, 1).toLocaleDateString(undefined, {
      month: "long",
      year: "numeric",
    });
  } catch {
    return period;
  }
}

/**
 * ADR-005: this line is the only place a visitor sees whether the scheduled
 * refresh is actually current, so it renders nothing - no placeholder, no
 * error text - the instant the backend or the ledger cannot answer honestly.
 * Fades in once real data lands rather than reserving space up front, so a
 * "table not created yet" state never leaves a permanent empty gap.
 */
export function FreshnessLine() {
  const [freshness, setFreshness] = useState<FreshnessStatus | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    void checkFreshness(controller.signal).then((status) => {
      if (
        status &&
        status.last_run_status !== "unknown" &&
        status.cadence &&
        status.latest_period &&
        status.last_successful_refresh
      ) {
        setFreshness(status);
      }
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!freshness) return;
    const id = requestAnimationFrame(() => setVisible(true));
    return () => cancelAnimationFrame(id);
  }, [freshness]);

  if (!freshness || !freshness.last_successful_refresh || !freshness.latest_period) return null;
  const date = formatDate(freshness.last_successful_refresh);
  if (!date) return null;

  return (
    <p
      className={`mt-3 text-center text-xs text-slate-400 transition-opacity duration-500 ${
        visible ? "opacity-100" : "opacity-0"
      }`}
    >
      Data as of {formatPeriod(freshness.latest_period)} - checked {freshness.cadence} - last refresh {date}
    </p>
  );
}
