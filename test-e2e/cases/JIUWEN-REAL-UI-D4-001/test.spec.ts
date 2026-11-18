// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { journey } from "../../infra/automation/d4/runner/journey";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

journey("JIUWEN-REAL-UI-D4-001", async ({ page, contract, expect }) => {
  const input = JSON.parse(readFileSync(process.env.NEXENT_REAL_UI_CONFIG!, "utf8"));
  const base = process.env.NEXENT_BASE_URL || "http://127.0.0.1:3000";
  const container = input.container || "nexent-runtime";
  const unique = randomUUID().replaceAll("-", "").slice(0, 12);
  const target = `/tmp/nexent_real_ui_${unique}`;
  const localState = join(contract.caseDir, "private-state.json");
  const localImage = join(contract.caseDir, "reference.jpg");
  const docker = (...args: string[]) => {
    try { return execFileSync("docker", args, { encoding: "utf8", timeout: 120000, stdio: ["ignore", "pipe", "pipe"] }); }
    catch (error) {
      const failure = String((error as any).stdout || "").split(/\r?\n/).find(line => line.startsWith("FIXTURE_FAILURE="));
      throw new Error(failure || "Owned fixture command failed; no successful execution is inferred");
    }
  };
  const fixture = (mode: string, ...args: string[]) => {
    const output = docker("exec", "-e", "PYTHONPATH=/opt/backend", "-w", "/opt/backend", container,
      "/opt/backend/.venv/bin/python", target + ".py", mode, target + ".json", ...args);
    return JSON.parse(output.trim().split(/\r?\n/).at(-1)!);
  };
  const source = join(process.env.NEXENT_REPO!, "test-e2e/cases/JIUWEN-REAL-UI-D4-001/fixture.py");
  docker("cp", source, container + ":" + target + ".py");
  const outcomes: Record<string, unknown>[] = [];
  let state: any;
  let conversation = 0;
  let runCount = 0;
  let cmEnabled = false;
  let referenceCapacity: any;
  let previous: any[] = [];
  const imageViews: any[] = [];
  const marker = "FILE_UI_" + unique;
  const save = () => writeFileSync(join(contract.caseDir, "real-outcomes.json"), JSON.stringify({ profile: "real_smoke", marker, outcomes }, null, 2));
  page.on("request", request => { if (request.method() === "POST" && new URL(request.url()).pathname === "/api/agent/run") runCount++; });
  contract.deferCleanup(async () => {
    try {
      const cleaned = fixture("cleanup");
      outcomes.push(cleaned); save();
      expect(cleaned.cleanup).toBe(true); expect(cleaned.source_unchanged).toBe(true);
    } finally {
      for (const path of [localState, localImage]) if (existsSync(path)) unlinkSync(path);
      docker("exec", container, "/opt/backend/.venv/bin/python", "-c", `from pathlib import Path; Path('${target}.py').unlink(missing_ok=True)`);
    }
  });
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    const setup = fixture("setup", String(input.source_agent_id), input.user_id, String(input.source_message_id));
    docker("cp", container + ":" + target + ".json", localState);
    state = JSON.parse(readFileSync(localState, "utf8"));
    docker("cp", container + ":" + state.image_path, localImage);
    await page.context().addCookies([
      { name: "nexent_access_token", value: state.access_token, url: base, httpOnly: true, sameSite: "Lax", expires: state.expires_at },
      { name: "nexent_token_expires_at", value: String(state.expires_at), url: base, sameSite: "Lax", expires: state.expires_at },
    ]);
    outcomes.push(setup); save();
    return "Authorized equivalent file-assistant clone and owned image are ready; no provider substitution.";
  });
  const roots = () => page.locator('[data-slot="aui_assistant-message-root"]');
  const openHistory = async (count: number) => {
    const before = runCount;
    await page.goto(`${base}/zh/newchat?${conversation ? "thread_id=" + conversation : "agent_id=" + state.agent_id}`);
    await expect(page.getByRole("textbox").last()).toBeVisible();
    if (count) {
      await expect(roots()).toHaveCount(count);
      for (const card of await roots().locator(".aui-reasoning-root").all())
        await expect(card).not.toContainText(/"type"\s*:\s*"step_count"/);
    }
    expect(runCount).toBe(before);
  };
  const openProcess = async (row: any) => {
    for (const button of await row.getByRole("button", { name: /^\d+ tool calls?$/ }).all())
      if (await button.getAttribute("data-state") === "closed") await button.click();
    const closed = row.locator('.aui-reasoning-root button[data-state="closed"]');
    for (let count = await closed.count(); count > 0; count--) await closed.first().click();
  };
  const finalTexts = (row: any) => row.locator(".aui-md").evaluateAll((nodes: Element[]) => nodes
    .filter(node => !node.closest(".aui-reasoning-root") && !node.closest("[data-subagent-run-id]"))
    .map(node => (node as HTMLElement).innerText));
  const renderedFinal = async (row: any) => {
    await expect.poll(async () => (await finalTexts(row)).some(text =>
      text.includes(marker) && text.includes(input.expected_fact))).toBe(true);
    const texts = await finalTexts(row);
    expect(texts).toHaveLength(1);
    expect(texts[0]).not.toMatch(/completed_action_history|historical_attachments|<\/?final_answer\b|MODEL_PRIVATE_HISTORY/);
    return texts;
  };
  const send = async (core: string, upload: boolean, query: string, document = false) => {
    if (upload) {
      const uploadButton = page.getByRole("button", { name: /^(添加附件|上传文件|上传附件)$/ }).first();
      if (!await uploadButton.isVisible()) await page.getByRole("button", { name: "添加", exact: true }).click();
      await expect(uploadButton).toBeVisible();
      const [chooser] = await Promise.all([page.waitForEvent("filechooser"), uploadButton.click()]);
      await chooser.setFiles(localImage);
      await expect(page.getByText("reference.jpg", { exact: true }).first()).toBeVisible();
    }
    await page.getByRole("textbox").last().fill(query);
    const wire = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/agent/run", { timeout: 30000 });
    await page.getByRole("button", { name: "发送", exact: true }).click();
    const response = await wire;
    expect(response.status()).toBe(200);
    const request = response.request().postDataJSON();
    expect(request.agent_id).toBe(state.agent_id);
    expect(request.agent_core).toBeUndefined();
    conversation = request.conversation_id ?? Number(response.headers()["conversation_id"]);
    expect(conversation).toBeGreaterThan(0);
    expect((request.minio_files || []).length).toBeGreaterThanOrEqual(upload ? 1 : 0);
    const events = (await response.body()).toString("utf8").split(/\r?\n/)
      .filter(line => line.startsWith("data:")).map(line => JSON.parse(line.slice(5).trim()));
    expect(events.filter(e => e.type === "error")).toEqual([]);
    const terminals = events.filter(e => e.type === "run_terminal" && !e.invocation_id);
    if (core === "jiuwen") { expect(terminals).toHaveLength(1); expect(terminals[0].status).toBe("completed"); }
    const capacityEvents = core === "jiuwen"
      ? events.filter(e => e.type === "step_observation").map(e => e.context_capacity)
      : events.filter(e => e.type === "token_count").map(e => JSON.parse(e.content));
    expect(capacityEvents.length).toBeGreaterThan(0);
    for (const capacity of capacityEvents) {
      expect(capacity.context_window_tokens).toBeGreaterThan(0);
      expect(capacity.token_threshold).toBeGreaterThan(0);
      expect(capacity.effective_input_limit_tokens).toBeGreaterThan(0);
      expect(capacity.context_processing_mode).toBe(cmEnabled ? "adaptive_compact" : "passthrough");
      const values = {window:capacity.context_window_tokens,threshold:capacity.token_threshold,input_limit:capacity.effective_input_limit_tokens};
      if (!referenceCapacity) referenceCapacity=values;
      expect(values).toEqual(referenceCapacity);
    }
    const calls = events.filter(e => e.type === "tool");
    const images = calls.filter(e => e.tool_name === "analyze_image");
    const complete = events.filter(e => e.type === "final_answer" && e.answer_phase === "complete" && !e.invocation_id);
    if (core === "smolagents") expect(complete).toHaveLength(1);
    const final = core === "jiuwen" ? terminals[0].final_content : complete[0].reclassify_step
      ? events.filter(e => e.type === "model_output_thinking" && e.step_id === complete[0].step_id).map(e => e.content).join("")
      : events.filter(e => e.type === "final_answer" && e.answer_phase === "delta" && !e.invocation_id).map(e => e.content).join("") || complete[0].content;
    outcomes.push({ kind: "wire", core, image_calls: images.length, explicit_complete: true, final_length: final.length }); save();
    expect(final).toContain(marker);
    expect(final).toContain(input.expected_fact);
    if (upload) {
      expect(images).toHaveLength(1);
      const results = core === "jiuwen" ? events.filter(e => e.type === "tool_result" && e.local_call_id === images[0].local_call_id)
        : events.filter(e => e.type === "execution_logs");
      expect(results.length).toBeGreaterThan(0);
      expect(results.some(e => e.is_error === true)).toBe(false);
      expect(JSON.stringify(results)).toContain(input.expected_fact);
    } else if (document) {
      expect(events.some(e => e.type === "subagent_start")).toBe(true);
      expect(final).toMatch(/s3:\/\/[^\s)]+\.docx/);
      expect(fixture("verify-docx", String(conversation), marker).downloaded_docx_verified).toBe(true);
    } else expect(calls.filter(e => !["final_answer", "search_memory"].includes(e.tool_name))).toHaveLength(0);
    expect(final).not.toMatch(/completed_action_history|historical_attachments|<\/?final_answer\b/);
    const number = outcomes.filter(e => e.kind === "turn").length + 1;
    await expect(roots()).toHaveCount(number, { timeout: 30000 });
    const row = roots().last();
    await expect(row.locator('[data-slot="aui_assistant-message-completion-indicator"]')).toBeVisible({ timeout: 30000 });
    await expect(page.locator("[data-runtime-output]")).toHaveCount(0);
    const texts = await renderedFinal(row);
    expect(texts).toHaveLength(1); expect(texts[0]).toContain(marker); expect(texts[0]).toContain(input.expected_fact);
    await expect(row.locator('[data-token-usage="summary"]')).toHaveCount(0);
    const usageButton=row.getByRole("button",{name:/\d+%.*本轮/});
    await expect(usageButton).toBeVisible(); await usageButton.click();
    await expect(row).toContainText(referenceCapacity.window.toLocaleString("en-US"));
    await usageButton.click();
    if (upload) {
      await openProcess(row);
      const tool = row.getByRole("button", { name: "Used tool: analyze_image", exact: true });
      await expect(tool).toBeVisible();
      if (await tool.getAttribute("data-state") === "closed") await tool.click();
      await expect(tool.locator("..")).toContainText(input.expected_fact);
      imageViews.push({ core, reasoning: await row.locator(".aui-reasoning-root").count(), tool: await tool.count(), finals: texts.length });
    }
    let snapshot: any;
    await expect.poll(() => { snapshot = fixture("check", String(conversation)); return snapshot.messages.filter((m: any) => m.role === "assistant" && m.status === "completed").length; }, { timeout: 30000 }).toBe(number);
    expect(snapshot.core).toBe(core);
    expect(request.version_no).toBe(snapshot.version);
    expect(snapshot.messages.map((m: any) => m.index)).toEqual(Array.from({ length: number * 2 }, (_, i) => i));
    expect(snapshot.messages.slice(0, previous.length)).toEqual(previous); previous = snapshot.messages;
    outcomes.push({ kind: "turn", core, upload, version: snapshot.version, completed: true, marker_recalled: true, visual_fact: true,
      image_calls: images.length, business_tools: calls.map(e => e.tool_name).filter(n => n !== "final_answer"),
      message_count: snapshot.messages.length, final_length: final.length, original_rows_unchanged: true,
      cm_enabled:cmEnabled,capacity:referenceCapacity,usage_percentage:true });
    save();
  };
  const configure = async (core: string) => {
    await page.goto(`${base}/zh/agents/${state.agent_id}`);
    const label = page.getByText("Agent Core", { exact: true });
    await expect(label).toBeAttached();
    if (!await label.isVisible()) await page.getByText("高级设置", { exact: true }).click();
    const saved = page.waitForResponse(response => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/agent/update"
      && response.request().postDataJSON()?.agent_core === core);
    await page.locator(".ant-select").filter({ has: page.locator("#agent-core") }).click();
    await page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter({ hasText: new RegExp(`^${core === "jiuwen" ? "Jiuwen" : "smolagents"}$`) }).click();
    expect((await saved).status()).toBe(200);
    const published = await page.request.post(`${base}/api/agent/${state.agent_id}/publish`, { data: { version_name: "Real-UI-" + core + "-" + Date.now(), release_note: "Owned real Core switch" } });
    expect(published.status()).toBe(200);
  };
  const enableCM = async () => {
    await page.goto(`${base}/zh/agents/${state.agent_id}`);
    const label=page.getByText("Agent Core",{exact:true});await expect(label).toBeAttached();
    if (!await label.isVisible()) await page.getByText("高级设置",{exact:true}).click();
    const toggle=page.getByRole("switch",{name:"上下文自动压缩",exact:true});
    await expect(toggle).not.toBeChecked();
    const saved=page.waitForResponse(r=>r.request().method()==="POST"&&new URL(r.url()).pathname==="/api/agent/update"&&r.request().postDataJSON()?.enable_context_manager===true);
    await toggle.click();expect((await saved).status()).toBe(200);
    fixture("expect-cm","true");cmEnabled=true;
    const published=await page.request.post(`${base}/api/agent/${state.agent_id}/publish`,{data:{version_name:"Real-UI-CM-on-"+Date.now(),release_note:"Owned CM validation"}});
    expect(published.status()).toBe(200);
  };
  const follow = "只根据本会话之前已经完成的图片分析，衣服主要是什么颜色？同时原样回复先前的验收编号。只用已有历史结果，不要调用任何工具，也不要重新分析图片。";
  const steps = contract.expectedIds("steps");
  await contract.step(steps[0], async () => {
    await openHistory(0);
    await send("smolagents", true, `请调用图片分析工具分析上传图片，说明人物衣服的主要颜色和画面内容。本会话验收编号是${marker}，请记住并在回答末尾原样带上编号。`);
    await openHistory(1); await send("smolagents", false, follow);
  });
  await contract.step(steps[1], async () => {
    await configure("jiuwen"); await openHistory(2); await send("jiuwen", false, follow);
    await send("jiuwen", true, `这是新的图片分析任务，请调用图片分析工具分析本次新上传图片，说明人物衣服主要颜色和画面内容，回答末尾仍带上验收编号${marker}。`);
    await openHistory(4); await send("jiuwen", false, follow);
  });
  await contract.step(steps[2], async () => {
    await configure("smolagents"); await openHistory(5); await send("smolagents", false, follow); await openHistory(6);
    await configure("jiuwen");await enableCM();await openHistory(6);await send("jiuwen",false,follow);
    await configure("smolagents");await openHistory(7);await send("smolagents",false,follow);await openHistory(8);
    for (let index = 0; index < 8; index++) {
      const text = await renderedFinal(roots().nth(index));
      expect(text).toHaveLength(1); expect(text[0]).toContain(marker); expect(text[0]).toContain(input.expected_fact);
      const row=roots().nth(index);await expect(row.locator('[data-token-usage="summary"]')).toHaveCount(0);
      const usage=row.getByRole("button",{name:/\d+%.*本轮/});await expect(usage).toBeVisible();await usage.click();
      await expect(row).toContainText(referenceCapacity.window.toLocaleString("en-US"));await usage.click();
    }
    const signatures = imageViews.map(({ reasoning, tool, finals }) => ({ process: reasoning > 0, tool, finals }));
    expect(signatures).toHaveLength(2); expect(signatures[0]).toEqual(signatures[1]);
    outcomes.push({ kind: "ui", common_components: true, image_views: imageViews, history_reload: true, run_count: runCount }); save();
  });
  await contract.step(steps[3], async () => {
    await configure("jiuwen"); await openHistory(8);
    await send("jiuwen", false, `请调用文件生成子智能体，实际生成并上传 protocol_ui.docx，包含标题及一段正文，正文必须包含验收编号${marker}。最终回答提供文件链接、该验收编号和之前图片的衣服颜色，不要重新分析图片。`, true);
    await openHistory(9);
    await send("jiuwen", false, `只根据之前已完成的任务，回复生成的文档名称、图片衣服颜色和验收编号${marker}。不要调用任何工具或重新生成文件。`);
    await openHistory(10);
    for (let index = 0; index < 10; index++) await renderedFinal(roots().nth(index));
    outcomes.push({kind:"document",actual_docx_verified:true,clean_history:true,no_followup_replay:true}); save();
  });
  const assertions = contract.expectedIds("assertions");
  await contract.assertion(assertions[0], async () => { expect(outcomes.filter(e => e.kind === "turn" && e.upload)).toHaveLength(2); });
  await contract.assertion(assertions[1], async () => { expect(runCount).toBe(10); expect(previous).toHaveLength(20); await expect(page.locator("[data-runtime-output]")).toHaveCount(0); });
  await contract.assertion(assertions[2], async () => { expect(outcomes.some(e=>e.kind==="document"&&e.actual_docx_verified===true&&e.clean_history===true)).toBe(true); });
});
