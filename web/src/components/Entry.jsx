import { useEffect, useState } from "react";
import { applyClarification, paragraphs, splitCitations, TONE_TEXT, VERDICTS, verdictsOf } from "../lib.js";
import Context from "./Context.jsx";
import Details from "./Details.jsx";

/** One question and whatever came back for it. */
export default function Entry({ entry, onAsk, busy }) {
  return (
    <article aria-busy={entry.status === "pending"}>
      <p className="text-sm text-muted">You asked</p>
      <p className="mt-1 font-serif text-lg leading-snug">{entry.question}</p>
      <div className="mt-4">
        {entry.status === "pending" && <Waiting startedAt={entry.startedAt} />}
        {entry.status === "cancelled" && <p className="text-muted">Stopped before an answer came back.</p>}
        {entry.status === "failed" && <Failed error={entry.error} onRetry={() => onAsk(entry.question)} busy={busy} />}
        {entry.status === "done" && <Response r={entry.response} id={entry.id} question={entry.question} onAsk={onAsk} busy={busy} />}
      </div>
    </article>
  );
}

function Waiting({ startedAt }) {
  // An honest progress indicator: elapsed time and the usual range, not a fake progress bar.
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const seconds = Math.floor((now - startedAt) / 1000);
  return (
    <p className="text-muted" role="status">
      Checking the calendar… {seconds}s
      <span className="block text-sm">Most answers take 5 to 10 seconds.</span>
    </p>
  );
}

function Failed({ error, onRetry, busy }) {
  return (
    <div role="alert">
      <p className="text-no">{error.message}</p>
      {error.requestId && <p className="mt-1 text-sm text-muted">Request {error.requestId}</p>}
      <button type="button" onClick={onRetry} disabled={busy}
        className="mt-3 rounded-md border border-rule bg-surface px-3 py-1.5 text-sm font-medium disabled:opacity-40">
        Ask again
      </button>
    </div>
  );
}

function Response({ r, id, question, onAsk, busy }) {
  if (r.status === "needs_clarification") return <Clarify r={r} question={question} onAsk={onAsk} busy={busy} />;
  if (r.status === "refused") return <Refused r={r} onAsk={onAsk} busy={busy} />;

  const verdicts = verdictsOf(r);
  return (
    <div>
      {verdicts.length > 0 && (
        <ul className="mb-5 space-y-2">
          {verdicts.map((v) => {
            const look = VERDICTS[v.verdict] ?? VERDICTS.UNKNOWN;
            return (
              <li key={v.code} className="flex flex-wrap items-baseline gap-x-4">
                <span className={`font-serif text-4xl font-semibold tracking-tight ${TONE_TEXT[look.tone]}`}>
                  {look.word}
                </span>
                <span className="text-sm text-muted">
                  {v.url ? <a href={v.url} target="_blank" rel="noreferrer" className="underline underline-offset-2">{v.code}</a> : v.code}
                  {v.title ? `, ${v.title}` : ""}
                </span>
              </li>
            );
          })}
        </ul>
      )}

      <AnswerText text={r.answer.text} id={id} />
      <Details r={r} />
      <Context context={r.context} />
      <Sources sources={r.answer.sources} id={id} />

      {r.log_id != null && <p className="mt-4 text-xs text-muted">Reference {r.log_id}</p>}
    </div>
  );
}

function AnswerText({ text, id }) {
  return (
    <div className="max-w-prose space-y-3 font-serif text-lg leading-relaxed">
      {paragraphs(text).map((p, i) => (
        <p key={i}>
          {splitCitations(p).map((part, j) =>
            part.type === "text" ? (
              <span key={j}>{part.value}</span>
            ) : (
              <sup key={j} className="ml-0.5 font-sans text-xs">
                <a href={`#src-${id}-${part.n}`} className="text-accent" aria-label={`Source ${part.n}`}>
                  [{part.n}]
                </a>
              </sup>
            ),
          )}
        </p>
      ))}
    </div>
  );
}

function Sources({ sources, id }) {
  if (!sources?.length) return null;
  return (
    <section className="mt-6">
      <h3 className="font-serif text-base font-semibold">Sources</h3>
      <ol className="mt-2 space-y-1 text-sm">
        {sources.map((s) => (
          <li key={s.n} id={`src-${id}-${s.n}`} className="flex gap-2 scroll-mt-4">
            <span className="text-muted">[{s.n}]</span>
            <a href={s.url} target="_blank" rel="noreferrer" className="text-accent underline underline-offset-2">
              {s.label}
            </a>
          </li>
        ))}
      </ol>
    </section>
  );
}

function Clarify({ r, question, onAsk, busy }) {
  return (
    <div>
      <p className="font-serif text-lg">Which course do you mean?</p>
      {r.clarification.options.map((opt) => (
        <div key={opt.as_written} className="mt-3">
          <p className="text-sm text-muted">“{opt.as_written}” could be:</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {opt.candidates.map((c) => (
              <button key={c} type="button" disabled={busy}
                onClick={() => onAsk(applyClarification(question, opt.as_written, c))}
                className="rounded-md border border-rule bg-surface px-3 py-1.5 text-sm font-medium hover:border-accent disabled:opacity-40">
                {c}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Refused({ r, onAsk, busy }) {
  return (
    <div>
      <p className="max-w-prose font-serif text-lg leading-relaxed">{r.refusal.message}</p>
      {r.refusal.examples?.length > 0 && (
        <>
          <p className="mt-4 text-sm text-muted">Questions I can answer:</p>
          <ul className="mt-2 space-y-1">
            {r.refusal.examples.map((q) => (
              <li key={q}>
                <button type="button" disabled={busy} onClick={() => onAsk(q)}
                  className="text-left text-accent underline decoration-rule underline-offset-4 hover:decoration-accent disabled:opacity-40">
                  {q}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
