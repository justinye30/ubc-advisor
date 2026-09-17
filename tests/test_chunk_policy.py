"""Chunker tests against a hand-written excerpt shaped like a calendar page.

No scraped HTML is committed (see DECISIONS.md, Terms of Use).
"""

from collections import Counter
from itertools import pairwise

from ingest.chunk_policy import CHROME_CANARIES, chunk_page

URL = ("https://vancouver.calendar.ubc.ca/faculties-colleges-and-schools/"
       "faculty-science/bachelor-science/computer-science")

PAGE = """
<html><body>
<a href="#main-content">Skip to main content</a>
<nav><h2>Main navigation</h2><ul><li><a href="/">Home</a></li></ul></nav>
<main>
  <h1>Computer Science</h1>
  <article class="node node--type-page node--view-mode-full">
    <ul class="share">
      <li>Print-friendly version</li>
      <li><a href="mailto:?subject=">Share via email</a></li>
    </ul>
    <div class="field">
      <p>The Department of Computer Science offers degrees.</p>
      <h3>Lecture-based courses</h3>
      <p>Lecture-based refers to all CPSC_V courses except CPSC_V 448 and 449.</p>
      <h3>Specializations</h3>
      <h4>Major (0376): Computer Science (CPSC)</h4>
      <table>
        <tr><th>Second Year</th><th></th></tr>
        <tr><td>CPSC_V 210<sup>1</sup></td><td>4</td></tr>
        <tr><td>STAT_V 251<sup>2</sup></td><td>3</td></tr>
        <tr><td><sup>2</sup> May be replaced by STAT_V 200 provided 302 is taken.</td><td></td></tr>
      </table>
    </div>
  </article>
</main>
</body></html>
"""


def chunks_for(html=PAGE, url=URL):
    return chunk_page(url, html, Counter())


def find(chunks, needle):
    return [c for c in chunks if needle in c.content]


def test_footnote_markers_do_not_merge_into_course_numbers():
    text = "\n".join(c.content for c in chunks_for())
    assert "CPSC_V 210 [1]" in text
    assert "2101" not in text
    assert "2512" not in text


def test_table_footnotes_stay_with_their_rows():
    [chunk] = find(chunks_for(), "STAT_V 251")
    assert "May be replaced by STAT_V 200" in chunk.content


def test_section_path_tracks_heading_nesting():
    [chunk] = find(chunks_for(), "STAT_V 251")
    assert chunk.section_path == (
        "B.Sc. > Computer Science > Specializations > "
        "Major (0376): Computer Science (CPSC)"
    )


def test_sibling_heading_replaces_previous_one():
    [chunk] = find(chunks_for(), "STAT_V 251")
    assert "Lecture-based" not in chunk.section_path


def test_intro_text_sits_at_document_level():
    [chunk] = find(chunks_for(), "offers degrees")
    assert chunk.section_path == "B.Sc. > Computer Science"


def test_no_page_chrome_in_any_chunk():
    for c in chunks_for():
        for canary in CHROME_CANARIES:
            assert canary not in c.content


def test_content_starts_with_section_path():
    for c in chunks_for():
        assert c.content.startswith(c.section_path)


def test_long_section_splits_at_paragraphs_with_overlap():
    paras = "".join(f"<p>Rule {i}: " + "word " * 60 + f"end{i}.</p>" for i in range(12))
    html = f"<main><h1>Registration</h1><article class='node--view-mode-full'><h3>Repeating Courses</h3>{paras}</article></main>"
    chunks = chunks_for(html)

    assert len(chunks) > 1
    for c in chunks:
        # every paragraph appears whole or not at all
        for i in range(12):
            assert (f"Rule {i}:" in c.content) == (f"end{i}." in c.content)
    # consecutive chunks share a paragraph
    for a, b in pairwise(chunks):
        last_rule = a.content.rsplit("Rule ", 1)[1].split(":")[0]
        assert f"Rule {last_rule}:" in b.content


def test_tables_are_never_carried_as_overlap():
    rows = "".join(f"<tr><td>MATH_V {100 + i}</td><td>3</td></tr>" for i in range(80))
    html = (f"<main><h1>X</h1><article class='node--view-mode-full'><h3>S</h3>"
            f"<table>{rows}</table><p>After the table.</p></article></main>")
    chunks = chunks_for(html)
    assert sum("MATH_V 100 |" in c.content for c in chunks) == 1


def test_missing_content_root_returns_nothing():
    stats = Counter()
    assert chunk_page(URL, "<html><body><div>hi</div></body></html>", stats) == []
    assert stats["no_content_root"] == 1


def test_share_widget_nested_inside_content_wrapper_does_not_hide_content():
    """Regression: on some pages the share widget and the real prose share one
    top-level wrapper div, unlike the fixture above where they're siblings
    under <article>. A whole-subtree chrome check wrongly discards the whole
    wrapper — and every paragraph in it — because the mailto link is somewhere
    inside. Only the widget itself should be removed."""
    html = """
    <main><h1>Introduction to Degree Options</h1>
    <article class="node--view-mode-full">
      <div class="field">
        <ul class="share">
          <li>Print-friendly version</li>
          <li><a href="mailto:?subject=">Share via email</a></li>
        </ul>
        <p>The B.Sc. degree begins with study of the foundations of science.</p>
        <p>To earn a B.Sc. students must follow one of seven options.</p>
      </div>
    </article></main>
    """
    chunks = chunks_for(html)
    text = "\n".join(c.content for c in chunks)
    assert "foundations of science" in text
    assert "seven options" in text
    for canary in CHROME_CANARIES:
        assert canary not in text
        

def test_unknown_url_gets_generic_scope():
    [first, *_] = chunks_for(url="https://vancouver.calendar.ubc.ca/something-else")
    assert first.section_path.startswith("Calendar > ")
