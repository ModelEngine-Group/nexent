// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { creatorEntries, prepareControls, enter, chooseModel, thinking, send, composer, input, trigger, openControls, settings, labels } from "../../infra/automation/d4/fixtures/model-controls";

journey("CHAT-MODEL-CONTROLS-D4-001", async ({ page, contract }) => {
  await page.setViewportSize({ width: 1441, height: 1244 });
  const state = await prepareControls(page);
  for (const id of contract.expectedIds("preconditions")) await contract.precondition(id, async () => {
    await enter(page, "workbench");
    await expect(trigger(page)).toContainText("Default A");
    expect(state.authorization.permissions).toEqual(["agent:create", "skill:create"]);
  });
  await contract.step(contract.expectedIds("steps")[0], async () => {
    for (const entry of creatorEntries) {
      await enter(page, entry);
      await chooseModel(page, "Effort B");
      await thinking(page, true);
      await openControls(page);
      await settings(page).getByRole("combobox").click();
      for (const label of labels) await expect(page.locator("[data-model-effort-popup]").getByText(label, { exact: true })).toBeVisible();
      await page.locator("[data-model-effort-popup]").getByText("极高", { exact: true }).click();
      await page.keyboard.press("Escape");
      await openControls(page);
      await expect(settings(page).locator(".ant-select")).toContainText("极高");
      await page.keyboard.press("Escape");
    }
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    for (const entry of creatorEntries) {
      await enter(page, entry); await chooseModel(page, "Effort B"); await thinking(page, true, "极高");
      for (const text of ["Create fixture capability", "Refine fixture capability"]) {
        const { path, body, effective } = await send(page, state, text);
        expect(path).toBe(entry.endsWith("skill") ? "/api/skills/nl2skill/run" : "/api/agent/nl2agent/run");
        expect(body.model_id).toBe(3);
        expect(effective).toMatchObject({ enable_thinking: true, reasoning_effort: "xhigh" });
        expect(body).not.toHaveProperty("generation_config");
        expect(body.query).toBe(text);
        expect(body.history).toBeInstanceOf(Array);
        expect(body).not.toHaveProperty("reasoning_effort");
        if (entry.startsWith("workbench")) {
          expect(body.persist_history).toBe(true);
          expect(body.workbench_config).not.toHaveProperty("model_id");
          expect(body.workbench_config).not.toHaveProperty("generation_config");
        }
        if (entry.endsWith("agent")) expect(body.agent_id).toBe(42);
        else { expect(body.language).toBe("zh"); expect(body.draft_snapshot).toBeDefined(); }
      }
      await expect(input(page)).toBeEditable();
      await expect(page.getByText(entry.endsWith("skill") ? "Fixture generated" : "Fixture draft updated", { exact: false }).first()).toBeVisible();
    }
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    for (const entry of creatorEntries) {
      await enter(page, entry); await chooseModel(page, "Effort B"); await thinking(page, true, "自动");
      expect((await send(page, state)).effective).toMatchObject({ enable_thinking: true, reasoning_effort: "low" });
      await thinking(page, false);
      await openControls(page);
      await expect(settings(page).getByRole("combobox")).toHaveCount(0);
      await page.keyboard.press("Escape");
      expect((await send(page, state)).effective.enable_thinking).toBe(false);
      await chooseModel(page, "Budget B"); await thinking(page, true); await openControls(page);
      const budget = settings(page).getByRole("spinbutton", { name: "reasoning_budget_tokens" }); await budget.fill("2048"); await budget.press("Enter"); await page.keyboard.press("Escape");
      expect((await send(page, state)).effective).toMatchObject({ enable_thinking: true, reasoning_budget_tokens: 2048 });
      await chooseModel(page, "Plain Model"); await openControls(page);
      await expect(settings(page).getByRole("switch")).toBeDisabled();
      await expect(settings(page).getByRole("combobox")).toHaveCount(0);
      await page.keyboard.press("Escape");
    }
  });
  for (const id of contract.expectedIds("assertions")) await contract.assertion(id, async () => {
    expect(new Set(state.requests.map(r => r.path))).toEqual(new Set(["/api/agent/nl2agent/run", "/api/skills/nl2skill/run"]));
    expect(state.requests.length).toBe(20);
    expect(state.requests.every(r => !Object.hasOwn(r.explicit, "temperature"))).toBe(true);
    expect(state.writes.filter(path => path.includes("model/") && !path.includes("list"))).toEqual([]);
  });
});
