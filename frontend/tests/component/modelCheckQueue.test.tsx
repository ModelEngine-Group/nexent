// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { expect, it, vi } from "vitest";
import { runModelCheck } from "../../lib/modelCheckQueue";

const flush = async () => {
  for (let i = 0; i < 8; i++) await Promise.resolve();
};
function deferred() {
  let resolve!: (value: string) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<string>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

it("Q-01 keeps three shared slots and fills the next FIFO task immediately", async () => {
  const jobs = Array.from({ length: 6 }, deferred);
  const started: number[] = [];
  let peak = 0,
    active = 0;
  const tasks = jobs.map((job, id) =>
    runModelCheck(async () => {
      started.push(id);
      peak = Math.max(peak, ++active);
      try {
        return await job.promise;
      } finally {
        active--;
      }
    })
  );
  await flush();
  expect(started).toEqual([0, 1, 2]);
  jobs[1].resolve("one");
  await flush();
  expect(started).toEqual([0, 1, 2, 3]);
  jobs[0].resolve("zero");
  await flush();
  expect(started).toEqual([0, 1, 2, 3, 4]);
  jobs[2].resolve("two");
  await flush();
  expect(started).toEqual([0, 1, 2, 3, 4, 5]);
  jobs.slice(3).forEach((job) => job.resolve("done"));
  await Promise.all(tasks);
  await flush();
  expect(peak).toBe(3);
  expect(active).toBe(0);
});

it("Q-02 releases failed and synchronously throwing slots", async () => {
  const held = deferred();
  const tasks = [
    runModelCheck(() => {
      throw new Error("synchronous");
    }),
    runModelCheck(() => Promise.reject(new Error("asynchronous"))),
    runModelCheck(() => held.promise),
    runModelCheck(async () => "refilled"),
  ];
  const results = Promise.allSettled(tasks);
  await flush();
  held.resolve("done");
  expect((await results).map((r) => r.status)).toEqual([
    "rejected",
    "rejected",
    "fulfilled",
    "fulfilled",
  ]);
  await flush();
  expect(await runModelCheck(async () => "next")).toBe("next");
});

it("Q-02 removes aborted queued tasks without sending them or leaking a slot", async () => {
  const held = Array.from({ length: 3 }, deferred);
  const tasks = held.map((item) => runModelCheck(() => item.promise));
  const cancelled = vi.fn(async () => "must not start");
  const signal = new AbortController();
  const queued = runModelCheck(cancelled, signal.signal);
  const rejected = expect(queued).rejects.toMatchObject({ name: "AbortError" });
  signal.abort();
  await rejected;
  const next = vi.fn(async () => "next");
  const resumed = runModelCheck(next);
  await flush();
  expect(next).not.toHaveBeenCalled();
  expect(cancelled).not.toHaveBeenCalled();
  held[0].resolve("done");
  await flush();
  expect(next).toHaveBeenCalledOnce();
  held.slice(1).forEach((item) => item.resolve("done"));
  await Promise.all([...tasks, resumed]);
  await flush();
});

it("Q-02 rejects an already cancelled task without executing it", async () => {
  const controller = new AbortController();
  controller.abort();
  const call = vi.fn(async () => "not called");
  await expect(runModelCheck(call, controller.signal)).rejects.toMatchObject({
    name: "AbortError",
  });
  expect(call).not.toHaveBeenCalled();
});
