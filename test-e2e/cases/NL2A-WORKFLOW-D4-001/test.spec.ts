// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";
import { makeDraft } from "../../infra/automation/d4/fixtures/agent-editor-reads.mjs";

journey("NL2A-WORKFLOW-D4-001", async ({ page, contract, expect }) => {
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
  const writes: string[] = [];
  let installationStatusReads = 0;
  let knowledgeChoice: boolean[] = [];
  const requests: Record<string, unknown>[] = [];
  const draft = {
    ...makeDraft(),
    description: "",
    model_ids: [1],
    model_names: ["Fixture Model"],
  };
  const history = {
    conversation_id: 601,
    conversation_title: "Workflow history",
    agent_system_key: "nl2agent_main",
    target: { type: "agent", id: 42 },
    create_time: 1700000000000,
    update_time: 1700000000000,
  };
  const json = (value: unknown) => ({
    contentType: "application/json",
    body: JSON.stringify(value),
  });
  const state = (stage: string, sequence: number, run_id = "fixture-run") => ({
    type: "nl2a_state",
    content: JSON.stringify({
      event: "resource_retrieval_progress",
      agent_id: 42,
      run_id,
      sequence,
      stage,
    }),
  });
  const knowledgeResources = ["datamate_search", "knowledge_base_search"].map(
    (name, index) => ({
      candidate: {
        candidate_ref: `tool:${201 + index}`,
        resource_type: "tool",
        source: "LOCAL_TOOL",
        name,
        description: "Search authorized knowledge documents",
        requirement_ids: ["r1"],
        score: index === 0 ? 0.99 : 0.2,
      },
      recommendation: index === 0 ? "recommended" : "optional",
      is_bound: false,
      form_kind: "TOOL_CONFIG",
      config: [],
      has_config: true,
    }),
  );
  const card = (subtype: string) => ({
    type: "nl2a",
    tool_name: "nl2a_show_resource_card",
    content: JSON.stringify({
      subtype,
      agent_id: 42,
      protocol_version: 2,
      run_id: "fixture-run",
      conversation_id: "601",
      card_id: `card-${subtype}`,
      state_version: 1,
      requirements: [
        {
          requirement_id: "r1",
          query: "联网搜索",
          required: true,
          coverage_status:
            subtype === "installed_resource_binding" ? "covered" : "uncovered",
          covered_resources:
            subtype === "installed_resource_binding"
              ? knowledgeResources.map((item) => item.candidate)
              : [],
          installable_resources: [],
        },
      ],
      ...(subtype === "installed_resource_binding"
        ? { resources: knowledgeResources }
        : {}),
    }),
  });
  const historicalCoverage = {
    ...card("requirement_coverage"),
    content: JSON.stringify({
      ...JSON.parse(card("requirement_coverage").content),
      card_id: "historical-installation-card",
      requirements: [
        {
          requirement_id: "old-tickets",
          query: "历史车票查询",
          required: true,
          coverage_status: "installable",
          covered_resources: [],
          installable_resources: [
            {
              candidate_ref: "tenant_mcp_repository:3",
              resource_type: "mcp_server",
              name: "历史票务服务",
              installation_status: "disabled",
            },
          ],
        },
      ],
    }),
  };
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (
      path === "/api/mcp/list" &&
      new URL(route.request().url()).searchParams.get(
        "installation_status_only",
      ) === "true"
    ) {
      installationStatusReads += 1;
      return route.fulfill(
        json({ remote_mcp_server_list: [{ market_id: 3, enabled: true }] }),
      );
    }
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
    if (path === "/api/tool/list")
      return route.fulfill(
        json(
          knowledgeResources.map((item) => ({
            tool_id: Number(item.candidate.candidate_ref.split(":")[1]),
            name: item.candidate.name,
            source: "local",
            is_available: true,
            params: [],
            inputs: {},
          })),
        ),
      );
    if (path === "/api/indices/health")
      return route.fulfill(json({ status: "healthy" }));
    if (path === "/api/indices")
      return route.fulfill(json({ indices: [], indices_info: [] }));
    if (path === "/api/datamate/sync_datamate_knowledges")
      return route.fulfill(
        json({ indices: [], indices_info: [], created_records: [] }),
      );
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
                {
                  role: "assistant",
                  message_id: 10,
                  message: [historicalCoverage],
                },
                {
                  role: "user",
                  message_id: 11,
                  message: [{ type: "text", content: "继续补充联网搜索能力" }],
                },
                {
                  role: "assistant",
                  message_id: 12,
                  message: [
                    state("searching_text", 1),
                    state("verifying_capabilities", 2),
                    {
                      type: "final_answer",
                      content: "历史需求说明。\n\n".repeat(80),
                    },
                    card("requirement_coverage"),
                  ],
                },
              ],
            },
          ],
        }),
      );
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
  const header = page.getByTestId("nl2agent-workflow-progress");
  const installTransport = () =>
    page.evaluate(() => {
      const original = window.fetch.bind(window);
      const fixture = {
        controller: null as ReadableStreamDefaultController<Uint8Array> | null,
        requests: [] as unknown[],
        emit(frame: unknown) {
          this.controller!.enqueue(
            new TextEncoder().encode(`data: ${JSON.stringify(frame)}\n\n`),
          );
        },
        end() {
          this.controller!.close();
          this.controller = null;
        },
      };
      (window as any).__workflow = fixture;
      window.fetch = async (...args) => {
        const url = String(args[0] instanceof Request ? args[0].url : args[0]);
        if (!url.includes("/agent/nl2agent/run")) return original(...args);
        fixture.requests.push(JSON.parse(String(args[1]?.body)));
        return new Response(
          new ReadableStream({
            start(controller) {
              fixture.controller = controller;
            },
          }),
          {
            headers: {
              "Content-Type": "text/event-stream",
              conversation_id: "601",
            },
          },
        );
      };
    });
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      await page.goto(`${process.env.NEXENT_BASE_URL}/zh/agents/42`);
      await expect(panel).toBeVisible();
      await expect(header).toHaveCount(0);
      await installTransport();
    },
  );
  const emit = (frame: unknown) =>
    page.evaluate((value) => (window as any).__workflow.emit(value), frame);
  const end = () => page.evaluate(() => (window as any).__workflow.end());
  const send = async (text: string) => {
    const input = panel
      .locator("[data-workbench-composer]:visible, .aui-lexical-input:visible")
      .first();
    await input.fill(text);
    await input.press("Enter");
    await expect
      .poll(() =>
        page.evaluate(() => Boolean((window as any).__workflow.controller)),
      )
      .toBe(true);
  };
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await send("创建一个联网调研助手");
    await emit({ type: "final_answer", content: "所有步骤都已经完成。" });
    await emit({
      type: "nl2a_state",
      content: JSON.stringify({
        event: "agent_generation_completed",
        agent_id: 99,
      }),
    });
    await expect(header).toHaveCount(0);
    await emit(state("searching_text", 1));
    await expect(header).toContainText("模糊匹配");
    await expect(header).not.toContainText("语义匹配暂不可用");
    await emit(state("verifying_capabilities", 2));
    await emit(card("requirement_coverage"));
    await end();
    await expect(header).toHaveAttribute("data-state", "waiting");
    await expect(header).toHaveAttribute("data-step", "coverage");
    await expect(header.getByTestId("nl2agent-workflow-spinner")).toHaveCount(
      0,
    );
    await page.screenshot({
      path: join(contract.caseDir, "coverage-fuzzy.png"),
    });
    await header.screenshot({
      path: join(contract.caseDir, "workflow-header.png"),
    });
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await send("再查找可用工具");
    await emit(state("searching_hybrid", 1, "hybrid-run"));
    await emit(state("preparing_embeddings", 2, "hybrid-run"));
    await expect(header).toContainText("语义 + 模糊");
    await expect(header.getByTestId("nl2agent-workflow-spinner")).toHaveCount(
      1,
    );
    await emit(state("computing_similarity", 3, "hybrid-run"));
    await emit(state("verifying_capabilities", 4, "hybrid-run"));
    await emit(card("installed_resource_binding"));
    await end();
    await expect(header).toHaveAttribute("data-step", "binding");
    await expect(header).toHaveAttribute("data-state", "waiting");
    const native = panel.locator('[data-resource-ref="tool:202"]');
    const alternative = panel.locator('[data-resource-ref="tool:201"]');
    await expect(native).toBeVisible();
    await expect(alternative).toBeVisible();
    expect((await alternative.boundingBox())!.y).toBeLessThan(
      (await native.boundingBox())!.y,
    );
    await expect(native.getByRole("checkbox")).not.toBeChecked();
    await expect(alternative.getByRole("checkbox")).toBeChecked();
    knowledgeChoice.push(
      await native.getByRole("checkbox").isChecked(),
      await alternative.getByRole("checkbox").isChecked(),
    );
    await alternative.getByRole("checkbox").uncheck();
    await native.getByRole("checkbox").check();
    await expect(native.getByRole("checkbox")).toBeChecked();
    await expect(alternative.getByRole("checkbox")).not.toBeChecked();
    knowledgeChoice.push(
      await native.getByRole("checkbox").isChecked(),
      await alternative.getByRole("checkbox").isChecked(),
    );
    expect(writes).toEqual([]);
    await panel
      .getByRole("button", { name: "返回需求确认", exact: true })
      .click();
    await expect
      .poll(() =>
        page.evaluate(() => Boolean((window as any).__workflow.controller)),
      )
      .toBe(true);
    await emit(card("requirement_clarification"));
    await end();
    await expect(header).toHaveAttribute("data-step", "requirements");
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await send("生成提示词");
    await emit({
      type: "nl2a_state",
      content: JSON.stringify({
        event: "agent_draft_fields_saved",
        agent_id: 42,
        updated_fields: ["prompt"],
      }),
    });
    await expect(header).toHaveAttribute("data-step", "generation");
    await expect(header).not.toHaveAttribute("data-state", "completed");
    await emit({
      type: "nl2a_state",
      content: JSON.stringify({
        event: "prompt_generation_failed",
        agent_id: 42,
        failed_fields: ["greeting_message"],
      }),
    });
    await end();
    await expect(header).toHaveAttribute("data-state", "error");
    await send("重试生成");
    await emit({
      type: "nl2a_state",
      content: JSON.stringify({
        event: "agent_generation_completed",
        agent_id: 42,
      }),
    });
    await end();
    await expect(header).toHaveAttribute("data-state", "completed");
  });
  await contract.step(contract.expectedIds("steps")[3], async () => {
    requests.push(
      ...(await page.evaluate(() => (window as any).__workflow.requests)),
    );
    draft.description = "Description saved before leaving creation";
    await page.reload();
    await expect(panel).toBeVisible();
    await expect(header).toHaveCount(0);
    await installTransport();
    await panel.getByRole("button", { name: /^历史/ }).click();
    await page.getByRole("button", { name: /Workflow history/ }).click();
    await expect(header).toHaveAttribute("data-step", "coverage");
    await expect(header).toContainText("模糊匹配");
    await expect(
      panel.getByText("历史票务服务", { exact: true }),
    ).toBeVisible();
    expect(installationStatusReads).toBe(0);
    await expect(panel).not.toContainText(
      '"event":"resource_retrieval_progress"',
    );
    const before = (await header.boundingBox())!.y;
    const viewport = panel.locator(".overflow-y-auto.max-w-4xl").first();
    await expect(viewport).toBeVisible();
    await expect
      .poll(() =>
        viewport.evaluate((node) => node.scrollHeight > node.clientHeight),
      )
      .toBe(true);
    await viewport.evaluate((node) => {
      node.scrollTop = 0;
    });
    await viewport.evaluate((node) => {
      node.scrollTop = 1000;
    });
    await expect
      .poll(() => viewport.evaluate((node) => node.scrollTop))
      .toBeGreaterThan(0);
    expect(Math.abs((await header.boundingBox())!.y - before)).toBeLessThan(2);
    await panel.evaluate((node) => {
      node.style.width = "360px";
    });
    await expect(header).toContainText("第 2/4 步");
    expect(
      await header.evaluate((node) => node.scrollWidth <= node.clientWidth + 1),
    ).toBe(true);
    await page.screenshot({
      path: join(contract.caseDir, "coverage-narrow.png"),
    });
    await panel.getByRole("button", { name: "新会话", exact: true }).click();
    await expect(header).toHaveCount(0);
    requests.push(
      ...(await page.evaluate(() => (window as any).__workflow.requests)),
    );
    draft.description = "";
    await page.reload();
    await expect(panel).toBeVisible();
    await expect(header).toHaveCount(0);
    await installTransport();
    await send("帮我优化一下提示词，主要是要增加一个示例");
    await expect(header).toHaveCount(0);
    await emit({
      type: "nl2a_state",
      content: JSON.stringify({
        event: "agent_draft_fields_saved",
        agent_id: 42,
        updated_fields: ["prompt"],
      }),
    });
    await expect(header).toHaveCount(0);
    await end();
    await expect(header).toHaveCount(0);
  });
  const assertions = contract.expectedIds("assertions");
  await contract.assertion(assertions[0], async () => {
    await expect(header).toHaveCount(0);
  });
  await contract.assertion(assertions[1], async () => {
    expect(knowledgeChoice).toEqual([false, true, true, false]);
  });
  await contract.assertion(assertions[2], async () => {
    expect(writes).toEqual([]);
    expect(installationStatusReads).toBe(0);
  });
  await contract.assertion(assertions[3], async () => {
    requests.push(
      ...(await page.evaluate(() => (window as any).__workflow.requests)),
    );
    expect(requests.length).toBe(6);
    expect(requests.every((body) => !("workflow_progress" in body))).toBe(true);
  });
});
