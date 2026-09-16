"""Graph logic that doesn't need a database: flattening, required chains,
tree drawing, and what-does-this-unlock bucketing."""

from core.graph import Dependent, EdgeRow, PathView, always_required, unlocks_for
from core.transcript import Transcript
from core.tree import edges
from ingest.rebuild_edges import derive


def C(code):
    return {"op": "COURSE", "code": code, "tracked": True}


def ALL(*kids):
    return {"op": "ALL_OF", "children": list(kids)}


def ONE(*kids):
    return {"op": "ONE_OF", "children": list(kids)}


def GRADE(pct, child):
    return {"op": "MIN_GRADE", "percent": pct, "child": child}


# ---------- flattening ----------

def test_edges_mark_alternatives_optional():
    assert dict(edges(ALL(C("A"), ONE(C("B"), C("D"))))) == {"A": False, "B": True, "D": True}


def test_edges_one_required_occurrence_wins():
    # The old flattening kept whichever occurrence came first — here, optional.
    assert dict(edges(ALL(ONE(C("A"), C("B")), C("A")))) == {"A": False, "B": True}


def test_edges_optional_everywhere_stays_optional():
    assert dict(edges(ONE(C("A"), ALL(C("A"), C("B"))))) == {"A": True, "B": True}


def test_edges_grade_threshold_keeps_parent_optionality():
    assert dict(edges(ALL(GRADE(68, C("A")), ONE(GRADE(70, C("B")), C("D"))))) == {
        "A": False, "B": True, "D": True,
    }


def test_derive_skips_self_references():
    out, self_refs = derive([("X 100", ALL(C("X 100"), C("Y 100")))])
    assert out == {("X 100", "Y 100", False)}
    assert self_refs == ["X 100"]


# ---------- required chains ----------

def E(course, requires, optional=False, known=True, status="parsed", title=None, tree=None):
    return EdgeRow(course, requires, optional, title, known, status, tree)


ROWS = [
    E("T", "A"),                 # T requires A
    E("T", "B", optional=True),  # T: B is one option
    E("A", "C"),                 # A requires C  -> C required for T
    E("B", "D"),                 # B requires D  -> D NOT required (B is optional)
    E("C", "EXT", known=False),  # C requires something outside our data
]


def test_required_chain_is_transitive():
    assert set(always_required("T", ROWS)) == {"A", "C", "EXT"}


def test_optional_hop_breaks_the_chain():
    assert "D" not in always_required("T", ROWS)
    assert "B" not in always_required("T", ROWS)


def test_required_chain_survives_a_cycle():
    rows = [E("T", "A"), E("A", "B"), E("B", "A")]
    assert set(always_required("T", rows)) == {"A", "B"}


def test_required_chain_stops_at_given_courses():
    assert set(always_required("T", ROWS, stop_at={"A"})) == {"A"}


# ---------- path view ----------

def STANDING(year):
    return {"op": "STANDING", "year": year}


def OKANAGAN(code):
    return {"op": "OUT_OF_SCOPE", "code": code, "reason": "okanagan"}


def U(code):
    return {"op": "COURSE", "code": code, "tracked": False}


def draw(target_tree, rows, spec="", year=None):
    view = PathView("T", target_tree, rows, Transcript.parse(spec, year=year))
    return view, "\n".join(view.render())


def test_path_stops_at_courses_already_takeable():
    # T needs P; P needs X; X needs (Y or Z) and the student has Y.
    # X is ready, so nothing beneath it (Z's whole lineage) is drawn.
    x_tree = ONE(C("Y"), C("Z"))
    rows = [
        E("T", "P", tree=ALL(C("X"))),
        E("P", "X", tree=x_tree),
        E("X", "Y", optional=True), E("X", "Z", optional=True, tree=ALL(C("Z0"))),
        E("Z", "Z0"),
    ]
    view, text = draw(ALL(C("P")), rows, "Y")
    assert "→ X" in text and "ready to take" in text
    assert "Z" not in text.replace("ready", "")
    assert view.ready() == {"X"}


def test_path_hides_alternatives_already_satisfied():
    rows = [E("T", "A", optional=True), E("T", "B", optional=True), E("T", "C")]
    _, text = draw(ALL(ONE(C("A"), C("B")), C("C")), rows, "A")
    assert "C " in text
    assert " B " not in text


def test_path_shows_non_course_blockers():
    _, text = draw(ALL(C("A"), STANDING(3)), [E("T", "A")])
    assert "? year standing not provided" in text


def test_path_hides_okanagan_alternatives_but_counts_them():
    view, text = draw(ONE(C("A"), OKANAGAN("MATH_O 200")), [E("T", "A", optional=True)])
    assert "MATH_O" not in text
    assert view.hidden_okanagan == 1


def test_path_explains_grade_problems_on_completed_courses():
    rows = [E("T", "A")]
    _, low = draw(ALL(GRADE(68, C("A"))), rows, "A:60")
    _, missing = draw(ALL(GRADE(68, C("A"))), rows, "A")
    assert "✓ A" in low and "grade below requirement" in low
    assert "grade not reported" in missing


