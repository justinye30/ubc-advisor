"""The citation guard: check every sentence of a composed answer against the
facts it was built from, and don't ship one that fails.

Designed from Step 14's hand-classified flags:
  - phrase matching alone was too noisy: hedges ("whether you can take"),
    negations ("we cannot confirm you meet") and partial claims ("you meet
    the year requirement") aren't claims about eligibility;
  - "should" and advisor referrals are fine when the cited calendar source
    says them;
  - the one real error ("CPEN 212 … you can take immediately") was a claim
    about a specific course that only the structured result can refute.

So claims are checked clause by clause, and against structured facts
(what the student has, what is actually ready) wherever those exist.

Enforcement: regenerate once with the violations explained; if some remain,
drop the offending sentences; if nothing is left, use the template answer.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass

from agent.checks import (
    NEGATIVE_CLAIMS,
    POSITIVE_CLAIMS,
    advice_phrases,
    ungrounded_codes,
    ungrounded_numbers,
    ungrounded_remedies,
)
from agent.composer import Answer, compose
from agent.present import Facts, Sentence, build_facts, plain_answer, render
from core.codes import find_codes

# ------------------------------------------------------------------ reading claims

# Where one claim ends and another begins. Relative clauses split too, so
# "You can take CPSC 221 now, which is one option for CPSC 304" doesn't
# claim CPSC 304 is ready.
_CLAUSE_BREAK = re.compile(
    r"\s+[—–]\s+|;\s*|:\s+|\(|\)"
    r"|,?\s+(?:but|however|although|though|while|whereas|except|yet|unlike"
    r"|rather than|instead of)\b"
    r"|,\s+(?=(?:both|all|each|either|neither|any|none) of (?:which|those|them)\b)"
    r"|,\s+(?=(?:which|where|because|since|so)\b)",
    re.IGNORECASE,
)
_BACK_REFERENCE = re.compile(
    r"^(?:and\s+)?(?:(?:both|all|each|either|neither|any) of (?:which|those|them|these)"
    r"|which|these|those|they|both)\b", re.IGNORECASE)

HEDGES = re.compile(
    r"\b(?:whether|if|once|after|before|unless|until|depends?|depending|would|could|might|may"
    r"|confirm|determine|verify|tell|sure|certain|possibly|potentially)\b", re.IGNORECASE)
NEGATIONS = re.compile(
    r"\b(?:not|never|no|cannot|unable|without)\b|n't\b", re.IGNORECASE)
PARTIAL = re.compile(
    r"^\W*(?:\w+\W+){0,6}?(?:requirements?|parts?|conditions?|portions?|components?"
    r"|criteri(?:on|a)|of the|of its|of these)\b", re.IGNORECASE)

AVAILABILITY = re.compile(
    r"\byou (?:can|may) (?:now )?(?:take|register (?:in|for)|enrol+ in)"
    r"|\byou(?:'re| are) (?:now )?(?:ready|eligible|able) (?:for|to take)"
    r"|\b(?:which|that) you can (?:take|register)"
    r"|\b(?:open|available) to you\b", re.IGNORECASE)
CALENDAR_SILENT = re.compile(
    r"\bthe (?:academic )?calendar (?:does not|doesn't|does't|fails to)\s+"
    r"(?:specify|mention|say|state|list|address|include|define|set)"
    r"|\b(?:isn't|is not|are not|aren't) (?:specified|mentioned|stated|listed|addressed) "
    r"(?:anywhere )?in the (?:academic )?calendar", re.IGNORECASE)
HISTORY_POSITIVE = re.compile(
    r"\byou(?:'ve| have)? (?:already )?(?:completed|taken|passed|finished|done)\b", re.IGNORECASE)
HISTORY_NEGATIVE = re.compile(
    r"\byou (?:haven't|have not|didn't|did not) (?:yet )?(?:completed|taken|passed|finished|done)\b",
    re.IGNORECASE)

# Advice wording that a cited calendar source can legitimately carry.
_GROUNDABLE = [
    (re.compile(r"\bshould\b", re.IGNORECASE), re.compile(r"\bshould\b", re.IGNORECASE)),
    (re.compile(r"consult|contact|speak|talk|advis", re.IGNORECASE),
     re.compile(r"advis", re.IGNORECASE)),
]


_CODE_SPAN = re.compile(r"\b[A-Za-z]{2,5}(?:_[VvOo])?\s*\d{3}[A-Za-z]?\b")
_LIST_GAP = re.compile(r"^\s*(?:,\s*)?(?:(?:and|or)\s+)?(?:either\s+)?$", re.IGNORECASE)


def trailing_list(clause: str) -> list[str]:
    """The courses listed at the end of a clause: what a following "which",
    "both of which" or "all of which" refers to.

    "To take CPSC 304, you need one of CPSC 221 or DSCI 221" -> CPSC 221, DSCI 221
    "... CPSC 313 and CPSC 317 would still require CPSC 213"  -> CPSC 213
    """
    spans = [m for m in _CODE_SPAN.finditer(clause) if find_codes(m.group(0))]
    if not spans:
        return []
    run = [spans[-1]]
    for prev in reversed(spans[:-1]):
        if not _LIST_GAP.match(clause[prev.end():run[0].start()]):
            break
        run.insert(0, prev)
    return [find_codes(m.group(0))[0] for m in run]


def clauses(sentence: str, targets: set[str] | frozenset[str] = frozenset()) -> list[tuple[str, list[str]]]:
    """Split a sentence into clauses, each with the course codes it's about.

    A clause that points back ("which you can take", "both of which…")
    borrows the list that ended the clause before it — not every course that
    clause mentioned, and never the target.
    """
    out: list[tuple[str, list[str]]] = []
    previous = ""
    for part in _CLAUSE_BREAK.split(sentence):
        part = (part or "").strip(" ,.")
        if not part:
            continue
        codes = find_codes(part)
        if not codes and previous and _BACK_REFERENCE.match(part):
            codes = [c for c in trailing_list(previous) if c not in targets]
        out.append((part, codes))
        previous = part
    return out


_PARTIAL_LEAD = re.compile(
    r"^\s+(?:the\s+)?(?:first|second|third|fourth|fifth|one|two|three|four|some|part|each"
    r"|either|that|this|only one|just one)\b", re.IGNORECASE)
_FULL_LEAD = re.compile(r"^\s+all\b", re.IGNORECASE)


def _is_partial(clause: str, match: re.Match) -> bool:
    """'you meet the first prerequisite', 'you satisfy two of the four
    requirements' — a claim about part of the rule. 'you meet all of the
    requirements' is a full claim."""
    rest = clause[match.end():]
    if _FULL_LEAD.match(rest):
        return False
    return _PARTIAL_LEAD.match(rest) is not None or PARTIAL.match(rest) is not None


