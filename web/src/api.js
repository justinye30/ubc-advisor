// The one place the UI talks to the server.

// `npm run dev:mock`: canned answers from mock.js, no server or API calls.
// Vite fixes MODE at build time, so a normal build drops the mock branches.
// Where mock.js gets imported, test MODE inline rather than through MOCK:
// only then is the import dropped too, instead of shipping an unused chunk.
export const MOCK = import.meta.env.MODE === "mock";
const MOCK_DELAY_MS = 900;

const TIMEOUT_MS = 130_000; // a little over gunicorn's 120s, so the server gives up first

export class AskError extends Error {
  constructor(message, { status = null, requestId = null } = {}) {
    super(message);
    this.status = status;
    this.requestId = requestId;
  }
}

export async function ask(question, { signal } = {}) {
  if (import.meta.env.MODE === "mock") return mockAsk(question, signal);
  const timeout = AbortSignal.timeout(TIMEOUT_MS);
  let res;
  try {
    res = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    });
  } catch (err) {
    if (err.name === "TimeoutError") {
      throw new AskError("No answer after two minutes, so the request was stopped. Try again.");
    }
    if (err.name === "AbortError") throw err; // the student cancelled; not an error to show
    throw new AskError("Can't reach the server. Check that the API is running, then try again.");
  }

  let body = null;
  try {
    body = await res.json();
  } catch {
    // not JSON: a proxy error page, or a login redirect once Cognito is in front
  }
  if (!res.ok || body === null) {
    throw new AskError(body?.error?.message ?? `The server responded with ${res.status}.`, {
      status: res.status,
      requestId: body?.error?.request_id ?? res.headers.get("X-Request-Id"),
    });
  }
  return body;
}

async function mockAsk(question, signal) {
  const { pickMock } = await import("./mock.js");
  const m = pickMock(question);
  await new Promise((resolve, reject) => {
    const t = setTimeout(resolve, m.delay ?? MOCK_DELAY_MS);
    signal?.addEventListener("abort", () => {
      clearTimeout(t);
      reject(new DOMException("Stopped", "AbortError"));
    }, { once: true });
  });
  if (m.error) throw new AskError(m.error.message, m.error);
  return structuredClone(m.response);
}
