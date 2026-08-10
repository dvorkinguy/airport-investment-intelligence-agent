export function BackendDownBanner({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
      <span>Can&apos;t reach the agent backend right now. Start it locally or check the deployment.</span>
      <button
        type="button"
        onClick={onRetry}
        className="shrink-0 rounded-md border border-amber-300 bg-white px-2.5 py-1 text-xs font-medium text-amber-800 hover:bg-amber-100"
      >
        Retry
      </button>
    </div>
  );
}
