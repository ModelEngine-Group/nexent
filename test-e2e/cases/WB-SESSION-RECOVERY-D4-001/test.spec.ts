// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { expect } from "playwright/test";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("WB-SESSION-RECOVERY-D4-001", async ({ page, contract }) => {
  const base = process.env.NEXENT_BASE_URL ?? "http://localhost:3037";
  await page.addInitScript(() => Object.defineProperty(window.crypto, "randomUUID", { value: undefined }));
  const history = { conversation_id: 91, conversation_title: "Recoverable creator fixture", agent_id: 1,
    target: { type: "agent", id: 42 }, agent_system_key: "nl2agent_main", create_time: Date.now(), update_time: Date.now() };
  await prepareWorkbench(page, 1, { histories: [history] });
  const json = (data: unknown) => ({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
  const card = (id: number, title: string, label: string) => ({ subtype: "requirement_clarification", agent_id: 42,
    card_id: `${id}:0`, questions: [{ question_id: "goal", question_type: "single_choice", title, required: true,
      options: [{ option_id: "yes", label }], allow_other: false, other_input_expanded: false }] });
  const first = card(10, "First requirement?", "First answer");
  const second = card(12, "Second requirement?", "Second answer");
  const units = (payload: unknown) => [{ type: "nl2a", content: JSON.stringify(payload) }];
  const messages: Array<Record<string, any>> = [
    { role: "user", message_id: 9, message_index: 0, message: "Create an Agent", status: "completed" },
    { role: "assistant", message_id: 10, message_index: 1, message: units(first), status: "completed" },
  ];
  let releaseTarget = () => {};
  let delayTarget = true;
  const targetGate = new Promise<void>((resolve) => { releaseTarget = resolve; });
  let releaseRetry = () => {};
  const retryGate = new Promise<void>((resolve) => { releaseRetry = resolve; });
  let releaseReplay = () => {};
  const replayGate = new Promise<void>((resolve) => { releaseReplay = resolve; });
  const requests: Array<{ resume: boolean; body: any }> = [];
  const target = { agent_id: 42, name: "recovery_fixture", display_name: "Recovery fixture", description: "Fixture",
    permission: "EDIT", model_ids: [1], model_names: ["Fixture Model"], prompt: "Return the supplied text",
    tools: [], max_steps: 3, enabled: true, is_available: true };
  await page.route("**/api/agent/search_info", async (route) => {
    if (delayTarget) await targetGate;
    await route.fulfill(json(target));
  });
  await page.route("**/api/conversation/91", async (route) => {
    const running = messages.findLast((message) => message.status === "streaming");
    await route.fulfill(json({ code: 0, data: [{ ...history, message: messages,
      chat_mode: "execution", workbench_config: { schema_version: 4, mode: "agent_create", agent_mounts: [], skill_mounts: [] },
      workbench_config_version: 1,
      ...(running ? { streaming_message: { message_id: running.message_id, status: "streaming" } } : {}),
    }] }));
  });
  await page.route("**/api/agent/nl2agent/run*", async (route) => {
    const resume = new URL(route.request().url()).searchParams.get("resume") === "true";
    const body = route.request().postDataJSON();
    if (!resume) expect(body.request_id).toEqual(expect.any(String));
    requests.push({ resume, body });
    let events: object[];
    if (resume) {
      expect(body.conversation_id).toBe(91);
      expect(body.resume_message_id).toBe(15);
      const running = messages.findLast((message) => message.status === "streaming")!;
      if (requests.filter((request) => request.resume).length === 1) {
        events = [{ status: "stopped", replay_unavailable: true }];
      } else {
        await replayGate;
        running.status = "completed";
        running.message = [
          { type: "final_answer", content: "Retry recovered ", answer_phase: "delta", step_id: "retry-step", attempt_id: "retry-attempt" },
          { type: "final_answer", content: "successfully", answer_phase: "delta", step_id: "retry-step", attempt_id: "retry-attempt" },
          { type: "final_answer", content: "", answer_phase: "complete", step_id: "retry-step", attempt_id: "retry-attempt" },
        ];
        events = [...running.message, { status: "completed" }];
      }
    } else if (body.retry_message_index !== undefined) {
      expect(body.retry_message_index).toBe(4);
      expect(body.retry_user_message_id).toBe(13);
      messages.push({ role: "assistant", message_id: 15, message_index: 5, status: "streaming",
        message: [{ type: "final_answer", content: "Retry partial" }] });
      await retryGate;
      events = [{ type: "final_answer", content: "Retry partial" }];
    } else {
      const action = JSON.parse(body.query);
      expect(action.result.answers).toEqual([{ question_id: "goal", value: "yes", other_text: null }]);
      const count = requests.filter((request) => !request.resume).length;
      expect(JSON.stringify(body.history)).toContain(count === 1 ? "First requirement?" : "Second requirement?");
      messages.push({ role: "user", message_id: count === 1 ? 11 : 13, message_index: count === 1 ? 2 : 4,
        message: body.query, status: "completed" });
      const output = count === 1 ? units(second) : [{ type: "error", content: "Controlled generation failure" }];
      messages.push({ role: "assistant", message_id: count === 1 ? 12 : 14, message_index: count === 1 ? 3 : 5,
        message: output, status: count === 1 ? "completed" : "failed" });
      events = output;
    }
    await route.fulfill({ status: 200, contentType: "text/event-stream", headers: { conversation_id: "91", run_id: "fixture-generation" },
      body: events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("") }).catch(() => {});
  });
  contract.deferCleanup(async () => {
    releaseTarget();
    releaseRetry();
    releaseReplay();
    await page.close();
  });
  const cards = page.locator('[data-slot="aui-requirement-clarification"]');
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    const read = page.waitForResponse((response) => response.url().endsWith("/api/conversation/91"));
    await page.goto(`${base}/zh/workbench?conversation_id=91`);
    await read;
    releaseTarget();
    delayTarget = false;
    await expect(cards).toHaveCount(1);
  });
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await expect(page.getByRole("radio", { name: "First answer" })).toBeEnabled();
    await page.getByRole("radio", { name: "First answer" }).check();
    await page.goto(`${base}/zh/workbench`);
    await page.goto(`${base}/zh/workbench?conversation_id=91`);
    await expect(page.getByRole("radio", { name: "First answer" })).toBeChecked();
    await expect(page.getByRole("radio", { name: "First answer" })).toBeEnabled();
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await cards.first().locator("button").last().click();
    await expect(cards).toHaveCount(2);
    await expect(page.getByRole("radio", { name: "First answer" })).toBeDisabled();
    await expect(page.getByRole("radio", { name: "Second answer" })).toBeEnabled();
    await page.getByRole("radio", { name: "Second answer" }).check();
    await cards.last().locator("button").last().click();
    await expect(page.getByText("Controlled generation failure", { exact: true })).toBeVisible();
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await page.reload();
    await expect(page.getByText("Controlled generation failure", { exact: true })).toBeVisible();
    await page.locator(".aui-assistant-action-bar-root").last().locator("button").nth(1).click();
    await expect.poll(() => requests.filter((request) => !request.resume).length).toBe(3);
    await page.goto(`${base}/zh/workbench`);
    releaseRetry();
    await page.goto(`${base}/zh/workbench?conversation_id=91`);
    await expect.poll(() => requests.filter((request) => request.resume).length).toBe(2);
    const assistant = page.locator('[data-slot="aui_assistant-message-root"]').last();
    await expect(assistant.getByText("Retry partial", { exact: true })).toBeVisible();
    await expect(assistant.locator('[data-slot="aui_assistant-message-completion-indicator"]')).toHaveCount(0);
    releaseReplay();
    await expect(page.getByText("Retry recovered successfully", { exact: true })).toBeVisible();
    await expect(assistant.locator('[data-slot="aui_assistant-message-completion-indicator"]')).toContainText("已完成");
    expect(requests.filter((request) => request.resume)).toHaveLength(2);
    expect(requests.filter((request) => !request.resume)).toHaveLength(3);
    expect(messages.filter((message) => message.role === "user")).toHaveLength(3);
    await page.screenshot({ path: join(contract.caseDir, "recovered-creator.png") });
  });
  await contract.step(contract.expectedIds("steps")[3], async () => {
    await expect(page.getByText("Retry recovered successfully", { exact: true })).toHaveCount(1);
    await page.reload();
    await expect(page.getByText("Retry recovered successfully", { exact: true })).toBeVisible();
    await expect(page.getByText("Retry recovered successfully", { exact: true })).toHaveCount(1);
    expect(requests.filter((request) => !request.resume)).toHaveLength(3);
  });
  for (const id of contract.expectedIds("assertions")) await contract.assertion(id, async () => {
    await expect(cards).toHaveCount(2);
    await expect(page.getByRole("radio", { name: "First answer" })).toBeChecked();
    await expect(page.getByRole("radio", { name: "Second answer" })).toBeChecked();
    await expect(page.getByRole("radio", { name: "Second answer" })).toBeDisabled();
    expect(requests.filter((request) => !request.resume)).toHaveLength(3);
  });
});
