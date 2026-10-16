import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { creatorEntries, prepareControls, enter, chooseModel, send, openControls, settings, input } from "../../infra/automation/d4/fixtures/model-controls";

journey("CHAT-MODEL-CONTROLS-D4-003", async ({ page, contract }) => {
  await page.setViewportSize({ width: 1441, height: 1244 });
  const state = await prepareControls(page);
  const panel = page.getByRole("region", { name: "高级设置", exact: true });
  const temperature = panel.getByRole("spinbutton", { name: "温度", exact: true });
  const topP = panel.getByRole("spinbutton", { name: "Top P", exact: true });
  const open = async () => {
    await openControls(page);
    const advanced = settings(page).getByRole("button", { name: "高级设置", exact: true });
    await advanced.focus(); await advanced.hover(); await expect(panel).toBeVisible();
  };
  const set = async (t: string, p: string) => {
    await open(); await temperature.fill(t); await temperature.press("Enter");
    await topP.fill(p); await topP.press("Enter");
  };
  for (const id of contract.expectedIds("preconditions")) await contract.precondition(id, async () => {
    await enter(page, "workbench-agent"); await chooseModel(page, "Default A"); await open();
    await expect(temperature).toHaveValue("50"); await expect(topP).toHaveValue("90");
  });
  await contract.step(contract.expectedIds("steps")[0], async () => {
    for (const entry of creatorEntries) {
      await enter(page, entry); await chooseModel(page, "Default A"); await open();
      await expect(temperature).toHaveValue("50"); await expect(topP).toHaveValue("90");
      for (const level of ["1", "73", "100"]) {
        await set(level, level);
        await expect(panel.getByRole("slider", { name: "温度 滑块", exact: true })).toHaveAttribute("aria-valuenow", level);
        await expect(panel.getByRole("slider", { name: "Top P 滑块", exact: true })).toHaveAttribute("aria-valuenow", level);
      }
      const slider = panel.getByRole("slider", { name: "温度 滑块", exact: true });
      await slider.focus(); await slider.press("ArrowLeft"); await expect(temperature).toHaveValue("99");
      for (const invalid of ["0", "101", "1.5", ""]) {
        await temperature.fill(invalid); await temperature.press("Enter");
        await expect(temperature).toHaveAttribute("aria-invalid", "true");
        await expect(panel.getByRole("alert")).toBeVisible();
      }
      await panel.getByRole("button", { name: "恢复默认", exact: true }).click();
      await expect(temperature).toHaveValue("50"); await expect(topP).toHaveValue("90");
      await page.keyboard.press("Escape");
    }
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    for (const entry of creatorEntries) {
      await enter(page, entry); await chooseModel(page, "Default A"); await set("73", "1"); await page.keyboard.press("Escape");
      await chooseModel(page, "Effort B"); await open(); await expect(temperature).toHaveValue("50"); await expect(topP).toHaveValue("90"); await page.keyboard.press("Escape");
      await chooseModel(page, "Default A"); await open(); await expect(temperature).toHaveValue("73"); await expect(topP).toHaveValue("1"); await page.keyboard.press("Escape");
      await send(page, state);
      await open(); await expect(temperature).toHaveValue("73"); await expect(topP).toHaveValue("1"); await page.keyboard.press("Escape");
      await expect(input(page)).toBeEditable();
      if (entry.startsWith("workbench")) {
        await page.getByRole("button", { name: entry === "workbench-agent" ? "智能体创建" : "技能创建", exact: true }).click();
        await page.getByRole("button", { name: entry === "workbench-agent" ? "技能创建" : "智能体创建", exact: true }).click();
        await open(); await expect(temperature).toHaveValue("50"); await page.keyboard.press("Escape");
      } else {
        await enter(page, entry); await open(); await expect(temperature).toHaveValue("50"); await expect(topP).toHaveValue("90"); await page.keyboard.press("Escape");
      }
    }
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    for (const entry of creatorEntries) {
      await enter(page, entry); await chooseModel(page, "Effort B"); await set("73", "100"); await page.keyboard.press("Escape");
      const { body } = await send(page, state);
      expect(body.model_id).toBe(3);
      expect(body.generation_config).not.toHaveProperty("temperature");
      expect(body.generation_config).not.toHaveProperty("top_p");
      expect(body).not.toHaveProperty("temperature"); expect(body).not.toHaveProperty("top_p");
      if (body.workbench_config) {
        expect(body.workbench_config.generation_config).not.toHaveProperty("temperature");
        expect(body.workbench_config.generation_config).not.toHaveProperty("top_p");
      }
    }
  });
  for (const id of contract.expectedIds("assertions")) await contract.assertion(id, async () => {
    expect(state.requests).toHaveLength(8);
    expect(state.writes.filter(path => /\/model\/|\/config\/save/.test(path))).toEqual([]);
    expect(state.requests.every(({ body }) => !JSON.stringify(body).includes("temperatureLevel"))).toBe(true);
  });
});
