// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  test,
  expect,
  loadSourceChat,
  sourceJourney,
  saveSourceResults,
} from "../../infra/automation/d4/helpers/source-performance";

test("PERF-SOURCES-300 warmed source operations meet the local fixture budget", async ({
  page,
}) => {
  const context = await loadSourceChat(page);
  await sourceJourney(page);
  const samples = await sourceJourney(
    page,
    Number(process.env.SOURCE_PERF_REPETITIONS || 7),
  );
  saveSourceResults("source-performance", { ...context, samples });
  expect(context.errors).toEqual([]);
  const opens = samples
    .filter((sample) => String(sample.operation).endsWith("-open"))
    .map((sample) => Number(sample.inputToPaintMs))
    .sort((a, b) => a - b);
  expect(opens[Math.ceil(opens.length * 0.95) - 1]).toBeLessThan(500);
  const switches = samples
    .filter((sample) => sample.operation === "citation-switch")
    .map((sample) => Number(sample.inputToPaintMs))
    .sort((a, b) => a - b);
  expect(switches[Math.ceil(switches.length * 0.95) - 1]).toBeLessThan(150);
  expect(
    Math.max(...samples.map((sample) => Number(sample.inputToPaintMs))),
  ).toBeLessThan(5000);
  const profiler = await page.context().newCDPSession(page);
  await profiler.send("Profiler.enable");
  await profiler.send("Profiler.start");
  await sourceJourney(page);
  const { profile } = await profiler.send("Profiler.stop");
  saveSourceResults("source-cpu-profile", profile);
  await profiler.detach();
});

test("PERF-SOURCES-300 same-page selection skips unchanged cards", async ({
  page,
}) => {
  await loadSourceChat(page);
  await page.locator('[data-citekey="j100"]').click();
  const panel = page.locator('[data-slot="sources-panel"]');
  await expect(panel.locator('[data-citation-key="j100"]')).toHaveAttribute(
    "data-citation-selected",
    "true",
  );
  const coverage = await page.context().newCDPSession(page);
  await coverage.send("Profiler.enable");
  await coverage.send("Profiler.startPreciseCoverage", {
    callCount: true,
    detailed: true,
  });
  await page.locator('[data-citekey="j99"]').click();
  await expect(panel.locator('[data-citation-key="j99"]')).toHaveAttribute(
    "data-citation-selected",
    "true",
  );
  const { result } = await coverage.send("Profiler.takePreciseCoverage");
  const cards = result.flatMap((script) =>
    script.functions.filter((fn) => fn.functionName === "SourceListItem"),
  );
  const count = cards.reduce(
    (total, fn) => total + (fn.ranges[0]?.count ?? 0),
    0,
  );
  saveSourceResults("source-same-page-calls", {
    count,
    cards,
    scripts: result.filter((script) => /sources-panel/.test(script.url)),
  });
  // Development renders can replay; reject an update of the whole visible page.
  expect(cards.length).toBeGreaterThan(0);
  expect(count).toBeGreaterThan(0);
  expect(count).toBeLessThan(20);
  await coverage.send("Profiler.stopPreciseCoverage");
  await coverage.detach();
});

test("PERF-SOURCES-300 records source rendering call counts", async ({
  page,
}) => {
  await loadSourceChat(page);
  const coverage = await page.context().newCDPSession(page);
  await coverage.send("Profiler.enable");
  await coverage.send("Profiler.startPreciseCoverage", {
    callCount: true,
    detailed: true,
  });
  await sourceJourney(page);
  const { result } = await coverage.send("Profiler.takePreciseCoverage");
  saveSourceResults(
    "source-call-counts",
    result
      .filter((script) =>
        /sourceMetadata|sources-panel|message-sources|markdown-text|citationDisplay/.test(
          script.url,
        ),
      )
      .map((script) => ({
        url: script.url,
        functions: script.functions.map((fn) => ({
          name: fn.functionName,
          count: fn.ranges[0]?.count,
        })),
      })),
  );
  await coverage.send("Profiler.stopPreciseCoverage");
  await coverage.detach();
});