_BEFORE_VERB = re.compile(r"(?:open|available) to you|(?:which|that) you can", re.IGNORECASE)


_POSSESSIVE = re.compile(r"(\d{3}[A-Za-z]?)\s*['’]s\b")
_DESTINATION = re.compile(
    r"(?:toward|towards|leading to|lead to|leads to|on the way to|en route to|before|"
    r"in order to take|to reach|to get into)\s+(?:meeting\s+)?(?:the\s+)?"
    r"(?:[a-z]+\s+){0,3}?[A-Za-z]{2,5}(?:_[VvOo])?\s*(\d{3}[A-Za-z]?)", re.IGNORECASE)


def _drop_possessives(text: str, codes: list[str]) -> list[str]:
    """"...toward meeting CPSC 221's prerequisites" names whose requirements
    they are; "...courses that lead toward CPSC 221" names the destination.
    Neither is a course the student is being told they can take."""
    named = set(_POSSESSIVE.findall(text)) | set(_DESTINATION.findall(text))
    return [c for c in codes if c.split()[-1] not in named]


def leading_list(text: str) -> list[str]:
    """The courses right at the start of `text`: the object of a claim.

    "CPSC 213 now since you've finished CPSC 210" -> CPSC 213
    "either CPSC 221 or DSCI 221 -> CPSC 221, DSCI 221
    """
    spans = [m for m in _CODE_SPAN.finditer(text) if find_codes(m.group(0))]
    run: list[re.Match] = []
    for m in spans:
        if run and not _LIST_GAP.match(text[run[-1].end():m.start()]):
            break
        run.append(m)
    return [find_codes(m.group(0))[0] for m in run]


def claimed_codes(clause: str, codes: list[str], match: re.Match) -> list[str]:
    """The courses a 'you can take' / 'you completed' claim is about.

    Codes borrowed through "both of which…" are the claim's subject. Otherwise
    it's the courses after the verb, except for "X is open to you" and
    "courses that you can take", where they come before it.
    """
    if not find_codes(clause):                      # borrowed
        return _drop_possessives(clause, codes)
    if _BEFORE_VERB.search(match.group(0)):
        return _drop_possessives(clause, find_codes(clause[:match.start()]))
    return _drop_possessives(clause, leading_list(clause[match.end():]))


