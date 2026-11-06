// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("CHAT-DETAIL-D4-001", async ({ page, contract }) => {
  const histories = [42, 43].map((id) => ({
    conversation_id: id,
    conversation_title: `Agent saved ${id}`,
    agent_id: 7,
    create_time: Date.now(),
    update_time: Date.now(),
  }));
  const state = await prepareWorkbench(page, 1, { histories });
  await page.route("**/api/agent/published_list", (route) =>
    route.fulfill({
      json: [
        {
          id: "7",
          agent_id: 7,
          name: "Detail Analyst",
          display_name: "Detail Analyst",
          description: "Detail fixture",
          current_version_no: 3,
          is_available: true,
          is_main_agent: true,
          model_ids: [1],
          allow_chat_metadata: true,
        },
      ],
    }),
  );
  await page.route("**/api/conversation/*", async (route) => {
    const match = new URL(route.request().url()).pathname.match(
      /^\/api\/conversation\/(\d+)$/,
    );
    if (!match) return route.fallback();
    const id = Number(match[1]);
    await route.fulfill({
      json: {
        code: 0,
        data: [
          {
            ...histories.find((history) => history.conversation_id === id),
            runtime_metadata: { key: String(id) },
            runtime_metadata_version: 4,
            message: [
              {
                role: "user",
                message_id: id * 2,
                message_index: 0,
                message: `Question ${id}`,
              },
              {
                role: "assistant",
                message_id: id * 2 + 1,
                message_index: 1,
                status: "completed",
                message: [{ type: "final_answer", content: `Answer ${id}` }],
              },
            ],
          },
        ],
      },
    });
  });
  const detailReads: string[] = [];
  page.on("request", (request) => {
    const match = new URL(request.url()).pathname.match(
      /^\/api\/conversation\/(\d+)$/,
    );
    if (request.method() === "GET" && match) detailReads.push(match[1]);
  });
  const composer = page.getByRole("textbox", { name: "对话输入", exact: true });
  const row = (id: string) =>
    page.getByText(`Agent saved ${id}`, { exact: true });
  const results = [false, false, false];
  const restored = async (id: string) => {
    await expect(composer).toBeEnabled();
    await expect(
      page.getByText(`Question ${id}`, { exact: true }),
    ).toBeVisible();
    await expect(page.getByText(`Answer ${id}`, { exact: true })).toBeVisible();
    await expect(
      page.getByText("Detail Analyst", { exact: true }).first(),
    ).toBeVisible();
    await page.getByRole("button", { name: /^Metadata/ }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog.getByRole("textbox")).toHaveValue(
      JSON.stringify({ key: id }, null, 2),
    );
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
    await page.waitForLoadState("networkidle");
    results[1] = true;
    expect(state.writes).toEqual([]);
  };
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      expect(histories).toHaveLength(2);
      expect(state.writes).toEqual([]);
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    const before = detailReads.length;
    await page.goto(
      `${process.env.NEXENT_BASE_URL ?? "http://localhost:3000"}/zh/newchat?conversation_id=42`,
    );
    await restored("42");
    expect(detailReads.slice(before)).toEqual(["42"]);
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    // Discovery groups start collapsed; selecting its Agent exposes both rows.
    if (!(await row("43").isVisible())) {
      await page
        .getByRole("button")
        .filter({ hasText: "Detail Analyst" })
        .first()
        .click();
    }
    for (const id of ["43", "42"]) {
      const before = detailReads.length;
      await row(id).click();
      await restored(id);
      expect(detailReads.slice(before)).toEqual([id]);
    }
    const before = detailReads.length;
    await row("42").click();
    await page.waitForLoadState("networkidle");
    expect(detailReads.slice(before)).toEqual([]);
    expect(state.writes).toEqual([]);
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    const before = detailReads.length;
    await page.reload();
    await restored("42");
    expect(detailReads.slice(before)).toEqual(["42"]);
    results[0] = true;
  });
  await contract.step(contract.expectedIds("steps")[3], async () => {
    const before = detailReads.length;
    await page.evaluate(() => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "hidden",
      });
      document.dispatchEvent(new Event("visibilitychange"));
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "visible",
      });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await expect.poll(() => detailReads.slice(before)).toEqual(["42"]);
    await restored("42");
    expect(detailReads.slice(before)).toEqual(["42"]);
    results[2] = true;
  });
  for (const [index, id] of contract.expectedIds("assertions").entries()) {
    await contract.assertion(id, async () => {
      expect(results[index]).toBe(true);
      expect(state.writes).toEqual([]);
    });
  }
});
