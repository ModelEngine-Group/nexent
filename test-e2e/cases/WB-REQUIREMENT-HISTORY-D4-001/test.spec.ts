// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("WB-REQUIREMENT-HISTORY-D4-001", async ({ page, contract }) => {
  const history = {
    conversation_id: 91,
    conversation_title: "Requirement replay fixture",
    agent_id: 1,
    target: { type: "agent", id: 42 },
    agent_system_key: "nl2agent_main",
    create_time: Date.now(),
    update_time: Date.now(),
  };
  await prepareWorkbench(page, 1, { histories: [history] });
  const mutations: string[] = [];
  const payload = {
    subtype: "requirement_clarification",
    agent_id: 42,
    questions: [
      {
        question_id: "audience",
        question_type: "single_choice",
        title: "Audience?",
        required: true,
        options: [
          { option_id: "team", label: "Internal team" },
          { option_id: "personal", label: "Personal" },
        ],
        allow_other: false,
        other_input_expanded: false,
      },
      {
        question_id: "scope",
        question_type: "multiple_choice",
        title: "Scope?",
        required: true,
        options: [
          { option_id: "text", label: "Text" },
          { option_id: "files", label: "Files" },
        ],
        allow_other: true,
        other_input_expanded: true,
      },
      {
        question_id: "constraints",
        question_type: "text",
        title: "Constraints?",
        required: false,
        options: [],
        allow_other: false,
        other_input_expanded: false,
      },
    ],
  };
  const card = (id: number) => ({
    role: "assistant",
    message_id: id,
    status: "completed",
    message: [{ type: "nl2a", content: JSON.stringify(payload) }],
  });
  const reply = (id: number, value: string) => ({
    role: "user",
    message_id: id,
    status: "completed",
    message: JSON.stringify({
      type: "nl2agent_card_action",
      subtype: "requirement_clarification",
      agent_id: 42,
      action: "submit",
      result: {
        answers: [
          { question_id: "audience", value: "team", other_text: null },
          {
            question_id: "scope",
            value: ["text", "files"],
            other_text: "Pasted text only",
          },
          { question_id: "constraints", value, other_text: null },
        ],
      },
    }),
  });
  const messages = [
    {
      role: "user",
      message_id: 9,
      status: "completed",
      message: "Create an isolated Agent fixture",
    },
    card(10),
    reply(11, "First round constraints"),
    card(12),
    reply(13, "Second round constraints"),
    card(14),
    {
      role: "user",
      message_id: 15,
      status: "completed",
      message: "Legacy reply without structured answers",
    },
    {
      role: "assistant",
      message_id: 16,
      status: "completed",
      message: [{ type: "final_answer", content: "Saved fixture complete" }],
    },
  ];
  const json = (data: unknown) => ({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(data),
  });
  const detail = {
    ...history,
    chat_mode: "execution",
    message: messages,
    workbench_config: {
      schema_version: 3,
      mode: "agent_create",
      agent_id: 42,
      model_id: 1,
      generation_config: { deep_thinking: false },
      agent_mounts: [],
      skill_mounts: [],
    },
    workbench_config_version: 1,
  };
  await page.route("**/api/conversation/91", (route) =>
    route.fulfill(json({ code: 0, data: [detail] })),
  );
  await page.route("**/api/conversation/creator_histories?*", (route) =>
    route.fulfill(json({ code: 0, data: { items: [history], total: 1 } })),
  );
  await page.route("**/api/agent/search_info", (route) =>
    route.fulfill(
      json({
        agent_id: 42,
        name: "requirement_fixture",
        display_name: "Requirement fixture",
        description: "Unpublished isolated fixture",
        permission: "EDIT",
        model_ids: [1],
        model_names: ["Fixture Model"],
        prompt: "Return the given text",
        tools: [],
        max_steps: 3,
        enabled: true,
        is_available: true,
        verification_config: {
          enabled: false,
          step_verification_enabled: true,
          final_verification_enabled: true,
          llm_verification_enabled: true,
          max_final_rounds: 2,
          strictness: "balanced",
          fail_policy: "repair_then_controlled_summary",
          pass_score: 0.75,
          critical_events: [
            "tool_precheck",
            "tool_result",
            "retrieval",
            "code_execution",
            "handoff",
            "final_answer",
          ],
          guardrail_config: {
            enabled: false,
            rules: [],
            default_action: "pass",
          },
        },
      }),
    ),
  );
  await page.route("**/api/tool/list**", (route) => route.fulfill(json([])));
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (
      [
        "/api/agent/run",
        "/api/agent/nl2agent/run",
        "/api/agent/update",
        "/api/agent/update_fields",
        "/api/agent/publish",
      ].includes(path)
    ) {
      mutations.push(path);
      await route.fulfill(json({}));
    } else await route.fallback();
  });
  contract.deferCleanup(async () => {
    await page.close();
  });
  const base = process.env.NEXENT_BASE_URL ?? "http://localhost:3031";
  const cards = page.locator('[data-slot="aui-requirement-clarification"]');
  const verify = async () => {
    await expect(cards).toHaveCount(3);
    for (const [index, text] of [
      "First round constraints",
      "Second round constraints",
    ].entries()) {
      const saved = cards.nth(index);
      await expect(
        saved.getByRole("radio", { name: "Internal team", exact: true }),
      ).toBeChecked();
      await expect(
        saved.getByRole("checkbox", { name: "Text", exact: true }),
      ).toBeChecked();
      await expect(
        saved.getByRole("checkbox", { name: "Files", exact: true }),
      ).toBeChecked();
      await expect(
        saved.getByRole("textbox", { name: "其他", exact: true }),
      ).toHaveValue("Pasted text only");
      await expect(
        saved.getByRole("textbox", { name: "Constraints?", exact: true }),
      ).toHaveValue(text);
      await expect(
        saved.getByRole("button", { name: "已提交", exact: true }),
      ).toBeDisabled();
      await expect(
        saved.getByRole("radio", { name: "Internal team", exact: true }),
      ).toBeDisabled();
    }
    await expect(
      cards.last().getByRole("textbox", { name: "Constraints?", exact: true }),
    ).toHaveValue("");
    await expect(
      cards.last().getByRole("radio", { name: "Internal team", exact: true }),
    ).not.toBeChecked();
    await expect(
      cards.last().getByRole("button", { name: "提交", exact: true }),
    ).toBeDisabled();
  };
  const openEditor = async () => {
    await page.goto(`${base}/zh/agents/42`);
    const panel = page.getByTestId("agent-config-conversation-panel");
    await expect(
      page.getByRole("textbox", { name: "* 智能体变量名", exact: true }),
    ).toHaveValue("requirement_fixture");
    if (!(await panel.isVisible()))
      await page.getByRole("button", { name: "智能生成", exact: true }).click();
    await expect(panel).toBeVisible();
    await panel.getByRole("button", { name: /^历史/ }).click();
    await page
      .getByRole("button", { name: /Requirement replay fixture/ })
      .click();
    await verify();
  };
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await page.goto(`${base}/zh/workbench?conversation_id=91`);
      await expect(cards).toHaveCount(3);
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await verify();
    await page.reload();
    await verify();
    await cards.first().scrollIntoViewIfNeeded();
    await page.screenshot({
      path: join(contract.caseDir, "workbench-restored.png"),
    });
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await openEditor();
    await openEditor();
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await verify();
    const checked = cards
      .first()
      .getByRole("radio", { name: "Internal team", exact: true });
    await expect(checked.click({ timeout: 1000 })).rejects.toThrow();
    await expect(checked).toBeChecked();
    expect(mutations).toEqual([]);
    await cards.first().scrollIntoViewIfNeeded();
    await page.screenshot({
      path: join(contract.caseDir, "editor-restored.png"),
    });
  });
  for (const id of contract.expectedIds("assertions"))
    await contract.assertion(id, async () => {
      await verify();
      expect(mutations).toEqual([]);
    });
});