# ------------------------------------------------------------------ what's true

@dataclass
class Truth:
    """What the result says, in the shape the checks need."""
    targets: set[str]
    verdicts: set[str]
    has: set[str]                 # completed or in progress
    history_known: bool
    can_take: set[str] | None     # courses a student may be told they can take (None: don't check)
    source_text: dict[str, str]


def truth_of(result: dict, facts: Facts) -> Truth:
    ctx = result.get("context") or {}
    kind, status = result.get("kind"), result.get("status")
    verdicts = {c["verdict"] for c in result.get("courses", []) if c.get("verdict")}
    if kind == "path" and result.get("verdict"):
        verdicts.add(result["verdict"])

    can_take: set[str] | None = None
    if kind == "path" and status == "ok":
        can_take = set(result.get("ready_now", []))
    elif kind == "unlock" and status == "personal":
        can_take = set(result.get("newly_eligible", [])) | set(result.get("already_eligible", []))
    elif kind == "unlock":
        can_take = set()                       # no history: nothing can be claimed
    elif kind == "eligibility" and status == "sweep":
        can_take = set(result.get("eligible", [])) | set(result.get("no_prereq", []))
    elif kind == "eligibility":
        can_take = {c["code"] for c in result.get("courses", [])
                    if c.get("verdict") in ("SATISFIED", "NO_PREREQUISITES")}

    return Truth(
        targets=set(result.get("codes", [])),
        verdicts=verdicts,
        has=set(ctx.get("completed", [])) | set(ctx.get("in_progress", [])),
        history_known=bool(ctx.get("transcript_given")),
        can_take=can_take,
        source_text={s["id"]: s.get("text", "") for s in facts.sources},
    )


# ------------------------------------------------------------------ checks

def sentence_violations(sentence: Sentence, truth: Truth, facts: Facts) -> list[str]:
    text = sentence.text
    out: list[str] = []

    out += [f"mentions {c}, which isn't in the facts" for c in ungrounded_codes(text, facts.text)]
    out += [f"states {n}, which isn't in the facts" for n in ungrounded_numbers(text, facts.text)]
    # Remedy words are checked clause by clause, skipping negated clauses:
    # "you cannot repeat the other course for a higher grade" states the rule,
    # it doesn't suggest a way around it.
    remedies: list[str] = []
    for clause, _ in clauses(text):
        if NEGATIONS.search(clause):
            continue
        remedies += [w for w in ungrounded_remedies(clause, facts.text) if w not in remedies]
    out += [f"suggests '{w}', which the facts don't mention" for w in remedies]

    if CALENDAR_SILENT.search(text):
        # Five retrieved sections can't show what the whole calendar omits.
        out.append("claims the calendar is silent; only the retrieved sections can be checked")

    cited = " ".join(truth.source_text.get(c, "") for c in sentence.cites)
    for phrase in advice_phrases(text):
        grounded = any(said.search(phrase) and source.search(cited) for said, source in _GROUNDABLE)
        if not grounded:
            out.append(f"gives advice ('{phrase}') that no cited source contains")

    for clause, codes in clauses(text, truth.targets):
        hedged = HEDGES.search(clause) is not None
        about_target = not codes or bool(set(codes) & truth.targets)
        others = [c for c in codes if c not in truth.targets]

        # "…required on every route to CPSC 404, and you're eligible to take it
        # now" is about the ready course in the clause, not the target.
        ready_here = [c for c in others if truth.can_take and c in truth.can_take]

        if truth.verdicts and about_target and not hedged:
            if not truth.verdicts & {"SATISFIED", "NO_PREREQUISITES"} and not NEGATIONS.search(clause):
                for m in POSITIVE_CLAIMS.finditer(clause):
                    subject = claimed_codes(clause, codes, m)
                    if ready_here and not (set(subject) & truth.targets):
                        continue
                    if not _is_partial(clause, m):
                        out.append(f"says '{m.group(0)}' but the verdict isn't a yes")
            if "NOT_SATISFIED" not in truth.verdicts:
                for m in NEGATIVE_CLAIMS.finditer(clause):
                    if not _is_partial(clause, m):
                        out.append(f"says '{m.group(0)}' but the verdict isn't a no")

        avail = AVAILABILITY.search(clause)
        if truth.can_take is not None and others and avail and not hedged \
                and not NEGATIONS.search(clause):
            claimed = [c for c in claimed_codes(clause, codes, avail) if c not in truth.targets]
            wrong = [c for c in claimed if c not in truth.can_take and c not in truth.has]
            out += [f"says the student can take {c}, which isn't ready" for c in wrong]

        if truth.history_known:
            neg = HISTORY_NEGATIVE.search(clause)
            pos = HISTORY_POSITIVE.search(clause)
            if neg:
                out += [f"says the student hasn't completed {c}, but they have"
                        for c in claimed_codes(clause, codes, neg) if c in truth.has]
            elif pos and not hedged and not NEGATIONS.search(clause):
                out += [f"says the student completed {c}, which they didn't mention"
                        for c in claimed_codes(clause, codes, pos)
                        if c not in truth.has and c not in truth.targets]
    return out


