import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export { test, expect };

export async function loadSourceChat(page: Page, provider = "aidp") {
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const sources = Array.from({ length: 300 }, (_, index) => ({
    cite_index: index + 1,
    tool_sign: provider === "aidp" ? "j" : "a",
    search_type:
      index === 299
        ? "web_search"
        : provider === "aidp"
          ? "aidp_search"
          : "knowledge_base_search",
    source_type: index === 299 ? "url" : "file",
    title: `Source document ${index + 1}`,
    filename: `source-${index + 1}.pdf`,
    url:
      index === 299
        ? "https://source-fixture.invalid/source-document-300"
        : provider === "aidp"
          ? ""
          : `s3://test-bucket/source-${index + 1}.pdf`,
    object_name: provider === "aidp" ? undefined : `source-${index + 1}.pdf`,
    text:
      `Evidence from source ${index + 1}. ` +
      "Deterministic retrieval content. ".repeat(60),
    score_details: {
      chunk_id: `chunk-${index + 1}`,
      metadata: {
        ...Object.fromEntries(
          Array.from({ length: 28 }, (_, field) => [
            `field_${field}`,
            `Source ${index + 1} metadata ${field}`,
          ]),
        ),
        nested: { deep: { unique_leaf: `nested-value-${index + 1}` } },
        array: ["first", "second"],
      },
    },
  }));
  const sign = provider === "aidp" ? "j" : "a";
  const answer =
    Array.from(
      { length: 100 },
      (_, index) => `Evidence paragraph ${index + 1} [[${sign}${index + 1}]].`,
    ).join("\n\n") + `\n\nFinal evidence [[${sign}300]].`;
  const item = {
    conversation_id: 930001,
    conversation_title: "300 source performance fixture",
    agent_id: 1,
    create_time: Date.now(),
    update_time: Date.now(),
  };
  const detail = {
    ...item,
    conversation_type: "agent_chat",
    message: [
      {
        role: "user",
        message_id: 930002,
        message: "Inspect 300 retrieval sources",
      },
      {
        role: "assistant",
        message_id: 930003,
        message: [{ type: "final_answer", content: answer }],
        search: sources,
      },
    ],
  };
  await page.context().route("https://source-fixture.invalid/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<h1>Source document 300</h1>",
    }),
  );
  await page.route("**/api/**", async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    requests.push(`${route.request().method()} ${pathname}`);
    let body: unknown = { code: 0, success: true, data: [], items: [] };
    if (pathname.endsWith("/tenant_config/deployment_version"))
      body = {
        deployment_version: "speed",
        app_version: "source-perf-fixture",
        enable_aidp_knowledge: provider === "aidp",
        status: "success",
      };
    else if (pathname.endsWith("/user/current_user_info"))
      body = {
        data: {
          user: {
            user_id: "source-perf-user",
            tenant_id: "source-perf-tenant",
            group_ids: [],
            user_email: "fixture@example.invalid",
            user_role: "SPEED",
            auth_provider: "local",
            permissions: ["AGENT:READ", "CONVERSATION:READ"],
            accessibleRoutes: ["/newchat", "/", "/agents", "/knowledges"],
          },
        },
      };
    else if (pathname.endsWith("/conversation/list"))
      body = {
        code: 0,
        data: {
          items: [item],
          metadata: { total: 1, today: 1, last_7_days: 0, older: 0 },
          next_cursor: null,
        },
      };
    else if (pathname.endsWith("/conversation/930001"))
      body = { code: 0, data: [detail] };
    else if (pathname.endsWith("/conversation/workbench_pins"))
      body = { code: 0, data: { items: [] } };
    else if (pathname.endsWith("/agent/published_list"))
      body = [
        {
          id: 1,
          agent_id: 1,
          name: "Source fixture agent",
          display_name: "Source fixture agent",
          is_available: true,
          is_main_agent: true,
        },
      ];
    else if (pathname.endsWith("/config/load")) body = { config: {} };
    else if (pathname.endsWith("/groups/list")) body = { data: [], total: 0 };
    else if (pathname.endsWith("/knowledge-scope"))
      body = { code: 0, data: { knowledge_scope: null } };
    if (pathname.endsWith("/memory/config/load"))
      body = { MEMORY_SWITCH: "N", DREAMING_SWITCH: "N" };
    if (pathname.endsWith("/memory/config/embedding-status"))
      body = { configured: true, current_es_index_name: "fixture-index" };
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  await page.addInitScript(() => {
    const state = {
      start: 0,
      armed: false,
      tasks: [] as { start: number; duration: number }[],
    };
    (window as any).__sourcePerf = state;
    for (const event of ["pointerdown", "pointerover"])
      document.addEventListener(
        event,
        () => {
          if (state.armed) {
            state.start = performance.now();
            state.armed = false;
          }
        },
        true,
      );
    new PerformanceObserver((list) =>
      state.tasks.push(
        ...list.getEntries().map((entry) => ({
          start: entry.startTime,
          duration: entry.duration,
        })),
      ),
    ).observe({ type: "longtask", buffered: false });
  });
  await page.goto(`/zh/newchat?conversation_id=930001`, {
    waitUntil: "domcontentloaded",
  });
  console.log("source fixture navigation completed");
  await expect(page.locator("[data-citation-marker]").first())
    .toBeVisible({ timeout: 30_000 })
    .catch(async (error) => {
      console.log(
        JSON.stringify({
          requests,
          errors,
          url: page.url(),
          body: (await page.locator("body").innerText()).slice(0, 4000),
        }),
      );
      throw error;
    });
  return { requests, errors };
}

