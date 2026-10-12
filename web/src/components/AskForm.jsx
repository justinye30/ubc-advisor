import { useLayoutEffect, useRef } from "react";
import { ArrowUp, Stop } from "./Icons.jsx";

const MAX = 500; // matches the API's limit, so the server never has to reject length
const MAX_HEIGHT = 200; // px; past this the box scrolls instead of growing

export default function AskForm({ value, onChange, onSubmit, onCancel, pending }) {
  const box = useRef(null);

  // Grow with the text, like most chat boxes, up to MAX_HEIGHT.
  useLayoutEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_HEIGHT)}px`;
  }, [value]);

  const send = (e) => {
    e.preventDefault();
    if (!pending && value.trim()) onSubmit(value);
  };

  // Enter sends; Shift+Enter adds a line, as in most chat boxes.
  const onKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) send(e);
  };

  const remaining = MAX - value.length;

  return (
    <form onSubmit={send}>
      <label htmlFor="question" className="sr-only">
        Ask about a course or a rule
      </label>
      <div className="rounded-2xl border border-rule bg-surface shadow-lg shadow-black/30 focus-within:border-accent/60">
        <textarea
          ref={box}
          id="question"
          rows={1}
          maxLength={MAX}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="Ask about a course or a rule…"
          className="block max-h-[200px] w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-[15px] leading-relaxed outline-none placeholder:text-muted/80"
        />
        <div className="flex items-center gap-3 px-3 pb-3">
          <span className="text-xs text-muted">
            {remaining < 80 ? (
              <span className={`tabular-nums ${remaining < 20 ? "text-no" : ""}`} aria-live="polite">
                {remaining} characters left
              </span>
            ) : (
              <span className="hidden sm:inline">Enter to send, Shift + Enter for a new line</span>
            )}
          </span>
          {pending ? (
            <button
              type="button"
              onClick={onCancel}
              aria-label="Stop"
              title="Stop"
              className="ml-auto grid size-9 place-items-center rounded-full bg-ink text-ground hover:bg-ink/85"
            >
              <Stop className="size-4" />
            </button>
          ) : (
            <button
              type="submit"
              disabled={!value.trim()}
              aria-label="Ask"
              title="Ask"
              className="ml-auto grid size-9 place-items-center rounded-full bg-accent-strong text-white hover:bg-accent-strong/85 disabled:bg-bubble disabled:text-muted"
            >
              <ArrowUp className="size-5" />
            </button>
          )}
        </div>
      </div>
    </form>
  );
}
