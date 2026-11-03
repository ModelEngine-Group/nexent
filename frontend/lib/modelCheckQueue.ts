// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

/** Shared by explicit model checks in one browser page; never by inference. */
const pending: Array<() => void> = [];
let active = 0;
const limit = 3;

export function runModelCheck<T>(
  check: () => Promise<T>,
  signal?: AbortSignal
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const abort = () => {
      const index = pending.indexOf(start);
      if (index >= 0) pending.splice(index, 1);
      signal?.removeEventListener("abort", abort);
      reject(new DOMException("Model check cancelled", "AbortError"));
    };
    const start = () => {
      signal?.removeEventListener("abort", abort);
      if (signal?.aborted) {
        abort();
        return;
      }
      active++;
      Promise.resolve()
        .then(check)
        .then(resolve, reject)
        .finally(() => {
          active--;
          pending.shift()?.();
        });
    };
    if (signal?.aborted) {
      abort();
    } else if (active < limit) {
      start();
    } else {
      pending.push(start);
      signal?.addEventListener("abort", abort, { once: true });
    }
  });
}
