const MAX = 500; // matches the API's limit, so the server never has to reject length

export default function AskForm({ value, onChange, onSubmit, onCancel, pending }) {
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
    <form onSubmit={send} className="mt-6">
      <label htmlFor="question" className="font-serif text-lg">
        Ask about a course or a rule
      </label>
      <textarea
        id="question"
        rows={3}
        maxLength={MAX}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        placeholder="I got 72 in MATH 226 and passed CPSC 210. Can I take CPSC 221?"
        className="mt-2 block w-full resize-y rounded-md border border-rule bg-surface px-3 py-2.5 text-base leading-relaxed placeholder:text-muted/70"
      />
      <div className="mt-2 flex items-center gap-3">
        {pending ? (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-rule bg-surface px-4 py-2 text-sm font-medium"
          >
            Stop
          </button>
        ) : (
          <button
            type="submit"
            disabled={!value.trim()}
            className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-surface disabled:opacity-40"
          >
            Ask
          </button>
        )}
        {remaining < 80 && (
          <span className={`text-sm ${remaining < 20 ? "text-no" : "text-muted"}`} aria-live="polite">
            {remaining} characters left
          </span>
        )}
      </div>
    </form>
  );
}
