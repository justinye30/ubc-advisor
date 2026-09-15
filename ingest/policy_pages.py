"""Policy pages to ingest. Deliberately short: more corpus is not better
retrieval, it's more chances to retrieve the wrong thing.

Every URL here should be the canonical slug URL, not /node/NNNNN.
The fetcher warns if the server redirects somewhere else.
"""

_BSC = "https://vancouver.calendar.ubc.ca/faculties-colleges-and-schools/faculty-science/bachelor-science"

POLICY_PAGES: list[str] = [
    # Program requirements — the page most questions will hit
    f"{_BSC}/computer-science",
    f"{_BSC}/introduction-degree-options",
    f"{_BSC}/general-degree-requirements",
    f"{_BSC}/communication-requirements",
    f"{_BSC}/science-and-arts-requirements",
    f"{_BSC}/lower-level-requirements",
    f"{_BSC}/upper-level-requirement",
    f"{_BSC}/promotion-requirements-and-degree-progression",
    # Regulations — repeating, credit, registration, standing
    f"{_BSC}/general-academic-regulations",
    f"{_BSC}/registration",
    f"{_BSC}/course-and-specialization-approval",
    f"{_BSC}/credit-ubc-and-elsewhere",
    f"{_BSC}/academic-performance-review-and-continuation",
]
