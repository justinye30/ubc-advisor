"""Boolean requirement trees: node types, validation, and traversal.

A prerequisite is represented as a tree of nodes. Leaf nodes assert a fact
about a student (took a course, has standing, earned a grade); interior
nodes combine them with AND/OR.

The UNPARSED and EXTERNAL_LIST escape hatches exist so the extractor can
admit ignorance instead of approximating. Both force INDETERMINATE
downstream, which is the honest answer.
"""

from typing import Any, Iterator

# Interior nodes: combine children
COMBINATORS = {"ALL_OF", "ONE_OF"}

# Leaf nodes: assert something about the student
LEAVES = {
    "COURSE",         # took this course.            {code, tracked}
    "MIN_GRADE",      # met a grade threshold.       {percent, child}
    "MIN_CREDITS",    # earned N credits from a set. {credits, from}
    "STANDING",       # is in year N or later.       {year}
    "PROGRAM",        # is registered in a program.  {name}
    "PERMISSION",     # needs instructor/dept OK.    {note}
    "OUT_OF_SCOPE",   # a real course we don't hold. {code, reason}
    "EXTERNAL_LIST",  # a list we haven't ingested.  {description, url}
    "UNPARSED",       # could not be structured.     {text}
}

VALID_OPS = COMBINATORS | LEAVES

# Nodes that can never be satisfied from a transcript alone
ALWAYS_INDETERMINATE = {"PERMISSION", "EXTERNAL_LIST", "UNPARSED"}


class TreeError(ValueError):
    """A tree violates the node schema."""


def validate(node: Any, path: str = "root") -> None:
    """Raise TreeError if the node (recursively) is malformed."""
    if not isinstance(node, dict):
        raise TreeError(f"{path}: expected object, got {type(node).__name__}")

    op = node.get("op")
    if op not in VALID_OPS:
        raise TreeError(f"{path}: unknown op {op!r}")

    if op in COMBINATORS:
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise TreeError(f"{path}: {op} needs a non-empty children list")
        for i, child in enumerate(children):
            validate(child, f"{path}.{op}[{i}]")
        return

    if op == "COURSE":
        if not isinstance(node.get("code"), str):
            raise TreeError(f"{path}: COURSE needs a code string")

    elif op == "MIN_GRADE":
        percent = node.get("percent")
        if not isinstance(percent, (int, float)) or not 0 < percent <= 100:
            raise TreeError(f"{path}: MIN_GRADE percent out of range: {percent!r}")
        if "child" not in node:
            raise TreeError(f"{path}: MIN_GRADE needs a child node")
        validate(node["child"], f"{path}.MIN_GRADE.child")

    elif op == "MIN_CREDITS":
        if not isinstance(node.get("credits"), (int, float)):
            raise TreeError(f"{path}: MIN_CREDITS needs a numeric credits value")
        spec = node.get("from")
        if not isinstance(spec, dict):
            raise TreeError(f"{path}: MIN_CREDITS needs a 'from' object")
        if not (spec.get("subjects") or spec.get("courses")):
            raise TreeError(f"{path}: MIN_CREDITS 'from' needs subjects or courses")

    elif op == "STANDING":
        if node.get("year") not in (1, 2, 3, 4, 5):
            raise TreeError(f"{path}: STANDING year invalid: {node.get('year')!r}")

    elif op == "PROGRAM":
        if not isinstance(node.get("name"), str):
            raise TreeError(f"{path}: PROGRAM needs a name string")

    elif op == "OUT_OF_SCOPE":
        if not isinstance(node.get("code"), str):
            raise TreeError(f"{path}: OUT_OF_SCOPE needs a code string")

    elif op == "UNPARSED":
        if not isinstance(node.get("text"), str) or not node["text"].strip():
            raise TreeError(f"{path}: UNPARSED needs non-empty source text")

    elif op == "EXTERNAL_LIST":
        if not isinstance(node.get("description"), str):
            raise TreeError(f"{path}: EXTERNAL_LIST needs a description")


def walk(node: dict) -> Iterator[dict]:
    """Yield every node in the tree, depth-first."""
    yield node
    for child in node.get("children", []):
        yield from walk(child)
    if "child" in node:
        yield from walk(node["child"])


def course_codes(node: dict, include_untracked: bool = True) -> set[str]:
    """Every course code referenced anywhere in the tree."""
    codes = set()
    for n in walk(node):
        if n["op"] == "COURSE":
            if include_untracked or n.get("tracked", True):
                codes.add(n["code"])
        elif n["op"] == "MIN_CREDITS":
            codes.update(n.get("from", {}).get("courses", []))
    return codes


def has_indeterminate(node: dict) -> bool:
    """True if any node can never be resolved from a transcript alone."""
    return any(n["op"] in ALWAYS_INDETERMINATE for n in walk(node))


def edges(node: dict) -> list[tuple[str, bool]]:
    """Flatten to (course_code, is_optional) pairs for prereq_edges.

    is_optional is True when the course sits under any ONE_OF, meaning
    alternatives exist. Without this a graph view would wrongly imply
    every listed course is required.
    """
    out: list[tuple[str, bool]] = []

    def visit(n: dict, optional: bool) -> None:
        op = n["op"]
        if op == "COURSE":
            out.append((n["code"], optional))
        elif op == "MIN_CREDITS":
            for code in n.get("from", {}).get("courses", []):
                out.append((code, True))
        for child in n.get("children", []):
            visit(child, optional or op == "ONE_OF")
        if "child" in n:
            visit(n["child"], optional)

    visit(node, False)
    return out

def canonical(node: dict) -> tuple:
    """A hashable, order-insensitive form of a tree.

    Children of ALL_OF and ONE_OF are sorted, since order carries no meaning.
    Two trees with the same canonical form are semantically equivalent.
    """
    op = node["op"]

    if op in COMBINATORS:
        return (op, tuple(sorted(canonical(c) for c in node["children"])))

    if op == "COURSE":
        return (op, node["code"], node.get("tracked", True))
    if op == "MIN_GRADE":
        return (op, node["percent"], canonical(node["child"]))
    if op == "MIN_CREDITS":
        spec = node.get("from", {})
        return (
            op,
            node["credits"],
            tuple(sorted(spec.get("subjects", []))),
            tuple(sorted(spec.get("courses", []))),
            spec.get("level_min"),
        )
    if op == "STANDING":
        return (op, node["year"])
    if op == "PROGRAM":
        return (op, node["name"])
    if op == "OUT_OF_SCOPE":
        return (op, node["code"])
    # PERMISSION, EXTERNAL_LIST, UNPARSED: presence matters, wording doesn't
    return (op,)


def node_type_counts(node: dict) -> dict[str, int]:
    """How many of each op appear in the tree. For failure breakdowns."""
    counts: dict[str, int] = {}
    for n in walk(node):
        counts[n["op"]] = counts.get(n["op"], 0) + 1
    return counts