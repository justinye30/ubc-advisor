"""Ways a composed answer can drift from its facts. Pure functions.

Step 14 only measures these (the composer eval reports them). Step 15's
citation guard enforces them.
"""

import re

from core.codes import find_codes

ADVICE_PATTERNS = [
    r"\byou should\b",
    r"\bI(?: would|'d)? (?:recommend|suggest|advise)\b",
    r"\bI(?: would|'d) (?:take|go with|start with)\b",
    r"\b(?:consider|try) taking\b",
    r"\byou (?:might|may) want to (?:take|consider|start)\b",
    r"\b(?:the )?best (?:option|choice|course|path|route)\b",
    r"\bit(?:'s| is| would be) (?:a good idea|wise|better|best)\b",
    r"\byou(?:'d| would| will)? need to (?:either |also |first )?(?:take|complete|retake|repeat|finish|get|achieve|earn|raise)\b",
    r"\b(?:consult|contact|speak (?:with|to)|talk to) (?:with )?(?:an? |your |the )?(?:\w+ )?advis",
]

# Ways to "fix" a gap. Fine when the facts discuss them (a repeat-course policy),
# invented when they don't (retaking a passed course is often not allowed).
REMEDY_WORDS = ["retake", "re-take", "repeat", "upgrade", "raise your grade",
                "improve your grade", "higher grade", "higher mark"]

POSITIVE_CLAIMS = re.compile(
    r"\byou (?:can|may) (?:take|register|enrol)|\byou(?:'re| are) eligible"
    r"|\byou (?:meet|satisfy|qualify)|\byou(?:'re| are) (?:all set|good to go|qualified)",
    re.IGNORECASE)
NEGATIVE_CLAIMS = re.compile(
    r"\byou (?:can't|cannot|can not) (?:take|register|enrol)|\byou(?:'re| are) not eligible"
    r"|\byou (?:don't|do not) (?:meet|satisfy|qualify)|\byou(?:'re| are) not qualified",
    re.IGNORECASE)

_BARE_NUMBER = re.compile(r"(?<![\d.%$])\b(\d{3}[A-Z]?)\b(?![\d%])")
_PERCENT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
_CREDITS = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*credits?\b", re.IGNORECASE)


def advice_phrases(text: str) -> list[str]:
    return [m.group(0) for p in ADVICE_PATTERNS for m in re.finditer(p, text, re.IGNORECASE)]


def ungrounded_codes(answer: str, facts: str) -> list[str]:
    """Course codes, and bare course-like numbers, that the facts never mention."""
    known = set(find_codes(facts))
    out = [c for c in find_codes(answer) if c not in known]
    fact_numbers = {n for n in _BARE_NUMBER.findall(facts)}
    code_numbers = {c.split()[-1] for c in find_codes(answer)}
    out += [n for n in dict.fromkeys(_BARE_NUMBER.findall(answer))
            if n not in fact_numbers and n not in code_numbers]
    return out


def ungrounded_numbers(answer: str, facts: str) -> list[str]:
    """Percentages and credit counts in the answer that the facts don't contain."""
    def numbers(pattern: re.Pattern, text: str) -> set[str]:
        return {m.group(1).rstrip("0").rstrip(".") if "." in m.group(1) else m.group(1)
                for m in pattern.finditer(text)}
    fact_numbers = set(re.findall(r"\d+(?:\.\d+)?", facts))
    found = numbers(_PERCENT, answer) | numbers(_CREDITS, answer)
    return sorted(n for n in found if n not in fact_numbers)


def ungrounded_remedies(answer: str, facts: str) -> list[str]:
    body, known = answer.lower(), facts.lower()
    return [w for w in REMEDY_WORDS if w in body and w not in known]


def verdicts_in(result: dict) -> set[str]:
    states = {c["verdict"] for c in result.get("courses", []) if c.get("verdict")}
    if result.get("kind") == "path" and result.get("verdict"):
        states.add(result["verdict"])
    return states


def _sentences(text: str) -> list[str]:
    return [x for x in re.split(r"(?<=[.!?])\s+", text) if x.strip()]


def verdict_conflicts(result: dict, body: str) -> list[str]:
    """Claims in the explanation that the computed verdicts don't support.

    Checked sentence by sentence, and only for sentences about the course the
    verdict is for (or about no course at all): "you can take CPSC 221 now"
    is true on the way to CPSC 404 even though CPSC 404 is out of reach.
    """
    states = verdicts_in(result)
    if not states:
        return []
    targets = set(result.get("codes", []))
    out = []
    for sentence in _sentences(body):
        mentioned = set(find_codes(sentence))
        if mentioned and not (mentioned & targets):
            continue
        if not states & {"SATISFIED", "NO_PREREQUISITES"}:
            out += [f"claims eligibility: '{m.group(0)}'" for m in POSITIVE_CLAIMS.finditer(sentence)]
        if "NOT_SATISFIED" not in states:
            out += [f"claims ineligibility: '{m.group(0)}'" for m in NEGATIVE_CLAIMS.finditer(sentence)]
    return out


def drift(result: dict, facts: str, body: str) -> dict[str, list[str]]:
    return {
        "advice": advice_phrases(body),
        "ungrounded_codes": ungrounded_codes(body, facts),
        "ungrounded_numbers": ungrounded_numbers(body, facts),
        "ungrounded_remedies": ungrounded_remedies(body, facts),
        "verdict_conflicts": verdict_conflicts(result, body),
    }
