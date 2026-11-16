// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import type { ElementHandle } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("WB-RESOURCE-LAZY-D4-001", async ({ page, contract }) => {
  // A non-secret session marker enables the intercepted tenant authorization flow.
  await page.context().addCookies([
    {
      name: "nexent_token_expires_at",
      value: String(Math.floor(Date.now() / 1000) + 3600),
      url: process.env.NEXENT_BASE_URL ?? "http://localhost:3031",
    },
  ]);
  contract.deferCleanup(async () => {
    await page.context().clearCookies({ name: "nexent_token_expires_at" });
  });
  const state = await prepareWorkbench(page);
  const composer = page.getByRole("textbox", { name: "对话输入", exact: true });
  const send = page.getByRole("button", { name: "发送", exact: true });
  let release!: () => void;
  const readiness = new Promise<void>((resolve) => {
    release = resolve;
  });
  let node: ElementHandle | null = null;
  const requests: string[] = [];
  const skillViews: Array<string | null> = [];
  let agentAttempts = 0;
  const catalogs = ["/api/agent/published_list", "/api/skills", "/api/indices"];
  const draft = "Keep this unsent Workbench draft";
  const retainDraft = async () => {
    expect(await node!.evaluate((element) => element.isConnected)).toBe(true);
    await expect(composer).toHaveText(draft);
  };
  contract.deferCleanup(async () => {
    release();
    await page.unrouteAll({ behavior: "wait" });
    await node?.dispose();
  });
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await expect(composer).toBeVisible();
      await page.route(
        /\/api\/(model\/list|agent\/workbench\/bootstrap)$/,
        async (route) => {
          await readiness;
          await route.fallback();
        },
      );
      await page.route("**/api/agent/published_list", async (route) => {
        agentAttempts++;
        if (agentAttempts === 1)
          await route.fulfill({
            status: 400,
            contentType: "application/json",
            body: JSON.stringify({ detail: "Controlled catalog failure" }),
          });
        else await route.fallback();
      });
      page.on("request", (request) => {
        const url = new URL(request.url());
        requests.push(url.pathname);
        if (url.pathname === "/api/skills")
          skillViews.push(url.searchParams.get("view"));
      });
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await expect(composer).toBeVisible();
    await composer.fill(draft);
    node = await composer.elementHandle();
    await expect(send).toBeDisabled();
    for (const name of ["智能体", "知识库", "技能"])
      await expect(
        page.getByRole("button", { name, exact: true }),
      ).toBeVisible();
    expect(
      requests.filter(
        (path) =>
          catalogs.includes(path) || path.endsWith("knowledge-capabilities"),
      ),
    ).toEqual([]);
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    release();
    await expect(send).toBeEnabled();
    await page.getByRole("button", { name: "智能体", exact: true }).click();
    const drawer = page.getByRole("dialog");
    await expect(drawer.getByRole("alert")).toBeVisible();
    await retainDraft();
    await drawer.getByRole("button", { name: "刷新", exact: true }).click();
    await expect(
      drawer.getByRole("option", { name: /Internal Analyst/ }),
    ).toBeVisible();
    expect(agentAttempts).toBe(2);
    await drawer
      .getByRole("button", { name: "关闭", exact: true })
      .last()
      .click();
    await expect(drawer).toHaveCount(0);
    await page.getByRole("button", { name: "智能体", exact: true }).click();
    await expect(
      drawer.getByRole("option", { name: /Internal Analyst/ }),
    ).toBeVisible();
    expect(agentAttempts).toBe(2);
    await drawer
      .getByRole("button", { name: "关闭", exact: true })
      .last()
      .click();
    await expect(drawer).toHaveCount(0);
    await retainDraft();
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    expect(requests).not.toContain("/api/skills");
    expect(requests).not.toContain("/api/indices");
    await page.getByRole("button", { name: "技能", exact: true }).click();
    const drawer = page.getByRole("dialog");
    await expect(
      drawer.getByRole("option", { name: "Invoice Skill", exact: true }),
    ).toBeVisible();
    expect(requests).toContain("/api/skills");
    expect(skillViews).toEqual(["mount"]);
    expect(requests).not.toContain("/api/indices");
    await drawer
      .getByRole("button", { name: "关闭", exact: true })
      .last()
      .click();
    await expect(drawer).toHaveCount(0);
    await page.getByRole("button", { name: "知识库", exact: true }).click();
    await expect(
      drawer.getByRole("option", { name: "Company Docs", exact: true }),
    ).toBeVisible();
    expect(requests).toContain("/api/indices");
    expect(
      requests.some((path) => path.endsWith("knowledge-capabilities")),
    ).toBe(true);
    await drawer
      .getByRole("button", { name: "关闭", exact: true })
      .last()
      .click();
    await expect(drawer).toHaveCount(0);
    await retainDraft();
  });
  for (const id of contract.expectedIds("assertions"))
    await contract.assertion(id, async () => {
      await retainDraft();
      expect(state.writes).toEqual([]);
      await expect(
        page.getByRole("button", { name: /Agent ·|Skill ·/ }),
      ).toHaveCount(0);
    });
});
