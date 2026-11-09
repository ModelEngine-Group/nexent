// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("WB-CREATION-INTENT-D4-001", async ({ page, contract }) => {
  const history = { conversation_id: 91, conversation_title: "AI creation fixture", agent_id: null, create_time: Date.now(), update_time: Date.now() };
  const state = await prepareWorkbench(page, 1, { histories: [history] });
  const input = page.locator("[data-workbench-composer]");
  const agentButton = page.getByRole("button", { name: "智能体创建", exact: true });
  const skillButton = page.getByRole("button", { name: "技能创建", exact: true });
  const cards = page.locator('[data-slot="clarification-message"]');
  const config = { schema_version: 3, mode: "generic_chat", model_id: 1, generation_config: { deep_thinking: false }, agent_mounts: [], skill_mounts: [] };
  const runs: Array<Record<string, any>> = [];
  const creationRuns: Array<Record<string, any>> = [];
  const acknowledgements: Array<Record<string, any>> = [];
  let stored: Array<Record<string, any>> = [];
  let mode = "agent_create";
  let failSave = false;
  let nextId = 100;
  const context = () => mode === "agent_create" ? "将长文章整理成带原文出处的中文要点，保留前几轮约定的输出要求。" : "可复用的发票字段提取技能，输出结构化 JSON。";
  const form = () => ({ schema_version: 1, questions: [{ id: "workbench_creation_mode", type: "single_choice", title: mode === "agent_create" ? "是否进入智能体创建模式？" : "是否进入技能创建模式？", required: true, allow_other: false, creation_request: context(), options: [{ id: mode, label: mode === "agent_create" ? "进入智能体创建" : "进入技能创建" }, { id: "continue_chat", label: "继续普通对话" }] }] });
  const json = (data: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
  await page.route("**/api/conversation/91", (route) => route.fulfill(json({ code: 0, data: [{ ...history, message: stored, workbench_config: config, workbench_config_version: 1 }] })));
  await page.route("**/api/agent/run", async (route) => {
    const body = route.request().postDataJSON(); runs.push(body);
    stored.push({ role: "user", message_id: ++nextId, message: body.query, status: "completed", ...(body.clarification_response ? { clarification_response: { ...body.clarification_response, source_message_id: stored.at(-1)?.message_id } } : {}) });
    const assistant = body.clarification_response
      ? [{ type: "final_answer", content: "好的，继续普通对话，不进入创建模式。", unit_index: 7 }]
      : [{ type: "human_interaction", content: JSON.stringify(form()), unit_index: 7 }];
    stored.push({ role: "assistant", message_id: ++nextId, status: "completed", message: assistant });
    await route.fulfill({ status: 200, headers: { conversation_id: "91" }, contentType: "text/event-stream", body: assistant.map((part) => `data: ${JSON.stringify(part)}\n\n`).join("") + 'data: {"type":"complete","content":""}\n\n' });
  });
  await page.route("**/api/conversation/91/creation_mode_responses", async (route) => {
    const body = route.request().postDataJSON();
    if (failSave) return route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ detail: "Save rejected" }) });
    const saved = { ...body, source_message_id: stored.at(-1)?.message_id, unit_index: 7 };
    acknowledgements.push(saved);
    stored.push({ role: "user", message_id: ++nextId, status: "completed", message: "Confirmed creation mode", clarification_response: saved });
    await route.fulfill(json({ code: 0, data: { message_id: nextId, mode: body.answers[0].value, clarification_response: saved } }));
  });
  await page.route("**/api/agent/update", route => route.fulfill(json({ agent_id: 42 })));
  await page.route("**/api/agent/search_info", route => route.fulfill(json({ agent_id: 42, name: "summary-draft", display_name: "Summary draft", permission: "EDIT", model_ids: [1], tools: [] })));
  await page.route("**/api/agent/nl2agent/run", async route => {
    const body = route.request().postDataJSON();
    creationRuns.push(body);
    // Model the deployed pre-target contract rather than accepting any body.
    if (!Number.isInteger(body.agent_id) || body.agent_id <= 0) {
      return route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ detail: [{ loc: ["body", "agent_id"], msg: "Field required" }] }) });
    }
    await route.fulfill({ status: 200, contentType: "text/event-stream", body: 'data: {"type":"final_answer","content":"创建需求已接收，开始生成摘要智能体。"}\n\ndata: {"type":"complete","content":""}\n\n' });
  });
  const submitCard = () => cards.last().getByRole("button", { name: "提交并继续", exact: true }).click();
  const ask = async (text: string) => { await input.fill(text); await input.press("Enter"); await expect(cards.last().getByRole("radio", { name: mode === "agent_create" ? "进入智能体创建" : "进入技能创建", exact: true })).toBeVisible(); };
  const reopen = () => page.goto(`${process.env.NEXENT_BASE_URL}/zh/workbench?conversation_id=91`);
  const openBlankConversations = async () => {
    for (let count = 0; count < 2; count++) {
      await page.getByRole("button", { name: "新对话", exact: true }).click();
      await expect(input).toHaveValue("");
      await expect(agentButton).toHaveAttribute("aria-pressed", "false");
      await expect(skillButton).toHaveAttribute("aria-pressed", "false");
    }
  };
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    await page.getByRole("button").filter({ has: page.getByText("AI creation fixture", { exact: true }) }).click();
    await expect(input).toBeVisible();
  });
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await ask("给我弄个能反复使用的小帮手，整理长文并保留出处。");
    expect(runs).toHaveLength(1);
    expect(runs[0].workbench.mode).toBe("generic_chat");
    expect(acknowledgements).toHaveLength(0);
    await expect(agentButton).toHaveAttribute("aria-pressed", "false");
    await cards.last().getByRole("radio", { name: "继续普通对话", exact: true }).check();
    await submitCard();
    await expect(page.getByText("好的，继续普通对话，不进入创建模式。", { exact: true })).toBeVisible();
    expect(runs).toHaveLength(2);
    expect(runs[1].clarification_response.answers[0].value).toBe("continue_chat");
    await expect(agentButton).toHaveAttribute("aria-pressed", "false");
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await ask("就按刚才的要求做一个");
    await input.fill("Ordinary unsent draft must survive creation");
    await cards.last().getByRole("radio", { name: "进入智能体创建", exact: true }).check();
    await submitCard();
    await expect(agentButton).toHaveAttribute("aria-pressed", "true");
    await expect(input).toHaveValue(new RegExp(context()));
    await expect(input).toHaveValue(/就按刚才的要求做一个/);
    expect(acknowledgements).toHaveLength(1);
    expect(runs).toHaveLength(3);
    await input.fill("Creation-only draft");
    await agentButton.click();
    await expect(input).toHaveValue("Ordinary unsent draft must survive creation");
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await reopen();
    await expect(cards.last().getByRole("button", { name: "已提交", exact: true })).toBeDisabled();
    mode = "skill_create";
    await ask("把发票字段提取整理成可复用的专项能力");
    await cards.last().getByRole("radio", { name: "进入技能创建", exact: true }).check();
    await submitCard();
    await expect(skillButton).toHaveAttribute("aria-pressed", "true");
    await expect(input).toHaveValue(new RegExp(context()));
    expect(acknowledgements).toHaveLength(2);
    expect(runs).toHaveLength(4);
    await openBlankConversations();
    await reopen();
  });
  await contract.step(contract.expectedIds("steps")[3], async () => {
    state.authorization.permissions = ["agent:create"];
    await reopen();
    await ask("再整理一个专项能力");
    await expect(cards.last().getByRole("radio", { name: "进入技能创建", exact: true })).toBeDisabled();
    expect(acknowledgements).toHaveLength(2);
    state.authorization.permissions = ["agent:create", "skill:create"];
    await reopen();
    mode = "agent_create";
    await ask("再给我一个独立使用的小帮手");
    await cards.last().getByRole("radio", { name: "进入智能体创建", exact: true }).check();
    failSave = true;
    await submitCard();
    await expect(cards.last().getByRole("alert")).toBeVisible();
    await expect(agentButton).toHaveAttribute("aria-pressed", "false");
    expect(acknowledgements).toHaveLength(2);
    failSave = false;
    await submitCard();
    await expect(agentButton).toHaveAttribute("aria-pressed", "true");
    expect(acknowledgements).toHaveLength(3);
  });
  await contract.step(contract.expectedIds("steps")[4], openBlankConversations);
  await contract.step(contract.expectedIds("steps")[5], async () => {
    await reopen();
    await ask("按照之前的要求搭建可复用的文章摘要助手");
    await cards.last().getByRole("radio", { name: "进入智能体创建", exact: true }).check();
    await submitCard();
    await expect(agentButton).toHaveAttribute("aria-pressed", "true");
    await expect(input).toHaveValue(new RegExp(context()));
    expect(creationRuns).toHaveLength(0);
    const carried = await input.inputValue();
    await input.press("Enter");
    await expect(page.getByText("创建需求已接收，开始生成摘要智能体。", { exact: true })).toBeVisible();
    expect(creationRuns).toHaveLength(1);
    expect(creationRuns[0]).toMatchObject({ query: carried, agent_id: 42, target: { type: "agent", id: 42 }, persist_history: true, workbench_config: { mode: "agent_create" } });
    await openBlankConversations();
  });
  await contract.assertion(contract.expectedIds("assertions")[0], async () => {
    expect(runs).toHaveLength(7);
    expect(creationRuns).toHaveLength(1);
    expect(state.writes.some((path) => /nl2agent|nl2skill|\/skills$|\/agent\/create$/.test(path))).toBe(false);
  });
  await contract.assertion(contract.expectedIds("assertions")[1], async () => {
    await expect(input).toHaveValue("");
    await expect(agentButton).toHaveAttribute("aria-pressed", "false");
    await expect(skillButton).toHaveAttribute("aria-pressed", "false");
  });
  await contract.assertion(contract.expectedIds("assertions")[2], async () => {
    expect(creationRuns).toHaveLength(1);
    expect(creationRuns[0].agent_id).toBe(creationRuns[0].target.id);
    expect(creationRuns[0].query).toContain("按照之前的要求搭建可复用的文章摘要助手");
  });
});
