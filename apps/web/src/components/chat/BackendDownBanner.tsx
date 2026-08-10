export function BackendDownBanner({ onRetry }: { onRetry: () => void }) {
  // Dev message helps Guy while running locally; production never tells a public
  // visitor to "start it locally" - process.env.NODE_ENV is inlined at build time,
  // so the dev string is dead-code-eliminated from the production bundle.
  const message =
    process.env.NODE_ENV === "production"
      ? "Agent backend not connected yet."
      : "Can't reach the agent backend right now. Start it locally, or check the deployment.";
  return (
    <div className="flex items-center justify-between gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-800">
      <span>{message}</span>
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
