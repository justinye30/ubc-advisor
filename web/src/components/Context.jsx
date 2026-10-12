import { withGrades } from "../lib.js";

/**
 * How the question was read: the history the system extracted and the
 * guesses it made. Shown so a misread ("121" taken as CPSC 121) is visible
 * instead of silently shaping the verdict.
 */
export default function Context({ context: c }) {
  if (!c) return null;
  const notes = [...(c.assumptions ?? []), ...(c.ignored ?? []).map((x) => `ignored ${x}`)];
  if (!c.transcript_given && !notes.length && !c.year && !c.programs?.length) return null;

  return (
    <section className="mt-5 rounded-xl border border-rule bg-surface p-4">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">How I read your question</h3>
      <dl className="mt-2.5 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
        {c.transcript_given && (
          <>
            <dt className="text-muted">Completed</dt>
            <dd>{c.completed?.length ? withGrades(c.completed, c.grades).join(", ") : "nothing yet"}</dd>
          </>
        )}
        {c.in_progress?.length > 0 && (
          <>
            <dt className="text-muted">In progress</dt>
            <dd>{c.in_progress.join(", ")}</dd>
          </>
        )}
        {c.year && (
          <>
            <dt className="text-muted">Year</dt>
            <dd>{c.year}</dd>
          </>
        )}
        {c.programs?.length > 0 && (
          <>
            <dt className="text-muted">Program</dt>
            <dd>{c.programs.join(", ")}</dd>
          </>
        )}
        {notes.length > 0 && (
          <>
            <dt className="text-muted">Assumed</dt>
            <dd>{notes.join("; ")}</dd>
          </>
        )}
      </dl>
      {!c.transcript_given && (
        <p className="mt-2 text-sm text-muted">
          You didn't list courses you've finished, so this shows requirements rather than a yes or no.
        </p>
      )}
    </section>
  );
}
