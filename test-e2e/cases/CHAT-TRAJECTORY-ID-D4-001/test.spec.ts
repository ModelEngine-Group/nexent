// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";
import { journey } from "../../infra/automation/d4/runner/journey";

journey("CHAT-TRAJECTORY-ID-D4-001", async ({ page, contract }) => {
  const base = process.env.NEXENT_BASE_URL ?? "http://localhost:3031";
  await page.context().grantPermissions(["clipboard-read", "clipboard-write"], {
    origin: new URL(base).origin,
  });
  contract.deferCleanup(async () => {
    await page.context().clearPermissions();
  });
  const histories = [42, 43, 44].map((conversationId) => ({
    conversation_id: conversationId,
    conversation_title: `Saved ${conversationId}`,
    agent_id: conversationId === 44 ? 7 : null,
    create_time: Date.now(),
    update_time: Date.now(),
  }));
  const state = await prepareWorkbench(page, 1, { histories });
  const copy = (id: number) =>
    page.getByRole("button", { name: `复制会话 ID ${id}`, exact: true });
  const copied: string[] = [];
  const verifyCopy = async (id: number) => {
    await expect(copy(id)).toBeVisible();
    await expect(copy(id)).toHaveText(`会话 ID: ${id}`);
    await copy(id).click();
    const read = () => page.evaluate(() => navigator.clipboard.readText());
    await expect.poll(read).toBe(String(id));
    copied.push(await read());
  };

  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await expect(page.getByText("Saved 42", { exact: true })).toBeVisible();
      await expect(
        page.getByRole("textbox", { name: "对话输入" }),
      ).toBeVisible();
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await expect(
      page.getByRole("button", { name: /^复制会话 ID/ }),
    ).toHaveCount(0);
    await page.getByText("Saved 42", { exact: true }).click();
    await verifyCopy(42);
    await page.getByText("Saved 43", { exact: true }).click();
    await expect(copy(42)).toHaveCount(0);
    await verifyCopy(43);
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await page.goto(`${base}/zh/newchat?conversation_id=44`);
    await verifyCopy(44);
    await expect(
      page.getByRole("button", { name: /^复制会话 ID/ }),
    ).toHaveCount(1);
  });
  const [workbench, agentChat] = contract.expectedIds("assertions");
  await contract.assertion(workbench, async () => {
    expect(copied.slice(0, 2)).toEqual(["42", "43"]);
    expect(state.writes).toEqual([]);
  });
  await contract.assertion(agentChat, async () => {
    expect(copied[2]).toBe("44");
    expect(state.writes).toEqual([]);
  });
});
