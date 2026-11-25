// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";
import { makeDraft } from "../../infra/automation/d4/fixtures/agent-editor-reads.mjs";

journey("NL2A-PROMPT-D4-001", async ({ page, contract, expect }) => {
  await page.setViewportSize({ width: 1800, height: 1000 });
  await page.context().addCookies([
    {
      name: "nexent_token_expires_at",
      value: String(Math.floor(Date.now() / 1000) + 3600),
      url: process.env.NEXENT_BASE_URL!,
    },
  ]);
  await page.addInitScript(() =>
    localStorage.setItem(
      "user_info",
      JSON.stringify({
        id: "workbench-fixture",
        role: "DEV",
        roles: ["DEV"],
        tenant_id: "workbench-tenant",
      }),
    ),
  );
  await prepareWorkbench(page);
  const draft = {
    ...makeDraft(),
    model_ids: [1],
    model_names: ["Fixture Model"],
  };
  const original = draft.prompt;
  const longText =
    "职责：保留全部原有约束。\n" +
    "提供可核验结果并注明不确定性。\n".repeat(50) +
    "全文结束标识";
  const editedText = longText + "\n用户编辑：保留约束，增加引用来源。";
  let card = {
    subtype: "prompt_generation",
    agent_id: 42,
    conversation_id: "601",
    run_id: "fixture-run",
    card_id: "prompt-1",
    prompt_revision: "revision-1",
    proposed_prompt: longText,
    status: "pending",
  };
  let olderCard: typeof card | undefined;
  const actions: any[] = [];
  const writes: string[] = [];
  const history = {
    conversation_id: 601,
    conversation_title: "Prompt confirmation history",
    agent_system_key: "nl2agent_main",
    target: { type: "agent", id: 42 },
    create_time: 1700000000000,
    update_time: 1700000000000,
  };
  const json = (body: unknown) => ({
    contentType: "application/json",
    body: JSON.stringify(body),
  });
  const frame = (value: unknown) => `data: ${JSON.stringify(value)}\n\n`;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/user/current_user_info")
      return route.fulfill(
        json({
          data: {
            user: {
              user_id: "workbench-fixture",
              tenant_id: "workbench-tenant",
              user_role: "DEV",
              roles: ["DEV"],
              user_email: "fixture@nexent.test",
              permissions: ["agent:create", "skill:create"],
              accessibleRoutes: ["/agents", "/workbench", "/newchat"],
            },
          },
        }),
      );
    if (path === "/api/agent/search_info") return route.fulfill(json(draft));
    if (path === "/api/conversation/creator_histories")
      return route.fulfill(
        json({ code: 0, data: { items: [history], total: 1 } }),
      );
    if (path === "/api/conversation/601")
      return route.fulfill(
        json({
          code: 0,
          data: [
            {
              ...history,
              workbench_config: { schema_version: 4, mode: "agent_create" },
              message: [
                ...(olderCard
                  ? [
                      {
                        role: "assistant",
                        message_id: 10,
                        message: [
                          { type: "nl2a", content: JSON.stringify(olderCard) },
                        ],
                      },
                      {
                        role: "user",
                        message_id: 12,
                        message: [
                          { type: "text", content: "调整待确认的提示词" },
                        ],
                      },
                    ]
                  : []),
                {
                  role: "assistant",
                  message_id: 11,
                  message: [{ type: "nl2a", content: JSON.stringify(card) }],
                },
              ],
            },
          ],
        }),
      );
    if (path === "/api/agent/nl2agent/run") {
      const request = route.request().postDataJSON();
      const action = JSON.parse(request.query);
      actions.push(action);
      expect(action.result).toEqual({
        card_id: card.card_id,
        prompt_revision: card.prompt_revision,
        ...(action.action === "apply" ? { prompt: editedText } : {}),
      });
      expect(action.agent_id).toBe(42);
      expect(action.subtype).toBe("prompt_generation");
      const apply = action.action === "apply";
      if (apply && actions.length === 1) return route.fulfill({
        contentType: "text/event-stream",
        headers: { conversation_id: "601" },
        body: frame({ type: "error", content: "Prompt revision conflict" }),
      });
      if (apply) draft.prompt = action.result.prompt;
      card = { ...card, proposed_prompt: apply ? action.result.prompt : card.proposed_prompt,
        status: apply ? "applied" : "cancelled" };
      const saved = {
        type: "nl2a_state",
        content: JSON.stringify({
          event: "agent_draft_fields_saved",
          agent_id: 42,
          updated_fields: ["prompt"],
        }),
      };
      return route.fulfill({
        contentType: "text/event-stream",
        headers: { conversation_id: "601" },
        body:
          (apply ? frame(saved) : "") +
          frame({ type: "nl2a", content: JSON.stringify(card) }),
      });
    }
    if (
      /\/agent\/(update|update_fields|publish)$/.test(path) ||
      path === "/api/tool/update"
    )
      writes.push(path);
    return route.fallback();
  });
  contract.deferCleanup(async () => {
    await page.close();
  });
  const panel = page.getByTestId("agent-config-conversation-panel");
  const preview = panel.getByTestId("prompt-generation").last();
  const openHistory = async () => {
    await expect(panel).toBeVisible();
    await panel.getByRole("button", { name: /^历史/ }).click();
    await page
      .getByRole("button", { name: /Prompt confirmation history/ })
      .click();
    await expect(preview).toBeVisible();
  };
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await page.goto(`${process.env.NEXENT_BASE_URL}/zh/agents/42`);
      await openHistory();
    },
  );
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await expect(preview).toContainText("提示词生成");
    await preview.getByRole("button", { name: "展开全文" }).click();
    await expect(preview.locator("pre")).toHaveText(longText);
    await expect(preview).toContainText("全文结束标识");
    const input = panel
      .locator("[data-workbench-composer]:visible, .aui-lexical-input:visible")
      .first();
    await expect(input).toBeEditable();
    expect(actions).toEqual([]);
    expect(draft.prompt).toBe(original);
    await panel.evaluate((node) => {
      node.style.width = "360px";
    });
    expect(
      await preview.evaluate(
        (node) => node.scrollWidth <= node.clientWidth + 1,
      ),
    ).toBe(true);
    await page.screenshot({
      path: join(contract.caseDir, "prompt-preview-narrow.png"),
    });
    await panel.evaluate((node) => {
      node.style.width = "";
    });
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await preview.getByRole("button", { name: "编辑", exact: true }).click();
    const editor = preview.getByRole("textbox", { name: "提示词内容" });
    await expect(editor).toHaveValue(longText);
    await editor.fill(editedText);
    await page.screenshot({ path: join(contract.caseDir, "prompt-editor.png") });
    expect(actions).toHaveLength(0);
    expect(draft.prompt).toBe(original);
    await preview.getByRole("button", { name: "预览", exact: true }).click();
    await expect(preview.locator("pre")).toHaveText(editedText);
    await preview.getByRole("button", { name: "确认应用" }).click();
    await expect(preview.getByRole("alert")).toBeVisible();
    await expect(preview).not.toContainText("已应用");
    expect(draft.prompt).toBe(original);
    await preview.getByRole("button", { name: "编辑", exact: true }).click();
    await expect(preview.getByRole("textbox", { name: "提示词内容" })).toHaveValue(editedText);
    await expect(preview.getByRole("button", { name: "确认应用" })).toBeEnabled();
    await preview.getByRole("button", { name: "确认应用" }).click();
    await expect(preview).toContainText("已应用");
    expect(actions.map((action) => action.action)).toEqual(["apply", "apply"]);
    expect(draft.prompt).toBe(editedText);
    await page.reload();
    await openHistory();
    await expect(preview).toContainText("已应用");
    await expect(preview.locator("pre")).toHaveText(editedText);
    await expect(preview.getByRole("button", { name: "确认应用" })).toHaveCount(
      0,
    );
    expect(actions).toHaveLength(2);
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    olderCard = { ...card, card_id: "superseded-prompt", status: "pending" };
    card = {
      ...card,
      card_id: "prompt-2",
      prompt_revision: "revision-2",
      proposed_prompt: "这次修改应被取消",
      status: "pending",
    };
    await page.reload();
    await openHistory();
    await expect(panel.getByTestId("prompt-generation")).toHaveCount(2);
    await expect(
      panel
        .getByTestId("prompt-generation")
        .first()
        .getByRole("button", { name: "确认应用" }),
    ).toBeDisabled();
    await preview.getByRole("button", { name: "编辑", exact: true }).click();
    await preview.getByRole("textbox", { name: "提示词内容" }).fill("取消时不应保存用户编辑");
    await preview.getByRole("button", { name: "取消", exact: true }).click();
    await expect(preview).toContainText("已取消");
    expect(draft.prompt).toBe(editedText);
    await page.reload();
    await openHistory();
    await expect(preview).toContainText("已取消");
    await expect(preview.getByRole("button", { name: "确认应用" })).toHaveCount(
      0,
    );
    expect(actions.map((action) => action.action)).toEqual(["apply", "apply", "cancel"]);
  });
  const assertions = contract.expectedIds("assertions");
  await contract.assertion(assertions[0], async () => {
    expect(longText.includes("\n")).toBe(true);
    await expect(preview).toBeVisible();
  });
  await contract.assertion(assertions[1], async () => {
    expect(
      actions.every(
        (action) =>
          Object.keys(action.result).sort().join(",") ===
          (action.action === "apply" ? "card_id,prompt,prompt_revision" : "card_id,prompt_revision"),
      ),
    ).toBe(true);
    expect(writes).toEqual([]);
  });
  await contract.assertion(assertions[2], async () => {
    expect(actions).toHaveLength(3);
    await expect(preview.getByRole("button", { name: "确认应用" })).toHaveCount(
      0,
    );
  });
});
