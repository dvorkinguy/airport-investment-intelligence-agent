import type { ChatMessage } from "@/lib/types";
import { MarkdownMessage } from "./MarkdownMessage";
import { AssumptionsBlock } from "./AssumptionsBlock";
import { ToolActivity } from "./ToolActivity";
import { FollowUpChips } from "./FollowUpChips";
import { ReadAloudToggle } from "./ReadAloudToggle";

export function MessageBubble({
  message,
  onFollowUp,
}: {
  message: ChatMessage;
  onFollowUp: (text: string) => void;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-2xl rounded-br-sm bg-slate-900 px-4 py-2.5 text-sm text-white">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-3 shadow-sm">
        {message.toolActivity && <ToolActivity entries={message.toolActivity} />}
        {message.content ? <MarkdownMessage content={message.content} /> : message.streaming ? <TypingDots /> : null}
        {message.errored && <p className="text-sm text-red-600">Something went wrong answering this one. Try again.</p>}
        {!message.streaming && message.content && <ReadAloudToggle text={message.content} />}
        {message.assumptions && message.assumptions.length > 0 && <AssumptionsBlock items={message.assumptions} />}
        {message.followUps && message.followUps.length > 0 && (
          <FollowUpChips items={message.followUps} onSelect={onFollowUp} />
        )}
      </div>
    </div>
  );
}

function TypingDots() {
  return (
    <div className="flex gap-1 py-1">
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-300 [animation-delay:-0.3s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-300 [animation-delay:-0.15s]" />
      <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-slate-300" />
    </div>
  );
}
