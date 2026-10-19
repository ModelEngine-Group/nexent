// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, test } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareControls } from "../../infra/automation/d4/fixtures/model-controls";

// Windows developers can use the installed Chromium-based Edge; Linux uses bundled Chromium.
if (process.platform === "win32") test.use({ channel: "msedge" });

journey("SEARCH-DEEPSEEK-D4-001", async ({ page, contract }) => {
  const state = await prepareControls(page);
  const requests: Array<Record<string, any>> = [];
  let saved: Record<string, any> = {};
  const params = [
    {
      name: "deepseek_api_key",
      type: "string",
      optional: false,
      description: "DeepSeek API key",
      description_zh: "DeepSeek API 密钥",
    },
    {
      name: "max_results",
      type: "integer",
      optional: true,
      default: 10,
      constraints: { ge: 1, le: 50 },
    },
    {
      name: "only_high_quality",
      type: "boolean",
      optional: true,
      default: false,
      description: "High-quality results only (score >= 1.5)",
      description_zh: "仅优质内容，开启后保留排序分不低于 1.5 的结果",
    },
  ];
  const tool = {
    tool_id: 9030,
    id: "9030",
    name: "deepseek_search",
    origin_name: "deepseek_search",
    class_name: "DeepSeekSearchTool",
    source: "local",
    category: "search",
    labels: ["search"],
    description: "DeepSeek web search",
    description_zh: "DeepSeek 网页检索",
    params,
    output_type: "string",
    is_available: true,
    is_user_selectable: true,
    inputs: JSON.stringify({
      query: {
        type: "string",
        description:
          "Use site:, -site:, exact phrases, after: and before:. The platform appends lang:en or lang:zh; final query <=128 characters.",
        description_zh:
          "支持 site:、-site:、精确短语、after: 和 before:。系统追加 lang:zh 或 lang:en，最终查询不超过 128 字符。",
      },
    }),
  };
  state.draft.tools = [tool] as any;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const body = route.request().postDataJSON();
    const json = (value: unknown) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(value),
      });
    if (path === "/api/tool/list") return json([tool]);
    if (path === "/api/tool/search")
      return json({ tool_instance: { params: saved } });
    if (path === "/api/tool/update") {
      saved = body.params;
      return json({ tool_instance: { params: saved } });
    }
    if (path === "/api/tool/validate") {
      requests.push(body);
      return json([
        {
          title: "Fixture result",
          text: "Fixture summary",
          index: "o1",
          reference_mark: "[[o1]]",
        },
      ]);
    }
    return route.fallback();
  });
  const root = process.env.NEXENT_BASE_URL ?? "http://localhost:3000";
  const open = async (language: "zh" | "en") => {
    await page.goto(`${root}/${language}/agents/42`);
    const configure = page.getByRole("button", {
      name: `${language === "zh" ? "配置" : "Configure"} deepseek_search`,
      exact: true,
    });
    // The high-fidelity editor groups selected tools in its capability tab.
    if (!(await configure.isVisible())) {
      const tab = page
        .getByRole("tab", {
          name: language === "zh" ? /工具与技能|能力/ : /Tools|Capabilities/,
        })
        .first();
      if (await tab.isVisible()) await tab.click();
    }
    await configure.click();
    return page.getByRole("dialog").last();
  };
  for (const id of contract.expectedIds("preconditions"))
    await contract.precondition(id, async () => {
      expect(
        tool.params.find((param) => param.name === "max_results")?.default,
      ).toBe(10);
      expect(requests).toHaveLength(0);
    });
  await contract.step(contract.expectedIds("steps")[0], async () => {
    for (const language of ["zh", "en"] as const) {
      const dialog = await open(language);
      const label =
        language === "zh" ? "仅优质内容" : "High-quality results only";
      const qualityRow = dialog
        .locator(".ant-form-item")
        .filter({ hasText: label });
      const quality = qualityRow.getByRole("switch");
      await expect(quality).toHaveAttribute("aria-checked", "false");
      await dialog
        .locator('input[type="password"]')
        .fill("synthetic-browser-key");
      await quality.click();
      await expect(quality).toHaveAttribute("aria-checked", "true");
      await dialog
        .getByText(language === "zh" ? "工具测试" : "Test Tool", {
          exact: true,
        })
        .click();
      const panel = dialog.locator('[data-config-part="test-panel"]');
      await panel
        .locator("input,textarea")
        .first()
        .fill("DeepSeek site:github.com after:2025");
      await panel.locator('[data-config-part="test-run"]').click();
      await expect.poll(() => requests.at(-1)?.language).toBe(language);
      expect(requests.at(-1)?.params).toMatchObject({
        max_results: 10,
        only_high_quality: true,
      });
      expect(requests.at(-1)?.inputs.query).toBe(
        "DeepSeek site:github.com after:2025",
      );
      await dialog
        .getByRole("button", {
          name: language === "zh" ? "确定" : "Confirm",
          exact: true,
        })
        .click();
      await expect(dialog).not.toBeVisible();
      expect(saved.only_high_quality).toBe(true);
      await page.getByRole("button", {
        name: `${language === "zh" ? "配置" : "Configure"} deepseek_search`, exact: true,
      }).click();
      const reopened = page.getByRole("dialog").last();
      await expect(reopened.locator(".ant-form-item").filter({ hasText: label }).getByRole("switch"))
        .toHaveAttribute("aria-checked", "true");
      await reopened.getByRole("button", { name: language === "zh" ? "取消" : "Cancel", exact: true }).click();
      saved = {};
    }
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    const dialog = await open("en");
    const quality = dialog
      .locator(".ant-form-item")
      .filter({ hasText: "High-quality results only" })
      .getByRole("switch");
    if ((await quality.getAttribute("aria-checked")) === "true")
      await quality.click();
    await dialog
      .locator('input[type="password"]')
      .fill("synthetic-browser-key");
    await dialog.getByText("Test Tool", { exact: true }).click();
    const panel = dialog.locator('[data-config-part="test-panel"]');
    await panel.locator("input,textarea").first().fill("topic");
    await panel.locator('[data-config-part="test-run"]').click();
    await expect
      .poll(() => requests.at(-1)?.params.only_high_quality)
      .toBe(false);
    expect(requests.at(-1)?.language).toBe("en");
  });
  for (const id of contract.expectedIds("assertions"))
    await contract.assertion(id, async () => {
      expect(requests).toHaveLength(3);
      expect(requests.map((request) => request.language)).toEqual([
        "zh",
        "en",
        "en",
      ]);
      expect(
        requests.map((request) => request.params.only_high_quality),
      ).toEqual([true, true, false]);
      expect(
        requests.every((request) => request.name === "deepseek_search"),
      ).toBe(true);
    });
});
