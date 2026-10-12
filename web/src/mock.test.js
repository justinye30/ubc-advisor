import { describe, expect, test } from "vitest";
import { applyClarification, verdictsOf } from "./lib.js";
import { MOCKS, pickMock } from "./mock.js";

describe("pickMock", () => {
  test("each listed question gets its own fixture", () => {
    for (const m of MOCKS) expect(pickMock(m.question).name).toBe(m.name);
  });
  test("typed questions match by pattern", () => {
    expect(pickMock("what does MATH 200 unlock?").name).toBe("unlock");
    expect(pickMock("how many times can I repeat a course").name).toBe("policy");
  });
  test("picking an option after a clarification gives an answer, not another question", () => {
    const clarify = MOCKS.find((m) => m.name === "clarification");
    const opt = clarify.response.clarification.options[0];
    const next = applyClarification(clarify.question, opt.as_written, opt.candidates[0]);
    expect(pickMock(next).response.status).toBe("evaluated");
  });
});

test("every fixture has what the answer view reads", () => {
  for (const m of MOCKS) {
    if (m.error) {
      expect(m.error.message).toBeTruthy();
      continue;
    }
    const r = m.response;
    expect(r.answer.text, m.name).toBeTypeOf("string");
    expect(Array.isArray(r.answer.sources), m.name).toBe(true);
    expect(r.details, m.name).toBeTypeOf("object");
    if (r.status === "evaluated") expect(verdictsOf(r).length, m.name).toBeGreaterThan(0);
  }
});
