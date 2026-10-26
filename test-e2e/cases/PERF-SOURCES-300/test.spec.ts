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
  expect(opens[Math.ceil(opens.length * 0.95) - 1]).toBeLessThan(2000);
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
        /sourceMetadata|sources-panel|markdown-text|citationDisplay/.test(
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
