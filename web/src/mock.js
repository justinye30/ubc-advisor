// Canned /api/ask responses, for designing the answer view without the
// server or the Anthropic API. On with `npm run dev:mock`; a normal build
// leaves this file out (it's only imported in mock mode).
//
// Shapes follow api/serialize.py. Course codes, titles and URLs are real;
// requirement wording, reasons and answers are invented for layout, not
// copied from the calendar.

const DISCLAIMER =
  "Unofficial — based on the UBC Academic Calendar, which is authoritative. " +
  "Prerequisites may be waived by instructors. Confirm with an academic advisor.";

const TITLES = {
  "CPSC 110": "Computation, Programs, and Programming",
  "CPSC 121": "Models of Computation",
  "CPSC 210": "Software Construction",
  "CPSC 213": "Introduction to Computer Systems",
  "CPSC 221": "Basic Algorithms and Data Structures",
  "CPSC 304": "Introduction to Relational Databases",
  "CPSC 313": "Computer Hardware and Operating Systems",
  "CPSC 320": "Intermediate Algorithm Design and Analysis",
  "CPSC 404": "Advanced Relational Databases",
  "MATH 200": "Calculus III",
  "MATH 320": "Real Variables I",
};

const url = (code) => {
  const [subject, number] = code.toLowerCase().split(" ");
  return `https://vancouver.calendar.ubc.ca/course-descriptions/courses/${subject}v-${number}`;
};

const POLICY_URL = "https://vancouver.calendar.ubc.ca/faculties-colleges-and-schools/faculty-science/bachelor-science";

const courseSource = (n, code) => ({ n, label: `${code} — ${TITLES[code]}`, url: url(code) });

const context = (over = {}) => ({
  completed: [], in_progress: [], grades: {}, year: null, programs: [],
  transcript_given: true, assumptions: [], ignored: [], ...over,
});

const NOT_ANSWERS = new Set(["needs_course", "needs_clarification", "course_not_found",
  "refused", "no_results", "error"]);

function response({ status = "ok", kind, codes = [], text = "", sources = [], context = null,
  details = {}, ...extra }) {
  return {
    status,
    answered: !NOT_ANSWERS.has(status),
    intent: kind === "out_of_scope" ? "out_of_scope" : kind,
    kind,
    codes,
    answer: { text, sources, composed_by: NOT_ANSWERS.has(status) ? "template" : "llm", guard: "passed" },
    disclaimer: DISCLAIMER,
    context,
    log_id: 4127,
    details,
    request_id: "mock",
    pipeline: "mock",
    ...extra,
  };
}

const course = (code, fields = {}) => ({
  code, found: true, title: TITLES[code], source_url: url(code), ...fields,
});

/** A path-tree line, padded the way core/graph.py PathView.render() pads it. */
function treeLine(prefix, last, mark, code, tag, note = "") {
  const title = (TITLES[code] ?? "").slice(0, 30);
  return `${prefix}${last ? "└─ " : "├─ "}${mark} ${code.padEnd(10)} ${tag.padEnd(9)} ${title.padEnd(30)} ${note}`.trimEnd();
}

// The usual answer: one course, a clear yes. Also served late as "slow".
const YES = response({
  status: "evaluated", kind: "eligibility", codes: ["CPSC 221"],
  text:
    "Yes — based on what you've told me, you meet the listed prerequisites for CPSC 221.\n\n" +
    "CPSC 221 asks for CPSC 210 and one of CPSC 121 or MATH 220, plus a calculus course. " +
    "You've completed CPSC 210 and CPSC 121, and your 72% in MATH 200 covers the math. [1]",
  sources: [courseSource(1, "CPSC 221")],
  context: context({
    completed: ["CPSC 110", "CPSC 121", "CPSC 210", "MATH 200"],
    grades: { "MATH 200": "72" },
    year: 2,
    assumptions: ["read '121' as CPSC 121", "read '210' as CPSC 210"],
  }),
  details: { courses: [course("CPSC 221", {
    prereq_text: "Either (a) CPSC 210 and one of CPSC 121, MATH 220; or (b) a score of 70% or higher in one of the listed calculus courses.",
    verdict: "SATISFIED",
    summary: "CPSC 210: completed",
    reasons: [
      { state: "SATISFIED", text: "CPSC 210: completed" },
      { state: "SATISFIED", text: "CPSC 121: completed" },
      { state: "SATISFIED", text: "MATH 200: 72% ≥ 70%" },
    ],
  })] },
});

