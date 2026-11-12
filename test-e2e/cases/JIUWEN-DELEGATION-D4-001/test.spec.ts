// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

journey("JIUWEN-DELEGATION-D4-001", async ({ page, contract, expect }) => {
  const config = JSON.parse(
    readFileSync(process.env.NEXENT_REAL_UI_CONFIG!, "utf8"),
  );
  const base = process.env.NEXENT_BASE_URL || "http://127.0.0.1:3000";
  const container = config.container || "nexent-runtime";
  const core = process.env.NEXENT_DELEGATION_CORE || "jiuwen";
  expect(["jiuwen", "smolagents"]).toContain(core);
  const target =
    "/tmp/nexent_delegate_" + randomUUID().replaceAll("-", "").slice(0, 12);
  const privateState = join(contract.caseDir, "private-state.json");
  const marker = "DELEGATION_" + randomUUID().slice(0, 8);
  const outcomes: Record<string, unknown>[] = [{ configured_core: core }];
  const save = () =>
    writeFileSync(
      join(contract.caseDir, "delegation-outcomes.json"),
      JSON.stringify(outcomes, null, 2),
    );
  const docker = (...args: string[]) =>
    execFileSync("docker", args, {
      encoding: "utf8",
      timeout: 120000,
      stdio: ["ignore", "pipe", "pipe"],
    });
  const fixture = (mode: string, ...args: unknown[]) =>
    JSON.parse(
      docker(
        "exec",
        "-e",
        "PYTHONPATH=/opt/backend",
        "-w",
        "/opt/backend",
        container,
        "/opt/backend/.venv/bin/python",
        target + ".py",
        mode,
        target + ".json",
        target + "_helper.py",
        ...args.map(String),
      )
        .trim()
        .split(/\r?\n/)
        .at(-1)!,
    );
  for (const [source, suffix] of [
    ["JIUWEN-DELEGATION-D4-001/fixture.py", ".py"],
    ["JIUWEN-REAL-UI-D4-001/fixture.py", "_helper.py"],
  ]) {
    docker(
      "cp",
      join(process.env.NEXENT_REPO!, "test-e2e/cases", source),
      container + ":" + target + suffix,
    );
  }
  let state: any;
  let cid = 0;
  let runs = 0;
  let original: unknown[] = [];
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.name));
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/agent/run"
    )
      runs++;
  });
  contract.deferCleanup(async () => {
    try {
      const cleaned = fixture("cleanup");
      outcomes.push(cleaned);
      save();
      expect(cleaned.cleanup).toBe(true);
      expect(cleaned.source_unchanged).toBe(true);
    } finally {
      if (existsSync(privateState)) unlinkSync(privateState);
      docker(
        "exec",
        container,
        "/opt/backend/.venv/bin/python",
        "-c",
        `from pathlib import Path;[Path('${target}'+s).unlink(missing_ok=True) for s in ['.py','_helper.py']]`,
      );
    }
  });
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      expect(
        fixture(
          "setup",
          config.source_agent_id,
          config.user_id,
          config.source_message_id,
        ).setup,
      ).toBe(true);
      expect(fixture("select-core", core).configured_core).toBe(core);
      docker("cp", container + ":" + target + ".json", privateState);
      state = JSON.parse(readFileSync(privateState, "utf8"));
      await page.context().addCookies([
        {
          name: "nexent_access_token",
          value: state.access_token,
          url: base,
          httpOnly: true,
          sameSite: "Lax",
          expires: state.expires_at,
        },
        {
          name: "nexent_token_expires_at",
          value: String(state.expires_at),
          url: base,
          sameSite: "Lax",
          expires: state.expires_at,
        },
      ]);
    },
  );
  const answers = () =>
    page.locator('[data-slot="aui_assistant-message-root"]');
  const child = () =>
    answers().first().locator("[data-subagent-run-id]").first();
  const openChildGroup = async () => {
    const group = answers()
      .first()
      .getByRole("button", { name: "1 subagent call", exact: true });
    await expect(group).toBeVisible();
    if ((await group.getAttribute("data-state")) === "closed")
      await group.click();
  };
  const send = async (query: string) => {
    await page.getByRole("textbox").last().fill(query);
    const wire = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/agent/run",
      { timeout: 30000 },
    );
    await page.getByRole("button", { name: "发送", exact: true }).click();
    const response = await wire;
    expect(response.status()).toBe(200);
    cid =
      response.request().postDataJSON().conversation_id ||
      Number(response.headers()["conversation_id"]);
    expect(cid).toBeGreaterThan(0);
    return response;
  };
  const events = async (response: Awaited<ReturnType<typeof send>>) =>
    (await response.body())
      .toString("utf8")
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => JSON.parse(line.slice(5).trim()));
  const steps = contract.expectedIds("steps");
  await contract.step(steps[0], async () => {
    await page.goto(`${base}/zh/newchat?agent_id=${state.agent_id}`);
    const response = await send(
      `调用子智能体，帮我生成一个docx文件，简单写点内容就行。文档正文必须包含验证标记 ${marker}，最后回答也请包含此标记和下载链接。`,
    );
    await expect(child()).toBeVisible({ timeout: 180000 });
    await expect(child().getByText("Running", { exact: true })).toBeVisible();
    await page.screenshot({ path: join(contract.caseDir, "child-live.png") });
    const wire = await events(response);
    expect(wire.filter((event) => event.type === "error")).toEqual([]);
    const terminals = wire.filter(
      (event) => event.type === "run_terminal" && !event.invocation_id,
    );
    if (core === "jiuwen") {
      expect(terminals).toHaveLength(1);
      expect(terminals[0].status, terminals[0].error?.category).toBe(
        "completed",
      );
    }
    expect(
      wire.filter(
        (event) =>
          event.type === "final_answer" &&
          (core === "jiuwen" || event.answer_phase === "complete") &&
          !event.invocation_id,
      ),
    ).toHaveLength(1);
    const starts = wire.filter((event) => event.type === "subagent_start");
    const ends = wire.filter((event) => event.type === "subagent_end");
    expect(starts).toHaveLength(1);
    expect(ends).toHaveLength(1);
    const invocation = JSON.parse(starts[0].content).invocation_id;
    expect(JSON.parse(ends[0].content).invocation_id).toBe(invocation);
    expect(
      wire.filter((event) => event.invocation_id === invocation).length,
    ).toBeGreaterThan(0);
    expect(
      wire
        .slice(0, wire.indexOf(ends[0]) + 1)
        .filter(
          (event) =>
            event.type === "tool" &&
            event.tool_name === "nexent_execute_python" &&
            !event.invocation_id,
        ),
    ).toEqual([]);
    expect(fixture("verify-docx", cid, marker).downloaded_docx_verified).toBe(
      true,
    );
    await expect(child().getByText("Completed", { exact: true })).toBeVisible();
    await expect(answers().first()).toContainText(marker);
    const saved = fixture("nested", cid);
    expect(saved.starts).toBe(1);
    expect(saved.ends).toBe(1);
    expect(saved.nested_units).toBeGreaterThan(0);
    expect(saved.messages.map((row: any) => row.status)).toEqual([
      "completed",
      "completed",
    ]);
    original = saved.messages;
    outcomes.push({
      actual_child: true,
      live_running_card: true,
      matched_boundaries: true,
      child_attributed_output: true,
      downloaded_docx_verified: true,
    });
    save();
  });
  await contract.step(steps[1], async () => {
    const before = runs;
    await page.goto(`${base}/zh/newchat?thread_id=${cid}`);
    await page.reload();
    await openChildGroup();
    await expect(child()).toBeVisible();
    await expect(child().getByText("Completed", { exact: true })).toBeVisible();
    const trigger = child().locator("button").first();
    if ((await trigger.getAttribute("data-state")) === "closed")
      await trigger.click();
    await expect(child()).toContainText("docx");
    await expect(answers().first()).toContainText(marker);
    expect(fixture("nested", cid).messages).toEqual(original);
    expect(runs).toBe(before);
    await page.screenshot({
      path: join(contract.caseDir, "child-history.png"),
    });
    outcomes.push({
      historical_child: true,
      identical_rows: true,
      no_history_execution: true,
    });
    save();
  });
  await contract.step(steps[2], async () => {
    const wire = await events(
      await send(
        "不要再次生成文件或调用工具。请根据上一轮结果，只回复文件名和文档中的验证标记。",
      ),
    );
    expect(
      wire.filter((event) =>
        ["error", "tool", "subagent_start"].includes(event.type),
      ),
    ).toEqual([]);
    await expect(answers().last()).toContainText(marker);
    await page.reload();
    await expect(answers()).toHaveCount(2);
    await openChildGroup();
    await expect(child()).toBeVisible();
    expect(fixture("nested", cid).messages.slice(0, 2)).toEqual(original);
    expect(errors).toEqual([]);
    outcomes.push({ followup_without_replay: true, source_isolated: true });
    save();
  });
  const assertions = contract.expectedIds("assertions");
  await contract.assertion(assertions[0], async () =>
    expect(
      outcomes.some(
        (row) =>
          row.actual_child &&
          row.live_running_card &&
          row.downloaded_docx_verified,
      ),
    ).toBe(true),
  );
  await contract.assertion(assertions[1], async () =>
    expect(
      outcomes.some((row) => row.historical_child && row.no_history_execution),
    ).toBe(true),
  );
  await contract.assertion(assertions[2], async () =>
    expect(outcomes.some((row) => row.followup_without_replay)).toBe(true),
  );
});
