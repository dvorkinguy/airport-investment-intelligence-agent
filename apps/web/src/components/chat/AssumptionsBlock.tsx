export function AssumptionsBlock({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
      <p className="mb-1 font-medium uppercase tracking-wide text-slate-400">Assumptions &amp; sources</p>
      <ul className="space-y-0.5">
        {items.map((item, i) => (
          <li key={i}>{item}</li>
        ))}
      </ul>
    </div>
  );
}
