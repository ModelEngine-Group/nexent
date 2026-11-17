// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect } from "playwright/test";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

journey("WB-EXECUTION-RECOVERY-D4-001", async ({ page, contract }) => {
  const base = process.env.NEXENT_BASE_URL ?? "http://localhost:3031";
  const config = { schema_version: 4, mode: "generic_chat", agent_mounts: [], skill_mounts: [] };
  const histories = [
    { conversation_id: 91, conversation_title: "Execution recovery fixture", chat_mode: "execution" },
    { conversation_id: 92, conversation_title: "Failed execution fixture", chat_mode: "execution" },
    { conversation_id: 93, conversation_title: "Stopped execution fixture", chat_mode: "execution" },
  ].map(h => ({ ...h, agent_id: 1, create_time: Date.now(), update_time: Date.now() }));
  await prepareWorkbench(page, 1, { histories });
  const metric = (step: number, duration: number, unit_index: number) => ({ type: "token_count", unit_index,
    content: JSON.stringify({ step_number: step, duration, total_output_tokens: step * 10 }) });
  const prefix = [{ type: "parse", content: "print('FIRST-CODE')", unit_index: 0 }, metric(1, 2, 1),
    { type: "parse", content: "print('SECOND-CODE')", unit_index: 2 }, metric(2, 3, 3)];
  const suffix = [{ type: "parse", content: "print('THIRD-CODE')", unit_index: 4 }, metric(3, 4, 5),
    { type: "final_answer", content: "EXECUTION-COMPLETE", unit_index: 6 }];
  const messages: Record<number, Array<Record<string, any>>> = {
    91: [{ role: "user", message_id: 1, message: "Execute three code actions" },
      { role: "assistant", message_id: 2, status: "streaming", message: [] }],
    92: [{ role: "user", message_id: 3, message: "Retry this controlled failure" },
      { role: "assistant", message_id: 4, status: "failed", message: [{ type: "error", content: "Controlled provider failure" }] }],
    93: [{ role: "user", message_id: 5, message: "Stopped request" },
      { role: "assistant", message_id: 6, status: "stopped", message: [{ type: "parse", content: "print('STOPPED')" }] }],
  };
  await page.route(/\/api\/conversation\/(91|92|93)$/, async route => {
    const id = Number(new URL(route.request().url()).pathname.split("/").at(-1));
    const running = messages[id].findLast(m => m.status === "streaming");
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ code: 0, data: [{
      ...histories.find(h => h.conversation_id === id), message: messages[id], workbench_config: config,
      workbench_config_version: 1, ...(running ? { streaming_message: { message_id: running.message_id, status: "streaming" } } : {}),
    }] }) });
  });
  await page.addInitScript(({ initial }) => {
    const original = window.fetch.bind(window);
    const fixture = { requests: [] as any[], reads: [] as string[], controller: null as ReadableStreamDefaultController<Uint8Array> | null,
      send(events: object[]) { for (const e of events) fixture.controller!.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(e)}\n\n`)); },
      complete(events: object[]) { fixture.send(events); fixture.send([{ status: "completed" }]); fixture.controller!.close(); },
    };
    (window as any).__executionFixture = fixture;
    window.fetch = async (input, init) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (!new URL(url, location.href).pathname.endsWith("/api/agent/run")) return original(input, init);
      const body = JSON.parse(String(init?.body ?? "{}"));
      fixture.requests.push({ ...body, is_resume: new URL(url, location.href).searchParams.get("resume") === "true" });
      const stream = new ReadableStream<Uint8Array>({ start(controller) {
        fixture.controller = controller;
        const events = Number(body.conversation_id) === 91 ? initial
          : [{ type: "final_answer", content: "RETRY-PARTIAL", answer_phase: "delta", answer_id: "retry" }];
        for (const e of events) controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(e)}\n\n`));
        init?.signal?.addEventListener("abort", () => { try { controller.error(new DOMException("Detached", "AbortError")); } catch {} }, { once: true });
      } });
      const getReader = stream.getReader.bind(stream);
      stream.getReader = (() => {
        const reader = getReader();
        const read = reader.read.bind(reader);
        reader.read = async () => {
          const result = await read();
          fixture.reads.push(result.done ? "done" : new TextDecoder().decode(result.value));
          return result;
        };
        return reader;
      }) as typeof stream.getReader;
      return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream", conversation_id: String(body.conversation_id) } });
    };
  }, { initial: prefix });
  contract.deferCleanup(async () => {
    const state = await page.evaluate(() => ({ requests: (window as any).__executionFixture?.requests, reads: (window as any).__executionFixture?.reads,
      connected: Boolean((window as any).__executionFixture?.controller) }));
    writeFileSync(join(contract.caseDir, "stream-fixture.json"), JSON.stringify(state, null, 2));
    await page.close();
  });
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    await page.goto(`${base}/zh/workbench`);
    await expect(page.getByRole("textbox", { name: "对话输入", exact: true })).toBeEnabled();
  });
  const input = () => page.getByRole("textbox", { name: "对话输入", exact: true });
  const open = async (title: string) => {
    await page.getByRole("button", { name: "工作台", exact: true }).click();
    await page.mouse.move(800, 500);
    await page.getByRole("button", { name: new RegExp(`^${title} (刚刚|\\d+分钟前)$`) }).click();
  };
  await contract.step(contract.expectedIds("steps")[0], async () => {
    await input().fill("UNSENT-EXECUTION-DRAFT");
    await page.getByRole("button", { name: "首页", exact: true }).click();
    await page.getByRole("button", { name: "工作台", exact: true }).click();
    await expect(input()).toHaveValue("UNSENT-EXECUTION-DRAFT");
    await input().fill("NEWER-EXECUTION-DRAFT");
    await page.reload(); await expect(input()).toHaveValue("NEWER-EXECUTION-DRAFT");
    await page.getByRole("button", { name: "新对话", exact: true }).click();
    await expect(input()).toHaveValue("");
  });
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await open("Execution recovery fixture");
    await expect(page.getByRole("button", { name: /^Executed code python$/i })).toHaveCount(2);
    await expect(page.getByRole("button", { name: "停止生成", exact: true })).toBeVisible();
    const origin = await page.evaluate(() => performance.timeOrigin);
    await page.getByRole("button", { name: "首页", exact: true }).click();
    await open("Execution recovery fixture");
    await expect(page.getByRole("button", { name: /^Executed code python$/i })).toHaveCount(2);
    expect(await page.evaluate(() => performance.timeOrigin)).toBe(origin);
    messages[91][1] = { ...messages[91][1], status: "completed", message: [...prefix, ...suffix] };
    await page.evaluate(events => (window as any).__executionFixture.complete(events), suffix);
    await expect(page.getByText("EXECUTION-COMPLETE", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /^Executed code python$/i })).toHaveCount(3);
    await expect(page.getByText("9.00s", { exact: true })).toBeVisible();
    const requests = await page.evaluate(() => (window as any).__executionFixture.requests);
    expect(requests.length).toBe(2);
    expect(requests.every((r: any) => r.is_resume && r.enable_plan === false)).toBe(true);
    await page.reload();
    await expect(page.getByRole("button", { name: /^Executed code python$/i })).toHaveCount(3);
    await expect(page.getByText("9.00s", { exact: true })).toBeVisible();
  });
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await open("Stopped execution fixture"); await expect(page.getByText("已停止", { exact: true })).toBeVisible();
    await open("Failed execution fixture"); await expect(page.getByText("执行失败", { exact: true })).toBeVisible();
    messages[92].push({ role: "assistant", message_id: 7, status: "streaming", message: [] });
    await page.getByRole("button", { name: "刷新", exact: true }).click();
    await expect(page.getByRole("button", { name: "停止生成", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "首页", exact: true }).click();
    await open("Failed execution fixture");
    await expect(page.getByRole("button", { name: "停止生成", exact: true })).toBeVisible();
    const final = { type: "final_answer", content: "RETRY-SUCCESS", answer_phase: "complete", answer_id: "retry" };
    messages[92][2] = { ...messages[92][2], status: "completed", message: [final] };
    await page.evaluate(e => (window as any).__executionFixture.complete([e]), final);
    await expect(page.getByText("RETRY-SUCCESS", { exact: true })).toBeVisible();
    const requests = await page.evaluate(() => (window as any).__executionFixture.requests);
    expect(requests.filter((r: any) => !r.is_resume)).toHaveLength(1);
    expect(requests.every((r: any) => r.enable_plan === false)).toBe(true);
  });
  for (const id of contract.expectedIds("assertions")) {
    await contract.assertion(id, async () => {
      await expect(page.getByText("RETRY-SUCCESS", { exact: true })).toBeVisible();
      await expect(page.getByRole("region", { name: "执行计划", exact: true })).toHaveCount(0);
    });
  }
});
