"use client";

import {
  Children,
  cloneElement,
  isValidElement,
  useMemo,
  useState,
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
      {/* min-w-[420px] + overflow-x-auto is the mobile fallback (unchanged: a
          narrow viewport still gets a real horizontal scroll). At lg+, the
          table switches to a fixed layout sized to its container - columns
          split the available width evenly and wrap instead of forcing a
          desktop scrollbar. (Tried shrink-to-content on numeric columns via
          w-px first - table-fixed takes that as a literal 1px column and
          overflows the content into its neighbour instead of reflowing, so
          every numeric column overlapped the next. Reverted; even columns
          plus wrapping is what actually renders correctly.) */}
      <div className="overflow-x-auto rounded-lg border border-slate-200">
        <table className="w-full min-w-[420px] border-collapse text-sm lg:min-w-0 lg:table-fixed">{tableBody}</table>
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
          <button
            type="button"
            onClick={() => onHeaderClick(col)}
            className="-mx-1.5 -my-0.5 inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-left font-semibold hover:bg-slate-100 hover:text-slate-900"
          >
            {(th.props as { children?: ReactNode }).children}
            <SortIndicator direction={active ? sort.direction : null} />
          </button>
        ),
      });
    }),
  );

  const reorderedBodyRows = permutation.map((i) => bodyRows[i]).filter(Boolean);

  return [cloneElement(theadEl, {}, sortedHeadRow), cloneElement(tbodyEl, {}, reorderedBodyRows)];
}

/**
 * Bulletproof TanStack/shadcn header pattern: rendered in the initial React
 * output (no client-only mount, nothing pops in after the fact). Resting
 * state is a single 16px "arrows up-down" glyph at a readable muted slate
 * (never below ~60% opacity - a 40%, 10px stacked-chevron version read as
 * near-invisible dots in live use). Active state swaps to a single, darker
 * arrow pointing the current direction. Same 16px box in every state, so
 * the header's width never shifts across rest/asc/desc.
 */
function SortIndicator({ direction }: { direction: SortState["direction"] }) {
  if (direction === null) {
    return (
      <svg viewBox="0 0 16 16" width="16" height="16" fill="none" aria-hidden="true" className="shrink-0 text-slate-400">
        <path d="M4.5 6.5 8 3l3.5 3.5M4.5 9.5 8 13l3.5-3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" fill="none" aria-hidden="true" className="shrink-0 text-slate-700">
      <path
        d={direction === "asc" ? "M4 10l4-4 4 4" : "M4 6l4 4 4-4"}
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
