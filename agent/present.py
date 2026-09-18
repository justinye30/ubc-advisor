"""Deterministic presentation: the facts the composer may use, the verdict
sentence, and a template answer for everything that doesn't need an LLM.

The composer (agent/composer.py) writes the explanation. It never writes the
verdict: "yes / not yet / can't tell" comes from here, from the evaluator's
state, so a fluent model can't turn INDETERMINATE into "you're good to go".
"""

from dataclasses import dataclass, field

DISCLAIMER = (
    "Unofficial — based on the UBC Academic Calendar, which is authoritative. "
    "Prerequisites may be waived by instructors. Confirm with an academic advisor."
)

# Fact ids that aren't documents: what the student said, and what was computed.
YOU = "you"
CHECK = "check"

MAX_SOURCE_CHARS = 1500


@dataclass
class Facts:
    text: str                                   # what the composer reads
    sources: list[dict] = field(default_factory=list)   # {"id", "label", "url"}
    ids: set[str] = field(default_factory=set)          # citable ids
    backing: list[str] = field(default_factory=list)    # sources [check] was computed from


@dataclass
class Sentence:
    text: str
    cites: list[str]


# ------------------------------------------------------------------ facts

def _you_block(ctx: dict) -> list[str]:
    if not ctx:
        return []
    lines = [f"WHAT THE STUDENT TOLD US [{YOU}]"]
    if ctx["transcript_given"]:
        done = [f"{c} ({ctx['grades'][c]})" if c in ctx["grades"] else c for c in ctx["completed"]]
        lines.append(f"- completed: {', '.join(done) or 'nothing yet'}")
        if ctx["in_progress"]:
            lines.append(f"- taking now (counted as completed): {', '.join(ctx['in_progress'])}")
    else:
        lines.append("- the student did not say which courses they have completed")
    if ctx["year"]:
        lines.append(f"- year standing: {ctx['year']}")
    if ctx["programs"]:
        lines.append(f"- program: {', '.join(ctx['programs'])}")
    lines += [f"- assumed: {a}" for a in ctx["assumptions"]]
    lines += [f"- ignored: {i}" for i in ctx["ignored"]]
    return lines


def _cant_check(verdict: str | None, reasons: list[dict]) -> list[str]:
    if verdict != "INDETERMINATE":
        return []
    return [r["text"] for r in reasons if r["state"] == "INDETERMINATE"]


def _unknowns(verdict: str | None, reasons: list[dict]) -> list[str]:
    unknown = _cant_check(verdict, reasons)
    if not unknown:
        return []
    return ["    can't be checked — unknown, not missing: " + "; ".join(unknown)]


def _source(facts: Facts, label: str, url: str, body: str | None) -> str:
    sid = f"S{len(facts.sources) + 1}"
    text = (body or "").strip()
    if len(text) > MAX_SOURCE_CHARS:
        text = text[:MAX_SOURCE_CHARS] + " …"
    facts.sources.append({"id": sid, "label": label, "url": url, "text": text})
    facts.ids.add(sid)
    return f"[{sid}] {label}\n{text}" if text else f"[{sid}] {label}"


