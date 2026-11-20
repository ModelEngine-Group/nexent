// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, type Locator } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { creatorEntries, prepareControls, enter, chooseModel, thinking, send, input, composer, trigger, openControls, settings, type Entry } from "../../infra/automation/d4/fixtures/model-controls";

async function expectReadableLabel(control: Locator, text: string) {
  const label = control.getByText(text, { exact: true });
  await expect(label).toBeVisible();
  await expect.poll(() => label.evaluate(element => {
    const range = document.createRange();
    range.selectNodeContents(element);
    return range.getBoundingClientRect().width <= element.getBoundingClientRect().width + 1 &&
      element.scrollWidth <= element.clientWidth + 1;
  })).toBe(true);
}

async function expectWithinViewport(control: Locator, width: number, height: number) {
  await expect(control).toBeVisible();
  await expect.poll(async () => {
    const box = await control.boundingBox();
    return !!box && box.x >= 0 && box.y >= 0 &&
      box.x + box.width <= width + 1 && box.y + box.height <= height + 1;
  }).toBe(true);
}

journey("CHAT-MODEL-CONTROLS-D4-002", async ({ page, contract }) => {
  const root = process.env.NEXENT_BASE_URL ?? "http://localhost:3000";
  await page.setViewportSize({ width: 1441, height: 1244 });
  // The client checks session expiry before requesting the mocked identity.
  await page.context().addCookies([{
    name: "nexent_token_expires_at",
    value: String(Math.floor(Date.now() / 1000) + 3600),
    url: root,
  }]);
  const histories = [91, 92].map(id => ({ conversation_id: id, conversation_title: id === 91 ? "Invalid saved model" : "Saved skill creation", create_time: Date.now(), update_time: Date.now() }));
  const state = await prepareControls(page, histories);
  const entries: Entry[] = ["workbench", "chat", ...creatorEntries];
  const inputText = async () => input(page).evaluate(el => el instanceof HTMLTextAreaElement ? el.value : el.textContent);
  for (const id of contract.expectedIds("preconditions")) await contract.precondition(id, async () => {
    await enter(page, "workbench"); await openControls(page);
    await expect(settings(page).getByText("Budget B", { exact: true })).toBeVisible();
    await page.keyboard.press("Escape");
  });
  await contract.step(contract.expectedIds("steps")[0], async () => {
    for (const entry of entries) {
      await enter(page, entry);
      if (entry === "workbench-agent" || entry === "workbench-skill") {
        const label = entry === "workbench-agent" ? "智能体创建" : "技能创建";
        await expect(page.getByRole("button", {name:label,exact:true})).toHaveAttribute("aria-pressed","true");
        await page.getByRole("button", {name:label,exact:true}).click();
        await expect(page.getByRole("button", {name:"返回普通对话",exact:true})).toHaveCount(0);
        await expect(page.getByRole("button", {name:"执行模式",exact:true})).toBeVisible();
        await page.getByRole("button", {name:label,exact:true}).click();
        await expect(page.getByRole("button", {name:label,exact:true})).toHaveAttribute("aria-pressed","true");
      }
      await openControls(page);
      await expect(settings(page).getByText("Effort B", { exact: true })).toBeVisible();
      if (entry === "chat") await expect(settings(page).getByText("Budget B", { exact: true })).toHaveCount(0);
      else await expect(settings(page).getByText("Budget B", { exact: true })).toBeVisible();
      await page.keyboard.press("Escape");
      if (entry === "workbench") {
        const chooser = page.waitForEvent("filechooser");
        await composer(page).getByRole("button", { name: "上传附件", exact: true }).click();
        await (await chooser).setFiles({ name: "model-controls-fixture.txt", mimeType: "text/plain", buffer: Buffer.from("fixture contents") });
        await expect(page.getByText("model-controls-fixture.txt", { exact: true }).first()).toBeVisible();
      }
      await input(page).fill("Preserve this local draft");
      await chooseModel(page, "Effort B"); await thinking(page, true, "极高");
      await chooseModel(page, "Default A"); await chooseModel(page, "Effort B");
      await openControls(page); await expect(settings(page).locator(".ant-select")).toContainText("极高"); await page.keyboard.press("Escape");
      expect(await inputText()).toBe("Preserve this local draft");
      if (entry === "workbench") {
        await expect(page.getByText("model-controls-fixture.txt", { exact: true }).first()).toBeVisible();
        const request = await send(page, state, "Preserve this local draft");
        expect(request.body.minio_files[0].object_name).toBe("attachments/model-controls-fixture.txt");
        await chooseModel(page, "Default A");
        await expect(page.getByText("model-controls-fixture.txt", { exact: true }).first()).toBeVisible();
      }
    }
    await enter(page, "workbench"); await chooseModel(page, "Effort B"); await input(page).fill("Ordinary draft");
    await page.getByRole("button", { name: "技能创建", exact: true }).click(); await chooseModel(page, "Default A");
    await page.getByRole("button", { name: "技能创建", exact: true }).click();
    await expect(trigger(page)).toContainText("Effort B"); expect(await inputText()).toBe("Ordinary draft");
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await enter(page, "workbench"); await page.locator("button[data-radix-collection-item]").filter({ hasText: "Saved skill creation" }).click();
    await expect(trigger(page)).toContainText("Effort B"); await openControls(page); await expect(settings(page).locator(".ant-select")).toContainText("极高"); await page.keyboard.press("Escape");
    await expect(page.getByRole("button", { name: "技能创建", exact: true })).toHaveAttribute("aria-pressed", "true");
    for (const entry of ["nl2agent", "nl2skill"] as Entry[]) {
      await enter(page, entry); await chooseModel(page, "Effort B");
      await enter(page, entry); await expect(trigger(page)).toContainText("Default A");
    }
    await page.evaluate(() => localStorage.clear());
    let release!: () => void; state.configGate = new Promise(resolve => { release = resolve; });
    const loaded = page.waitForResponse(r => new URL(r.url()).pathname === "/api/config/load_config");
    await enter(page, "nl2agent"); await chooseModel(page, "Effort B"); release(); await loaded; state.configGate = undefined;
    await expect(trigger(page)).toContainText("Effort B");
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    for (const entry of entries) {
      await enter(page, entry); await chooseModel(page, "Effort B"); await thinking(page, true, "极高");
      state.delayed = true;
      await send(page, state, "Delayed fixture request");
      await expect(trigger(page)).toBeDisabled();
      const release = state.release;
      await composer(page).getByRole("button", { name: "停止生成", exact: true }).click();
      state.delayed = false;
      await expect(trigger(page)).toBeEnabled();
      await chooseModel(page, "Default A"); await send(page, state, "Retry on selected A");
      release(); await expect(trigger(page)).toContainText("Default A");
      expect(state.requests.at(-1)!.body.model_id).toBe(1);
    }
  });
  await contract.step(contract.expectedIds("steps")[3], async () => {
    await enter(page, "workbench"); await page.locator("button[data-radix-collection-item]").filter({ hasText: "Invalid saved model" }).click();
    await expect(page.getByText("所选模型出口已不可用，请检查配置或手动重新选择模型。", { exact: true }).first()).toBeVisible();
    await input(page).fill("Recover invalid saved selection");
    await expect(composer(page).getByRole("button", { name: "发送", exact: true })).toBeDisabled();
    await chooseModel(page, "Effort B"); await send(page, state, "Recovered saved selection");
    state.unavailable = true; await send(page, state, "Controlled unavailable model");
    await expect(page.getByText("所选模型出口已不可用，请检查配置或手动重新选择模型。", { exact: true }).first()).toBeVisible();
    state.unavailable = false; await chooseModel(page, "Default A"); await send(page, state, "Reselected valid model");
    for (const [permission, label] of [["agent:create", "智能体创建"], ["skill:create", "技能创建"]]) {
      state.authorization.permissions = [permission === "agent:create" ? "skill:create" : "agent:create"];
      await enter(page, "workbench"); await expect(page.getByRole("button", { name: label, exact: true })).toHaveCount(0);
      await enter(page, permission === "agent:create" ? "nl2agent" : "nl2skill");
      await expect(trigger(page)).toBeDisabled();
    }
    state.authorization.permissions = ["agent:create", "skill:create"];
    state.authorization.tenantId = "another-fixture-tenant"; state.authorization.userId = "another-fixture-user";
    await enter(page, "workbench"); await expect(trigger(page)).toContainText("Default A");
  });
  await contract.step(contract.expectedIds("steps")[4], async () => {
    const viewport = { width: 908, height: 608 };
    await page.setViewportSize(viewport);
    state.omitEffortDefault = true;
    state.omitSamplingDefaults = true;
    const requestCount = state.requests.length;
    const preferenceWrites: string[] = [];
    page.on("request", request => {
      const path = new URL(request.url()).pathname;
      if (request.method() !== "GET" && /\/api\/(model\/|config\/save|conversation\/\d+\/model_preferences)/.test(path)) {
        preferenceWrites.push(path);
      }
    });

    for (const [locale, choice, fallback, resetEffort, advanced, tempLabel, resetSampling, topPRange] of [
      ["zh", "极高", "服务默认", "继承 Agent / 出口配置", "高级设置", "温度", "恢复默认", "0–1，不可为 0"],
      ["en", "Extra high", "Service default", /Inherit Agent/, "Advanced settings", "Temperature", "Restore defaults", "0–1, excluding 0"],
    ] as const) {
      await page.goto(`${root}/${locale}/workbench`);
      await expect(input(page)).toBeVisible();
      await chooseModel(page, "Effort B");
      await openControls(page);
      const menu = settings(page);
      const toggle = menu.getByRole("switch");
      await expect(toggle).toBeEnabled();
      if ((await toggle.getAttribute("aria-checked")) !== "true") await toggle.click();
      const select = menu.locator(".ant-select");
      const popup = page.locator("[data-model-effort-popup]");
      await select.click();
      await expectReadableLabel(popup, choice);
      await popup.getByText(choice, { exact: true }).click();
      await expectReadableLabel(select, choice);
      await expect.poll(async () => (await select.boundingBox())?.width ?? Infinity).toBeLessThanOrEqual(128);
      await expect(trigger(page)).toContainText(choice);
      await menu.getByRole("button", { name: resetEffort }).click();
      await expect(trigger(page)).toContainText(fallback);
      await page.keyboard.press("Escape");
      await openControls(page);
      await expectReadableLabel(select, fallback);

      await menu.getByRole("button", { name: advanced, exact: true }).click();
      const panel = page.getByRole("region", { name: advanced, exact: true });
      const temperature = panel.getByRole("spinbutton", { name: tempLabel, exact: true });
      const restore = panel.getByRole("button", { name: resetSampling, exact: true });
      await expectWithinViewport(panel, viewport.width, viewport.height);
      for (const [field, placeholder] of [
        [temperature, "0–2"],
        [panel.getByRole("spinbutton", { name: "Top P", exact: true }), topPRange],
      ] as const) {
        await expectWithinViewport(field, viewport.width, viewport.height);
        await expect(field).toHaveValue("");
        await expect(field).toHaveAttribute("placeholder", placeholder);
        expect(await field.evaluate((element: HTMLInputElement) => {
          const style = getComputedStyle(element);
          const context = document.createElement("canvas").getContext("2d")!;
          context.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
          const available = element.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) - 20;
          return context.measureText(element.placeholder).width <= available;
        })).toBe(true);
      }
      await expectWithinViewport(restore, viewport.width, viewport.height);
      await temperature.press("ArrowUp");
      await expect(temperature).not.toHaveValue("");
      await restore.click();
      await expect(temperature).toHaveValue("");
      await page.keyboard.press("Escape");
      await expect(panel).not.toBeVisible();
      await select.click();
      await expect(popup.getByText(choice, { exact: true })).toBeVisible();
    }
    expect(state.requests).toHaveLength(requestCount);
    expect(preferenceWrites).toEqual([]);
  });
  for (const id of contract.expectedIds("assertions")) await contract.assertion(id, async () => {
    const retries = state.requests.filter(({ body }) => body.query === "Retry on selected A");
    expect(retries).toHaveLength(6); expect(retries.every(({ body }) => body.model_id === 1)).toBe(true);
    expect(state.requests.filter(({ body }) => body.model_id === 999)).toEqual([]);
    expect(state.writes.filter(path => /\/model\/|\/config\/save/.test(path))).toEqual([]);
  });
});
