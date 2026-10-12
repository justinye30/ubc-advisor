import { TONE_TEXT, VERDICTS } from "../lib.js";

/** The computed facts behind the prose, per kind of question. */
export default function Details({ r }) {
  const d = r.details ?? {};
  if (r.kind === "eligibility" && d.courses) return <Requirements courses={d.courses} />;
  if (r.kind === "eligibility" && d.eligible) return <Sweep d={d} />;
  if (r.kind === "path") return <Path d={d} />;
  if (r.kind === "unlock") return <Unlock d={d} />;
  return null;
}

function Section({ title, children }) {
  return (
    <section className="mt-6">
      <h3 className="font-serif text-base font-semibold">{title}</h3>
      <div className="mt-2 text-sm leading-relaxed">{children}</div>
    </section>
  );
}

function Codes({ label, codes, empty }) {
  if (!codes?.length && !empty) return null;
  return (
    <p className="mt-1">
      <span className="text-muted">{label}: </span>
      {codes?.length ? codes.join(", ") : empty}
    </p>
  );
}

function Mark({ state }) {
  const look = VERDICTS[state] ?? VERDICTS.UNKNOWN;
  return (
    <span className={`inline-block w-4 shrink-0 text-center font-semibold ${TONE_TEXT[look.tone]}`} aria-label={look.word}>
      {look.mark}
    </span>
  );
}

function Requirements({ courses }) {
  const found = courses.filter((c) => c.found);
  if (!found.length) return null;
  return (
    <Section title="Requirement check">
      {found.map((c) => (
        <div key={c.code} className="mt-3 first:mt-0">
          {found.length > 1 && <p className="font-medium">{c.code}</p>}
          {c.reasons?.length > 0 && (
            <ul className="space-y-1">
              {c.reasons.map((x, i) => (
                <li key={i} className="flex gap-2">
                  <Mark state={x.state} />
                  <span>{x.text}</span>
                </li>
              ))}
            </ul>
          )}
          {c.prereq_text && (
            <blockquote className="mt-2 border-l-2 border-rule pl-3 text-muted">
              Calendar wording: {c.prereq_text}
            </blockquote>
          )}
        </div>
      ))}
    </Section>
  );
}

function Sweep({ d }) {
  const n = d.counts ?? {};
  return (
    <Section title={`What you can take in ${d.subjects?.join(", ")}`}>
      <Codes label={`Ready now (${n.eligible ?? d.eligible.length})`} codes={d.eligible} empty="none yet" />
      <Codes label={`No prerequisites (${n.no_prereq ?? 0})`} codes={d.no_prereq} />
      {d.to_confirm?.length > 0 && (
        <>
          <p className="mt-2 text-muted">Can't tell from what you've told me ({n.to_confirm ?? d.to_confirm.length}):</p>
          <ul className="mt-1 space-y-1">
            {d.to_confirm.map((x) => (
              <li key={x.code} className="flex gap-2"><Mark state="INDETERMINATE" /><span>{x.code}: {x.summary}</span></li>
            ))}
          </ul>
        </>
      )}
      <p className="mt-2 text-xs text-muted">Lists are cut at the first entries; counts are complete.</p>
    </Section>
  );
}

function Path({ d }) {
  return (
    <Section title="Route to this course">
      <Codes label="Needed on every route" codes={d.required_on_every_route} empty="nothing beyond what you have" />
      <Codes label="Ready to take now" codes={d.ready_now} />
      {d.tree?.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-accent">Full prerequisite tree</summary>
          <pre className="mt-2 overflow-x-auto rounded-md border border-rule bg-surface p-3 text-xs leading-relaxed">
            {d.tree.join("\n")}
          </pre>
        </details>
      )}
      {d.hidden_okanagan > 0 && (
        <p className="mt-2 text-xs text-muted">{d.hidden_okanagan} Okanagan-campus options hidden.</p>
      )}
    </Section>
  );
}

function Unlock({ d }) {
  const personal = "newly_eligible" in d;
  return (
    <Section title={personal ? "What finishing it opens for you" : "Courses that list it"}>
      {personal ? (
        <>
          <Codes label="Newly open" codes={d.newly_eligible} empty="nothing new on its own" />
          <Codes label="Already open to you" codes={d.already_eligible} />
          {[...(d.to_confirm ?? []), ...(d.still_blocked ?? [])].length > 0 && (
            <ul className="mt-2 space-y-1">
              {d.to_confirm?.map((x) => (
                <li key={x.code} className="flex gap-2"><Mark state="INDETERMINATE" /><span>{x.code}: {x.summary}</span></li>
              ))}
              {d.still_blocked?.map((x) => (
                <li key={x.code} className="flex gap-2"><Mark state="NOT_SATISFIED" /><span>{x.code}: {x.summary}</span></li>
              ))}
            </ul>
          )}
        </>
      ) : (
        <>
          <Codes label="Required by" codes={d.required_by} empty="none" />
          <Codes label="One option for" codes={d.option_for} />
        </>
      )}
    </Section>
  );
}
