// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";

journey("JIUWEN-WORKBENCH-HITL-D4-001", async ({ page, expect, contract }) => {
  const config = JSON.parse(
    readFileSync(process.env.NEXENT_REAL_WORKBENCH_HITL_CONFIG!, "utf8"),
  );
  const container = config.container || "nexent-runtime";
  const base = process.env.NEXENT_BASE_URL!;
  const target =
    "/tmp/workbench_hitl_" + randomUUID().replaceAll("-", "").slice(0, 12);
  const privateState = join(contract.caseDir, "private-state.json");
  const docker = (...args: string[]) =>
    execFileSync("docker", args, { encoding: "utf8", timeout: 120000 });
  const fixture = (mode: string, ...args: unknown[]) =>
    JSON.parse(
      docker(
        "exec",
        "-e",
        "PYTHONPATH=/opt/backend",
        container,
        "/opt/backend/.venv/bin/python",
        target + ".py",
        mode,
        target + ".json",
        ...args.map(String),
      )
        .trim()
        .split(/\r?\n/)
        .at(-1)!,
    );
  docker(
    "cp",
    join(
      process.env.NEXENT_REPO!,
      "test-e2e/cases/JIUWEN-WORKBENCH-HITL-D4-001/fixture.py",
    ),
    container + ":" + target + ".py",
  );
  let started = false,
    state: any,
    cid = 0,
    runs = 0,
    form: any,
    pendingAudit: any,
    completedAudit: any,
    cleanup: any;
  let responseIdentity: any,
    continuation = "",
    followUp = "";
  const values: Record<string, string> = {};
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      new URL(request.url()).pathname === "/api/agent/run"
    )
      runs++;
  });
  contract.deferCleanup(async () => {
    try {
      const result = started
        ? fixture("cleanup")
        : { cleanup: true, original_records_unchanged: true };
      writeFileSync(
        join(contract.caseDir, "cleanup.json"),
        JSON.stringify(result),
      );
      expect(result.cleanup).toBe(true);
      expect(result.original_records_unchanged).toBe(true);
    } finally {
      if (existsSync(privateState)) unlinkSync(privateState);
      docker(
        "exec",
        container,
        "python",
        "-c",
        `from pathlib import Path;Path('${target}.py').unlink(missing_ok=True)`,
      );
    }
  });
  const card = () =>
    page.locator('[data-slot="clarification-message"]').first();
  const wireFor = () =>
    page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/agent/run",
      { timeout: 30000 },
    );
  const events = async (response: any) => {
    expect(response.status()).toBe(200);
    cid =
      response.request().postDataJSON().conversation_id ||
      Number(response.headers()["conversation_id"]);
    expect(cid).toBeGreaterThan(0);
    const wire = (await response.text())
      .split(/\r?\n/)
      .filter((line: string) => line.startsWith("data:"))
      .map((line: string) => JSON.parse(line.slice(5)));
    expect(wire.filter((event: any) => event.type === "error")).toEqual([]);
    const terminal = wire.filter(
      (event: any) => event.type === "run_terminal" && !event.invocation_id,
    );
    expect(terminal).toHaveLength(1);
    expect(terminal[0].status, terminal[0].error?.category).toBe("completed");
    expect(terminal[0].agent_core).toBe("jiuwen");
    return wire;
  };
  const send = async (query: string) => {
    await page.getByRole("textbox").last().fill(query);
    const pending = wireFor();
    await page.getByRole("button", { name: "发送", exact: true }).click();
    return pending;
  };
  const history = async () => {
    const response = await page.request.get(`${base}/api/conversation/${cid}`);
    expect(response.ok()).toBe(true);
    const detail = (await response.json()).data[0];
    expect(JSON.stringify(detail)).not.toMatch(
      /JIUWEN_FINAL_OUTPUT_INVALID|NEXENT_TERMINAL_MISSING/,
    );
    return detail;
  };
  const sameAudit = (before: any) => {
    const after = fixture("audit", cid);
    expect(after.messages_hash).toBe(before.messages_hash);
    expect(after.units_hash).toBe(before.units_hash);
  };
  const savedCard = async () => {
    await expect(
      card().getByRole("button", { name: /已提交|Submitted/ }),
    ).toBeDisabled();
    for (const question of form.questions) {
      const input = card().getByRole("textbox", {
        name: question.title,
        exact: true,
      });
      await expect(input).toHaveValue(values[question.id]);
      await expect(input).toBeDisabled();
    }
  };
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      expect(
        (
          await (
            await page.request.get(
              base + "/api/tenant_config/deployment_version",
            )
          ).json()
        ).agent_core,
      ).toBe("jiuwen");
      started = true;
      fixture("setup", config.auth_source_agent_id);
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
  const steps = contract.expectedIds("steps");
  await contract.step(steps[0], async () => {
    await page.goto(base + "/zh/workbench");
    const wire = await events(
      await send(
        `请起草一封技术评审会议通知，参会人是后端研发组。必需的开会日期、开始时间和会议室我尚未提供，请先用一张文本输入澄清卡询问这三项，等我提交后再写，不要自行假设，不要询问其他偏好。测试标记 ${state.marker}。`,
      ),
    );
    const forms = wire.filter(
      (event: any) =>
        event.type === "human_interaction" && !event.invocation_id,
    );
    expect(forms).toHaveLength(1);
    form = JSON.parse(forms[0].content);
    expect(form.questions.length).toBeGreaterThan(0);
    expect(
      form.questions.every((question: any) => question.type === "text"),
    ).toBe(true);
    expect(
      form.questions.every(
        (question: any) => question.creation_request === undefined,
      ),
    ).toBe(true);
    expect(
      wire.find((event: any) => event.type === "run_terminal").end_reason,
    ).toBe("awaiting_input");
    await expect(card()).toBeVisible();
    await expect(
      page.locator('[data-slot="agent-creation-result"]'),
    ).toHaveCount(0);
    await expect(page.getByTestId("workbench-edit-agent-draft")).toHaveCount(0);
    pendingAudit = fixture("audit", cid);
    expect(pendingAudit.mode).toBe("generic_chat");
    expect(pendingAudit.message_count).toBe(2);
  });
  await contract.step(steps[1], async () => {
    await page.goto(`${base}/zh/workbench?thread_id=${cid}`);
    await expect(card()).toBeVisible();
    await expect(
      card().getByRole("button", { name: "提交并继续", exact: true }),
    ).toBeVisible();
    sameAudit(pendingAudit);
    expect(runs).toBe(1);
    for (const question of form.questions) {
      values[question.id] =
        "会议日期为2027年1月20日，开始时间15:30，地点研发楼A301会议室。";
      const input = card().getByRole("textbox", {
        name: question.title,
        exact: true,
      });
      await expect(input).toBeEnabled();
      await input.fill(values[question.id]);
    }
    await expect(
      card().getByRole("button", { name: "提交并继续", exact: true }),
    ).toBeEnabled();
    const pending = wireFor();
    await card()
      .getByRole("button", { name: "提交并继续", exact: true })
      .click();
    const response = await pending;
    responseIdentity = response.request().postDataJSON().clarification_response;
    expect(responseIdentity.form).toEqual(form);
    const wire = await events(response);
    expect(
      wire.filter((event: any) => event.type === "human_interaction"),
    ).toHaveLength(0);
    continuation = wire
      .filter((event: any) => event.type === "final_answer")
      .map((event: any) => event.content)
      .join("");
    expect(continuation).toContain("2027");
    expect(continuation).toContain("A301");
    completedAudit = fixture("audit", cid);
    expect(completedAudit.message_count).toBe(4);
    const detail = await history();
    const saved = detail.message.findLast(
      (message: any) => message.clarification_response,
    )?.clarification_response;
    expect(saved.form).toEqual(responseIdentity.form);
    expect(saved.answers).toEqual(responseIdentity.answers);
    expect(saved.unit_index).toBe(responseIdentity.unit_index);
    expect(saved.source_message_id).toBeGreaterThan(0);
    await savedCard();
  });
  await contract.step(steps[2], async () => {
    await page.reload();
    await savedCard();
    await history();
    sameAudit(completedAudit);
    expect(runs).toBe(2);
    await page.screenshot({
      path: join(contract.caseDir, "submitted-workbench.png"),
      fullPage: true,
    });
    const wire = await events(
      await send(
        "请只复述刚确认的会议日期、开始时间和会议室，不要新增建议或重新提问。",
      ),
    );
    expect(
      wire.filter((event: any) => event.type === "human_interaction"),
    ).toHaveLength(0);
    followUp = wire
      .filter((event: any) => event.type === "final_answer")
      .map((event: any) => event.content)
      .join("");
    expect(followUp).toContain("2027");
    expect(followUp).toContain("A301");
    expect(followUp).toMatch(/15[:：]30|十五点三十|三点半|三点三十/);
    cleanup = fixture("cleanup");
    started = false;
    writeFileSync(
      join(contract.caseDir, "owned-cleanup.json"),
      JSON.stringify(cleanup),
    );
  });
  const assertions = contract.expectedIds("assertions");
  await contract.assertion(assertions[0], async () => {
    expect(form.schema_version).toBe(1);
    expect(pendingAudit.mode).toBe("generic_chat");
    expect(pendingAudit.message_count).toBe(2);
  });
  await contract.assertion(assertions[1], async () => {
    expect(responseIdentity.unit_index).toBeGreaterThanOrEqual(0);
    expect(responseIdentity.answers).toHaveLength(form.questions.length);
    expect(completedAudit.message_count).toBe(4);
  });
  await contract.assertion(assertions[2], async () => {
    expect(runs).toBe(3);
    expect(continuation).toContain("A301");
    expect(followUp).toContain("2027");
    expect(cleanup).toEqual({
      cleanup: true,
      original_records_unchanged: true,
      owned_conversations: 1,
    });
  });
});
