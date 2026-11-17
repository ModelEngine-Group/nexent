// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

journey("JIUWEN-CLARIFICATION-D4-001", async ({ page, contract, expect }) => {
  const config = JSON.parse(
    readFileSync(process.env.NEXENT_REAL_HITL_CONFIG!, "utf8"),
  );
  const base = process.env.NEXENT_BASE_URL || "http://127.0.0.1:3000";
  const container = config.container || "nexent-runtime";
  const target =
    "/tmp/nexent_hitl_" + randomUUID().replaceAll("-", "").slice(0, 12);
  const privateState = join(contract.caseDir, "private-state.json");
  const outcomes: Record<string, unknown>[] = [];
  const save = () =>
    writeFileSync(
      join(contract.caseDir, "outcomes.json"),
      JSON.stringify(outcomes, null, 2),
    );
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
      "test-e2e/cases/JIUWEN-CLARIFICATION-D4-001/fixture.py",
    ),
    container + ":" + target + ".py",
  );
  let state: any,
    cid = 0,
    runs = 0;
  let setupAttempted = false;
  let form: any,
    secondWire: any[] = [],
    thirdWire: any[] = [];
  let first: any, continued: any, restored: any, finalAudit: any;
  const submitted: Record<string, string> = {};
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
      const result = setupAttempted
        ? fixture("cleanup")
        : {
            cleanup: true,
            source_unchanged: true,
            source_history_unchanged: true,
          };
      outcomes.push(result);
      save();
      expect(result.cleanup).toBe(true);
      expect(result.source_unchanged).toBe(true);
      expect(result.source_history_unchanged).toBe(true);
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
  const labels = JSON.parse(
    readFileSync(
      join(process.env.NEXENT_REPO!, "frontend/public/locales/zh/common.json"),
      "utf8",
    ),
  );
  const card = () =>
    page.locator('[data-slot="clarification-message"]').first();
  const answers = () =>
    page.locator('[data-slot="aui_assistant-message-root"]');
  const wireFor = () =>
    page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname === "/api/agent/run",
      { timeout: 30000 },
    );
  const events = async (response: Awaited<ReturnType<typeof wireFor>>) => {
    expect(response.status()).toBe(200);
    cid =
      response.request().postDataJSON().conversation_id ||
      Number(response.headers()["conversation_id"]);
    expect(cid).toBeGreaterThan(0);
    const result = (await response.body())
      .toString("utf8")
      .split(/\r?\n/)
      .filter((line) => line.startsWith("data:"))
      .map((line) => JSON.parse(line.slice(5).trim()));
    expect(result.filter((event) => event.type === "error")).toEqual([]);
    const terminal = result.filter(
      (event) => event.type === "run_terminal" && !event.invocation_id,
    );
    expect(terminal).toHaveLength(1);
    expect(terminal[0].status, terminal[0].error?.category).toBe("completed");
    expect(terminal[0].agent_core).toBe("jiuwen");
    return result;
  };
  const send = async (query: string) => {
    await page.getByRole("textbox").last().fill(query);
    const promise = wireFor();
    await page.getByRole("button", { name: "发送", exact: true }).click();
    return promise;
  };
  const savedCard = async () => {
    await expect(card()).toBeVisible();
    await expect(
      card().getByRole("button", { name: /已提交|Submitted/ }),
    ).toBeDisabled();
    for (const question of form.questions) {
      if (question.type === "text") {
        const input = card().getByRole("textbox", {
          name: question.title,
          exact: true,
        });
        await expect(input).toHaveValue(submitted[question.id]);
        await expect(input).toBeDisabled();
      } else {
        const role = question.type === "single_choice" ? "radio" : "checkbox";
        const selected = card().getByRole(role, {
          name: submitted[question.id],
          exact: true,
        });
        await expect(selected).toBeChecked();
        await expect(selected).toBeDisabled();
      }
    }
  };
  const validWaitingHistory = async () => {
    const response = await page.request.get(`${base}/api/conversation/${cid}`);
    expect(response.status()).toBe(200);
    const body = await response.json();
    expect(JSON.stringify(body)).not.toContain("JIUWEN_FINAL_OUTPUT_INVALID");
    const terminals: any[] = [];
    const visit = (value: any) => {
      if (typeof value === "string") {
        try {
          visit(JSON.parse(value));
        } catch {
          /* Plain message text is not a runtime event. */
        }
      } else if (value && typeof value === "object") {
        if (
          value.type === "run_terminal" &&
          value.end_reason === "awaiting_input"
        )
          terminals.push(value);
        for (const entry of Object.values(value)) visit(entry);
      }
    };
    visit(body);
    expect(terminals).toHaveLength(1);
    expect(terminals[0].status).toBe("completed");
    expect(terminals[0].final_content).toBe("");
    expect(terminals[0].final_block_ids).toEqual([]);
    expect(terminals[0].error).toBeNull();
    await expect(
      page.getByText("JIUWEN_FINAL_OUTPUT_INVALID", { exact: true }),
    ).toHaveCount(0);
  };
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      const deployed = await (
        await page.request.get(base + "/api/tenant_config/deployment_version")
      ).json();
      expect(deployed.agent_core).toBe("jiuwen");
      setupAttempted = true;
      expect(
        fixture("setup", config.source_agent_id).same_model_and_config,
      ).toBe(true);
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
    await page.goto(`${base}/zh/agents/${state.agent_id}`);
    const cm = page.getByText(labels["agent.core.contextManager"], {
      exact: true,
    });
    await expect(cm).toBeAttached();
    if (!(await cm.isVisible()))
      await page
        .getByText(labels["agent.highFidelity.advancedTitle"], { exact: true })
        .click();
    await expect(page.locator("#agent-core")).toHaveCount(0);
    await expect(
      page.getByText(labels["agent.core.label"], { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByRole("switch", { name: labels["agent.core.contextManager"] }),
    ).toBeVisible();
    await page.screenshot({
      path: join(contract.caseDir, "settings-no-core.png"),
    });
    outcomes.push({
      no_core_setting: true,
      deployment_core: "jiuwen",
      source_models: state.source_models,
    });
    save();
  });
  await contract.step(steps[1], async () => {
    await page.goto(`${base}/zh/newchat?agent_id=${state.agent_id}`);
    const response = await send("我的感情运势如何？");
    await expect(card()).toBeVisible({ timeout: 180000 });
    const wire = await events(response);
    const forms = wire.filter(
      (event) => event.type === "human_interaction" && !event.invocation_id,
    );
    expect(forms).toHaveLength(1);
    form =
      typeof forms[0].content === "string"
        ? JSON.parse(forms[0].content)
        : forms[0].content;
    expect(form.schema_version).toBe(1);
    expect(form.questions.length).toBeGreaterThan(0);
    expect(wire.filter((event) => event.type === "final_answer")).toHaveLength(
      0,
    );
    expect(wire.filter((event) => event.type === "tool")).toHaveLength(0);
    first = fixture("audit", cid);
    expect(first.message_count).toBe(2);
    expect(first.forms).toHaveLength(1);
    expect(first.terminals[0].end_reason).toBe("awaiting_input");
    const before = runs;
    await page.goto(`${base}/zh/newchat?thread_id=${cid}`);
    await expect(
      card().getByRole("button", { name: /提交并继续|Submit and continue/ }),
    ).toBeVisible();
    await expect(card().locator("input, textarea").first()).toBeEnabled();
    await validWaitingHistory();
    expect(runs).toBe(before);
    const pending = fixture("audit", cid);
    expect(pending.messages_hash).toBe(first.messages_hash);
    expect(pending.units_hash).toBe(first.units_hash);
    await page.screenshot({
      path: join(contract.caseDir, "clarification-live.png"),
      fullPage: true,
    });
    outcomes.push({
      live_card: true,
      terminal: "awaiting_input",
      message_count: 2,
    });
    save();
  });
  await contract.step(steps[2], async () => {
    for (const question of form.questions) {
      const hint = question.title + " " + question.id;
      if (question.type === "text") {
        let value =
          "公历1998年6月15日，上午9点30分，性别女，出生地杭州，目前单身。";
        const date = /日期|年月|生日|date|birthdate/i.test(hint),
          time = /时间|几点|时辰|time/i.test(hint),
          sex = /性别|gender|sex/i.test(hint);
        if (date && !time && !sex) value = "公历1998年6月15日";
        else if (time && !date && !sex) value = "上午9点30分（09:30）";
        else if (sex && !date && !time) value = "女";
        else if (/出生地|地点|城市|place|city/i.test(hint)) value = "杭州";
        submitted[question.id] = value;
        await card()
          .getByRole("textbox", { name: question.title, exact: true })
          .fill(value);
      } else {
        const options = question.options;
        const option =
          options.find((entry: any) =>
            /女|female|公历|阳历|Gregorian|单身/i.test(entry.label),
          ) || options[0];
        submitted[question.id] = option.label;
        await card()
          .getByRole(question.type === "single_choice" ? "radio" : "checkbox", {
            name: option.label,
            exact: true,
          })
          .check();
      }
    }
    const promise = wireFor();
    await expect(
      card().getByRole("button", { name: /提交并继续|Submit and continue/ }),
    ).toBeEnabled();
    await card()
      .getByRole("button", { name: /提交并继续|Submit and continue/ })
      .click();
    const response = await promise;
    expect(
      response.request().postDataJSON().clarification_response.unit_index,
    ).toBe(first.forms[0].unit_index);
    secondWire = await events(response);
    expect(
      secondWire.filter((event) => event.type === "human_interaction"),
    ).toHaveLength(0);
    expect(
      secondWire.filter((event) => event.type === "final_answer"),
    ).toHaveLength(1);
    continued = fixture("audit", cid);
    expect(continued.message_count).toBe(4);
    expect(continued.responses).toHaveLength(1);
    expect(continued.responses[0].source_message_id).toBe(
      first.forms[0].source_message_id,
    );
    expect(continued.responses[0].unit_index).toBe(first.forms[0].unit_index);
    await savedCard();
    await expect(answers().last()).not.toBeEmpty();
    outcomes.push({
      submitted_once: true,
      answer_persisted: true,
      successful_continuation: true,
    });
    save();
  });
  await contract.step(steps[3], async () => {
    const before = runs;
    // agent_id is an explicit new-chat entry; the persisted history route identifies this conversation.
    await page.goto(`${base}/zh/newchat?thread_id=${cid}`);
    await savedCard();
    await page.reload();
    await savedCard();
    await validWaitingHistory();
    await page.goto(`${base}/zh/newchat?thread_id=${cid}`);
    await savedCard();
    expect(runs).toBe(before);
    restored = fixture("audit", cid);
    expect(restored.messages_hash).toBe(continued.messages_hash);
    expect(restored.units_hash).toBe(continued.units_hash);
    thirdWire = await events(
      await send("请只复述我刚才提供的出生日期和时间，不要重新计算。"),
    );
    expect(
      thirdWire.filter((event) =>
        ["human_interaction", "tool"].includes(event.type),
      ),
    ).toHaveLength(0);
    const answer = thirdWire.find(
      (event) => event.type === "run_terminal" && !event.invocation_id,
    ).final_content;
    expect(answer).toContain("1998");
    expect(answer).toMatch(/6[月\/-]15|六月十五/);
    expect(answer).toMatch(
      /0?9[：:]30|(?:9|九)(?:点(?:30|三十)|时(?:30|三十)|点半)|九时三十分/,
    );
    finalAudit = fixture("audit", cid);
    expect(finalAudit.message_count).toBe(6);
    expect(finalAudit.forms).toHaveLength(1);
    expect(finalAudit.responses).toHaveLength(1);
    await page.reload();
    await savedCard();
    await validWaitingHistory();
    expect(runs).toBe(before + 1);
    await expect(
      page.getByText(labels.modelProfile.modelUnavailable, { exact: true }),
    ).toHaveCount(0);
    await page.screenshot({
      path: join(contract.caseDir, "clarification-restored.png"),
      fullPage: true,
    });
    outcomes.push({
      history_reload: true,
      history_unchanged: true,
      followup_recalled_birth: true,
      runs,
    });
    save();
  });
  const assertions = contract.expectedIds("assertions");
  await contract.assertion(assertions[0], async () => {
    expect(runs).toBe(3);
    expect(first.forms).toHaveLength(1);
    expect(errors).toEqual([]);
  });
  await contract.assertion(assertions[1], async () => {
    expect(continued.responses).toHaveLength(1);
    expect(
      finalAudit.message_statuses.every(
        (status: string) => status === "completed",
      ),
    ).toBe(true);
  });
  await contract.assertion(assertions[2], async () => {
    expect(restored.messages_hash).toBe(continued.messages_hash);
    expect(finalAudit.message_count).toBe(6);
  });
});
