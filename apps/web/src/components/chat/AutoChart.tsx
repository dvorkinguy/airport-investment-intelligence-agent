"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

// Matches the app's sm: breakpoint (640px) - below it we're inside a phone
// chat bubble with real plot width down to ~200px, above it Tailwind's sm:
// classes already gave the chart room, so behavior there stays exactly as
// it was (see the `isNarrow` gates below - every one of them is a no-op at
// sm+).
function useIsNarrow() {
  const [isNarrow, setIsNarrow] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 639px)");
    setIsNarrow(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setIsNarrow(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return isNarrow;
}

export function AutoChart({
  data,
  valueLabel,
}: {
  data: { name: string; value: number }[];
  valueLabel: string;
}) {
  const isNarrow = useIsNarrow();
  if (data.length === 0) return null;
  // Chart sits inside a chat bubble capped at 85% width, so even a modest
  // bar count runs out of horizontal room for a label like "LAX 2023" -
  // count alone (the old `> 6` cutoff) isn't a reliable signal once bars
  // carry a year suffix. Angle a bit more aggressively so real device
  // widths (mobile chat bubble down to ~200px of plot area) still separate
  // adjacent labels instead of stacking them illegibly. On phone, ticks
  // are already shrunk to just the first token (see `firstTokenTick`
  // below), so angling only kicks in past a more generous bar count.
  const angled = isNarrow ? data.length > 6 : data.length > 4;
  // Some agent answers use a full name ("Rhode Island T.F. Green
  // International Airport") rather than a code - even angled, that overruns
  // the fixed label height and clips against the chart edge. Truncate the
  // ON-AXIS text only; the Tooltip below still reads the untouched `name`.
  const truncateTick = (value: string) => (value.length > 11 ? `${value.slice(0, 10)}…` : value);
  // Phone-only: names like "PWM Portland" collide edge-to-edge even
  // truncated to 10 chars at 4 bars across ~200px of plot. The IATA code
  // (first token) is the part that matters on-axis; the Tooltip still
  // shows the full name on tap.
  const firstTokenTick = (value: string) => value.split(" ")[0];
  const tickFormatter = isNarrow ? firstTokenTick : truncateTick;
  const tickFontSize = isNarrow ? 9 : angled ? 10 : 11;
  return (
    <div data-testid="auto-chart" className="mt-2 h-56 w-full rounded-lg border border-slate-200 bg-white p-3">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 12, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          <XAxis
            dataKey="name"
            tick={{ fontSize: tickFontSize, fill: "#475569" }}
            tickFormatter={tickFormatter}
            interval={0}
            angle={angled ? -60 : 0}
            textAnchor={angled ? "end" : "middle"}
            height={angled ? 56 : 24}
          />
          <YAxis tick={{ fontSize: 11, fill: "#475569" }} width={40} />
          <Tooltip
            cursor={{ fill: "#f1f5f9", fillOpacity: 0.6 }}
            formatter={(value) => [
              <span key="value" style={{ color: "#047857", fontWeight: 600 }}>
                {value}
              </span>,
              valueLabel,
            ]}
            contentStyle={{
              fontSize: 12,
              borderRadius: 8,
              border: "1px solid #e2e8f0",
              boxShadow: "0 4px 12px rgba(15, 23, 42, 0.08)",
              backgroundColor: "#ffffff",
              color: "#475569",
              outline: "none",
            }}
            wrapperStyle={{ outline: "none" }}
            itemStyle={{ color: "#475569", fontSize: 12 }}
            labelStyle={{ color: "#334155", fontWeight: 600, marginBottom: 2 }}
          />
          <Bar dataKey="value" fill="#0f766e" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
