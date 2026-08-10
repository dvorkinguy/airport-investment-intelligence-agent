export interface ParsedAnswer {
  body: string;
  followUps: string[];
}

// Matches a trailing "Follow-ups:" (optionally bold) heading followed by a
// bullet list, so it can be stripped out of the rendered markdown and shown
// as chips instead.
const FOLLOWUP_RE = /\n{1,2}(?:\*\*)?Follow-ups?:?(?:\*\*)?\s*\n((?:[-*]\s+.+\n?)+)\s*$/i;

export function extractFollowUps(markdown: string): ParsedAnswer {
  const match = markdown.match(FOLLOWUP_RE);
  if (!match || match.index === undefined) {
    return { body: markdown.trimEnd(), followUps: [] };
  }
  const items = match[1]
    .split("\n")
    .map((line) => line.replace(/^[-*]\s+/, "").trim())
    .filter(Boolean);
  return { body: markdown.slice(0, match.index).trimEnd(), followUps: items };
}

export const DEFAULT_FOLLOW_UPS = [
  "Which New England airports are strong terminal-expansion candidates?",
  "Compare congestion at LAX and SNA.",
  "What is the estimated unmet demand at SFO, and why?",
];
