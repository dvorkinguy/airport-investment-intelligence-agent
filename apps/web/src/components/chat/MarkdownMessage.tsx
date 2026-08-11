import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { TableBlock } from "./TableBlock";

const components: Components = {
  table: TableBlock,
  thead: ({ node, ...rest }) => {
    void node;
    return <thead className="bg-slate-50" {...rest} />;
  },
  tbody: ({ node, ...rest }) => {
    void node;
    return <tbody className="divide-y divide-slate-100" {...rest} />;
  },
  th: ({ node, className, ...rest }) => {
    void node;
    return (
      <th
        className={[
          "border-b border-slate-200 px-3 py-2 text-left font-semibold text-slate-700 lg:px-2 lg:py-1.5",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
        {...rest}
      />
    );
  },
  td: ({ node, ...rest }) => {
    void node;
    return <td className="px-3 py-2 align-top text-slate-600 lg:px-2 lg:py-1.5" {...rest} />;
  },
  a: ({ node, ...rest }) => {
    void node;
    return <a className="text-emerald-700 underline underline-offset-2" target="_blank" rel="noreferrer" {...rest} />;
  },
  code: ({ node, ...rest }) => {
    void node;
    return <code className="rounded bg-slate-100 px-1 py-0.5 text-[0.85em]" {...rest} />;
  },
  p: ({ node, ...rest }) => {
    void node;
    return <p className="leading-relaxed" {...rest} />;
  },
  ul: ({ node, ...rest }) => {
    void node;
    return <ul className="list-disc space-y-1 pl-5" {...rest} />;
  },
  ol: ({ node, ...rest }) => {
    void node;
    return <ol className="list-decimal space-y-1 pl-5" {...rest} />;
  },
  strong: ({ node, ...rest }) => {
    void node;
    return <strong className="font-semibold text-slate-800" {...rest} />;
  },
};

/**
 * The model streams prose, then a heading, in one run-on line -
 * "...concentration:## Answer" - which isn't valid ATX heading syntax (a
 * "#" only starts a heading at the start of a line), so it rendered as
 * literal text. Insert the paragraph break the model didn't. Frontend-only;
 * the backend's raw stream is untouched.
 */
function fixMidLineHeadings(content: string): string {
  return content.replace(/([^\n])(#{1,6} )/g, "$1\n\n$2");
}

export function MarkdownMessage({ content }: { content: string }) {
  return (
    <div className="max-w-none break-words text-[0.95rem] text-slate-700">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {fixMidLineHeadings(content)}
      </ReactMarkdown>
    </div>
  );
}