// Each entry: name, question, optional match (for typed questions), and
// either a response or an error. Order matters for matching.
export const MOCKS = [
  {
    name: "yes",
    question: "I got 72 in MATH 200 and passed CPSC 110, 121 and 210. Can I take CPSC 221?",
    match: /\b221\b/,
    response: YES,
  },
  {
    name: "not yet + can't tell",
    question: "I finished CPSC 213 and 221. Can I take CPSC 313 and CPSC 320?",
    match: /\b(313|320)\b/,
    response: response({
      status: "evaluated", kind: "eligibility", codes: ["CPSC 313", "CPSC 320"],
      text:
        "Not yet — based on what you've told me, you don't meet the listed prerequisites for CPSC 313. " +
        "It needs CPSC 261 as well as CPSC 213, and you haven't mentioned CPSC 261. [1]\n\n" +
        "I can't tell for certain whether you meet the prerequisites for CPSC 320. It asks for a " +
        "minimum grade in CPSC 221, and you didn't give one. [2]\n\n" +
        "What I can't check: CPSC 221: needs 68%, grade not reported.",
      sources: [courseSource(1, "CPSC 313"), courseSource(2, "CPSC 320")],
      context: context({ completed: ["CPSC 213", "CPSC 221"] }),
      details: { courses: [
        course("CPSC 313", {
          prereq_text: "CPSC 213 and CPSC 261.",
          verdict: "NOT_SATISFIED",
          summary: "CPSC 261: not completed",
          reasons: [
            { state: "SATISFIED", text: "CPSC 213: completed" },
            { state: "NOT_SATISFIED", text: "CPSC 261: not completed" },
          ],
        }),
        course("CPSC 320", {
          prereq_text: "A score of 68% or higher in CPSC 221, and one of the listed discrete math courses.",
          verdict: "INDETERMINATE",
          summary: "CPSC 221: needs 68%, grade not reported",
          reasons: [
            { state: "INDETERMINATE", text: "CPSC 221: needs 68%, grade not reported" },
            { state: "SATISFIED", text: "CPSC 121: completed" },
          ],
        }),
      ] },
    }),
  },
  {
    name: "requirements only",
    question: "What are the prerequisites for CPSC 213?",
    match: /prereq|require/i,
    response: response({
      status: "requirements_only", kind: "eligibility", codes: ["CPSC 213"],
      text:
        "You didn't say which courses you've completed, so here's what the calendar lists — tell me " +
        "your courses and I can check them.\n\n" +
        "CPSC 213 needs CPSC 121 and CPSC 210. [1]",
      sources: [courseSource(1, "CPSC 213")],
      context: context({ transcript_given: false }),
      details: { courses: [course("CPSC 213", { prereq_text: "All of CPSC 121, CPSC 210." })] },
    }),
  },
  {
    name: "what can I take",
    question: "I've done CPSC 110, 121, 210 and 213. What CPSC courses can I take?",
    match: /what (else )?can i take/i,
    response: response({
      status: "sweep", kind: "eligibility", codes: [],
      text:
        "Based on what you've told me, you meet the listed prerequisites for 9 courses in CPSC.\n\n" +
        "The ones most students take next are CPSC 221 and CPSC 310. A few more depend on grades or " +
        "standing you didn't mention, so they're listed separately.",
      context: context({ completed: ["CPSC 110", "CPSC 121", "CPSC 210", "CPSC 213"], year: 2 }),
      details: {
        subjects: ["CPSC"],
        eligible: ["CPSC 221", "CPSC 259", "CPSC 261", "CPSC 310", "CPSC 311", "CPSC 312", "CPSC 330", "CPSC 340", "CPSC 368"],
        no_prereq: ["CPSC 100", "CPSC 103", "CPSC 107", "CPSC 110"],
        to_confirm: [
          { code: "CPSC 313", summary: "CPSC 261: not completed, or an alternative we can't verify" },
          { code: "CPSC 344", summary: "year standing not provided" },
          { code: "CPSC 420", summary: "CPSC 320: needs 64%, grade not reported" },
        ],
        counts: { eligible: 9, no_prereq: 4, to_confirm: 3, not_yet: 41 },
      },
    }),
  },
  {
    name: "path",
    question: "I've done CPSC 110 and 121. How do I get to CPSC 404?",
    match: /how do i get|path|route|\b404\b/i,
    response: response({
      status: "ok", kind: "path", codes: ["CPSC 404"],
      text:
        "Not yet — based on what you've told me, you don't meet the listed prerequisites for CPSC 404.\n\n" +
        "Every route goes through CPSC 210, CPSC 221 and CPSC 304. You can take CPSC 210 now; " +
        "CPSC 221 opens after that, then CPSC 304, then CPSC 404. [1]",
      sources: [courseSource(1, "CPSC 404")],
      context: context({ completed: ["CPSC 110", "CPSC 121"] }),
      details: {
        title: TITLES["CPSC 404"],
        source_url: url("CPSC 404"),
        verdict: "NOT_SATISFIED",
        summary: "CPSC 304: not completed",
        reasons: [{ state: "NOT_SATISFIED", text: "CPSC 304: not completed" }],
        required_on_every_route: ["CPSC 210", "CPSC 221", "CPSC 304"],
        ready_now: ["CPSC 210"],
        tree: [
          treeLine("", true, "·", "CPSC 304", "required"),
          treeLine("   ", true, "·", "CPSC 221", "required"),
          treeLine("      ", false, "→", "CPSC 210", "required", "ready to take"),
          treeLine("      ", false, "✓", "CPSC 121", "option"),
          treeLine("      ", true, "·", "MATH 200", "option", "(not needed now: another option is ready)"),
        ],
        hidden_okanagan: 2,
      },
    }),
  },
  {
    name: "unlock (personal)",
    question: "I've done CPSC 210 and 221. What would CPSC 213 open up for me?",
    match: /(unlock|open).*for me/i,
    response: response({
      status: "personal", kind: "unlock", codes: ["CPSC 213"],
      text:
        "Taking CPSC 213 opens 2 courses for you.\n\n" +
        "With CPSC 213 added to what you've done, you'd meet the listed prerequisites for CPSC 313 and " +
        "CPSC 317. CPSC 415 would still need more. [1]",
      sources: [courseSource(1, "CPSC 213")],
      context: context({ completed: ["CPSC 210", "CPSC 221"] }),
      details: {
        title: TITLES["CPSC 213"],
        source_url: url("CPSC 213"),
        already_taken: false,
        newly_eligible: ["CPSC 313", "CPSC 317"],
        already_eligible: ["CPSC 310"],
        to_confirm: [{ code: "CPSC 314", summary: "MATH 200: needs 60%, grade not reported" }],
        still_blocked: [{ code: "CPSC 415", summary: "CPSC 313: not completed" }],
      },
    }),
  },
  {
    name: "unlock",
    question: "What does CPSC 213 unlock?",
    match: /unlock|open up|lead to|leads to/i,
    response: response({
      status: "ok", kind: "unlock", codes: ["CPSC 213"],
      text:
        "6 courses list CPSC 213 in their prerequisites.\n\n" +
        "Four require it outright, including CPSC 313 and CPSC 317. For two more it's one of several " +
        "options. [1]",
      sources: [courseSource(1, "CPSC 213")],
      context: context({ transcript_given: false }),
      details: {
        title: TITLES["CPSC 213"],
        source_url: url("CPSC 213"),
        required_by: ["CPSC 313", "CPSC 317", "CPSC 415", "CPSC 418"],
        option_for: ["CPSC 314", "CPSC 427"],
      },
    }),
  },
  {
    name: "policy",
    question: "Can I retake a course I already passed?",
    match: /retake|repeat|standing|policy|withdraw/i,
    response: response({
      status: "ok", kind: "policy", codes: [],
      text:
        "Generally, yes, but with limits. You can repeat a course you've passed once, and both " +
        "attempts stay on your transcript. [1]\n\n" +
        "Only the higher grade counts toward your degree, but both are used when your sessional " +
        "average is calculated. [1][2] Some departments restrict repeating their courses, so check the " +
        "course listing as well.",
      sources: [
        { n: 1, label: "B.Sc. > Academic Performance Review and Continuation > Repeating Courses", url: `${POLICY_URL}/academic-performance-review-and-continuation` },
        { n: 2, label: "B.Sc. > Promotion Requirements and Degree Progression > Promotion to 3rd-Year Class Standing", url: `${POLICY_URL}/promotion-requirements-and-degree-progression` },
      ],
    }),
  },
  {
    name: "clarification",
    question: "Can I take 320 next term?",
    response: response({
      status: "needs_clarification", kind: "eligibility", codes: [],
      text: "'320' could be CPSC 320, MATH 320. Which did you mean?",
      context: context({ transcript_given: false }),
      clarification: {
        message: "'320' could be CPSC 320, MATH 320. Which did you mean?",
        options: [{ as_written: "320", candidates: ["CPSC 320", "MATH 320"] }],
      },
    }),
  },
  {
    name: "course not found",
    question: "Can I take CPSC 999?",
    match: /\b999\b/,
    response: response({
      status: "course_not_found", kind: "eligibility", codes: ["CPSC 999"],
      text: "I couldn't find CPSC 999 in the 2026/27 calendar. Check the course code — it may be retired or a typo.",
      context: context({ transcript_given: false }),
      details: { courses: [{ code: "CPSC 999", found: false }] },
    }),
  },
  {
    name: "refused",
    question: "Which is easier, CPSC 310 or CPSC 340?",
    match: /easier|harder|should i|best|professor|instructor/i,
    response: response({
      status: "refused", kind: "out_of_scope", codes: [],
      text: "I only have what the Academic Calendar says — requirements and policies — not workload, difficulty, instructors, or reviews.",
      refusal: {
        message: "I only have what the Academic Calendar says — requirements and policies — not workload, difficulty, instructors, or reviews.",
        examples: [
          "Can I take CPSC 221 with CPSC 110, 121 and 210?",
          "What does CPSC 213 unlock?",
          "Can I retake a course I already passed?",
        ],
      },
    }),
  },
  {
    name: "server error",
    question: "Show me a server error",
    match: /error|fail/i,
    error: { message: "Something went wrong answering that. Try again in a moment.", status: 503, requestId: "mock5f3a2c1e" },
  },
  {
    name: "slow",
    question: "Show me a slow answer (12 seconds)",
    match: /slow|loading|wait/i,
    delay: 12_000,
    response: YES,
  },
];

export const MOCK_QUESTIONS = MOCKS.map((m) => m.question);

let rotation = 0;

/**
 * Which canned answer a question gets: the fixture with that exact question,
 * else the first whose pattern matches, else the next one in turn, so any
 * typed question still shows something.
 */
export function pickMock(question) {
  const q = question.trim();
  return (
    MOCKS.find((m) => m.question === q) ??
    MOCKS.find((m) => m.match?.test(q)) ??
    MOCKS[rotation++ % MOCKS.length]
  );
}
