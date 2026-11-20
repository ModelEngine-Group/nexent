// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, unlinkSync, existsSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

journey("CHAT-RETRY-HISTORY-D4-001", async ({ page, contract, expect }) => {
  const input = JSON.parse(
    readFileSync(process.env.NEXENT_REAL_UI_CONFIG!, "utf8"),
  );
  const base = process.env.NEXENT_BASE_URL || "http://127.0.0.1:3000";
  const container = input.container || "nexent-runtime";
  const target =
    "/tmp/nexent_retry_" + randomUUID().replaceAll("-", "").slice(0, 12);
  const stateFile = join(contract.caseDir, "private-state.json");
  const outcomes: any[] = [];
  const save = () =>
    writeFileSync(
      join(contract.caseDir, "retry-outcomes.json"),
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
    ["CHAT-RETRY-HISTORY-D4-001/fixture.py", ".py"],
    ["JIUWEN-REAL-UI-D4-001/fixture.py", "_helper.py"],
  ]) {
    docker(
      "cp",
      join(process.env.NEXENT_REPO!, "test-e2e/cases", source),
      container + ":" + target + suffix,
    );
  }
  let state: any;
  let runs = 0;
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
      if (existsSync(stateFile)) unlinkSync(stateFile);
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
          input.source_agent_id,
          input.user_id,
          input.source_message_id,
        ).setup,
      ).toBe(true);
      docker("cp", container + ":" + target + ".json", stateFile);
      state = JSON.parse(readFileSync(stateFile, "utf8"));
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
  const users = () => page.locator('[data-slot="aui_user-message-root"]');
  const answers = () =>
    page.locator('[data-slot="aui_assistant-message-root"]');
  const counter = (index = 0) =>
    answers().nth(index).locator(".aui-branch-picker-root");
  const records = (cid: number) => fixture("check", cid).messages;
  const open = async (cid?: number) => {
    const count = runs;
    await page.goto(
      `${base}/zh/newchat?${cid ? "thread_id=" + cid : "agent_id=" + state.agent_id}`,
    );
    await expect(page.getByRole("textbox").last()).toBeVisible();
    if (cid) await expect(answers().first()).toBeVisible();
    expect(runs).toBe(count);
  };
  const request = async (action: () => Promise<unknown>, streaming = false) => {
    const wire = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/agent/run",
      { timeout: 30000 },
    );
    await action();
    const response = await wire;
    expect(response.status()).toBe(200);
    const body = response.request().postDataJSON();
    const cid =
      body.conversation_id || Number(response.headers()["conversation_id"]);
    expect(cid).toBeGreaterThan(0);
    if (!streaming) {
      const events = (await response.body())
        .toString("utf8")
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data:"))
        .map((line) => JSON.parse(line.slice(5).trim()));
      expect(events.filter((event) => event.type === "error")).toEqual([]);
      await expect(
        answers()
          .last()
          .locator('[data-slot="aui_assistant-message-completion-indicator"]'),
      ).toBeVisible();
      await expect.poll(() => records(cid).at(-1)?.status).toBe("completed");
    }
    return { cid, body };
  };
  const send = async (text: string) => {
    await page.getByRole("textbox").last().fill(text);
    return request(() =>
      page.getByRole("button", { name: "发送", exact: true }).click(),
    );
  };
  const retry = (streaming = false) =>
    request(
      () =>
        answers()
          .last()
          .getByRole("button", { name: "刷新", exact: true })
          .click(),
      streaming,
    );
  const completed: {
    core: string;
    cid: number;
    marker: string;
    question: string;
    original: any[];
  }[] = [];
  const steps = contract.expectedIds("steps");
  await contract.step(steps[0], async () => {
    for (const core of ["smolagents", "jiuwen"]) {
      expect(fixture("select-core", core).configured_core).toBe(core);
      await open();
      const marker = "RETRY_" + core + "_" + randomUUID().slice(0, 8);
      const question = `不要调用工具，只回复“重试验收 ${marker}”，不要补充其他内容。`;
      const first = await send(question);
      for (let count = 2; count <= 3; count++) {
        const result = await retry();
        expect(result.cid).toBe(first.cid);
        expect(result.body.retry_user_message_id).toBeGreaterThan(0);
        await expect(counter()).toContainText(`${count} / ${count}`);
      }
      const rows = records(first.cid);
      expect(rows.filter((row: any) => row.role === "user")).toHaveLength(1);
      expect(
        rows
          .filter((row: any) => row.role === "assistant")
          .map((row: any) => row.index),
      ).toEqual([1, 1, 1]);
      completed.push({
        core,
        cid: first.cid,
        marker,
        question,
        original: rows,
      });
      outcomes.push({
        core,
        completed_retry: true,
        saved_user_rows: 1,
        saved_answers: 3,
      });
      save();
    }
  });
  await contract.step(steps[1], async () => {
    for (const item of completed) {
      fixture("select-core", item.core);
      await open(item.cid);
      const before = runs;
      await page.reload();
      await expect(counter()).toContainText("3 / 3");
      await expect(users()).toHaveCount(1);
      await expect(answers()).toHaveCount(1);
      const buttons = counter().getByRole("button");
      await buttons.first().click();
      await expect(counter()).toContainText("2 / 3");
      await buttons.first().click();
      await expect(counter()).toContainText("1 / 3");
      await buttons.last().click();
      await buttons.last().click();
      await expect(counter()).toContainText("3 / 3");
      expect(runs).toBe(before);
      await send(item.question);
      const rows = records(item.cid);
      expect(
        rows
          .filter((row: any) => row.role === "user")
          .map((row: any) => row.index),
      ).toEqual([0, 2]);
      expect(rows.filter((row: any) => row.role === "assistant")).toHaveLength(
        4,
      );
      expect(
        rows.filter((row: any) =>
          item.original.some((old) => old.id === row.id),
        ),
      ).toEqual(item.original);
      await open(item.cid);
      await page.reload();
      await expect(users()).toHaveCount(2);
      await expect(answers()).toHaveCount(2);
      await expect(counter()).toContainText("3 / 3");
      outcomes.push({
        core: item.core,
        completed_reload: true,
        branch_navigation: true,
        independent_equal_question: true,
      });
      save();
    }
  });
  await contract.step(steps[2], async () => {
    for (const core of ["smolagents", "jiuwen"]) {
      fixture("select-core", core);
      await open();
      const marker = "STREAM_" + core + "_" + randomUUID().slice(0, 8);
      const first = await send(
        `不要调用任何工具。请按1到120逐行写中文简短说明，每行至少10字，最后单独写${marker}。`,
      );
      await retry();
      await retry(true);
      await expect
        .poll(
          () =>
            records(first.cid).filter((row: any) => row.role === "assistant")
              .length,
        )
        .toBe(3);
      const before = records(first.cid);
      expect(
        before.filter((row: any) => row.role === "assistant").at(-1).status,
      ).toBe("streaming");
      // Enter canonical history while the same backend answer is still running.
      const reconnect = page.waitForResponse(
        (response) => {
          const url = new URL(response.url());
          return (
            response.request().method() === "POST" &&
            url.pathname === "/api/agent/run" &&
            url.searchParams.get("resume") === "true"
          );
        },
        { timeout: 30000 },
      );
      await page.goto(`${base}/zh/newchat?thread_id=${first.cid}`);
      expect((await reconnect).status()).toBe(200);
      await expect(counter()).toContainText("3 / 3");
      await expect(users()).toHaveCount(1);
      await expect(answers()).toHaveCount(1);
      await expect
        .poll(
          () =>
            records(first.cid).find((row: any) => row.id === before.at(-1).id)
              ?.status,
          { timeout: 180000 },
        )
        .toBe("completed");
      await expect(
        answers()
          .last()
          .locator('[data-slot="aui_assistant-message-completion-indicator"]'),
      ).toBeVisible({ timeout: 180000 });
      await open(first.cid);
      await page.reload();
      await expect(counter()).toContainText("3 / 3");
      const after = records(first.cid);
      expect(after.map((row: any) => row.id)).toEqual(
        before.map((row: any) => row.id),
      );
      expect(after.filter((row: any) => row.role === "assistant")).toHaveLength(
        3,
      );
      outcomes.push({
        core,
        streaming_resume: true,
        live_reconnect_completed: true,
        same_persisted_answer: true,
        no_fourth_branch: true,
      });
      save();
    }
  });
  const assertions = contract.expectedIds("assertions");
  await contract.assertion(assertions[0], async () => {
    expect(
      outcomes.filter(
        (row) => row.independent_equal_question && row.branch_navigation,
      ),
    ).toHaveLength(2);
  });
  await contract.assertion(assertions[1], async () => {
    expect(
      outcomes.filter((row) => row.streaming_resume && row.no_fourth_branch),
    ).toHaveLength(2);
  });
});
