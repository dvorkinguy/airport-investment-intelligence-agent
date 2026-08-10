"use client";

import { useMemo, type ReactNode } from "react";
import { extractTableMatrix, findChartColumns, parseNumericCell, type HastNode } from "@/lib/table";
import { TableActions } from "./TableActions";
import { AutoChart } from "./AutoChart";

const MAX_CHART_ROWS = 12;

/**
 * Replaces react-markdown's default `table` renderer. Reads the raw hast
 * node to build a plain string matrix (for Copy/CSV/chart) while still
 * rendering the already-formatted `children` for the visible table, so
 * inline markdown inside cells (bold, links) is preserved.
 */
export function TableBlock({ node, children }: { node?: unknown; children?: ReactNode }) {
  const { headers, rows } = useMemo(() => extractTableMatrix(node as HastNode | undefined), [node]);
  const { metricCol, labelCol, yearCol } = useMemo(() => findChartColumns(headers, rows), [headers, rows]);
  const showChart = metricCol !== -1 && rows.length > 0 && rows.length <= MAX_CHART_ROWS;
  const chartData = showChart
    ? rows.map((row) => {
        const identifier = row[labelCol] ?? "";
        const year = yearCol !== -1 ? row[yearCol] : undefined;
        return { name: year ? `${identifier} ${year}` : identifier, value: parseNumericCell(row[metricCol] ?? "0") };
      })
    : [];

  return (
    <div className="my-3">
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full min-w-[420px] border-collapse text-sm">{children}</table>
      </div>
      <TableActions headers={headers} rows={rows} filenameHint="airport-data" />
      {showChart && <AutoChart data={chartData} valueLabel={headers[metricCol] ?? "value"} />}
    </div>
  );
}
