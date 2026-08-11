export function FollowUpChips({ items, onSelect }: { items: string[]; onSelect: (text: string) => void }) {
  if (items.length === 0) return null;
  return (
    <div data-testid="follow-up-chips" className="mt-3 flex flex-col items-start gap-2 sm:flex-row sm:flex-wrap">
      {items.map((item, i) => (
        <button
          key={i}
          type="button"
          onClick={() => onSelect(item)}
          className="w-fit max-w-full break-words rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-medium text-emerald-700 hover:bg-emerald-100"
        >
          {item}
        </button>
      ))}
    </div>
  );
}
