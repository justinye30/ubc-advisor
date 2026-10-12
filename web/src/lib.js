// Pure helpers: no React, no fetch. Everything here is unit-tested.

// How each evaluator state reads to a student. The verdict comes from the
// deterministic evaluator; the UI only chooses the word and the colour.
export const VERDICTS = {
  SATISFIED: { word: "Yes", tone: "yes", mark: "✓" },
  NOT_SATISFIED: { word: "Not yet", tone: "no", mark: "✗" },
  INDETERMINATE: { word: "Can't tell", tone: "unsure", mark: "?" },
  NO_PREREQUISITES: { word: "No prerequisites", tone: "yes", mark: "✓" },
  UNKNOWN: { word: "Not checked", tone: "unsure", mark: "?" },
};

export const TONE_TEXT = { yes: "text-yes", no: "text-no", unsure: "text-unsure" };

/** "Take CPSC 221. [1] It needs 210. [2]" → text and citation pieces. */
export function splitCitations(text) {
  const parts = [];
  let last = 0;
  for (const m of text.matchAll(/\[(\d+)\]/g)) {
    if (m.index > last) parts.push({ type: "text", value: text.slice(last, m.index) });
    parts.push({ type: "cite", n: Number(m[1]) });
    last = m.index + m[0].length;
  }
  if (last < text.length) parts.push({ type: "text", value: text.slice(last) });
  return parts;
}

export function paragraphs(text) {
  return (text ?? "").split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
}

/**
 * The student picked one reading of an ambiguous number. Rewrite the question
 * with that course in place of what they typed, so the next answer is about
 * exactly what they chose. "is 320 open to me?" + CPSC 320 → "is CPSC 320 open to me?"
 */
export function applyClarification(question, asWritten, candidate) {
  const escaped = asWritten.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const re = new RegExp(`(?<![\\w])${escaped}(?![\\w])`, "i");
  return re.test(question)
    ? question.replace(re, candidate)
    : `${question.trim()} (I mean ${candidate})`;
}

/** The verdict lines to show large: one per course the question was about. */
export function verdictsOf(response) {
  const d = response?.details ?? {};
  if (response?.kind === "eligibility" && d.courses) {
    return d.courses
      .filter((c) => c.found && c.verdict)
      .map((c) => ({ code: c.code, title: c.title, verdict: c.verdict, url: c.source_url }));
  }
  if (response?.kind === "path" && d.verdict) {
    return [{ code: response.codes?.[0], title: d.title, verdict: d.verdict, url: d.source_url }];
  }
  return [];
}

/** "CPSC 221 (72%)" for completed courses with a known grade. */
export function withGrades(codes = [], grades = {}) {
  return codes.map((c) => (grades[c] ? `${c} (${grades[c]})` : c));
}

/**
 * A source label split for a compact chip: the specific part first, the
 * path to it after. "B.Sc. > Repeating > Rules" → { main: "Rules", trail: "B.Sc. › Repeating" }.
 * Course labels ("CPSC 221 — Basic Algorithms") have no path and stay whole.
 */
export function sourceLabel(label = "") {
  const parts = label.split(" > ").map((p) => p.trim()).filter(Boolean);
  return { main: parts.at(-1) ?? "", trail: parts.slice(0, -1).join(" › ") };
}
