// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { appendFileSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import {
  appPath,
  configuredModel,
  runToken,
} from "../../infra/automation/d4/runner/runtime-config";
import {
  loginCurrent,
  loginIsolated,
} from "../../infra/automation/d4/runner/sessions";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

journey("NL2AGENT-PROTOCOL-D4-001", async (context) => {
  const { page, expect, contract } = context;
  const agents = new AgentPage(page);
  const ids: number[] = [];
  const generatedIds: number[] = [];
  let workbenchConversationId = "";
  let fixtureModelId = 0;
  const runtimeChecked: number[] = [];
  const observations: Array<{
    entry: string;
    enabled: boolean;
    agentId: number;
  }> = [];
  const token = runToken("NL2AGENT-PROTOCOL-D4-001");
  contract.deferCleanup(async () => {
    for (const id of ids) await agents.delete(id);
  });
  const read = async (id: number) => {
    const response = await page.request.post("/api/agent/search_info", {
      data: { agent_id: id, version_no: 0 },
    });
    expect(response.ok()).toBe(true);
    const body = await response.json();
    return body.data || body;
  };
  const stable = (draft: Record<string, unknown>) =>
    Object.fromEntries(
      [
        "description",
        "duty_prompt",
        "greeting_message",
        "example_questions",
        "tools",
        "skill_instances",
      ].map((key) => [key, draft[key]]),
    );
  const dismissGuide = async () => {
    const skip = page.getByRole("button", { name: "全部跳过", exact: true });
    await skip
      .waitFor({ state: "visible", timeout: 5000 })
      .catch(() => undefined);
    if (await skip.isVisible()) await skip.click();
  };
  const configureTargetModel = async (id: number) => {
    const response = await page.request.get("/api/model/list");
    expect(response.ok()).toBe(true);
    const body = await response.json();
    const rows = Array.isArray(body) ? body : body.data;
    const model = rows.find(
      (item: { display_name?: string; model_name?: string }) =>
        item.display_name === configuredModel("llm").displayName ||
        item.model_name === configuredModel("llm").model,
    );
    expect(model).toBeTruthy();
    fixtureModelId = Number(model.model_id);
    const saved = await page.request.post("/api/agent/update", {
      data: { agent_id: id, model_ids: [model.model_id] },
    });
    expect(saved.ok()).toBe(true);
    await page.reload({ waitUntil: "domcontentloaded" });
    await dismissGuide();
  };
  const ensureDirectCreator = async () => {
    await page
      .getByTestId("agent-config-conversation-panel")
      .waitFor({ state: "attached" });
    await dismissGuide();
    if (
      !(await page.getByTestId("agent-config-conversation-panel").isVisible())
    ) {
      await page.getByRole("button", { name: "智能生成", exact: true }).click();
    }
  };
  const selectCreatorModel = async () => {
    await page
      .locator('[data-slot="model-selector-trigger"]:visible')
      .last()
      .click();
    await page
      .locator('[data-slot="model-selector-item"]:visible')
      .filter({ hasText: configuredModel("llm").displayName })
      .click();
  };
  const policy = async (
    entry: string,
    id: number,
    enabled: boolean,
    prefix = "",
  ) => {
    const query = `${prefix}本轮只${enabled ? "开启" : "关闭"}目标智能体的严格输出协议与静默修复（严格协议与重试，enable_protocol_repair_retry=${enabled}），不要生成或修改描述、提示词、欢迎语、推荐问题或资源；保存成功后确认。`;
    const pending = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname.endsWith("/agent/nl2agent/run"),
    );
    const composer = page.getByRole("textbox", {
      name: "对话输入",
      exact: true,
    });
    await composer.fill(query);
    await composer.press("Enter");
    const response = await pending;
    expect(response.ok()).toBe(true);
    if (entry === "workbench") {
      workbenchConversationId = response.headers()["conversation_id"];
      expect(Number(workbenchConversationId)).toBeGreaterThan(0);
    }
    const request = response.request().postDataJSON();
    const agentId = Number(request.agent_id);
    if (id) expect(agentId).toBe(id);
    else if (!ids.includes(agentId)) ids.push(agentId);
    expect(request.workbench_config ?? {}).not.toHaveProperty(
      "execution_config",
    );
    const stream = await response.text();
    expect(stream).toContain("agent_draft_fields_saved");
    expect(stream).toContain("enable_protocol_repair_retry");
    expect(stream).not.toContain("agent_generation_completed");
    await expect
      .poll(async () => (await read(agentId)).enable_protocol_repair_retry, {
        timeout: 120_000,
      })
      .toBe(enabled);
    observations.push({ entry, enabled, agentId });
    appendFileSync(
      join(contract.caseDir, "creator-runs.jsonl"),
      `${JSON.stringify({ entry, enabled, agentId, runId: response.headers()["run_id"], conversationId: response.headers()["conversation_id"] })}\n`,
    );
    return agentId;
  };
  const assertPolicyUI = async (enabled: boolean, screenshot?: string) => {
    await agents.openAdvanced();
    await page.getByRole("button", { name: "更多配置", exact: true }).click();
    const dialog = page.getByRole("dialog", { name: "更多配置", exact: true });
    const control = dialog
      .locator(".ant-form-item")
      .filter({ hasText: "严格输出协议与静默修复" })
      .getByRole("switch");
    if (enabled) await expect(control).toBeChecked();
    else await expect(control).not.toBeChecked();
    if (screenshot)
      await page.screenshot({ path: join(contract.caseDir, screenshot) });
    await dialog.locator(".ant-modal-close").click();
  };
  const fullGeneration = async (id: number) => {
    const send = async (action: () => Promise<unknown>) => {
      const pending = page.waitForResponse(
        (response) =>
          response.request().method() === "POST" &&
          new URL(response.url()).pathname.endsWith("/agent/nl2agent/run"),
      );
      await action();
      const response = await pending;
      expect(response.ok()).toBe(true);
      expect(Number(response.request().postDataJSON().agent_id)).toBe(id);
      return response.text();
    };
    let stream = await send(async () => {
      const input = page.getByRole("textbox", {
        name: "对话输入",
        exact: true,
      });
      await input.fill(
        "请完整生成当前中文格式整理助手，同时开启严格输出协议与静默修复。服务普通办公用户，仅将用户提供的文本整理成中文分点列表，保留原意，不添加事实。无需任何工具、Skill、知识库或外部资源。请按完整生成流程澄清并保存全部配置。",
      );
      await input.press("Enter");
    });
    expect(stream).toContain("requirement_clarification");
    expect((await read(id)).enable_protocol_repair_retry).toBe(true);
    for (
      let round = 0;
      round < 3 && !stream.includes("agent_generation_completed");
      round++
    ) {
      const card = page
        .locator("[data-slot='aui-requirement-clarification']")
        .last();
      await expect(card).toBeVisible();
      const fields = card.locator("fieldset");
      for (let index = 0; index < (await fields.count()); index++) {
        const field = fields.nth(index);
        const text = field.locator("textarea");
        for (let n = 0; n < (await text.count()); n++)
          await text
            .nth(n)
            .fill(
              "普通办公用户；中文分点列表；只整理用户原文，保留原意，不添加事实；无需任何工具、Skill、知识库或外部资源。",
            );
        const radio = field.getByRole("radio");
        if (await radio.count()) await radio.first().check();
        const checks = field.getByRole("checkbox");
        if (await checks.count()) await checks.first().check();
      }
      stream = await send(() =>
        card.getByRole("button", { name: "提交", exact: true }).click(),
      );
      expect((await read(id)).enable_protocol_repair_retry).toBe(true);
    }
    expect(stream).toContain("agent_generation_completed");
    const draft = await read(id);
    expect(draft.duty_prompt.trim().length).toBeGreaterThan(0);
    expect(draft.enable_protocol_repair_retry).toBe(true);
    generatedIds.push(id);
  };
  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        configuredModel("llm");
        await loginCurrent(page, "tenant_a_admin");
        return "Authenticated creator with a configured real model; Langfuse trace review is recorded separately.";
      },
    ],
    steps: [
      async () => {
        await agents.open();
        const id = await agents.create(
          `Protocol ${token}`,
          `proto_${token}_assistant`,
        );
        ids.push(id);
        await configureTargetModel(id);
        const before = stable(await read(id));
        await ensureDirectCreator();
        await selectCreatorModel();
        await policy("direct", id, true);
        expect(stable(await read(id))).toEqual(before);
        await page.reload({ waitUntil: "domcontentloaded" });
        await dismissGuide();
        expect((await read(id)).enable_protocol_repair_retry).toBe(true);
        await ensureDirectCreator();
        await selectCreatorModel();
        await policy("direct", id, false);
        expect(stable(await read(id))).toEqual(before);
        await page.reload({ waitUntil: "domcontentloaded" });
        await dismissGuide();
        await assertPolicyUI(false);
        await ensureDirectCreator();
        await selectCreatorModel();
        await fullGeneration(id);
        await page.reload({ waitUntil: "domcontentloaded" });
        await dismissGuide();
        await assertPolicyUI(true, "direct-policy-enabled.png");
        return "Direct creator saves both boolean values; full generation preserves enabled policy across clarification.";
      },
      async () => {
        await page.goto(appPath("/workbench"), {
          waitUntil: "domcontentloaded",
        });
        await page
          .getByRole("button", { name: "智能体创建", exact: true })
          .click();
        await selectCreatorModel();
        const id = await policy(
          "workbench",
          0,
          true,
          "当前创建目标为中文格式整理助手，显示名为格式助手。按既有规则初始化名称后，",
        );
        const initialDraft = await read(id);
        expect(initialDraft.description ?? "").toBe("");
        expect(initialDraft.duty_prompt ?? "").toBe("");
        expect(initialDraft.greeting_message ?? "").toBe("");
        expect(initialDraft.example_questions ?? []).toEqual([]);
        const before = stable(initialDraft);
        await page.goto(
          appPath(`/workbench?conversation_id=${workbenchConversationId}`),
          { waitUntil: "domcontentloaded" },
        );
        expect((await read(id)).enable_protocol_repair_retry).toBe(true);
        await policy("workbench", id, false);
        expect(stable(await read(id))).toEqual(before);
        await page.goto(
          appPath(`/workbench?conversation_id=${workbenchConversationId}`),
          { waitUntil: "domcontentloaded" },
        );
        expect((await read(id)).enable_protocol_repair_retry).toBe(false);
        await expect(
          page.getByText("严格输出协议与静默修复", { exact: true }),
        ).toHaveCount(0);
        await fullGeneration(id);
        await page.goto(
          appPath(`/workbench?conversation_id=${workbenchConversationId}`),
          { waitUntil: "domcontentloaded" },
        );
        expect((await read(id)).enable_protocol_repair_retry).toBe(true);
        await page.screenshot({
          path: join(contract.caseDir, "workbench-creation-complete.png"),
        });
        await page.goto(appPath(`/agents/${id}`), {
          waitUntil: "domcontentloaded",
        });
        await dismissGuide();
        await assertPolicyUI(true, "workbench-created-policy-enabled.png");
        return "Workbench uses the shared chain; full generation preserves enabled target policy without a session switch.";
      },
      async () => {
        for (const id of ids) {
          const unclear = await page.request.post("/api/agent/nl2agent/run", {
            data: {
              agent_id: id,
              model_id: fixtureModelId,
              query: "只关闭重试，不更改其他配置。",
            },
            timeout: 180000,
          });
          expect(unclear.ok()).toBe(true);
          const clarification = await unclear.text();
          const clarificationEvents = clarification
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => {
              const value = JSON.parse(line.slice(5).trim());
              return typeof value === "string" ? JSON.parse(value) : value;
            });
          appendFileSync(
            join(contract.caseDir, "ambiguity-runs.jsonl"),
            JSON.stringify({
              agentId: id,
              eventTypes: [
                ...new Set(clarificationEvents.map((event) => event.type)),
              ],
              policyToolCalls: clarificationEvents
                .filter((event) => event.type === "tool")
                .map((event) => ({
                  name: event.tool_name,
                  arguments: event.tool_arguments,
                })),
            }) + "\n",
          );
          expect(clarification).toContain("requirement_clarification");
          expect(clarification).not.toContain("agent_draft_fields_saved");
          expect((await read(id)).enable_protocol_repair_retry).toBe(true);
          const draft = await read(id);
          if (!draft.model_ids?.length) {
            const configured = await page.request.post("/api/agent/update", {
              data: { agent_id: id, model_ids: [fixtureModelId] },
            });
            expect(configured.ok()).toBe(true);
          }
          const response = await page.request.post("/api/agent/run", {
            data: {
              agent_id: id,
              version_no: 0,
              is_debug: true,
              query: "请把这三个词逐项列出：苹果、香蕉、梨。只整理原文。",
            },
            timeout: 180000,
          });
          expect(response.ok()).toBe(true);
          const events = (await response.text())
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => JSON.parse(line.slice(5).trim()));
          expect(events.some((event) => event.type === "error")).toBe(false);
          const final = events
            .filter((event) => event.type === "final_answer")
            .map((event) => String(event.content))
            .join("\n");
          for (const word of ["苹果", "香蕉", "梨"])
            expect(final).toContain(word);
          expect((await read(id)).enable_protocol_repair_retry).toBe(true);
          runtimeChecked.push(id);
          appendFileSync(
            join(contract.caseDir, "target-runs.jsonl"),
            `${JSON.stringify({ agentId: id, conversationId: response.headers()["conversation_id"], result: "formatted-three-words", enabled: true })}\n`,
          );
        }
        const other = await loginIsolated(page, "tenant_b_admin");
        try {
          const denied = await other.page.request.post(
            "/api/agent/nl2agent/run",
            { data: { agent_id: ids[0], query: "关闭严格协议与重试。" } },
          );
          expect(denied.status()).toBe(404);
        } finally {
          await other.context.close();
        }
        for (const id of ids)
          expect((await read(id)).enable_protocol_repair_retry).toBe(true);
        return "Both real target runs succeed; ambiguous retry and cross-tenant attempts preserve the saved policy.";
      },
    ],
    assertions: [
      async () => {
        expect(
          observations.map(({ entry, enabled }) => [entry, enabled]),
        ).toEqual([
          ["direct", true],
          ["direct", false],
          ["workbench", true],
          ["workbench", false],
        ]);
        for (const id of ids)
          expect((await read(id)).enable_protocol_repair_retry).toBe(true);
        return "Both target drafts persisted both boolean states and survived reload.";
      },
      async () => {
        expect(ids).toHaveLength(2);
        expect(ids[0]).not.toBe(ids[1]);
        return "Partial-save assertions prove unchanged prompt/resources, no false generation completion, and no session policy.";
      },
      async () => {
        expect(generatedIds).toEqual(ids);
        for (const id of generatedIds)
          expect((await read(id)).enable_protocol_repair_retry).toBe(true);
        return "Both complete generation flows preserve the requested policy through clarification and completion.";
      },
      async () => {
        expect(runtimeChecked).toEqual(ids);
        return "Runtime outputs, ambiguity and cross-tenant rejection were asserted for the generated drafts.";
      },
    ],
  });
});