def build_facts(question: str, result: dict) -> Facts:
    kind, status = result.get("kind"), result.get("status")
    facts = Facts(text="")
    parts: list[str] = [f"QUESTION (for context only — not a source)\n{question}"]

    you = _you_block(result.get("context", {}))
    if you:
        facts.ids.add(YOU)
        parts.append("\n".join(you))

    check: list[str] = []
    docs: list[str] = []

    if kind == "eligibility" and status in ("evaluated", "requirements_only"):
        for c in result.get("courses", []):
            if not c["found"]:
                check.append(f"- {c['code']}: not in the calendar data")
                continue
            if c.get("verdict"):
                check.append(f"- {c['code']}: {c['verdict']}"
                             + (f" — {c['summary']}" if c.get("summary") else ""))
                check += [f"    [{r['state']}] {r['text']}" for r in c.get("reasons", [])]
                check += _unknowns(c.get("verdict"), c.get("reasons", []))
            docs.append(_source(facts, f"{c['code']} — {c['title']}", c["source_url"],
                                f"Prerequisites as written in the calendar: {c['prereq_text']}"
                                if c.get("prereq_text") else "No prerequisites listed."))
            if c.get("verdict"):
                facts.backing.append(facts.sources[-1]["id"])

    elif kind == "eligibility" and status == "sweep":
        n = result["counts"]
        check += [
            f"- subjects checked: {', '.join(result['subjects'])} (graduate courses excluded)",
            f"- prerequisites met ({n['eligible']}): {', '.join(result['eligible'])}"
            + (" …" if n["eligible"] > len(result["eligible"]) else ""),
            f"- no listed prerequisites ({n['no_prereq']}): {', '.join(result['no_prereq'])}"
            + (" …" if n["no_prereq"] > len(result["no_prereq"]) else ""),
            f"- can't tell yet ({n['to_confirm']}):",
            *[f"    {t['code']}: {t['summary']}" for t in result["to_confirm"]],
            f"- prerequisites not yet met: {n['not_yet']} courses",
        ]

    elif kind == "unlock" and status == "ok":
        check += [
            (f"- courses whose prerequisites require {result['codes'][0]} "
            f"({len(result['required_by'])}): {', '.join(result['required_by']) or 'none'}"),
            (f"- courses where {result['codes'][0]} is one of several options "
            f"({len(result['option_for'])}): {', '.join(result['option_for']) or 'none'}"),
        ]
        docs.append(_source(facts, f"{result['codes'][0]} — {result['title']}", result["source_url"], None))
        facts.backing.append(facts.sources[-1]["id"])

    elif kind == "unlock" and status == "personal":
        code = result["codes"][0]
        check += [
            f"- newly meets prerequisites after {code}: {', '.join(result['newly_eligible']) or 'none'}",
            f"- after {code}, still can't tell:",
            *[f"    {t['code']}: {t['summary']}" for t in result["to_confirm"]],
            f"- after {code}, still missing something:",
            *[f"    {t['code']}: {t['summary']}" for t in result["still_blocked"]],
            (f"- already meets prerequisites without {code}: "
            f"{', '.join(result['already_eligible']) or 'none'}"),
        ]
        docs.append(_source(facts, f"{code} — {result['title']}", result["source_url"], None))
        facts.backing.append(facts.sources[-1]["id"])

    elif kind == "path" and status == "ok":
        code = result["codes"][0]
        if result.get("verdict"):
            check.append(f"- {code} right now: {result['verdict']}"
                         + (f" — {result['summary']}" if result.get("summary") else ""))
            check += _unknowns(result["verdict"], result.get("reasons", []))
        check += [
            (f"- required on every route to {code}: "
            f"{', '.join(result['required_on_every_route']) or 'none'}"),
            f"- can be taken now on the way: {', '.join(result['ready_now']) or 'none'}",
            ("- prerequisite tree (✓ completed, → can take now, · not yet, ? can't check;"
            " 'option' = one of several alternatives):"),
            *[f"    {line}" for line in result["tree"]],
        ]
        docs.append(_source(facts, f"{code} — {result['title']}", result["source_url"], None))
        facts.backing.append(facts.sources[-1]["id"])

    elif kind == "policy" and status == "ok":
        for h in result["hits"]:
            body = h["content"].split("\n\n", 1)[-1]
            docs.append(_source(facts, h["section_path"], h["source_url"], body))

    if check:
        facts.ids.add(CHECK)
        parts.append(f"COMPUTED FROM THE CALENDAR'S PREREQUISITE DATA [{CHECK}]\n" + "\n".join(check))
    if docs:
        parts.append("CALENDAR SOURCES\n" + "\n\n".join(docs))
    facts.text = "\n\n".join(parts)
    return facts


# ------------------------------------------------------------------ verdict sentence

def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


VERDICT_SENTENCE = {
    "SATISFIED": "Yes — based on what you've told me, you meet the listed prerequisites for {code}.",
    "NOT_SATISFIED": "Not yet — based on what you've told me, you don't meet the listed prerequisites for {code}.",
    "INDETERMINATE": "I can't tell for certain whether you meet the prerequisites for {code}.",
    "NO_PREREQUISITES": "{code} has no listed prerequisites.",
    "UNKNOWN": "I don't have usable prerequisite data for {code}.",
}


def _verdict_lines(code: str, verdict: str, reasons: list[dict]) -> list[str]:
    lines = [VERDICT_SENTENCE[verdict].format(code=code)]
    unknown = _cant_check(verdict, reasons)
    if unknown:
        lines.append("What I can't check: " + "; ".join(unknown) + ".")
    return lines


def headline(result: dict) -> list[str]:
    """Sentences that state the outcome. Fixed text, chosen by the result."""
    kind, status = result.get("kind"), result.get("status")

    if kind == "eligibility" and status == "evaluated":
        return [line for c in result["courses"] if c.get("verdict")
                for line in _verdict_lines(c["code"], c["verdict"], c.get("reasons", []))]
    if kind == "eligibility" and status == "requirements_only":
        return [("You didn't say which courses you've completed, so here's what the "
                "calendar lists — tell me your courses and I can check them.")]
    if kind == "eligibility" and status == "sweep":
        n = result["counts"]
        return [(f"Based on what you've told me, you meet the listed prerequisites for "
                f"{_plural(n['eligible'], 'course')} in {', '.join(result['subjects'])}.")]
    if kind == "unlock" and status == "personal":
        verb = "Finishing" if result.get("already_taken") else "Taking"
        return [(f"{verb} {result['codes'][0]} opens "
                f"{_plural(len(result['newly_eligible']), 'course')} for you.")]
    if kind == "unlock" and status == "ok":
        n = len(result["required_by"]) + len(result["option_for"])
        return [f"{_plural(n, 'course')} list {result['codes'][0]} in their prerequisites."]
    if kind == "path" and status == "ok" and result.get("verdict"):
        return _verdict_lines(result["codes"][0], result["verdict"], result.get("reasons", []))
    return []


