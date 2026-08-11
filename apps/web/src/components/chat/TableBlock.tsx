"use client";

import {
  Children,
  cloneElement,
  isValidElement,
  useMemo,
  useState,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
} from "react";
import {
  extractTableMatrix,
  findChartColumns,
  parseNumericCell,
  sortPermutation,
  type HastNode,
  type SortState,
} from "@/lib/table";
import { TableActions } from "./TableActions";
import { AutoChart } from "./AutoChart";

const MAX_CHART_ROWS = 12;

/**
 * Replaces react-markdown's default `table` renderer. Reads the raw hast
 * node to build a plain string matrix (for Copy/CSV/chart/sort) while still
 * rendering the already-formatted `children` for the visible table, so
 * inline markdown inside cells (bold, links) is preserved.
 */
export function TableBlock({ node, children }: { node?: unknown; children?: ReactNode }) {
  const { headers, rows } = useMemo(() => extractTableMatrix(node as HastNode | undefined), [node]);
  const [sort, setSort] = useState<SortState>({ col: null, direction: null });

  // Chart always reads the ORIGINAL row order - a sort is a display/export
  // preference, not a re-ranking of what the agent answered.
  const { metricCol, labelCol, yearCol } = useMemo(() => findChartColumns(headers, rows), [headers, rows]);
  const showChart = metricCol !== -1 && rows.length > 0 && rows.length <= MAX_CHART_ROWS;
  const chartData = showChart
    ? rows.map((row) => {
        const year = yearCol !== -1 ? row[yearCol] : undefined;
        let name: string;
        if (labelCol !== -1) {
          const identifier = row[labelCol] ?? "";
          name = year ? `${identifier} ${year}` : identifier;
        } else {
          // No text identifier column (e.g. a bare Year + metric table) -
          // label by year alone rather than inventing a fake identifier.
          name = year ?? "";
        }
        return { name, value: parseNumericCell(row[metricCol] ?? "0") };
      })
    : [];

  const permutation = useMemo(
    () => (sort.col === null || sort.direction === null ? rows.map((_, i) => i) : sortPermutation(rows, sort.col, sort.direction)),
    [rows, sort],
  );
  const sortedRows = useMemo(() => permutation.map((i) => rows[i]), [permutation, rows]);

  function handleHeaderClick(col: number) {
    setSort((prev) => {
      if (prev.col !== col) return { col, direction: "asc" };
      if (prev.direction === "asc") return { col, direction: "desc" };
      return { col: null, direction: null }; // third click - back to original order
    });
  }

  const kids = Children.toArray(children) as ReactNode[];
  const [theadEl, tbodyEl] = kids;
  const tableBody =
    isValidElement(theadEl) && isValidElement(tbodyEl)
      ? applySort(theadEl, tbodyEl, sort, permutation, handleHeaderClick)
      : children;

  return (
    <div className="my-3">
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full min-w-[420px] border-collapse text-sm">{tableBody}</table>
      </div>
      <TableActions headers={headers} rows={sortedRows} filenameHint="airport-data" />
      {showChart && <AutoChart data={chartData} valueLabel={headers[metricCol] ?? "value"} />}
    </div>
  );
}

/**
 * Clones the already-rendered thead/tbody elements to add click-to-sort
 * headers and reorder the body's <tr> elements - without touching their
 * inner (already markdown-formatted) content.
 */
function applySort(
  theadEl: ReactElement,
  tbodyEl: ReactElement,
  sort: SortState,
  permutation: number[],
  onHeaderClick: (col: number) => void,
): ReactNode {
  const headRow = (theadEl.props as { children?: ReactNode }).children;
  const bodyRows = Children.toArray((tbodyEl.props as { children?: ReactNode }).children);
  if (!isValidElement(headRow)) return [theadEl, tbodyEl];

  const thCells = Children.toArray((headRow.props as { children?: ReactNode }).children);
  const sortedHeadRow = cloneElement(
    headRow,
    {},
    thCells.map((thNode, col) => {
      if (!isValidElement(thNode)) return thNode;
      const th = thNode as ReactElement<{ children?: ReactNode }>;
      const active = sort.col === col && sort.direction !== null;
      return cloneElement(th, {
        key: th.key ?? col,
        children: (
          <span
            role="button"
            tabIndex={0}
            onClick={() => onHeaderClick(col)}
            onKeyDown={(e: KeyboardEvent) => {
              if (e.key === "Enter" || e.key === " ") onHeaderClick(col);
            }}
            className="inline-flex cursor-pointer select-none items-center gap-1 hover:text-slate-900"
          >
            {(th.props as { children?: ReactNode }).children}
            {/* Fixed-width slot rendered in every state (rest/asc/desc) so the
                header's own width never shifts when sort state changes. */}
            <span className="inline-flex w-3 shrink-0 items-center justify-center">
              <SortIndicator direction={active ? sort.direction : null} />
            </span>
          </span>
        ),
      });
    }),
  );

  const reorderedBodyRows = permutation.map((i) => bodyRows[i]).filter(Boolean);

  return [cloneElement(theadEl, {}, sortedHeadRow), cloneElement(tbodyEl, {}, reorderedBodyRows)];
}

/**
 * Resting state (direction=null): stacked up/down chevrons at low opacity -
 * discoverable before the first click. Active state: a single chevron
 * pointing the current sort direction, full weight. Same viewBox/stroke
 * geometry in both so the glyph never changes size, only shape.
 */
function SortIndicator({ direction }: { direction: SortState["direction"] }) {
  if (direction === null) {
    return (
      <svg viewBox="0 0 12 12" width="10" height="10" fill="none" aria-hidden="true" className="text-slate-400 opacity-40">
        <path d="M3 5.5 6 2.5 9 5.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M3 6.5 6 9.5 9 6.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 12 12" width="10" height="10" fill="none" aria-hidden="true" className="text-slate-500">
      <path
        d={direction === "asc" ? "M3 7 6 4 9 7" : "M3 5 6 8 9 5"}
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
