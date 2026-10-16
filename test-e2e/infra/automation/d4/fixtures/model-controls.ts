// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, type Page } from "playwright/test";
import { prepareWorkbench } from "./workbench-controls";
import { makeDraft, fulfillEditorReadFixture } from "./agent-editor-reads.mjs";

export const creatorEntries = ["workbench-agent", "workbench-skill", "nl2agent", "nl2skill"] as const;
export type Entry = typeof creatorEntries[number] | "workbench" | "chat";
export const levels = ["none", "minimal", "low", "medium", "high", "xhigh", "max"];
export const labels = ["无", "最低", "低", "中", "高", "极高", "最高"];

export async function prepareControls(page: Page, histories: Array<Record<string, any>> = []) {
  const base = await prepareWorkbench(page, 1, { reasoning: true, histories });
  const state = { ...base, requests: [] as Array<{ path: string; body: any }>,
    unavailable: false, delayed: false, release: () => {}, configDelay: 0,
    configGate: undefined as Promise<void> | undefined,
    draft: { ...makeDraft(), model_ids: [1, 3], model_names: ["Default A", "Effort B"] },
  };
  const model = (id: number, name: string, capability: any) => ({
    model_id: id, display_name: name, model_name: name, model_factory: "openai", model_type: "llm",
    connect_status: "available", extra_params: { enable_thinking: false, reasoning_effort: "low" }, reasoning_capability: capability,
  });
  const effort = { status: "supported", source: "catalog", levels, controls: [{ type: "effort", values: levels }] };
  await page.route("**/api/**", async route => {
    const path = new URL(route.request().url()).pathname;
    const json = (body: any, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/file/storage") return json({ success_count: 1, failed_count: 0, results: [{
      success: true, object_name: "attachments/model-controls-fixture.txt", file_name: "model-controls-fixture.txt",
      url: "/api/file/storage/model-controls-fixture.txt", file_size: 16,
    }] });
    if (path.endsWith("/workbench-config") && route.request().method() === "PATCH") {
      const body = route.request().postDataJSON();
      state.writes.push(path);
      return json({ code: 0, data: { workbench_config: body.config, workbench_config_version: (body.expected_version ?? 0) + 1 } });
    }
    if (["/api/agent/run", "/api/agent/nl2agent/run", "/api/skills/nl2skill/run"].includes(path)) {
      const body = route.request().postDataJSON(); state.requests.push({ path, body });
      if (state.unavailable) return json({ detail: { code: "model_unavailable" } }, 409);
      if (state.delayed) await new Promise<void>(resolve => { state.release = resolve; });
      const events = path.includes("nl2skill") ? [
        { type: "skill_body", content: "---\nname: model-control-fixture\ndescription: Fixture skill\n---\n# Fixture" },
        { type: "summary", content: "Fixture generated" },
      ] : path.includes("nl2agent") ? [
        { type: "nl2a_state", content: JSON.stringify({ event: "agent_draft_fields_saved", agent_id: 42, updated_fields: ["description"] }) },
        { type: "final_answer", content: "Fixture draft updated" },
      ] : [{ type: "final_answer", content: "Fixture response" }];
      await route.fulfill({ status: 200, contentType: "text/event-stream", body: [...events, { type: "done", content: "" }].map(e => `data: ${JSON.stringify(e)}\n\n`).join("") }).catch(() => {});
      return;
    }
    if (path === "/api/model/list") return json({ data: [model(1, "Default A", effort), model(3, "Effort B", effort),
      model(4, "Budget B", { status: "supported", source: "catalog", levels: [], controls: [{ type: "budget_tokens", min: 1024, max: 8192 }] }),
      model(2, "Plain Model", { status: "unsupported", levels: [], controls: [], source: "catalog" })] });
    if (path === "/api/config/load_config") {
      if (state.configGate) await state.configGate;
      if (state.configDelay) await new Promise(resolve => setTimeout(resolve, state.configDelay));
      return json({ config: { models: { llm: { id: 1, modelName: "Default A", displayName: "Default A", apiConfig: {} } } } });
    }
    if (/^\/api\/conversation\/9[12]$/.test(path)) {
      const id = Number(path.split("/").at(-1));
      return json({ code: 0, data: [{ ...histories.find(h => h.conversation_id === id), message: [],
        workbench_config: { schema_version: 3, mode: id === 92 ? "skill_create" : "generic_chat", model_id: id === 92 ? 3 : 999,
          generation_config: { deep_thinking: true, thinking_effort: "xhigh" }, agent_mounts: [], skill_mounts: [] } }] });
    }
    if (path === "/api/agent/search_info") return json(state.draft);
    if (path === "/api/agent/update") return json({ status: "success", agent_id: 42 });
    if (path === "/api/agent/published_list") return json([{ ...state.draft, id: "42", current_version_no: 1 }]);
    if (path === "/api/agent/check_name") return json([]);
    if (path === "/api/repository/skill/mine") return json({ items: [{ new_skill_padding: true }], pagination: { page: 1, page_size: 20, total: 1, total_pages: 1 }, counts: { all: 0, created: 0, others: 0 } });
    // Reuse established editor read fixtures without replacing the identity/model boundaries.
    if (!path.includes("user/") && !path.includes("model/") && !path.includes("config/") && !path.includes("conversation/") &&
        !path.includes("published_list") && await fulfillEditorReadFixture(route, path.replace("/api", ""))) return;
    return route.fallback();
  });
  return state;
}

