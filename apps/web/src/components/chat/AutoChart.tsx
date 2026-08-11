"use client";

import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

export function AutoChart({
  data,
  valueLabel,
}: {
  data: { name: string; value: number }[];
  valueLabel: string;
}) {
  if (data.length === 0) return null;
  // Chart sits inside a chat bubble capped at 85% width, so even a modest
  // bar count runs out of horizontal room for a label like "LAX 2023" -
  // count alone (the old `> 6` cutoff) isn't a reliable signal once bars
  // carry a year suffix. Angle a bit more aggressively so real device
  // widths (mobile chat bubble down to ~200px of plot area) still separate
  // adjacent labels instead of stacking them illegibly.
  const angled = data.length > 4;
  // Some agent answers use a full name ("Rhode Island T.F. Green
  // International Airport") rather than a code - even angled, that overruns
  // the fixed label height and clips against the chart edge. Truncate the
  // ON-AXIS text only; the Tooltip below still reads the untouched `name`.
  const truncateTick = (value: string) => (value.length > 11 ? `${value.slice(0, 10)}…` : value);
  return (
    <div className="mt-2 h-56 w-full rounded-lg border border-slate-200 bg-white p-3">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 12, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          <XAxis
            dataKey="name"
            tick={{ fontSize: angled ? 10 : 11, fill: "#475569" }}
            tickFormatter={truncateTick}
            interval={0}
            angle={angled ? -60 : 0}
            textAnchor={angled ? "end" : "middle"}
            height={angled ? 56 : 24}
          />
          <YAxis tick={{ fontSize: 11, fill: "#475569" }} width={40} />
          <Tooltip
            formatter={(value) => [value, valueLabel]}
            contentStyle={{ fontSize: 12, borderRadius: 8, borderColor: "#e2e8f0" }}
          />
          <Bar dataKey="value" fill="#0f766e" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