def test_path_labels_codes_we_cannot_check():
    tree = ALL(U("PREC 12"), C("CPSC 261"), C("CPSC 999"))
    rows = [E("T", "PREC 12", known=False), E("T", "CPSC 261", known=False),
            E("T", "CPSC 999", known=False)]
    _, text = draw(tree, rows)
    assert "high-school course" in text
    assert "no longer offered" in text
    assert "not in current calendar" in text


def test_path_marks_courses_without_prerequisites_ready():
    rows = [E("T", "A", status="no_prereq")]
    _, text = draw(ALL(C("A")), rows)
    assert "→ A" in text


def test_path_draws_shared_subtree_once():
    s_tree = ALL(C("Z"))
    rows = [E("T", "A", tree=ALL(C("S"), C("X"))), E("T", "B", tree=ALL(C("S"))),
            E("A", "S", tree=s_tree), E("A", "X"), E("B", "S", tree=s_tree),
            E("S", "Z", tree=ALL(C("W"))), E("Z", "W")]
    _, text = draw(ALL(C("A"), C("B")), rows)
    assert text.count(" Z ") == 1
    assert "(shown above)" in text


def test_path_cycle_back_to_target_terminates():
    rows = [E("T", "A", tree=ALL(C("T"))), E("A", "T", tree=ALL(C("A")))]
    _, text = draw(ALL(C("A")), rows)
    assert len(text.splitlines()) == 2


# ---------- unlocks ----------

def dep(code, tree, optional=False):
    return Dependent(code, None, optional, "parsed", tree)


def t_(spec):
    return Transcript.parse(spec)


def test_unlocks_buckets():
    candidates = [
        dep("NEW", ALL(C("X"), C("HAVE"))),        # X completes it
        dep("GRADE", ALL(GRADE(68, C("X")))),      # needs a grade we don't know
        dep("BLOCK", ALL(C("X"), C("MISSING"))),   # still missing something
        dep("ALREADY", ONE(C("X"), C("HAVE"))),    # satisfied without X
    ]
    u = unlocks_for("X", t_("HAVE"), candidates)
    assert [d.code for d, _ in u.newly_eligible] == ["NEW"]
    assert [d.code for d, _ in u.to_confirm] == ["GRADE"]
    assert [d.code for d, _ in u.still_blocked] == ["BLOCK"]
    assert [d.code for d in u.already_eligible] == ["ALREADY"]
    assert "MISSING" in u.still_blocked[0][1].headline


def test_unlocks_skips_courses_already_taken():
    u = unlocks_for("X", t_("DONE"), [dep("DONE", ALL(C("X")))])
    assert not (u.newly_eligible or u.to_confirm or u.still_blocked or u.already_eligible)


def test_unlocks_does_not_mutate_transcript():
    t = t_("HAVE")
    unlocks_for("X", t, [dep("NEW", ALL(C("X")))])
    assert t.completed == {"HAVE"}


def test_dead_ends_are_grouped_by_meaning():
    from ingest.rebuild_edges import classify_dead_ends
    groups = classify_dead_ends({"PREC 12", "CPSC 261", "CPSC 999", "AI 240", "MATH 11"})
    assert groups == {
        "high_school": ["MATH 11", "PREC 12"],
        "retired": ["CPSC 261"],
        "unexplained": ["CPSC 999"],
        "out_of_scope": ["AI 240"],
    }


def test_path_does_not_explore_options_when_a_sibling_is_ready():
    # T needs one of (R, D). R has no prerequisites, so D's lineage is a detour.
    rows = [E("T", "R", optional=True, status="no_prereq"),
            E("T", "D", optional=True, tree=ALL(C("DEEP"))), E("D", "DEEP")]
    _, text = draw(ONE(C("R"), C("D")), rows)
    assert "→ R" in text
    assert "another option is ready" in text
    assert "DEEP" not in text


def test_path_still_explores_groups_with_nothing_ready():
    # ALL_OF( one of (R ready, X), one of (Y, Z) ): Y and Z still get expanded.
    rows = [E("T", "R", optional=True, status="no_prereq"),
            E("T", "X", optional=True, tree=ALL(C("X0"))), E("X", "X0"),
            E("T", "Y", optional=True, tree=ALL(C("Y0"))), E("Y", "Y0"),
            E("T", "Z", optional=True, tree=ALL(C("Z0"))), E("Z", "Z0")]
    _, text = draw(ALL(ONE(C("R"), C("X")), ONE(C("Y"), C("Z"))), rows)
    assert "X0" not in text
    assert "Y0" in text and "Z0" in text


def test_path_draws_identical_prerequisite_sets_once():
    hs = ONE(U("PREC 12"), U("MATH 12"))
    rows = [E("T", c, optional=True, tree=hs) for c in ("M100", "M102", "M104")]
    rows += [E(c, h, optional=True, known=False)
             for c in ("M100", "M102", "M104") for h in ("PREC 12", "MATH 12")]
    _, text = draw(ONE(C("M100"), C("M102"), C("M104")), rows)
    assert text.count("PREC 12") == 1
    assert "(same as M100)" in text


def test_okanagan_count_is_not_doubled_by_repeat_lookups():
    view, _ = draw(ONE(C("A"), OKANAGAN("MATH_O 200")), [E("T", "A", optional=True)])
    view.blockers("T")
    view.render()
    assert view.hidden_okanagan == 1