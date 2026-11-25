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
    skills: [{ skill_id: 901, name: "ready_skill", description: "Saved existing skill", source: "local", config_schemas: [], config_values: {} }],
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
  const card = (coverage: "covered" | "uncovered") => ({
    type: "nl2a",
    tool_name: "nl2a_show_resource_card",
    content: JSON.stringify({
      subtype: "requirement_resources",
      purpose: "generate",
      resources: [],
      agent_id: 42,
      protocol_version: 2,
      run_id: "fixture-run",
      conversation_id: "601",
      card_id: `card-${coverage}`,
      state_version: 1,
      requirements: [
        {
          requirement_id: "r1",
          query: "联网搜索",
          required: true,
          coverage_status: coverage,
          covered_resources:
            coverage === "covered"
              ? knowledgeResources.map((item) => item.candidate)
              : [],
          installable_resources: [],
        },
      ],
      ...(coverage === "covered"
        ? { resources: knowledgeResources }
        : {}),
    }),
  });
  const historicalCoverage = {
    ...card("uncovered"),
    content: JSON.stringify({
      ...JSON.parse(card("uncovered").content),
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
    if (path === "/api/agent/nl2agent/knowledge_recommendations") {
      const body = route.request().postDataJSON();
      const refs = body.card_id.startsWith("seven") ? [203, 202] : [202];
      return route.fulfill(json({ resources: refs.map(id => ({
        candidate_ref: `tool:${id}`, tool_name: "knowledge_base_search",
        recommendations: [{ id: "901", binding_value: "expense-index", name: "报销制度库", score: .9 }],
        selected_values: [id === 202 ? "extra-index" : "expense-index"],
        selection_source: id === 202 ? "saved" : "recommended",
        settings: id === 202 ? { top_k: 8 } : {},
        models: { embedding_model_id: 1, embedding_model_name: "Fixture Embedding" }, mode: "hybrid",
      })) }));
    }
    if (path === "/api/tool/search") {
      const id = new URL(route.request().url()).searchParams.get("tool_id");
      return route.fulfill(json({ params: id === "202" ? { index_names: ["extra-index"], top_k: 8 } : {}, enabled: false }));
    }
    if (path === "/api/tool/list")
      return route.fulfill(
        json(
          [...knowledgeResources.map((item) => ({
            tool_id: Number(item.candidate.candidate_ref.split(":")[1]),
            name: item.candidate.name,
            source: "local",
            is_available: true,
            params: [],
            inputs: {},
          })), { tool_id: 203, name: "shared_knowledge_search", origin_name: "knowledge_base_search", source: "local", is_available: true, params: [], inputs: {} }],
        ),
      );
    if (path === "/api/indices/health")
      return route.fulfill(json({ status: "healthy", elasticsearch: "connected" }));
    if (path === "/api/indices")
      return route.fulfill(json({ indices: ["expense-index", "extra-index"], indices_info: ["expense-index", "extra-index"].map((name, i) => ({
        name, display_name: i ? "额外资料库" : "报销制度库", knowledge_id: 901 + i,
        embedding_model_id: 1, embedding_model_name: "Fixture Embedding", knowledge_sources: "elasticsearch",
        permission: "READ_ONLY", is_multimodal: false, stats: { base_info: { doc_count: 1, chunk_count: 2 } },
      })) }));
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
                    card("uncovered"),
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
    await expect(header).not.toHaveAttribute("data-state", "completed");
    await emit(state("searching_text", 1));
    await expect(header).toContainText("模糊匹配");
    await expect(header).not.toContainText("语义匹配暂不可用");
    await emit(state("verifying_capabilities", 2));
    await emit(card("uncovered"));
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
    await emit(card("covered"));
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
    await panel.getByRole("button", { name: "编辑需求", exact: true }).click();
    await expect(panel.getByText("正在修改需求，保存后将重新匹配受影响需求的资源。")).toBeVisible();
    await expect(native.getByRole("checkbox")).toBeDisabled();
    await expect(panel.getByRole("button", { name: "更新需求并重新搜索" })).toBeDisabled();
    await panel.getByRole("button", { name: "取消修改", exact: true }).click();
    await expect(native.getByRole("checkbox")).toBeChecked();
    await expect(alternative.getByRole("checkbox")).not.toBeChecked();
    expect(writes).toEqual([]);
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
    await expect(header).toHaveAttribute("data-step", "coverage");
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
    await panel.getByRole("button", { name: "新会话", exact: true }).click();
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
  await contract.step(contract.expectedIds("steps")[4], async () => {
    await send("重新匹配七项能力");
    const resource = { ...knowledgeResources[0], has_config: false, candidate: { ...knowledgeResources[0].candidate, candidate_ref: "tool:203", name: "shared_search", requirement_ids: ["r1", "r2"] } };
    const second = { ...knowledgeResources[1], has_config: false, candidate: { ...knowledgeResources[1].candidate, name: "second_search", requirement_ids: ["r3"] } };
    const ready = { ...resource, is_bound: false, candidate: { ...resource.candidate, candidate_ref: "skill:901", resource_type: "skill", name: "ready_skill", requirement_ids: ["r4", "r5", "r6"] }, form_kind: "SKILL_CONFIG" };
    const requirements = Array.from({ length: 7 }, (_, i) => ({
      requirement_id: `r${i + 1}`, query: `能力 ${i + 1}`, required: true,
      search_queries: { zh: `能力 ${i + 1}`, en: `capability ${i + 1}` },
      coverage_status: i === 6 ? "uncovered" : "covered",
      covered_resources: i === 6 ? [] : [{ candidate_ref: i < 2 ? "tool:203" : i === 2 ? "tool:202" : "skill:901", name: "resource", retrieval_score: 0.9 }], installable_resources: [],
    }));
    const unified = { protocol_version: 2, subtype: "requirement_resources", agent_id: 42, purpose: "generate", run_id: "seven", conversation_id: "601", card_id: "seven", state_version: 9, requirements, resources: [resource, second, ready] };
    await emit({ type: "nl2a", content: JSON.stringify(unified) });
    await end();
    const cardView = panel.getByTestId("requirement_resources");
    await expect(header).toHaveAttribute("data-step", "coverage");
    const summary = cardView.locator('[aria-live="polite"]').filter({ hasText: "待选择" });
    await expect(summary.locator("svg")).toHaveCount(4);
    const firstRow = cardView.locator(".nl2agent-requirement-row").first();
    const editButton = firstRow.getByRole("button", { name: "编辑需求", exact: true });
    await page.mouse.move(1790, 10);
    await expect(editButton).toBeVisible();
    await expect(firstRow.locator(".nl2agent-requirement-actions")).toHaveCSS("opacity", "1");
    await expect(firstRow.getByRole("button", { name: "删除", exact: true })).toBeVisible();
    await expect(firstRow.getByText("待绑定", { exact: true })).toHaveCount(0);
    const toggle = firstRow.getByRole("button", { name: /能力 1/ });
    expect((await toggle.boundingBox())!.width).toBeGreaterThanOrEqual(28);
    const headingBox = (await firstRow.getByText("能力 1", { exact: true }).boundingBox())!;
    await expect(firstRow.getByText("能力 1", { exact: true })).toHaveCSS("font-size", "13px");
    await expect(firstRow.getByText("能力 1 · capability 1", { exact: true })).toHaveCSS("font-size", "12px");
    const detailBox = (await firstRow.getByText("能力 1 · capability 1", { exact: true }).boundingBox())!;
    const arrowBox = (await toggle.boundingBox())!;
    const resourceBox = (await firstRow.locator(".divide-y").first().boundingBox())!;
    expect(arrowBox.x).toBeLessThan(detailBox.x);
    expect(arrowBox.y).toBeGreaterThan(headingBox.y);
    expect(Math.abs(headingBox.x - resourceBox.x)).toBeLessThan(2);
    await expect(firstRow.getByText("90", { exact: true })).toHaveClass(/color-success/);
    await toggle.click();
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect(firstRow.getByRole("checkbox")).toHaveCount(0);
    await toggle.click();
    await expect(firstRow.getByRole("checkbox")).toBeVisible();
    await expect(firstRow.getByRole("button", { name: "创建 Skill", exact: true })).toBeVisible();
    await expect(firstRow.getByRole("button", { name: "创建 Skill", exact: true })).not.toHaveClass(/\bborder\b/);
    await expect(firstRow.getByRole("button", { name: "创建 MCP", exact: true })).toBeVisible();
    const unmatchedRow = cardView.locator(".nl2agent-requirement-row").filter({ hasText: "能力 7" });
    await expect(unmatchedRow.getByText("当前候选中没有核验通过的资源", { exact: true })).toBeVisible();
    await expect(unmatchedRow.getByText("可以创建新的 Skill 或接入 MCP 服务，创建后自动加入该需求。", { exact: true })).toBeVisible();
    await expect(unmatchedRow.getByRole("button", { name: "创建 Skill", exact: true })).toBeEnabled();
    await expect(unmatchedRow.getByRole("button", { name: "创建 MCP", exact: true })).toBeEnabled();
    // The server card predates this saved binding; actual Agent facts win.
    const savedSkillBoxes = cardView.locator('[data-resource-ref="skill:901"]').getByRole("checkbox");
    await expect(savedSkillBoxes).toHaveCount(3);
    for (const box of await savedSkillBoxes.all()) { await expect(box).toBeChecked(); await expect(box).toBeDisabled(); }
    const sharedKnowledge = cardView.locator('[data-resource-ref="tool:203"]');
    await expect(sharedKnowledge.first().getByText("报销制度库", { exact: true })).toBeVisible();
    await expect(cardView.locator('[data-resource-ref="tool:202"]').getByText("额外资料库", { exact: true })).toBeVisible();
    for (const rowIndex of [1, 0]) {
      await sharedKnowledge.nth(rowIndex).getByRole("button", { name: "选择知识库", exact: true }).click();
      const knowledgeDialog = page.getByRole("dialog");
      await expect(knowledgeDialog).toHaveCount(1);
      await expect(knowledgeDialog).toBeVisible();
      await expect(cardView.getByRole("button", { name: /绑定所选资源/ })).toBeDisabled();
      await expect(sharedKnowledge.nth(0).getByRole("checkbox")).toBeDisabled();
      const choices = knowledgeDialog.locator('[data-picker-part="list-content"]').getByRole("option");
      await expect(choices).toHaveCount(2);
      if (rowIndex === 1) {
        await expect(choices.first()).toHaveAttribute("aria-selected", "true");
        await choices.first().click();
      } else {
        // The explicit empty confirmation must survive opening from another occurrence.
        await expect(choices.first()).toHaveAttribute("aria-selected", "false");
        await choices.nth(1).click();
      }
      await knowledgeDialog.getByRole("button", { name: "确认", exact: true }).click();
      await expect(knowledgeDialog).toHaveCount(0);
      await expect(sharedKnowledge.nth(0).getByRole("checkbox")).toBeEnabled();
    }
    await expect(cardView.getByRole("button", { name: /绑定所选资源.*2/ })).toBeEnabled();
    await expect(cardView.getByRole("button", { name: "继续", exact: true })).toBeDisabled();
    const checkboxes = cardView.getByRole("checkbox");
    await checkboxes.nth(0).uncheck();
    await expect(checkboxes.nth(1)).toBeChecked();
    await expect(cardView.getByRole("button", { name: /绑定所选资源.*2/ })).toBeEnabled();
    await cardView.getByRole("button", { name: "编辑需求", exact: true }).first().click();
    await expect(checkboxes.nth(1)).toBeDisabled();
    await expect(cardView.getByRole("button", { name: /绑定所选资源/ })).toHaveCount(0);
    const input = cardView.getByRole("textbox", { name: "需求", exact: true });
    await input.fill("能力 1 修改");
    await input.press("Tab");
    await cardView.getByRole("button", { name: "更新需求并重新搜索", exact: true }).click();
    await expect.poll(() => page.evaluate(() => Boolean((window as any).__workflow.controller))).toBe(true);
    const editedRequirements = requirements.map((row, i) => i === 0 ? { ...row, query: "能力 1 修改" } : row);
    await emit({ type: "nl2a", content: JSON.stringify({ ...unified, card_id: "seven-updated", previous_card_id: "seven", state_version: 11, requirements: editedRequirements }) });
    await end();
    await expect(panel.getByTestId("requirement_resources").last().getByText("能力 1 修改", { exact: true })).toBeVisible();
    expect(writes).toEqual([]);
    await page.screenshot({ path: join(contract.caseDir, "unified-requirements.png"), fullPage: true });
    await expect(header).toHaveAttribute("data-step", "coverage");
    await send("已补齐最后一项需求的候选");
    const completeResource = { ...resource, candidate: { ...resource.candidate, requirement_ids: ["r1", "r2", "r7"] } };
    const completeRequirements = editedRequirements.map((row, i) => i === 6 ? { ...row, coverage_status: "covered", covered_resources: [{ candidate_ref: "tool:203", name: "resource", retrieval_score: 0.9 }] } : row);
    await emit({ type: "nl2a", content: JSON.stringify({ ...unified, card_id: "seven-covered", previous_card_id: "seven-updated", state_version: 12, requirements: completeRequirements, resources: [completeResource, second, ready] }) });
    await end();
    await expect(header).toHaveAttribute("data-step", "binding");
    await send("重新核验后最后一项仍有缺口");
    await emit({ type: "nl2a", content: JSON.stringify({ ...unified, card_id: "seven-gap", previous_card_id: "seven-covered", state_version: 13, requirements: editedRequirements }) });
    await end();
    await expect(header).toHaveAttribute("data-step", "coverage");
    expect(writes).toEqual([]);
    await expect(panel.getByTestId("requirement_resources").last().getByRole("button", { name: "继续", exact: true })).toBeDisabled();
    await send("检查已绑定需求的列表展示");
    const readyRequirements = completeRequirements.map((row, i) => ({ ...row, covered_resources: [
      { candidate_ref: "skill:901", name: "ready_skill", retrieval_score: .9 },
      ...(i === 2 ? row.covered_resources : []),
    ] }));
    await emit({ type: "nl2a", content: JSON.stringify({ ...unified, card_id: "seven-ready", previous_card_id: "seven-gap", state_version: 14,
      requirements: readyRequirements, resources: [
        { ...ready, candidate: { ...ready.candidate, requirement_ids: readyRequirements.map(row => row.requirement_id) } },
        { ...second, recommendation: "optional" },
      ],
    }) });
    await end();
    const readyCard = panel.getByTestId("requirement_resources").last();
    const readyRows = readyCard.locator(".nl2agent-requirement-row");
    await expect(readyRows).toHaveCount(7);
    for (const row of await readyRows.all()) await expect(row).toBeVisible();
    await expect(readyCard.getByRole("button", { name: /已就绪的需求|已绑定的需求/ })).toHaveCount(0);
    const boundBoxes = readyCard.locator('[data-resource-ref="tool:203"], [data-resource-ref="skill:901"]').getByRole("checkbox");
    await expect(boundBoxes).toHaveCount(7);
    for (const box of await boundBoxes.all()) { await expect(box).toBeChecked(); await expect(box).toBeDisabled(); }
    const optionalBox = readyCard.locator('[data-resource-ref="tool:202"]').getByRole("checkbox");
    await expect(optionalBox).toBeEnabled();
    await expect(optionalBox).not.toBeChecked();
    await expect(readyCard.getByRole("button", { name: "继续", exact: true })).toBeEnabled();
    await optionalBox.check();
    await expect(optionalBox).toBeChecked();
    await optionalBox.uncheck();
    await expect(readyCard.getByRole("button", { name: "继续", exact: true })).toBeEnabled();
    expect(writes).toEqual([]);
    await page.screenshot({ path: join(contract.caseDir, "ready-requirements.png"), fullPage: true });
  });
  const assertions = contract.expectedIds("assertions");
  await contract.assertion(assertions[0], async () => {
    await expect(header).toHaveAttribute("data-state", "waiting");
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
    expect(requests.length).toBe(10);
    expect(requests.every((body) => !("workflow_progress" in body))).toBe(true);
  });
  await contract.assertion(assertions[4], async () => {
    await expect(panel.getByTestId("requirement_resources").last().getByText("能力 1 修改", { exact: true })).toBeVisible();
    await expect(panel.getByTestId("requirement_resources").last().getByRole("button", { name: "继续", exact: true })).toBeEnabled();
    expect(writes).toEqual([]);
  });
});