export async function enter(page: Page, entry: Entry) {
  const root = process.env.NEXENT_BASE_URL ?? "http://localhost:3000";
  if (entry.startsWith("workbench")) {
    await page.goto(`${root}/zh/workbench`);
    if (entry !== "workbench") await page.getByRole("button", { name: entry === "workbench-agent" ? "智能体创建" : "技能创建", exact: true }).click();
  } else if (entry === "nl2agent") {
    await page.goto(`${root}/zh/agents/42`);
  } else if (entry === "nl2skill") {
    await page.goto(`${root}/zh/skill-space`);
    await page.getByRole("tab", { name: /^我的 Skill/ }).click();
    await page.getByRole("button", { name: "添加Skill服务", exact: true }).click();
  } else {
    await page.goto(`${root}/zh/newchat`);
    await page.getByRole("button", { name: /健康小助手 更多操作/ }).click();
  }
  await expect(input(page)).toBeVisible();
  await expect(trigger(page)).toBeVisible();
}
export const composer = (page: Page) => page.locator("form").filter({ has: page.locator('[data-slot="model-selector-trigger"]:visible') }).last();
export const input = (page: Page) => composer(page).locator('textarea,[contenteditable="true"][role="textbox"]').last();
export const trigger = (page: Page) => composer(page).locator('[data-slot="model-selector-trigger"]');
export const settings = (page: Page) => page.locator('[data-slot="model-selector-content"][data-state="open"]');
export async function openControls(page: Page) {
  if (!(await settings(page).isVisible())) await trigger(page).click();
  await expect(settings(page)).toBeVisible();
}
export async function chooseModel(page: Page, name: string) {
  await openControls(page);
  await settings(page).getByText(name, { exact: true }).click();
  await expect(trigger(page)).toContainText(name);
}
export async function thinking(page: Page, enabled: boolean, effort?: string) {
  await openControls(page);
  const toggle = settings(page).getByRole("switch");
  if ((await toggle.getAttribute("aria-checked")) !== String(enabled)) await toggle.click();
  await expect(toggle).toHaveAttribute("aria-checked", String(enabled));
  if (effort) {
    await settings(page).getByRole("combobox").click();
    await page.locator("[data-model-effort-popup]").getByText(effort, { exact: true }).click();
  }
  await page.keyboard.press("Escape");
}
export async function send(page: Page, state: Awaited<ReturnType<typeof prepareControls>>, text = "Create fixture capability") {
  const before = state.requests.length;
  await page.keyboard.press("Escape");
  await input(page).fill(text);
  await composer(page).getByRole("button", { name: "发送", exact: true }).click();
  await expect.poll(() => state.requests.length).toBe(before + 1);
  if (!state.delayed) await expect(trigger(page)).toBeEnabled();
  return state.requests.at(-1)!;
}
