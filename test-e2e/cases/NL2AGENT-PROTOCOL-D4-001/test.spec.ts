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
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

journey("NL2AGENT-PROTOCOL-D4-001", async (context) => {
  const { page, expect, contract } = context;
  const agents = new AgentPage(page);
  const ids: number[] = [];
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
  const selectCreatorModel = async () => {
    await page.locator('[data-slot="model-selector-trigger"]').last().click();
    await page
      .locator('[data-slot="model-selector-item"]')
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
    const composer = page
      .locator("textarea:visible, [data-workbench-composer]:visible")
      .last();
    await composer.fill(query);
    await composer.press("Enter");
    const response = await pending;
    expect(response.ok()).toBe(true);
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
        await agents.selectModel(configuredModel("llm").displayName);
        const before = stable(await read(id));
        await page
          .getByRole("button", { name: "智能生成", exact: true })
          .click();
        await selectCreatorModel();
        await policy("direct", id, true);
        expect(stable(await read(id))).toEqual(before);
        await page.reload({ waitUntil: "domcontentloaded" });
        expect((await read(id)).enable_protocol_repair_retry).toBe(true);
        if (
          !(await page
            .getByRole("button", { name: "关闭智能生成", exact: true })
            .isVisible())
        ) {
          await page
            .getByRole("button", { name: "智能生成", exact: true })
            .click();
        }
        await selectCreatorModel();
        await policy("direct", id, false);
        expect(stable(await read(id))).toEqual(before);
        await page.reload({ waitUntil: "domcontentloaded" });
        await agents.openAdvanced();
        const label = page
          .getByText("严格输出协议与静默修复", { exact: true })
          .first();
        await expect(
          label
            .locator('xpath=ancestor::*[.//button[@role="switch"]][1]')
            .getByRole("switch"),
        ).not.toBeChecked();
        return "Direct NL2Agent saves true/false without rewriting other fields; editor reads false after reload.";
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
        await page.reload({ waitUntil: "domcontentloaded" });
        expect((await read(id)).enable_protocol_repair_retry).toBe(true);
        await policy("workbench", id, false);
        expect(stable(await read(id))).toEqual(before);
        await page.reload({ waitUntil: "domcontentloaded" });
        expect((await read(id)).enable_protocol_repair_retry).toBe(false);
        await expect(
          page.getByText("严格输出协议与静默修复", { exact: true }),
        ).toHaveCount(0);
        return "Workbench creation uses the same endpoint and saves target policy without a Workbench switch.";
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
          expect((await read(id)).enable_protocol_repair_retry).toBe(false);
        return "Both target drafts persisted both boolean states and survived reload.";
      },
      async () => {
        expect(ids).toHaveLength(2);
        expect(ids[0]).not.toBe(ids[1]);
        return "Per-step assertions prove unchanged prompt/resources, no full-generation completion, and no session policy.";
      },
    ],
  });
});
