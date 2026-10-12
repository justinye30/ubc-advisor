import { Close, Info, Mark, Plus } from "./Icons.jsx";

/**
 * Left rail: the app, a fresh start, example questions, and the disclaimer.
 * A fixed column from md up; below that, a drawer opened from the top bar.
 */
export default function Sidebar({ examples, onAsk, onNewChat, canReset, busy, open, onClose, mock }) {
  return (
    <>
      {open && (
        <div className="fixed inset-0 z-30 bg-black/60 md:hidden" onClick={onClose} aria-hidden="true" />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-72 flex-col border-r border-sidebar-rule bg-sidebar transition-transform md:static md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
        aria-label="Sidebar"
      >
        <div className="flex items-center gap-2.5 px-4 pt-4 pb-3">
          <Mark />
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-semibold tracking-tight">UBC Course Advisor</p>
            <p className="truncate text-xs text-muted">2026/27 Vancouver Calendar</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-1.5 text-muted hover:bg-sidebar-hover hover:text-ink md:hidden" aria-label="Close sidebar">
            <Close className="size-5" />
          </button>
        </div>

        <div className="px-3">
          <button
            type="button"
            onClick={onNewChat}
            disabled={!canReset}
            className="flex w-full items-center gap-2 rounded-lg border border-sidebar-rule px-3 py-2 text-sm font-medium hover:bg-sidebar-hover disabled:opacity-40 disabled:hover:bg-transparent"
          >
            <Plus className="size-4" />
            New chat
          </button>
        </div>

        <nav className="mt-6 min-h-0 flex-1 overflow-y-auto px-3" aria-labelledby="try-asking">
          <h2 id="try-asking" className="px-2 text-xs font-semibold uppercase tracking-wider text-muted">
            Try asking
          </h2>
          <ul className="mt-2 space-y-0.5">
            {examples.map((q) => (
              <li key={q}>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onAsk(q)}
                  className="w-full rounded-lg px-2 py-2 text-left text-sm leading-snug text-ink/85 hover:bg-sidebar-hover hover:text-ink disabled:opacity-40 disabled:hover:bg-transparent"
                >
                  {q}
                </button>
              </li>
            ))}
          </ul>
        </nav>

        <div className="space-y-3 p-3">
          {mock && (
            <p className="rounded-lg bg-unsure/10 px-3 py-2 text-xs font-semibold text-unsure">
              Mock mode: canned answers, no API calls
            </p>
          )}
          <div className="flex gap-2.5 rounded-lg border border-sidebar-rule bg-black/15 p-3 text-xs leading-relaxed text-muted">
            <Info className="mt-px size-4 shrink-0 text-unsure" />
            <p>
              <span className="font-semibold text-ink">Unofficial, not academic advising.</span> Answers come
              from the Academic Calendar, which is authoritative; instructors can waive prerequisites.
              Confirm decisions with an advisor.
            </p>
          </div>
        </div>
      </aside>
    </>
  );
}
