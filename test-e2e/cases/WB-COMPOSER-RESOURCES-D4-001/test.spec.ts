// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("WB-COMPOSER-RESOURCES-D4-001", async ({ page, contract, expect }) => {
  const [precondition] = contract.expectedIds("preconditions");
  const [mount, remove] = contract.expectedIds("steps");
  const [assertion] = contract.expectedIds("assertions");
  const state = await prepareWorkbench(page);
  const composer = page.locator('[data-slot="chat-composer"]');
  const input = composer.getByRole("textbox", {
    name: "对话输入",
    exact: true,
  });
  const tags = composer.locator('[data-slot="composer-resources"]');
  const options = [
    { button: "智能体", name: "Internal Analyst" },
    { button: "知识库", name: "Company Docs" },
    { button: "技能", name: "Invoice Skill" },
  ];
  await contract.precondition(precondition, async () => {
    await expect(input).toBeVisible();
  });
  await contract.step(mount, async () => {
    await input.fill("Keep this draft");
    for (const { button, name } of options) {
      const entry = composer.getByRole("button", { name: button, exact: true });
      await entry.click();
      const drawer = page.getByRole("dialog");
      await drawer.getByRole("option", { name, exact: true }).click();
      await drawer.getByRole("button", { name: "确认", exact: true }).click();
      await expect(drawer).toHaveCount(0);
      await expect(tags.getByText(name, { exact: true })).toBeVisible();
      await expect(entry).toHaveText(`${button}1`);
    }
    const [tagBox, inputBox] = await Promise.all([
      tags.boundingBox(),
      input.boundingBox(),
    ]);
    expect(tagBox!.y + tagBox!.height).toBeLessThanOrEqual(inputBox!.y);
  });
  await contract.step(remove, async () => {
    for (const { button, name } of options) {
      await tags
        .getByRole("button", { name: `移除 ${name}`, exact: true })
        .click();
      await expect(tags.getByText(name, { exact: true })).toHaveCount(0);
      await expect(
        composer.getByRole("button", { name: button, exact: true }),
      ).toHaveText(button);
    }
    await expect(tags).toHaveCount(0);
  });
  await contract.assertion(assertion, async () => {
    await expect(input).toHaveValue("Keep this draft");
    expect(state.writes).toEqual([]);
  });
});
