import type { Page, Response } from "playwright/test";
import { writeFileSync } from "node:fs";

// Inspect completed generation streams, not arbitrary reasoning text in the UI.
// Persist only classifications: generated text/headers/credentials are excluded.
export function generationFailure(status: number, body: string): string | null {
  if (status !== 200) return `generation HTTP ${status}`;
  for (const frame of body.split(/\r?\n\r?\n/)) {
    const data = frame.split(/\r?\n/).filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart()).join("\n");
    if (!data || data === "[DONE]") continue;
    let event: any;
    try { event = JSON.parse(data); } catch { continue; }
    if (event.type === "error") return "generation SSE error event";
    if (event.type === "final_answer" && /^\*?模型返回了空内容。\*?$/.test(String(event.content || "").trim())) {
      return "generation completed with empty model output; provider/adaptation root cause requires review";
    }
  }
  return null;
}

export function watchGeneration(page: Page, evidencePath: string) {
  let failure: string | null = null;
  let active = true;
  const onResponse = async (response: Response) => {
    const path = new URL(response.url()).pathname;
    if (response.request().method() !== "POST" || !/\/(?:nl2agent|agent)\/run$/.test(path)) return;
    try {
      const reason = generationFailure(response.status(), await response.text());
      if (active && reason) {
        failure = reason;
        writeFileSync(evidencePath, JSON.stringify({ http_status: response.status(), reason,
          path, finished_at: new Date().toISOString() }, null, 2) + "\n");
      }
    } catch {
      // An interrupted stream is not proof of empty output. Existing timeout
      // and browser network evidence retain transport failures independently.
    }
  };
  page.on("response", onResponse);
  return {
    check() {
      if (failure) {
        const error = new Error(failure);
        error.name = "ProductFailure"; // observed business failure, not a causal attribution
        throw error;
      }
    },
    close() { active = false; page.off("response", onResponse); },
  };
}

export async function waitForGenerationProgress(
  page: Page, watcher: { check(): void }, ready: () => Promise<boolean>, timeout: number,
): Promise<void> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    watcher.check();
    if (await ready()) { watcher.check(); return; }
    await page.waitForTimeout(200);
  }
  watcher.check();
  const error = new Error(`generation did not reach its required next stage within ${timeout}ms`);
  error.name = "TimeoutError";
  throw error;
}
