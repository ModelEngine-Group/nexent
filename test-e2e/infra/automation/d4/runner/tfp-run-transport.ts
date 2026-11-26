// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { Page, Request } from "playwright/test";

type TransportState = { failure: string | null };

export async function waitForTfpRunTransport(
  page: Page,
  start: () => Promise<Request>,
  verifyAbortedRun: () => Promise<void>,
  timeout = 300_000,
): Promise<void> {
  const states = new WeakMap<Request, TransportState>();
  let owned: Request | undefined;
  let settle: (state: TransportState) => void = () => {};
  let timer: ReturnType<typeof setTimeout> | undefined;
  const terminal = new Promise<TransportState>((resolve) => { settle = resolve; });
  const record = (request: Request, failure: string | null) => {
    const state = { failure };
    states.set(request, state);
    if (request === owned) settle(state);
  };
  const onFinished = (request: Request) => record(request, null);
  const onFailed = (request: Request) => record(request, request.failure()?.errorText || "request failed");
  page.on("requestfinished", onFinished);
  page.on("requestfailed", onFailed);
  try {
    owned = await start();
    const state = states.get(owned) ?? await Promise.race([
      terminal,
      new Promise<never>((_, reject) => {
        timer = setTimeout(() => {
          const error = new Error(`Agent run SSE transport did not settle within ${timeout} ms`);
          error.name = "TimeoutError";
          reject(error);
        }, timeout);
      }),
    ]);
    if (state.failure === "net::ERR_ABORTED") {
      // A browser abort is terminal for transport only. Verify the exact owned run separately.
      await verifyAbortedRun();
    } else if (state.failure) {
      throw new Error(`Agent run SSE transport failed: ${state.failure}`);
    }
  } finally {
    clearTimeout(timer);
    page.off("requestfinished", onFinished);
    page.off("requestfailed", onFailed);
  }
}
