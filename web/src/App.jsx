import { useCallback, useRef, useState } from "react";
import { ask, AskError, MOCK } from "./api.js";
import AskForm from "./components/AskForm.jsx";
import Entry from "./components/Entry.jsx";

const EXAMPLES = import.meta.env.MODE === "mock" ? (await import("./mock.js")).MOCK_QUESTIONS : [
  "I did CPSC 110, 121 and 210. Can I take CPSC 221?",
  "What does CPSC 213 unlock?",
  "Can I retake a course I already passed?",
];

export default function App() {
  // Newest first. Each entry: { id, question, status, response, error, startedAt }
  const [entries, setEntries] = useState([]);
  const [draft, setDraft] = useState("");
  const controller = useRef(null);
  const nextId = useRef(1);

  const pending = entries.some((e) => e.status === "pending");

  const update = (id, patch) =>
    setEntries((all) => all.map((e) => (e.id === id ? { ...e, ...patch } : e)));

  const submit = useCallback(async (question) => {
    const q = question.trim();
    if (!q) return;
    const id = nextId.current++;
    setEntries((all) => [{ id, question: q, status: "pending", startedAt: Date.now() }, ...all]);
    setDraft("");

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

  return (
    <div className="min-h-screen">
      <header className="border-b border-rule bg-surface">
        <div className="mx-auto max-w-2xl px-4 py-5 sm:px-6">
          <h1 className="font-serif text-2xl font-semibold tracking-tight">UBC Course Advisor</h1>
          <p className="mt-1 text-sm text-muted">
            Prerequisites and academic policy from the 2026/27 UBC Vancouver Academic Calendar.
          </p>
          {MOCK && (
            <p className="mt-2 text-xs font-semibold uppercase tracking-wide text-unsure">
              Mock mode: canned answers, no API calls
            </p>
          )}
        </div>
      </header>

      <main className="mx-auto max-w-2xl px-4 pb-24 sm:px-6">
        <p className="mt-5 border-l-4 border-unsure bg-surface px-4 py-3 text-sm leading-relaxed">
          Unofficial and not academic advising. Answers come from the Academic Calendar, which is
          authoritative; instructors can waive prerequisites. Confirm decisions with an advisor.
        </p>

        <AskForm value={draft} onChange={setDraft} onSubmit={submit} onCancel={cancel} pending={pending} />

        {entries.length === 0 ? (
          <section className="mt-10">
            <h2 className="font-serif text-lg">Try asking</h2>
            <ul className="mt-3 space-y-2">
              {EXAMPLES.map((q) => (
                <li key={q}>
                  <button
                    type="button"
                    onClick={() => submit(q)}
                    className="text-left text-accent underline decoration-rule underline-offset-4 hover:decoration-accent"
                  >
                    {q}
                  </button>
                </li>
              ))}
            </ul>
            <p className="mt-6 text-sm leading-relaxed text-muted">
              Mention the courses you've finished (and grades, if you have them) to get a yes or
              no for yourself. Without them, you'll get the requirements.
            </p>
          </section>
        ) : (
          <ol className="mt-8 divide-y divide-rule">
            {entries.map((e) => (
              <li key={e.id} className="py-8 first:pt-0">
                <Entry entry={e} onAsk={submit} busy={pending} />
              </li>
            ))}
          </ol>
        )}
      </main>
    </div>
  );
}
