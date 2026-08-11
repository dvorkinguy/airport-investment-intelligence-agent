import { toCsv } from "./table";
import type { ChatMessage } from "./types";

function splitTableRow(line: string): string[] {
  let trimmed = line.trim();
  if (trimmed.startsWith("|")) trimmed = trimmed.slice(1);
  if (trimmed.endsWith("|")) trimmed = trimmed.slice(0, -1);
  return trimmed.split("|").map((cell) => cell.trim());
}

/** CSV has no bold/italic/code concept - a cell pasted into a spreadsheet
 * should read "LAX", not "**LAX**". The Markdown table itself keeps the
 * original formatting; only the CSV block strips it. */
function stripEmphasis(cell: string): string {
  return cell.replace(/\*\*(.+?)\*\*|__(.+?)__|\*(.+?)\*|_(.+?)_|`(.+?)`/g, (...m) => m.slice(1, 6).find(Boolean) ?? "");
}

const SEPARATOR_ROW_RE = /^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$/;

function isSeparatorRow(line: string): boolean {
  return SEPARATOR_ROW_RE.test(line.trim());
}

/**
 * Walks a message's raw markdown and, right after every GFM table, appends a
 * fenced ```csv block of the same rows - the markdown table stays readable,
 * the CSV block pastes straight into a spreadsheet without the analyst
 * needing to reconstruct it from the export's Copy/CSV buttons per table.
 */
function annotateTablesWithCsv(content: string): string {
  const lines = content.split("\n");
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const next = lines[i + 1];
    if (line.trim().startsWith("|") && next !== undefined && isSeparatorRow(next)) {
      const headers = splitTableRow(line);
      const bodyLines: string[] = [];
      let j = i + 2;
      while (j < lines.length && lines[j].trim().startsWith("|")) {
        bodyLines.push(lines[j]);
        j++;
      }
      const rows = bodyLines.map(splitTableRow);
      const csvHeaders = headers.map(stripEmphasis);
      const csvRows = rows.map((row) => row.map(stripEmphasis));
      out.push(line, next, ...bodyLines, "", "```csv", toCsv(csvHeaders, csvRows), "```", "");
      i = j;
      continue;
    }
    out.push(line);
    i++;
  }
  return out.join("\n");
}

function slugify(text: string): string {
  const slug = text
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 60);
  return slug || "thread";
}

export function exportThreadFilename(title: string): string {
  const date = new Date().toISOString().slice(0, 10);
  return `airport-intel-${slugify(title)}-${date}.md`;
}

export function exportThreadMarkdown(title: string, messages: ChatMessage[]): string {
  const parts: string[] = [`# ${title}`, ""];
  for (const m of messages) {
    if (m.role === "user") {
      parts.push(`## Q: ${m.content}`, "");
      continue;
    }
    if (m.content.trim()) {
      parts.push(annotateTablesWithCsv(m.content), "");
    }
    if (m.assumptions && m.assumptions.length > 0) {
      parts.push("**Assumptions & sources**", "", ...m.assumptions.map((a) => `- ${a}`), "");
    }
  }
  return parts.join("\n");
}

/** Client-side only - no backend call. Same Blob-download pattern as the
 * per-table CSV button in TableActions. */
export function downloadThreadExport(title: string, messages: ChatMessage[]): void {
  const blob = new Blob([exportThreadMarkdown(title, messages)], { type: "text/markdown;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = exportThreadFilename(title);
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
