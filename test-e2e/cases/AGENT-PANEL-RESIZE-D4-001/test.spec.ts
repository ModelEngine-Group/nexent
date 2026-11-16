// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, type Locator } from "playwright/test";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("AGENT-PANEL-RESIZE-D4-001", async ({ page, contract }) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await prepareWorkbench(page);
  const writes: string[] = [];
  const json = (data: unknown) => ({
    contentType: "application/json",
    body: JSON.stringify(data),
  });
  await page.route("**/api/agent/search_info", (route) =>
    route.fulfill(
      json({
        agent_id: 42,
        name: "resize_fixture",
        display_name: "Resize fixture",
        description: "Isolated resize fixture",
        permission: "EDIT",
        model_ids: [1],
        model_names: ["Fixture Model"],
        prompt: "Return the given text",
        tools: [],
        max_steps: 3,
        enabled: true,
        is_available: true,
        verification_config: {
          enabled: false,
          step_verification_enabled: true,
          final_verification_enabled: true,
          llm_verification_enabled: true,
          max_final_rounds: 2,
          strictness: "balanced",
          fail_policy: "repair_then_controlled_summary",
          pass_score: 0.75,
          critical_events: [
            "tool_precheck",
            "tool_result",
            "retrieval",
            "code_execution",
            "handoff",
            "final_answer",
          ],
          guardrail_config: {
            enabled: false,
            rules: [],
            default_action: "pass",
          },
        },
      }),
    ),
  );
  await page.route("**/api/tool/list**", (route) => route.fulfill(json([])));
  await page.route("**/api/agent/check_name", (route) =>
    route.fulfill(
      json([{ name_conflict: false, display_name_conflict: false }]),
    ),
  );
  await page.route("**/api/conversation/creator_histories?*", (route) =>
    route.fulfill(json({ code: 0, data: { items: [], total: 0 } })),
  );
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (
      /\/agent\/(?:update|update_fields|run|publish|nl2agent\/run)$/.test(path)
    ) {
      writes.push(path);
      await route.fulfill(json({}));
    } else await route.fallback();
  });
  contract.deferCleanup(async () => {
    await page.close();
  });
  const generation = page.getByTestId("agent-config-conversation-panel");
  const debug = page.getByTestId("agent-debug-pane");
  const config = page.getByTestId("agent-config-scroll-region");
  const generationSplit = page.getByTestId("agent-generation-split");
  const debugSplit = page.getByTestId("agent-debug-split");
  const handle = (split: Locator) =>
    split.locator(
      ':scope > .ant-splitter > .ant-splitter-bar [role="separator"]',
    );
  const width = async (target: Locator) => (await target.boundingBox())!.width;
  const drag = async (split: Locator, offset: number) => {
    const box = (await handle(split).boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    // AntD reserves mouse downs within 300ms for its double-click gesture.
    await page.waitForTimeout(350);
    await page.mouse.down();
    await page.mouse.move(
      box.x + box.width / 2 + offset,
      box.y + box.height / 2,
      { steps: 12 },
    );
    await page.mouse.up();
  };
  let generationWidth = 0;
  let debugWidth = 0;
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await page.goto(`${process.env.NEXENT_BASE_URL}/zh/agents/42`);
      await expect(
        page.getByRole("textbox", { name: "* 智能体变量名", exact: true }),
      ).toHaveValue("resize_fixture");
      await expect(generation).toBeVisible();
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    const before = await width(generation);
    await drag(generationSplit, 100);
    await expect.poll(() => width(generation)).toBeGreaterThan(before + 60);
    const grown = await width(generation);
    await drag(generationSplit, -60);
    await expect.poll(() => width(generation)).toBeLessThan(grown - 30);
    const header = page.getByTestId("agent-config-header");
    for (const viewport of [1600, 1200]) {
      await page.setViewportSize({ width: viewport, height: 1000 });
      await drag(generationSplit, 2000);
      await expect.poll(() => width(debugSplit)).toBeGreaterThanOrEqual(799);
      const publish = (await header
        .getByRole("button", { name: "发布", exact: true })
        .boundingBox())!;
      const modes = (await header.getByRole("group").boundingBox())!;
      expect(
        Math.abs(publish.y + publish.height / 2 - modes.y - modes.height / 2),
      ).toBeLessThan(5);
      await page.screenshot({
        path: join(contract.caseDir, `configuration-min-width-${viewport}.png`),
      });
    }
    await page.setViewportSize({ width: 1600, height: 1000 });
    await drag(generationSplit, -2000);
    generationWidth = await width(generation);
    await expect(config).toBeVisible();
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await page.getByRole("button", { name: "智能体调试", exact: true }).click();
    await expect(debug).toBeVisible();
    const before = await width(debug);
    await drag(debugSplit, -80);
    await expect.poll(() => width(debug)).toBeGreaterThan(before + 40);
    const grown = await width(debug);
    await drag(debugSplit, 60);
    await expect.poll(() => width(debug)).toBeLessThan(grown - 30);
    for (const viewport of [1600, 1100]) {
      await page.setViewportSize({ width: viewport, height: 1000 });
      for (const [offset, expected] of [
        [-2000, 0.65],
        [2000, 0.25],
      ] as const) {
        await drag(debugSplit, offset);
        await expect
          .poll(async () => (await width(debug)) / (await width(debugSplit)))
          .toBeCloseTo(expected, 1);
        expect(await width(config)).toBeGreaterThan(100);
      }
    }
    await page.setViewportSize({ width: 1600, height: 1000 });
    await drag(debugSplit, -100);
    debugWidth = await width(debug);
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await debug.evaluate((element) =>
      element.setAttribute("data-retained", "debug"),
    );
    await page.getByRole("button", { name: "全屏调试", exact: true }).click();
    await expect(handle(debugSplit)).toHaveAttribute("aria-disabled", "true");
    await page
      .getByRole("button", { name: "还原调试布局", exact: true })
      .click();
    await expect.poll(() => width(debug)).toBeCloseTo(debugWidth, 0);
    await page
      .getByRole("button", { name: "切换对比模式", exact: true })
      .click();
    await expect(handle(debugSplit)).toHaveAttribute("aria-disabled", "true");
    await page
      .getByRole("button", { name: "切换对比模式", exact: true })
      .click();
    await expect.poll(() => width(debug)).toBeCloseTo(debugWidth, 0);
    await page.getByRole("button", { name: "智能体调试", exact: true }).click();
    await expect(handle(debugSplit)).toHaveAttribute("aria-disabled", "true");
    await page.getByRole("button", { name: "智能体调试", exact: true }).click();
    await expect.poll(() => width(debug)).toBeCloseTo(debugWidth, 0);
    await expect(debug).toHaveAttribute("data-retained", "debug");
    await page.getByRole("button", { name: "智能体调试", exact: true }).click();
    await page.getByRole("button", { name: "智能生成", exact: true }).click();
    await expect.poll(() => width(generation)).toBeCloseTo(generationWidth, 0);
    await generation.evaluate((element) =>
      element.setAttribute("data-retained", "generation"),
    );
    await page.getByRole("button", { name: "智能生成", exact: true }).click();
    await expect(handle(generationSplit)).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    await page.getByRole("button", { name: "智能生成", exact: true }).click();
    await expect(generation).toHaveAttribute("data-retained", "generation");
    await expect.poll(() => width(generation)).toBeCloseTo(generationWidth, 0);
    expect(writes).toEqual([]);
    await page.screenshot({
      path: join(contract.caseDir, "resized-editor.png"),
    });
  });
  for (const id of contract.expectedIds("assertions")) {
    await contract.assertion(id, async () => {
      expect(generationWidth).toBeGreaterThan(0);
      expect(debugWidth).toBeGreaterThan(0);
      await expect(config).toBeVisible();
      expect(writes).toEqual([]);
    });
  }
});
