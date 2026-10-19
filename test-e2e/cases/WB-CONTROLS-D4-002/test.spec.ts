// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("WB-CONTROLS-D4-002", async ({ page, contract }) => {
  await page.setViewportSize({ width: 1174, height: 1188 });
  const state = await prepareWorkbench(page);
  const input = page.locator("[data-workbench-composer]");
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    await expect(input).toBeVisible();
    await expect(page.getByText("Fixture Model", { exact: true })).toBeVisible();
  });
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await input.fill("Ordinary conversation draft");
    const initialInputY = (await input.boundingBox())!.y;
    const composer = page.locator("fieldset").filter({ has: input });
    const initialComposerY = (await composer.boundingBox())!.y;
    const expectPosition = async () => {
      await expect.poll(async () => Math.abs((await input.boundingBox())!.y - initialInputY)).toBeLessThanOrEqual(1);
      await expect.poll(async () => Math.abs((await composer.boundingBox())!.y - initialComposerY)).toBeLessThanOrEqual(1);
    };
    for (const [mode, example] of [["智能体创建", "体检报告解读助手"], ["技能创建", "发票信息提取"]]) {
      const button = page.getByRole("button", { name: mode, exact: true });
      const a = await button.boundingBox(), b = await input.boundingBox();
      expect(a!.y).toBeLessThan(b!.y);
      await button.click();
      await expect(button).toHaveAttribute("aria-pressed", "true");
      await expect(input).toHaveValue("");
      await expect(page.getByRole("button", { name: "返回普通对话", exact: true })).toHaveCount(0);
      await expectPosition();
      await page.getByRole("button", { name: new RegExp(example) }).click();
      await expect(input).not.toHaveValue("");
      await expectPosition();
      await expect(page.locator("[data-workbench-composer]")).toBeVisible();
      await button.click();
      await expect(input).toHaveValue("Ordinary conversation draft");
      await expectPosition();
    }
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await contract.assertion(contract.expectedIds("assertions")[0], async () => {
      await page.getByText("Fixture Model", { exact: true }).click();
      const advanced = page.getByRole("button", { name: "高级设置", exact: true });
      await expect(advanced).toBeVisible();
      await expect(advanced.locator(".lucide-settings")).toHaveCount(0);
      await expect.poll(async () => {
        const advancedLabel = await advanced.getByText("高级设置", { exact: true }).boundingBox();
        const thinkingLabel = await page.getByText("深度思考", { exact: true }).boundingBox();
        return Math.abs(advancedLabel!.x - thinkingLabel!.x);
      }).toBeLessThanOrEqual(1);
      const effort = page.getByText("思考强度", { exact: true });
      await expect(effort).toHaveCount(0);
      expect((await advanced.boundingBox())!.y).toBeGreaterThan((await page.getByText("深度思考", {exact:true}).boundingBox())!.y);
      await advanced.hover();
      const panel = page.getByRole("region", { name: "高级设置", exact: true });
      const temperature = panel.getByRole("spinbutton", { name: "温度", exact: true });
      await expect(temperature).toHaveValue("50");
      const slider = panel.getByRole("slider", { name: "温度 滑块", exact: true });
      await slider.focus();
      await slider.hover();
      const handle = await slider.boundingBox();
      await page.mouse.move(handle!.x + handle!.width / 2, handle!.y + handle!.height / 2);
      await page.mouse.down(); await page.mouse.move(handle!.x + 24, handle!.y + handle!.height / 2, { steps: 6 }); await page.mouse.up();
      await expect(temperature).not.toHaveValue("50");
      await temperature.fill("100"); await temperature.press("Enter");
      await expect(slider).toHaveAttribute("aria-valuenow", "100");
      const topP = panel.getByRole("spinbutton", { name: "Top P", exact: true });
      await topP.fill("1"); await topP.press("Enter");
      for (const invalid of ["0", "101", "1.5"]) {
        await temperature.fill(invalid); await temperature.press("Enter");
        await expect(temperature).toHaveAttribute("aria-invalid", "true");
        await expect(panel.getByRole("alert")).toHaveText("请输入 1–100 的整数");
      }
      await panel.getByRole("button", { name: "恢复默认", exact: true }).click();
      await expect(temperature).toHaveValue("50"); await expect(topP).toHaveValue("90");
      await expect(input).toHaveValue("Ordinary conversation draft");
      await page.goto(`${process.env.NEXENT_BASE_URL}/zh/newchat`);
      await expect(page).toHaveURL(/\/zh\/newchat/);
      await page.getByRole("button", { name: /Internal Analyst/ }).first().click();
      await expect(page.getByText("Fixture Model", { exact: true })).toBeVisible();
      const writesBeforeParameters = [...state.writes];
      await page.getByText("Fixture Model", { exact: true }).click();
      const sharedAdvanced = page.getByRole("button", { name: "高级设置", exact: true });
      await expect(sharedAdvanced).toBeVisible();
      await expect(page.getByText("深度思考", { exact: true })).toBeVisible();
      await expect(page.getByText("思考强度", { exact: true })).toHaveCount(0);
      await sharedAdvanced.hover();
      const sharedPanel = page.getByRole("region", { name: "高级设置", exact: true });
      const sharedTemperature = sharedPanel.getByRole("spinbutton", { name: "温度", exact: true });
      await sharedTemperature.fill("73"); await sharedTemperature.press("Enter");
      await expect(sharedPanel.getByRole("slider", { name: "温度 滑块" })).toHaveAttribute("aria-valuenow", "73");
      const sharedTopP = sharedPanel.getByRole("spinbutton", { name: "Top P", exact: true });
      await sharedTopP.fill("42"); await sharedTopP.press("Enter");
      await expect(sharedPanel.getByRole("slider", { name: "Top P 滑块" })).toHaveAttribute("aria-valuenow", "42");
      await sharedPanel.getByRole("button", { name: "恢复默认", exact: true }).click();
      await expect(sharedTemperature).toHaveValue("50"); await expect(sharedTopP).toHaveValue("90");
      expect(state.writes).toEqual(writesBeforeParameters);
      await page.goto(`${process.env.NEXENT_BASE_URL}/zh/workbench`);
      await expect(input).toBeVisible();
    });
    expect(state.writes).toEqual([]);
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    for (const permissions of [[], ["agent:create"], ["skill:create"], ["agent:create", "skill:create"]]) {
      state.authorization.permissions = permissions;
      await page.reload();
      await expect(input).toBeVisible();
      await expect(page.getByText("Fixture Model", { exact: true })).toBeVisible();
      for (const [permission, label] of [["agent:create", "智能体创建"], ["skill:create", "技能创建"]]) {
        const button = page.getByRole("button", { name: label, exact: true });
        if (permissions.includes(permission)) {
          await expect(button).toBeVisible();
          await button.click();
          await expect(button).toHaveAttribute("aria-pressed", "true");
          await button.click();
          await expect(button).toHaveAttribute("aria-pressed", "false");
        } else {
          await expect(button).toHaveCount(0);
        }
      }
    }
    expect(state.writes).toEqual([]);
  });
});
