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
      for (const label of ["自动", ...labels]) await expect(page.locator("[data-model-effort-popup]").getByText(label, { exact: true })).toBeVisible();
      await page.locator("[data-model-effort-popup]").getByText("极高", { exact: true }).click();
      await page.keyboard.press("Escape");
      await expect(trigger(page)).toContainText("极高");
    }
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    for (const entry of creatorEntries) {
      await enter(page, entry); await chooseModel(page, "Effort B"); await thinking(page, true, "极高");
      for (const text of ["Create fixture capability", "Refine fixture capability"]) {
        const { path, body } = await send(page, state, text);
        expect(path).toBe(entry.endsWith("skill") ? "/api/skills/nl2skill/run" : "/api/agent/nl2agent/run");
        expect(body.model_id).toBe(3);
        expect(body.generation_config).toMatchObject({ deep_thinking: true, thinking_effort: "xhigh" });
        expect(body.query).toBe(text);
        expect(body.history).toBeInstanceOf(Array);
        expect(body).not.toHaveProperty("reasoning_effort");
        if (entry.startsWith("workbench")) {
          expect(body.persist_history).toBe(true);
          expect(body.workbench_config.model_id).toBe(body.model_id);
          expect(body.workbench_config.generation_config).toMatchObject(body.generation_config);
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
      expect((await send(page, state)).body.generation_config).toMatchObject({ deep_thinking: true, thinking_effort: "auto" });
      await thinking(page, false);
      await openControls(page);
      await expect(settings(page).getByRole("combobox")).toHaveCount(0);
      await page.keyboard.press("Escape");
      expect((await send(page, state)).body.generation_config.deep_thinking).toBe(false);
      await chooseModel(page, "Budget B"); await thinking(page, true); await openControls(page);
      const slider = settings(page).getByRole("slider"); await slider.fill("2048"); await page.keyboard.press("Escape");
      expect((await send(page, state)).body.generation_config).toMatchObject({ deep_thinking: true, thinking_effort: "auto", reasoning_budget_tokens: 2048 });
      await chooseModel(page, "Plain Model"); await openControls(page);
      await expect(settings(page).getByRole("switch")).toBeDisabled();
      await expect(settings(page).getByRole("combobox")).toHaveCount(0);
      await page.keyboard.press("Escape");
    }
  });
  for (const id of contract.expectedIds("assertions")) await contract.assertion(id, async () => {
    expect(new Set(state.requests.map(r => r.path))).toEqual(new Set(["/api/agent/nl2agent/run", "/api/skills/nl2skill/run"]));
    expect(state.requests.length).toBe(20);
    expect(state.requests.every(r => !JSON.stringify(r.body.generation_config).includes("temperature"))).toBe(true);
    expect(state.writes.filter(path => path.includes("model/") && !path.includes("list"))).toEqual([]);
  });
});
