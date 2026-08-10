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
  const angled = data.length > 6;
  return (
    <div className="mt-2 h-56 w-full rounded-lg border border-slate-200 bg-white p-3">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 12, left: 0, bottom: 4 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          <XAxis
            dataKey="name"
            tick={{ fontSize: 11, fill: "#475569" }}
            interval={0}
            angle={angled ? -30 : 0}
            textAnchor={angled ? "end" : "middle"}
            height={angled ? 44 : 24}
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
