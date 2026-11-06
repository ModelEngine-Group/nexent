// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { creatorEntries, prepareControls, enter, chooseModel, thinking, send, input, composer, trigger, openControls, settings, type Entry } from "../../infra/automation/d4/fixtures/model-controls";

journey("CHAT-MODEL-CONTROLS-D4-002", async ({ page, contract }) => {
  await page.setViewportSize({ width: 1441, height: 1244 });
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
  for (const id of contract.expectedIds("assertions")) await contract.assertion(id, async () => {
    const retries = state.requests.filter(({ body }) => body.query === "Retry on selected A");
    expect(retries).toHaveLength(6); expect(retries.every(({ body }) => body.model_id === 1)).toBe(true);
    expect(state.requests.filter(({ body }) => body.model_id === 999)).toEqual([]);
    expect(state.writes.filter(path => /\/model\/|\/config\/save/.test(path))).toEqual([]);
  });
});
