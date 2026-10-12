import { useCallback, useEffect, useRef, useState } from "react";
import { ask, AskError, MOCK } from "./api.js";
import AskForm from "./components/AskForm.jsx";
import Entry from "./components/Entry.jsx";
import { Mark, Menu } from "./components/Icons.jsx";
import Sidebar from "./components/Sidebar.jsx";

const EXAMPLES = import.meta.env.MODE === "mock" ? (await import("./mock.js")).MOCK_QUESTIONS : [
  "I did CPSC 110, 121 and 210. Can I take CPSC 221?",
  "What does CPSC 213 unlock?",
  "Can I retake a course I already passed?",
];

export default function App() {
  // Oldest first, as in a chat. Each entry: { id, question, status, response, error, startedAt }
  const [entries, setEntries] = useState([]);
  const [draft, setDraft] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const controller = useRef(null);
  const nextId = useRef(1);
  const scroller = useRef(null);
  const latest = useRef(null);

  const pending = entries.some((e) => e.status === "pending");

  const update = (id, patch) =>
    setEntries((all) => all.map((e) => (e.id === id ? { ...e, ...patch } : e)));

  const submit = useCallback(async (question) => {
    const q = question.trim();
    if (!q) return;
    const id = nextId.current++;
    setEntries((all) => [...all, { id, question: q, status: "pending", startedAt: Date.now() }]);
    setDraft("");
    setSidebarOpen(false);

    controller.current = new AbortController();
    try {
      const response = await ask(q, { signal: controller.current.signal });
      update(id, { status: "done", response });
    } catch (err) {
      if (err.name === "AbortError") {
        update(id, { status: "cancelled" });
      } else {
        update(id, { status: "failed", error: err instanceof AskError ? err : new AskError(String(err)) });
      }
    } finally {
      controller.current = null;
    }
  }, []);

  const cancel = () => controller.current?.abort();

  const newChat = () => {
    cancel();
    setEntries([]);
    setDraft("");
    setSidebarOpen(false);
  };

  // A new question scrolls to the top of the chat, so its answer reads
  // downward from the verdict instead of landing at the end of it. Only the
  // chat column scrolls (scrollIntoView would move the whole page too).
  useEffect(() => {
    const box = scroller.current, el = latest.current;
    if (!box || !el) return;
    const top = box.scrollTop + el.getBoundingClientRect().top - box.getBoundingClientRect().top - 24;
    box.scrollTo({ top, behavior: "smooth" });
  }, [entries.length]);

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar
        examples={EXAMPLES}
        onAsk={submit}
        onNewChat={newChat}
        canReset={entries.length > 0 || draft.length > 0}
        busy={pending}
        open={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
        mock={MOCK}
      />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-rule px-3 py-2.5 md:hidden">
          <button type="button" onClick={() => setSidebarOpen(true)} aria-label="Open sidebar"
            className="rounded-md p-1.5 text-muted hover:bg-bubble hover:text-ink">
            <Menu />
          </button>
          <p className="text-sm font-semibold">UBC Course Advisor</p>
        </header>

        <main ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
          {entries.length === 0 ? (
            <Welcome />
          ) : (
            <ol className="mx-auto max-w-3xl space-y-10 px-4 pt-8 pb-10 sm:px-6">
              {entries.map((e, i) => (
                // The newest turn is at least a screen tall, so its question can sit at the top.
                <li key={e.id} ref={i === entries.length - 1 ? latest : null}
                  className={i === entries.length - 1 ? "min-h-[calc(100dvh-16rem)]" : ""}>
                  <Entry entry={e} onAsk={submit} busy={pending} />
                </li>
              ))}
            </ol>
          )}
        </main>

        <div className="mx-auto w-full max-w-3xl px-4 pb-3 sm:px-6">
          <AskForm value={draft} onChange={setDraft} onSubmit={submit} onCancel={cancel} pending={pending} />
          <p className="mt-2 text-center text-xs text-muted">
            Unofficial. The Academic Calendar is authoritative; confirm decisions with an advisor.
          </p>
        </div>
      </div>
    </div>
  );
}

function Welcome() {
  return (
    <div className="mx-auto flex h-full max-w-xl flex-col items-center justify-center px-6 text-center">
      <Mark className="size-12" />
      <h1 className="mt-5 text-2xl font-semibold tracking-tight">Can you take that course?</h1>
      <p className="mt-3 leading-relaxed text-muted">
        Ask about prerequisites or academic policy at UBC Vancouver. Mention the courses you've
        finished (and grades, if you have them) to get a yes or no for yourself; without them,
        you'll get the requirements.
      </p>
    </div>
  );
}
