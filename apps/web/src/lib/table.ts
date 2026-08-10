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

/** First column where every row's value looks numeric, or -1 if none. */
export function findNumericColumn(headers: string[], rows: string[][]): number {
  if (rows.length === 0) return -1;
  for (let col = 0; col < headers.length; col++) {
    if (rows.every((row) => isNumericCell(row[col] ?? ""))) return col;
  }
  return -1;
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