KINDS = [
    ("mentions ", "invented code"),
    ("states ", "invented number"),
    ("suggests ", "invented remedy"),
    ("gives advice", "advice"),
    ("says the student can take", "not ready"),
    ("says the student completed", "invented history"),
    ("says the student hasn't", "contradicts history"),
    ("says '", "contradicts verdict"),
    ("claims the calendar is silent", "unverifiable absence"),
]


def violation_kind(message: str) -> str:
    return next((kind for prefix, kind in KINDS if message.startswith(prefix)), "other")


def check_answer(answer: Answer, result: dict, facts: Facts) -> dict[int, list[str]]:
    """Violations by sentence index. Empty means the answer may ship."""
    truth = truth_of(result, facts)
    found = {}
    for i, s in enumerate(answer["sentences"]):
        v = sentence_violations(Sentence(s["text"], s["cites"]), truth, facts)
        if v:
            found[i] = v
    return found


def describe(answer: Answer, violations: dict[int, list[str]]) -> list[str]:
    return [f'sentence {i + 1} ("{answer["sentences"][i]["text"]}"): {"; ".join(v)}'
            for i, v in sorted(violations.items())]


# ------------------------------------------------------------------ enforcement

def _with_guard(answer: Answer, action: str, before: dict, after: dict,
                draft: Answer | None = None) -> Answer:
    source = draft or answer
    return Answer(**{**answer, "guard": {
        "action": action,
        "violations": [f"{i + 1}: {m}" for i, ms in sorted(before.items()) for m in ms],
        "remaining": [f"{i + 1}: {m}" for i, ms in sorted(after.items()) for m in ms],
        # The flagged draft sentences themselves, so flags can be read by hand.
        "caught": [{"sentence": source["sentences"][i]["text"], "why": ms}
                   for i, ms in sorted(before.items())],
    }})


def guard(question: str, result: dict, answer: Answer,
          compose_fn: Callable[..., Answer] = compose) -> Answer:
    if answer["composed_by"] == "template" or not answer["sentences"]:
        return _with_guard(answer, "not needed", {}, {})
    facts = build_facts(question, result)
    before = check_answer(answer, result, facts)
    if not before:
        return _with_guard(answer, "passed", {}, {})

    # 1. Regenerate once, telling the model exactly what was wrong.
    retry = compose_fn(question, result, feedback=describe(answer, before), previous=answer)
    after = check_answer(retry, result, facts) if retry["composed_by"] == "llm" else None
    if after == {}:
        return _with_guard(retry, "regenerated", before, {}, draft=answer)

    # 2. Keep what's clean from the better attempt.
    base, bad = (retry, after) if after is not None and len(after) < len(before) else (answer, before)
    keep = [Sentence(s["text"], s["cites"]) for i, s in enumerate(base["sentences"]) if i not in bad]
    if keep:
        text, used = render(base["lead"], keep, facts)
        trimmed = Answer(**{**base, "text": text, "sources": used,
                            "sentences": [{"text": s.text, "cites": s.cites} for s in keep]})
        return _with_guard(trimmed, "trimmed", before, {}, draft=answer)

    # 3. Nothing survived: the template explanation.
    body = plain_answer(result, facts)
    text, used = render(base["lead"], body, facts)
    fallback = Answer(**{**base, "text": text, "sources": used, "composed_by": "fallback",
                         "sentences": [{"text": s.text, "cites": s.cites} for s in body]})
    return _with_guard(fallback, "fallback", before, {}, draft=answer)