export async function sourceJourney(page: Page, repetitions = 1) {
  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Performance.enable");
  const metrics = async () =>
    Object.fromEntries(
      (await cdp.send("Performance.getMetrics")).metrics.map((metric: any) => [
        metric.name,
        metric.value,
      ]),
    );
  const samples: Record<string, unknown>[] = [];
  const measure = async (
    operation: string,
    action: () => Promise<unknown>,
    ready: () => Promise<unknown>,
  ) => {
    console.log(`source operation: ${operation}`);
    const before = await metrics();
    const apiBefore = await page.evaluate(
      () =>
        performance
          .getEntriesByType("resource")
          .filter((entry) => entry.name.includes("/api/")).length,
    );
    await page.evaluate(() => {
      const s = (window as any).__sourcePerf;
      s.armed = true;
      s.start = performance.now();
      s.tasks = [];
    });
    await action();
    await ready();
    const measurement = await page.evaluate(async () => {
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
      );
      const s = (window as any).__sourcePerf;
      return {
        inputToPaintMs: performance.now() - s.start,
        longTasks: s.tasks,
        apiCount: performance
          .getEntriesByType("resource")
          .filter((entry) => entry.name.includes("/api/")).length,
      };
    });
    const after = await metrics();
    samples.push({
      operation,
      ...measurement,
      apiRequests: measurement.apiCount - apiBefore,
      layoutCount: after.LayoutCount - before.LayoutCount,
      layoutMs: (after.LayoutDuration - before.LayoutDuration) * 1000,
      scriptMs: (after.ScriptDuration - before.ScriptDuration) * 1000,
    });
  };
  const panel = page.locator('[data-slot="sources-panel"]');
  const close = () =>
    panel.getByRole("button", { name: "关闭来源面板", exact: true }).click();
  const summary = page.locator(".aui-source-group-button");
  for (let iteration = 0; iteration < repetitions; iteration++) {
    await measure(
      "citation-open",
      () => page.locator("[data-citation-marker]").last().click(),
      async () => {
        await expect(panel).toBeVisible();
        await expect(panel.locator("[data-source-metadata]")).toHaveCount(300);
      },
    );
    await measure(
      "citation-switch",
      () => page.locator('[data-citekey$="100"]').click(),
      async () => {
        await expect(
          panel.getByText("Source document 100", { exact: true }),
        ).toBeVisible();
      },
    );
    await close();
    await measure(
      "summary-open",
      () => summary.click(),
      async () => {
        await expect(panel.locator("[data-source-metadata]")).toHaveCount(300);
      },
    );
    await measure(
      "source-link",
      async () => {
        const popup = page.waitForEvent("popup");
        await panel
          .getByRole("link")
          .filter({ hasText: "Source document 300" })
          .click();
        const sourcePage = await popup;
        await sourcePage.waitForLoadState();
        await expect(sourcePage.getByRole("heading")).toHaveText(
          "Source document 300",
        );
        await sourcePage.close();
      },
      async () => expect(panel).toBeVisible(),
    );
    const trigger = panel.locator("[data-source-metadata] button").first();
    const dialog = page.getByRole("dialog", { name: "来源属性", exact: true });
    await measure(
      "metadata-hover",
      () => trigger.hover(),
      () => expect(dialog).toBeVisible(),
    );
    await dialog.hover();
    await expect(dialog).toBeVisible();
    if (!process.env.SOURCE_PERF_BASELINE)
      await expect(
        dialog.getByText("nested-value-1", { exact: true }),
      ).toHaveCount(0);
    await dialog
      .locator("summary")
      .filter({ hasText: /^nested$/ })
      .click();
    await dialog
      .locator("summary")
      .filter({ hasText: /^deep$/ })
      .click();
    await expect(
      dialog.getByText("nested-value-1", { exact: true }),
    ).toBeVisible();
    await measure(
      "metadata-json",
      () => dialog.getByRole("tab", { name: "原始 JSON" }).click(),
      () => expect(dialog.locator("pre")).toBeVisible(),
    );
    expect(await dialog.locator("pre").textContent()).toContain(
      "nested-value-1",
    );
    await trigger.click();
    await page.mouse.move(10, 10);
    await expect(dialog).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog).toBeHidden();
    await close();
  }
  await cdp.detach();
  return samples;
}

export function saveSourceResults(name: string, result: unknown) {
  const directory =
    process.env.SOURCE_PERF_OUTPUT ||
    process.env.RESULT_DIR ||
    test.info().outputDir;
  mkdirSync(directory, { recursive: true });
  writeFileSync(
    join(directory, `${name}.json`),
    JSON.stringify(result, null, 2),
  );
}
