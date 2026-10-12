import { describe, expect, test } from "vitest";
import { applyClarification, paragraphs, splitCitations, verdictsOf, withGrades } from "./lib.js";

describe("splitCitations", () => {
  test("separates markers from prose", () => {
    expect(splitCitations("Yes. [1] Also this. [2][3]")).toEqual([
      { type: "text", value: "Yes. " },
      { type: "cite", n: 1 },
      { type: "text", value: " Also this. " },
      { type: "cite", n: 2 },
      { type: "cite", n: 3 },
    ]);
  });
  test("leaves text without markers alone", () => {
    expect(splitCitations("Which course?")).toEqual([{ type: "text", value: "Which course?" }]);
  });
});

describe("applyClarification", () => {
  test("replaces the number the student typed", () => {
    expect(applyClarification("is 320 open to me?", "320", "CPSC 320")).toBe("is CPSC 320 open to me?");
  });
  test("does not replace inside a longer number", () => {
    expect(applyClarification("I did 1320 and 320", "320", "MATH 320")).toBe("I did 1320 and MATH 320");
  });
  test("falls back to saying which course was meant", () => {
    expect(applyClarification("can I take it?", "320", "CPSC 320")).toBe("can I take it? (I mean CPSC 320)");
  });
  test("treats regex characters literally", () => {
    expect(applyClarification("what about 3.2?", "3.2", "CPSC 320")).toBe("what about CPSC 320?");
  });
});

describe("verdictsOf", () => {
  test("one line per course found, skipping missing ones", () => {
    const r = { kind: "eligibility", details: { courses: [
      { code: "CPSC 221", found: true, title: "Algorithms", verdict: "SATISFIED", source_url: "u" },
      { code: "CPSC 999", found: false },
      { code: "CPSC 213", found: true, title: "Systems" },   // requirements only: no verdict
    ] } };
    expect(verdictsOf(r)).toEqual([{ code: "CPSC 221", title: "Algorithms", verdict: "SATISFIED", url: "u" }]);
  });
  test("path verdicts use the target code", () => {
    const r = { kind: "path", codes: ["CPSC 404"], details: { verdict: "NOT_SATISFIED", title: "DB" } };
    expect(verdictsOf(r)[0]).toMatchObject({ code: "CPSC 404", verdict: "NOT_SATISFIED" });
  });
  test("nothing for policy answers", () => {
    expect(verdictsOf({ kind: "policy", details: {} })).toEqual([]);
  });
});

test("paragraphs and grades", () => {
  expect(paragraphs("a\n\n b \n\n\n")).toEqual(["a", "b"]);
  expect(withGrades(["MATH 226", "CPSC 210"], { "MATH 226": "72" })).toEqual(["MATH 226 (72)", "CPSC 210"]);
});
