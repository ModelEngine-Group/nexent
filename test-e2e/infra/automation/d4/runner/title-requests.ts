import type { Page, Request, Response } from "playwright/test";
import { writeFileSync } from "node:fs";

// Observe browser lifecycle events: Request.response()/Response.finished()
// promises can remain pending across navigation or a cancelled request.
// Retain paths and terminal classifications, never headers or response bodies.
export function watchTitleRequests(page: Page, evidencePath: string) {
  type Entry = { path: string; state: "pending" | "finished" | "failed"; status?: number };
  const entries = new Map<Request, Entry>();
  const save = () => writeFileSync(evidencePath, JSON.stringify({
    recorded_at: new Date().toISOString(), requests: [...entries.values()],
  }, null, 2) + "\n");
  const onRequest = (request: Request) => {
    const path = new URL(request.url()).pathname;
    if (path.endsWith("/conversation/generate_title")) {
      entries.set(request, { path, state: "pending" });
      save();
    }
  };
  const onResponse = (response: Response) => {
    const entry = entries.get(response.request());
    if (entry) { entry.status = response.status(); save(); }
  };
  const onFinished = (request: Request) => {
    const entry = entries.get(request);
    if (entry) { entry.state = "finished"; save(); }
  };
  const onFailed = (request: Request) => {
    const entry = entries.get(request);
    if (entry) { entry.state = "failed"; save(); }
  };
  page.on("request", onRequest);
  page.on("response", onResponse);
  page.on("requestfinished", onFinished);
  page.on("requestfailed", onFailed);
  return {
    async settle(timeoutMs = 120_000) {
      const deadline = Date.now() + timeoutMs;
      while ([...entries.values()].some((entry) => entry.state === "pending")) {
        if (Date.now() >= deadline) {
          save();
          const error = new Error(`Automatic title request did not settle within ${timeoutMs}ms; inspect title-requests.json`);
          error.name = "TimeoutError";
          throw error;
        }
        await page.waitForTimeout(Math.min(100, Math.max(1, deadline - Date.now())));
      }
      save();
      // Failed/aborted browser requests are terminal, not evidence of title
      // persistence. Callers still assert both server state and refreshed UI.
    },
    close() {
      save();
      page.off("request", onRequest);
      page.off("response", onResponse);
      page.off("requestfinished", onFinished);
      page.off("requestfailed", onFailed);
    },
  };
}
