import { useEffect, useState } from "react";
import {
  applyClarification, paragraphs, sourceLabel, splitCitations, TONE_TEXT, VERDICTS, verdictsOf,
} from "../lib.js";
import Context from "./Context.jsx";
import Details from "./Details.jsx";
import { Link, Spinner } from "./Icons.jsx";

const TONE_BG = { yes: "bg-yes/15", no: "bg-no/15", unsure: "bg-unsure/15" };

/** One question and whatever came back for it: a turn in the chat. */
export default function Entry({ entry, onAsk, busy }) {
  return (
    <article aria-busy={entry.status === "pending"}>
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-bubble px-4 py-2.5 text-[15px] leading-relaxed">
          <span className="sr-only">You asked: </span>
          {entry.question}
        </p>
      </div>
      <div className="mt-6">
        {entry.status === "pending" && <Waiting startedAt={entry.startedAt} />}
        {entry.status === "cancelled" && <p className="text-sm text-muted">Stopped before an answer came back.</p>}
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
    <div role="status" className="text-sm text-muted">
      <p className="flex items-center gap-2 tabular-nums">
        <Spinner className="size-4 text-accent" />
        Checking the calendar… {seconds}s
      </p>
      <p className="mt-1 pl-6 text-xs">Most answers take 5 to 10 seconds.</p>
    </div>
  );
}

function Failed({ error, onRetry, busy }) {
  return (
    <div role="alert" className="rounded-xl border border-no/30 bg-no/10 px-4 py-3">
      <p className="text-sm text-no">{error.message}</p>
      {error.requestId && <p className="mt-1 text-xs text-muted">Request {error.requestId}</p>}
      <button type="button" onClick={onRetry} disabled={busy}
        className="mt-3 rounded-lg border border-rule bg-surface px-3 py-1.5 text-sm font-medium hover:border-accent/60 disabled:opacity-40">
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
        <ul className="mb-5 grid grid-cols-1 gap-2 sm:grid-cols-[repeat(auto-fit,minmax(15rem,1fr))]">
          {verdicts.map((v) => {
            const look = VERDICTS[v.verdict] ?? VERDICTS.UNKNOWN;
            return (
              <li key={v.code} className="flex min-w-0 items-center gap-3 rounded-xl border border-rule bg-surface px-4 py-3">
                <span className={`grid size-9 shrink-0 place-items-center rounded-full text-lg font-bold ${TONE_BG[look.tone]} ${TONE_TEXT[look.tone]}`} aria-hidden="true">
                  {look.mark}
                </span>
                <span className="min-w-0">
                  <span className={`block text-lg leading-tight font-semibold ${TONE_TEXT[look.tone]}`}>{look.word}</span>
                  <span className="block truncate text-sm text-muted">
                    {v.url ? <a href={v.url} target="_blank" rel="noreferrer" className="text-ink hover:text-accent hover:underline">{v.code}</a> : v.code}
                    {v.title ? ` · ${v.title}` : ""}
                  </span>
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

      {r.log_id != null && <p className="mt-4 text-xs text-muted/70">Reference {r.log_id}</p>}
    </div>
  );
}

function AnswerText({ text, id }) {
  return (
    <div className="space-y-3 text-[15px] leading-7">
      {paragraphs(text).map((p, i) => (
        <p key={i}>
          {splitCitations(p).map((part, j) =>
            part.type === "text" ? (
              <span key={j}>{part.value}</span>
            ) : (
              <a key={j} href={`#src-${id}-${part.n}`} aria-label={`Source ${part.n}`}
                className="mx-0.5 inline-grid min-w-5 place-items-center rounded-md bg-accent/15 px-1 align-[0.1em] text-[11px] leading-5 font-semibold text-accent no-underline hover:bg-accent/25">
                {part.n}
              </a>
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
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Sources</h3>
      <ol className="mt-2 flex flex-wrap gap-2">
        {sources.map((s) => {
          const { main, trail } = sourceLabel(s.label);
          return (
            <li key={s.n} id={`src-${id}-${s.n}`} className="max-w-full scroll-mt-6 target:[&>a]:border-accent">
              <a href={s.url} target="_blank" rel="noreferrer" title={s.label}
                className="flex max-w-full items-center gap-2 rounded-lg border border-rule bg-surface px-2.5 py-1.5 text-xs hover:border-accent/60">
                <span className="grid size-5 shrink-0 place-items-center rounded bg-accent/15 font-semibold text-accent">{s.n}</span>
                <span className="truncate">
                  <span className="font-medium text-ink">{main}</span>
                  {trail && <span className="text-muted"> · {trail}</span>}
                </span>
                <Link className="size-3.5 shrink-0 text-muted" />
              </a>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function Clarify({ r, question, onAsk, busy }) {
  return (
    <div>
      <p className="text-[15px]">Which course do you mean?</p>
      {r.clarification.options.map((opt) => (
        <div key={opt.as_written} className="mt-3">
          <p className="text-sm text-muted">“{opt.as_written}” could be:</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {opt.candidates.map((c) => (
              <button key={c} type="button" disabled={busy}
                onClick={() => onAsk(applyClarification(question, opt.as_written, c))}
                className="rounded-lg border border-rule bg-surface px-3 py-1.5 text-sm font-medium hover:border-accent hover:text-accent disabled:opacity-40">
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
      <p className="text-[15px] leading-7">{r.refusal.message}</p>
      {r.refusal.examples?.length > 0 && (
        <>
          <p className="mt-4 text-xs font-semibold uppercase tracking-wider text-muted">Questions I can answer</p>
          <ul className="mt-2 flex flex-col items-start gap-2">
            {r.refusal.examples.map((q) => (
              <li key={q}>
                <button type="button" disabled={busy} onClick={() => onAsk(q)}
                  className="rounded-lg border border-rule bg-surface px-3 py-1.5 text-left text-sm hover:border-accent/60 hover:text-accent disabled:opacity-40">
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
