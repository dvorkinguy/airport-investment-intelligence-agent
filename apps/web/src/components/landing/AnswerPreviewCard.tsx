// Real component preview, not a mock: the border/radius/table classes below
// are the same ones MessageBubble/MarkdownMessage render in the live app.
// Numbers are verified against the deployed backend (2026-08-11), not
// invented - "Compare congestion at LAX and SNA."
export function AnswerPreviewCard() {
  return (
    <div className="mx-auto mt-10 max-w-2xl text-left">
      <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-lg shadow-slate-200/60">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
          <span className="truncate text-xs font-medium text-slate-400">Compare congestion at LAX and SNA.</span>
          <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true" />
            Live demo
          </span>
        </div>
        <div className="px-5 py-4">
          <p className="text-sm leading-relaxed text-slate-700">
            LAX runs hotter than SNA: a higher delay rate and longer average delays across the years measured.
          </p>
          <div className="mt-4 overflow-hidden rounded-lg border border-slate-200">
            <table className="w-full border-collapse text-sm">
              <thead className="bg-slate-50">
                <tr>
                  <th className="border-b border-slate-200 px-3 py-2 text-left font-semibold text-slate-700">Airport</th>
                  <th className="border-b border-slate-200 px-3 py-2 text-left font-semibold text-slate-700">Delay rate</th>
                  <th className="border-b border-slate-200 px-3 py-2 text-left font-semibold text-slate-700">Avg delay</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                <tr>
                  <td className="px-3 py-2 text-slate-600">LAX</td>
                  <td className="px-3 py-2 text-slate-600">20.7%</td>
                  <td className="px-3 py-2 text-slate-600">15.1 min</td>
                </tr>
                <tr>
                  <td className="px-3 py-2 text-slate-600">SNA</td>
                  <td className="px-3 py-2 text-slate-600">18.9%</td>
                  <td className="px-3 py-2 text-slate-600">11.0 min</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
