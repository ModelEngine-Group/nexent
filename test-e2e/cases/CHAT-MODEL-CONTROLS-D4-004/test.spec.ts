// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import {
  chooseModel,
  input,
  openControls,
  prepareControls,
  settings,
  trigger,
} from "../../infra/automation/d4/fixtures/model-controls";
import {
  expectCompactDegree,
  expectReadableLabel,
  expectReadablePlaceholder,
  expectWithinViewport,
} from "../../infra/automation/d4/fixtures/selector-interaction";

journey("CHAT-MODEL-CONTROLS-D4-004", async ({ page, contract }) => {
  await page.setViewportSize({ width: 908, height: 608 });
  const state = await prepareControls(page);
  state.omitEffortDefault = true;
  state.omitSamplingDefaults = true;
  const root = process.env.NEXENT_BASE_URL ?? "http://localhost:3000";
  const writes: string[] = [];
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (request.method() !== "GET" && /\/api\/(model\/|config\/save|conversation\/\d+\/model_preferences)/.test(path))
      writes.push(path);
  });

  const open = async (locale: "zh" | "en") => {
    await page.goto(`${root}/${locale}/workbench`);
    await expect(input(page)).toBeVisible();
    await chooseModel(page, "Effort B");
    await openControls(page);
  };
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    await open("zh");
    await expect(settings(page).getByRole("switch")).toBeEnabled();
  });

  await contract.step(contract.expectedIds("steps")[0], async () => {
    for (const [locale, choice, fallback, resetName] of [
      ["zh", "极高", "服务默认", "继承 Agent / 出口配置"],
      ["en", "Extra high", "Service default", /Inherit Agent/],
    ] as const) {
      if (locale === "en") await open(locale);
      const toggle = settings(page).getByRole("switch");
      await expect(toggle).toBeEnabled();
      if ((await toggle.getAttribute("aria-checked")) !== "true") await toggle.click();
      const select = settings(page).locator(".ant-select");
      await select.click();
      const popup = page.locator("[data-model-effort-popup]");
      await expectReadableLabel(popup, choice);
      await popup.getByText(choice, { exact: true }).click();
      await expectCompactDegree(select, choice);
      await expect(trigger(page)).toContainText(choice);
      await settings(page).getByRole("button", { name: resetName }).click();
      await expect(trigger(page)).toContainText(fallback);
      await page.keyboard.press("Escape");
      await openControls(page);
      await expectReadableLabel(select, fallback);
      await select.click();
      await expect(popup.getByText(choice, { exact: true })).toBeVisible();
      await page.keyboard.press("Escape");
    }
  });

  await contract.step(contract.expectedIds("steps")[1], async () => {
    await openControls(page);
    await settings(page).getByRole("button", { name: "Advanced settings", exact: true }).click();
    const panel = page.getByRole("region", { name: "Advanced settings", exact: true });
    await expectWithinViewport(page, panel);
    const temperature = panel.getByRole("spinbutton", { name: "Temperature", exact: true });
    const topP = panel.getByRole("spinbutton", { name: "Top P", exact: true });
    const restore = panel.getByRole("button", { name: "Restore defaults", exact: true });
    for (const field of [temperature, topP]) {
      await expectWithinViewport(page, field);
      await expect(field).toHaveValue("");
      await expectReadablePlaceholder(field, "Service default");
    }
    await expectWithinViewport(page, restore);
    await topP.fill("0");
    await topP.press("Enter");
    await expect(topP).toHaveAttribute("aria-invalid", "true");
    const topPTrack = panel.getByRole("slider", { name: "Top P slider" });
    await topPTrack.focus();
    await topPTrack.press("End");
    await topPTrack.press("Home");
    await expect(topP).toHaveValue("0.01");
    await topP.fill("0.995");
    await topP.press("Enter");
    await expect(topP).toHaveValue("0.995");
    await topP.clear();
    await topP.press("Enter");
    await expect(topP).toHaveValue("");
    await expectReadablePlaceholder(topP, "Service default");
    const track = temperature.locator("..").locator(".ant-slider");
    const box = (await track.boundingBox())!;
    await track.click({ position: { x: box.width / 4, y: box.height / 2 } });
    await expect(temperature).not.toHaveValue("");
    await restore.click();
    await expect(temperature).toHaveValue("");
    await page.keyboard.press("Escape");
    await expect(panel).not.toBeVisible();
    await expect(settings(page).getByRole("switch")).toBeEnabled();
  });

  for (const id of contract.expectedIds("assertions")) {
    await contract.assertion(id, async () => {
      expect(state.requests).toEqual([]);
      expect(writes).toEqual([]);
    });
  }
});
