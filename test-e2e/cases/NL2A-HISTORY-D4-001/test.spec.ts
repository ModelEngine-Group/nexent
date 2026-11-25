// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";
import { makeDraft, fulfillEditorReadFixture } from "../../infra/automation/d4/fixtures/agent-editor-reads.mjs";

journey("NL2A-HISTORY-D4-001", async ({ page, contract, expect }) => {
  await prepareWorkbench(page);
  const histories = [603, 602, 601].map((id) => ({
    conversation_id: id, conversation_title: `Optimization ${id}`,
    agent_system_key: "nl2agent_main", target: { type: "agent", id: 42 },
    create_time: id * 1000, update_time: id * 1000,
  }));
  const requests: Array<Record<string, unknown>> = [];
  const unexpectedWrites: string[] = [];
  const restored: number[] = [];
  let historyReads = 0;
  const json = (value: unknown) => ({ contentType: "application/json", body: JSON.stringify(value) });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/user/current_user_info") return route.fallback();
    if (path === "/api/agent/search_info")
      return route.fulfill(json({ ...makeDraft(), tools: [] }));
    if (path === "/api/conversation/creator_histories") {
      historyReads++;
      expect([...new URL(route.request().url()).searchParams.keys()].sort()).toEqual(["kind", "target_id"]);
      return route.fulfill(json({ code: 0, data: { items: histories, total: 3 } }));
    }
    const selected = histories.find((item) => path === `/api/conversation/${item.conversation_id}`);
    if (selected) {
      restored.push(selected.conversation_id);
      return route.fulfill(json({ code: 0, data: [{ ...selected, message: [
        { role: "user", message_id: 1, message: `Saved optimization ${selected.conversation_id}` },
        { role: "assistant", message_id: 2, message: [{ type: "final_answer", content: `Previous reply ${selected.conversation_id}` }] },
      ] }] }));
    }
    if (path === "/api/agent/nl2agent/run") {
      requests.push(route.request().postDataJSON());
      return route.fulfill({ contentType: "text/event-stream", headers: { conversation_id: String(requests.at(-1)?.conversation_id ?? 604) },
        body: `data: ${JSON.stringify({ type: "final_answer", content: "Optimization complete" })}\n\n` });
    }
    if (route.request().method() !== "GET" && !path.endsWith("/filter") && !path.endsWith("/preview") && !["/api/groups/list", "/api/conversation/list"].includes(path)) {
      unexpectedWrites.push(path);
      return route.fulfill({ status: 400, ...json({ error: "Unexpected write" }) });
    }
    if (await fulfillEditorReadFixture(route, path.replace(/^\/api/, ""))) return;
    return route.fallback();
  });
  contract.deferCleanup(async () => {
    await page.close();
    expect(unexpectedWrites).toEqual([]);
  });
  const panel = page.getByTestId("agent-config-conversation-panel");
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    await page.goto(`${process.env.NEXENT_BASE_URL}/zh/agents/42`);
    await expect(panel).toBeVisible();
  });
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await expect(panel.getByText("Previous reply 603")).toBeVisible();
    expect(restored).toEqual([603]);
    await panel.getByRole("button", { name: "历史 3" }).click();
    const list = page.getByRole("list", { name: "此智能体的生成记录" });
    await expect(list.getByRole("button")).toHaveCount(3);
    await expect(page.getByRole("button", { name: "加载更多" })).toHaveCount(0);
    await expect(page.getByText("保留最近 3 条会话，建议在已有会话中持续优化智能体。")).toBeVisible();
    await panel.getByRole("button", { name: "历史 3" }).click();
  });
  const send = async (text: string) => {
    const input = panel.locator("[data-workbench-composer]:visible, .aui-lexical-input:visible").first();
    await input.fill(text);
    await input.press("Enter");
    await expect(panel.getByText("Optimization complete")).toBeVisible();
  };
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await send("继续优化已有智能体");
    expect(requests[0].conversation_id).toBe(603);
    await panel.getByRole("button", { name: "新会话" }).click();
    await expect(panel.getByText("Previous reply 603")).toHaveCount(0);
    const before = historyReads;
    await panel.getByRole("button", { name: "历史 3" }).click();
    await expect.poll(() => historyReads).toBeGreaterThan(before);
    await panel.getByRole("button", { name: "历史 3" }).click();
    await expect(panel.getByText("Previous reply 603")).toHaveCount(0);
    expect(restored).toEqual([603]);
    await send("从新的方向开始");
    expect(requests[1].conversation_id).toBeUndefined();
  });
  const assertions = contract.expectedIds("assertions");
  await contract.assertion(assertions[0], async () => expect(restored).toEqual([603]));
  await contract.assertion(assertions[1], async () => expect(requests).toHaveLength(2));
});
