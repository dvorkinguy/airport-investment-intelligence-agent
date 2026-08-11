// Reads the hast (HTML AST) node react-markdown hands custom `table`
// components and turns it into a plain string matrix, for the Copy/CSV
// buttons and the auto-chart - independent of how the cells are styled.

export interface HastNode {
  type: string;
  tagName?: string;
  value?: string;
  children?: HastNode[];
}

function textOf(node?: HastNode): string {
  if (!node) return "";
  if (node.type === "text") return node.value ?? "";
  if (!node.children) return "";
  return node.children.map(textOf).join("");
}

function findAll(node: HastNode | undefined, tagName: string): HastNode[] {
  if (!node?.children) return [];
  const out: HastNode[] = [];
  for (const child of node.children) {
    if (child.tagName === tagName) out.push(child);
    out.push(...findAll(child, tagName));
  }
  return out;
}

export interface TableMatrix {
  headers: string[];
  rows: string[][];
}

export function extractTableMatrix(node?: HastNode): TableMatrix {
  if (!node) return { headers: [], rows: [] };
  const thead = findAll(node, "thead")[0];
  const tbody = findAll(node, "tbody")[0];
  const headers = thead ? findAll(thead, "th").map((cell) => textOf(cell).trim()) : [];
  const rows = tbody
    ? findAll(tbody, "tr").map((tr) => findAll(tr, "td").map((cell) => textOf(cell).trim()))
    : [];
  return { headers, rows };
}

const NUMERIC_RE = /^-?\$?\d[\d,]*(\.\d+)?%?$/;

export function isNumericCell(value: string): boolean {
  return NUMERIC_RE.test(value.trim());
}

export function parseNumericCell(value: string): number {
  return Number(value.replace(/[$,%]/g, ""));
}

const YEAR_HEADER_RE = /^(year|fy|date)$/i;
const RANK_HEADER_RE = /^(rank|#|no\.?)$/i;

function columnValues(rows: string[][], col: number): string[] {
  return rows.map((row) => row[col] ?? "");
}

/** Header says "year", or every value is a bare integer in [1900, 2100]. */
function isYearLikeColumn(header: string, values: string[]): boolean {
  if (YEAR_HEADER_RE.test(header.trim())) return true;
  return values.every((v) => {
    if (!/^\d{4}$/.test(v.trim())) return false;
    const n = Number(v);
    return n >= 1900 && n <= 2100;
  });
}

/** Header says "rank", or every value equals its 1-indexed row position. */
function isRankLikeColumn(header: string, values: string[]): boolean {
  if (RANK_HEADER_RE.test(header.trim())) return true;
  return values.every((v, i) => isNumericCell(v) && parseNumericCell(v) === i + 1);
}

export interface ChartColumns {
  /** Bar height. -1 if no eligible metric column exists. */
  metricCol: number;
  /** Bar identifier (first non-metric, non-year, non-rank column). -1 if every column is numeric - i.e. no text identifier column exists. */
  labelCol: number;
  /** Present when a year/date column exists, so labels can disambiguate a repeated identifier - "LAX 2025". -1 otherwise. */
  yearCol: number;
}

/**
 * Picks which columns feed the auto-chart. Year and rank columns are
 * numeric-looking but meaningless as a bar height (a "Year" or "Rank"
 * column charted as the metric produces a staircase, not an answer) - they
 * are excluded from metric selection even though they'd otherwise pass a
 * plain numeric check. A column named "Score" wins if present; otherwise
 * the first remaining numeric column.
 */
export function findChartColumns(headers: string[], rows: string[][]): ChartColumns {
  if (rows.length === 0 || headers.length === 0) return { metricCol: -1, labelCol: -1, yearCol: -1 };

  let yearCol = -1;
  let rankCol = -1;
  const metricCandidates: number[] = [];

  for (let col = 0; col < headers.length; col++) {
    const values = columnValues(rows, col);
    if (!values.every((v) => isNumericCell(v))) continue;
    if (yearCol === -1 && isYearLikeColumn(headers[col] ?? "", values)) {
      yearCol = col;
      continue;
    }
    if (rankCol === -1 && isRankLikeColumn(headers[col] ?? "", values)) {
      rankCol = col;
      continue;
    }
    metricCandidates.push(col);
  }

  if (metricCandidates.length === 0) return { metricCol: -1, labelCol: -1, yearCol };

  const scoreCol = metricCandidates.find((col) => /^score$/i.test((headers[col] ?? "").trim()));
  const metricCol = scoreCol ?? metricCandidates[0];

  const excluded = new Set([metricCol, yearCol, rankCol]);
  const labelCol = headers.findIndex((_, col) => !excluded.has(col));

  return { metricCol, labelCol, yearCol };
}

function escapeCsv(value: string): string {
  return /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export function toCsv(headers: string[], rows: string[][]): string {
  return [headers, ...rows].map((row) => row.map(escapeCsv).join(",")).join("\n");
}

export function toTsv(headers: string[], rows: string[][]): string {
  return [headers, ...rows].map((row) => row.join("\t")).join("\n");
}

export type SortDirection = "asc" | "desc";

export interface SortState {
  col: number | null;
  direction: SortDirection | null;
}

const PARENTHETICAL_RE = /\([^)]*\)/g;

/**
 * Numeric-aware value for sorting: strips $, commas, %, and any trailing
 * "(annotation)" - "1,186 (unconcentrated)" -> 1186. Returns null when the
 * cleaned value isn't a number, so the caller can fall back to a plain
 * string compare for that column.
 */
export function parseSortValue(value: string): number | null {
  const cleaned = value.replace(PARENTHETICAL_RE, "").replace(/[$,%]/g, "").trim();
  if (cleaned === "") return null;
  const n = Number(cleaned);
  return Number.isFinite(n) ? n : null;
}

/**
 * Row indices in sorted order for the given column. Numeric compare when
 * every value in the column parses via parseSortValue; locale string
 * compare otherwise. Ties keep their original relative order regardless of
 * direction (stable sort).
 */
export function sortPermutation(rows: string[][], col: number, direction: SortDirection): number[] {
  const values = rows.map((row) => row[col] ?? "");
  const allNumeric = values.length > 0 && values.every((v) => parseSortValue(v) !== null);
  const indices = rows.map((_, i) => i);
  indices.sort((ia, ib) => {
    const a = values[ia];
    const b = values[ib];
    const cmp = allNumeric
      ? (parseSortValue(a) as number) - (parseSortValue(b) as number)
      : a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
    return cmp !== 0 ? (direction === "asc" ? cmp : -cmp) : ia - ib;
  });
  return indices;
}