# ------------------------------------------------------------------ templates

TEMPLATE_STATUSES = {"needs_course", "course_not_found", "needs_clarification",
                     "refused", "error", "no_results"}


def template_answer(result: dict) -> list[Sentence]:
    """Answers that need no LLM at all."""
    status = result.get("status")
    if status == "needs_course":
        return [Sentence("Which course do you mean? Give me its code, like CPSC 221.", [])]
    if status == "course_not_found":
        code = (result.get("codes") or ["That course"])[0]
        return [Sentence(f"{code} isn't in the UBC Vancouver calendar data I have.", [])]
    if status == "needs_clarification":
        return [Sentence(result["message"], [])]
    if status == "refused":
        return [Sentence(result["message"], []),
                Sentence("You could ask things like "
                         + ", ".join(f'"{e}"' for e in result["examples"][:-1])
                         + f', or "{result["examples"][-1]}"', [])]
    if status == "error":
        return [Sentence("Something went wrong answering that. Please try again.", [])]
    if status == "no_results":
        return [Sentence("I couldn't find a calendar section that answers that.", [])]
    return []


def plain_answer(result: dict, facts: Facts) -> list[Sentence]:
    """A no-LLM explanation built directly from the result: the fallback."""
    kind, status = result.get("kind"), result.get("status")
    out: list[Sentence] = []
    src = iter(s["id"] for s in facts.sources)

    if kind == "eligibility" and status in ("evaluated", "requirements_only"):
        for c in result["courses"]:
            sid = next(src, None) if c["found"] else None
            cites = [x for x in (sid, CHECK if c.get("reasons") else None) if x]
            if c.get("reasons"):
                why = "; ".join(r["text"] for r in c["reasons"] if r["state"] == c["verdict"])
                out.append(Sentence(f"For {c['code']}: {why}.", cites))
            elif c.get("prereq_text"):
                out.append(Sentence(f"{c['code']} requires: {c['prereq_text']}", cites))
    elif kind == "eligibility" and status == "sweep":
        if result["eligible"]:
            out.append(Sentence("Courses you meet the prerequisites for: "
                                + ", ".join(result["eligible"]) + ".", [CHECK]))
        if result["to_confirm"]:
            out.append(Sentence("Courses to confirm: "
                                + ", ".join(t["code"] for t in result["to_confirm"]) + ".", [CHECK]))
    elif kind == "unlock":
        sid = next(src, None)
        cites = [x for x in (CHECK, sid) if x]
        if status == "personal":
            if result["to_confirm"]:
                out.append(Sentence("Still to confirm: " + "; ".join(
                    f"{t['code']} ({t['summary']})" for t in result["to_confirm"]) + ".", cites))
        else:
            out.append(Sentence("Required by: " + (", ".join(result["required_by"]) or "none")
                                + ". One option for: " + (", ".join(result["option_for"]) or "none")
                                + ".", cites))
    elif kind == "path" and status == "ok":
        sid = next(src, None)
        cites = [x for x in (CHECK, sid) if x]
        req = ", ".join(result["required_on_every_route"]) or "nothing in particular"
        out.append(Sentence(f"Required on every route to {result['codes'][0]}: {req}.", cites))
        if result["ready_now"]:
            out.append(Sentence("You can take these now on the way: "
                                + ", ".join(result["ready_now"]) + ".", [CHECK]))
    elif kind == "policy" and status == "ok":
        out.append(Sentence("These calendar sections look most relevant: "
                            + "; ".join(s["label"] for s in facts.sources[:3]) + ".",
                            [s["id"] for s in facts.sources[:3]]))
    return out


# ------------------------------------------------------------------ rendering

def render(lead: list[str], body: list[Sentence], facts: Facts) -> tuple[str, list[dict]]:
    """Join sentences, number cited sources in order of first use, add the footer."""
    numbers: dict[str, int] = {}
    by_id = {s["id"]: s for s in facts.sources}
    pieces = list(lead)
    for s in body:
        marks = []
        cites = [x for cid in s.cites for x in (facts.backing if cid == CHECK else [cid])]
        for cid in dict.fromkeys(cites):
            if cid in by_id:
                numbers.setdefault(cid, len(numbers) + 1)
                marks.append(f"[{numbers[cid]}]")
        text = s.text.strip()
        pieces.append(f"{text} {''.join(marks)}".rstrip() if marks else text)

    used = [{"n": n, "id": cid, "label": by_id[cid]["label"], "url": by_id[cid]["url"]}
            for cid, n in numbers.items()]
    text = " ".join(p for p in pieces if p)
    if used:
        text += "\n\nSources:\n" + "\n".join(f"[{u['n']}] {u['label']} — {u['url']}" for u in used)
    text += f"\n\n{DISCLAIMER}"
    return text, used
