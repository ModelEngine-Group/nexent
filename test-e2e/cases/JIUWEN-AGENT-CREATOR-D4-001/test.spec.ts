// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, unlinkSync, existsSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

journey("JIUWEN-AGENT-CREATOR-D4-001", async ({ page, expect, contract }) => {
  const config = JSON.parse(
    readFileSync(process.env.NEXENT_REAL_AGENT_CREATOR_CONFIG!, "utf8"),
  );
  const locale = config.locale || "zh";
  expect(["zh", "en"]).toContain(locale);
  const labels =
    locale === "zh"
      ? {
          create: "智能体创建",
          send: "发送",
          submit: "提交",
          submitted: "已提交",
          summary: "已提交需求信息",
        }
      : {
          create: "Create Agent",
          send: "Send",
          submit: "Submit",
          submitted: "Submitted",
          summary: "Requirements submitted",
        };
  const container = config.container || "nexent-runtime";
  const target =
    "/tmp/agent_card_" + randomUUID().replaceAll("-", "").slice(0, 12);
  const privateState = join(contract.caseDir, "private-state.json");
  const base = process.env.NEXENT_BASE_URL || "http://127.0.0.1:3000";
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
      "test-e2e/cases/JIUWEN-AGENT-CREATOR-D4-001/fixture.py",
    ),
    container + ":" + target + ".py",
  );
  let setup = false,
    state: any,
    cid = 0,
    runs = 0,
    audit: any;
  let resumed = false,
    historyVerified = false,
    cleanupResult: any,
    submittedAction: any,
    clarification: any;
  let selectedCore: "jiuwen" | "smolagents";
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/nl2agent/run"))
      runs++;
  });
  contract.deferCleanup(async () => {
    try {
      const result = setup
        ? fixture("cleanup")
        : { cleanup: true, original_history_unchanged: true };
      writeFileSync(
        join(contract.caseDir, "cleanup.json"),
        JSON.stringify(result),
      );
      expect(result.cleanup).toBe(true);
      expect(result.original_history_unchanged).toBe(true);
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
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      selectedCore = (
        await (
          await page.request.get(base + "/api/tenant_config/deployment_version")
        ).json()
      ).agent_core;
      expect(["smolagents", "jiuwen"]).toContain(selectedCore);
      setup = true;
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
  const card = () =>
    page.locator("[data-slot='aui-requirement-clarification']").first();
  const events = async (response: any) => {
    expect(response.ok()).toBe(true);
    return (await response.text())
      .split(/\r?\n/)
      .filter((line: string) => line.startsWith("data:"))
      .map((line: string) => JSON.parse(line.slice(5)));
  };
  const publicHistory = async () => {
    const response = await page.request.get(`${base}/api/conversation/${cid}`);
    expect(response.ok()).toBe(true);
    const body = await response.json();
    const messages = body.data[0].message.filter(
      (m: any) => m.role === "assistant",
    );
    expect(messages.length).toBeGreaterThan(0);
    for (const message of messages) {
      expect(message.status).toBe("completed");
      expect(message.message.filter((p: any) => p.type === "error")).toEqual(
        [],
      );
    }
    const parts = messages[0].message;
    expect(parts.filter((p: any) => p.type === "nl2a")).toHaveLength(1);
    const terminals = parts
      .filter((p: any) => p.type === "run_terminal")
      .map((p: any) => JSON.parse(p.content));
    if (selectedCore === "jiuwen") {
      expect(terminals).toHaveLength(1);
      expect(terminals[0].end_reason).toBe("awaiting_input");
      expect(terminals[0].error).toBeNull();
    }
    if (messages.length > 1) {
      const actions = body.data[0].message
        .filter((m: any) => m.role === "user")
        .map((m: any) =>
          typeof m.message === "string"
            ? m.message
            : m.message
                .filter((p: any) => p.type === "text")
                .map((p: any) => p.content)
                .join("\n"),
        )
        .map((text: string) => {
          try {
            return JSON.parse(text);
          } catch {
            return null;
          }
        })
        .filter((action: any) => action?.type === "nl2agent_card_action");
      expect(actions).toHaveLength(1);
      expect(actions[0].result.answers.length).toBeGreaterThan(0);
      expect(actions[0].result.answers).toEqual(submittedAction.result.answers);
    }
  };
  const noErrors = async () => {
    await expect(
      page.getByText(
        /NEXENT_(?:TERMINAL_MISSING|TOOL_RESULT_UNPAIRED|TOOL_RESULT_MISSING)|JIUWEN_FINAL_OUTPUT_INVALID/,
      ),
    ).toHaveCount(0);
  };
  await contract.step(steps[0], async () => {
    await page.goto(`${base}/${locale}/workbench`);
    await page
      .getByRole("button", { name: labels.create, exact: true })
      .click();
    await page
      .getByRole("textbox")
      .last()
      .fill(
        `请创建一个简单文本整理智能体，名称 ${state.name}。标记 ${state.marker}。我还没有确定具体用途、服务对象和输出格式，请先只通过 nl2a_wrapper 的需求澄清卡向我确认，收到提交后才生成。不要提前写入描述和提示词。无需工具、Skill、知识库或外部资源。`,
      );
    const pending = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" && r.url().includes("/nl2agent/run"),
      { timeout: 30000 },
    );
    await page.getByRole("button", { name: labels.send, exact: true }).click();
    const response = await pending;
    cid =
      response.request().postDataJSON().conversation_id ||
      Number(response.headers()["conversation_id"]);
    const stream = await events(response);
    expect(stream.filter((e: any) => e.type === "nl2a")).toHaveLength(1);
    const rawCard = stream.find((e: any) => e.type === "nl2a").content;
    clarification = typeof rawCard === "string" ? JSON.parse(rawCard) : rawCard;
    if (selectedCore === "jiuwen")
      expect(
        stream.some(
          (e: any) => e.type === "tool" && e.tool_name === "nl2a_wrapper",
        ),
      ).toBe(true);
    expect(stream.filter((e: any) => e.type === "error")).toEqual([]);
    const terminal = stream.find((e: any) => e.type === "run_terminal");
    if (selectedCore === "jiuwen")
      expect(terminal?.end_reason).toBe("awaiting_input");
    await expect(card()).toBeVisible();
    await expect(
      card().getByRole("button", { name: labels.submit, exact: true }),
    ).toBeVisible();
    await noErrors();
    audit = fixture("audit", cid);
    expect(audit.mode).toBe("agent_create");
    expect(audit.description || "").toBe("");
    expect(audit.prompt || "").toBe("");
    expect(runs).toBe(1);
    await expect(
      page.locator('[data-slot="agent-creation-result"]'),
    ).toHaveCount(0);
    await expect(page.getByText("草稿已保存", { exact: true })).toHaveCount(0);
    const draftLink = page.getByTestId("workbench-edit-agent-draft");
    await expect(draftLink).toHaveAttribute(
      "href",
      `/${locale}/agents/${audit.target_id}`,
    );
  });
  await contract.step(steps[1], async () => {
    await page.goto(`${base}/${locale}/workbench?thread_id=${cid}`);
    await expect(card()).toBeVisible();
    await publicHistory();
    await expect(
      page.locator('[data-slot="agent-creation-result"]'),
    ).toHaveCount(0);
    await page.getByTestId("workbench-edit-agent-draft").click();
    await expect(page).toHaveURL(
      new RegExp(`/${locale}/agents/${audit.target_id}$`),
    );
    await page.goto(`${base}/${locale}/workbench?thread_id=${cid}`);
    await expect(card()).toBeVisible();
    await expect(
      page.locator('[data-slot="agent-creation-result"]'),
    ).toHaveCount(0);
    await expect(
      page.getByTestId("workbench-edit-agent-draft"),
    ).toHaveAttribute("href", `/${locale}/agents/${audit.target_id}`);
    const restored = fixture("audit", cid);
    expect(restored.messages_hash).toBe(audit.messages_hash);
    expect(restored.units_hash).toBe(audit.units_hash);
    expect(runs).toBe(1);
    await page.screenshot({
      path: join(contract.caseDir, "pending-card.png"),
      fullPage: true,
    });
    const fields = card().locator("fieldset");
    for (let i = 0; i < (await fields.count()); i++) {
      const field = fields.nth(i);
      for (const text of await field.locator("textarea").all())
        await text.fill(
          `普通办公用户；中文分点列表；只整理用户原文并保留原意，不添加事实；无需任何工具、Skill、知识库或外部资源。${state.marker}`,
        );
      if (await field.getByRole("radio").count())
        await field.getByRole("radio").first().check();
      if (await field.getByRole("checkbox").count())
        await field.getByRole("checkbox").first().check();
    }
    const pending = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" && r.url().includes("/nl2agent/run"),
      { timeout: 30000 },
    );
    await card()
      .getByRole("button", { name: labels.submit, exact: true })
      .click();
    const submittedResponse = await pending;
    submittedAction = JSON.parse(
      submittedResponse.request().postDataJSON().query,
    );
    await expect(page.getByText(labels.summary, { exact: true })).toHaveCount(
      1,
    );
    const next = await events(submittedResponse);
    expect(next.some((e: any) => e.type === "error")).toBe(false);
    expect(runs).toBe(2);
    expect(
      next.some(
        (e: any) =>
          e.type === "nl2a_state" &&
          JSON.parse(e.content).event === "agent_generation_completed" &&
          JSON.parse(e.content).agent_id === audit.target_id,
      ),
    ).toBe(true);
    await expect(
      page.locator('[data-slot="agent-creation-result"]'),
    ).toHaveCount(1);
    await expect(
      page.locator('[data-slot="agent-creation-result"]'),
    ).toHaveAttribute("href", `/${locale}/agents/${audit.target_id}`);
    expect(fixture("audit", cid).description.trim().length).toBeGreaterThan(0);
    resumed = true;
    const after = fixture("audit", cid);
    for (let i = 0; i < 2; i++) {
      if (i === 0)
        await page.goto(`${base}/${locale}/workbench?thread_id=${cid}`);
      else await page.reload();
      await expect(card()).toBeVisible();
      await expect(
        card().getByRole("button", { name: labels.submitted, exact: true }),
      ).toBeDisabled();
      await expect(card().locator("fieldset").first()).toHaveAttribute(
        "disabled",
        "",
      );
      for (const input of await card().locator("textarea,input").all())
        await expect(input).toBeDisabled();
      for (const [index, question] of clarification.questions.entries()) {
        const answer = submittedAction.result.answers.find(
          (entry: any) => entry.question_id === question.question_id,
        );
        expect(answer).toBeDefined();
        const field = card().locator("fieldset").nth(index);
        if (question.question_type === "text") {
          await expect(
            field.getByRole("textbox", { name: question.title, exact: true }),
          ).toHaveValue(answer.value);
        } else {
          const selected = Array.isArray(answer.value)
            ? answer.value
            : [answer.value];
          const role =
            question.question_type === "single_choice" ? "radio" : "checkbox";
          for (const option of question.options) {
            const input = field.getByRole(role, {
              name: option.label,
              exact: true,
            });
            if (selected.includes(option.option_id))
              await expect(input).toBeChecked();
            else await expect(input).not.toBeChecked();
          }
          if (answer.other_text)
            await expect(field.getByRole("textbox").first()).toHaveValue(
              answer.other_text,
            );
        }
      }
      await expect(page.getByText(labels.summary, { exact: true })).toHaveCount(
        1,
      );
      await noErrors();
      await publicHistory();
      await expect(
        page.locator('[data-slot="agent-creation-result"]'),
      ).toHaveCount(1);
      await expect(
        page.locator('[data-slot="agent-creation-result"]'),
      ).toHaveAttribute("href", `/${locale}/agents/${audit.target_id}`);
      const current = fixture("audit", cid);
      expect(current.messages_hash).toBe(after.messages_hash);
      expect(current.units_hash).toBe(after.units_hash);
      expect(runs).toBe(2);
    }
    writeFileSync(
      join(contract.caseDir, "localized-summary.json"),
      JSON.stringify({
        core: selectedCore,
        locale,
        summary: labels.summary,
        liveAndReloadAgree: true,
        runs,
      }),
    );
    historyVerified = true;
    await page.screenshot({
      path: join(contract.caseDir, "submitted-card.png"),
      fullPage: true,
    });
  });
  await contract.step(steps[2], async () => {
    cleanupResult = fixture("cleanup");
    setup = false;
    expect(cleanupResult.original_history_unchanged).toBe(true);
    expect(cleanupResult.owned_conversations).toBe(1);
    expect(cleanupResult.owned_drafts).toBe(1);
    writeFileSync(
      join(contract.caseDir, "owned-cleanup.json"),
      JSON.stringify(cleanupResult),
    );
  });
  await contract.assertion(contract.expectedIds("assertions")[0], async () => {
    expect(audit.description || "").toBe("");
    expect(audit.target_id).toBeGreaterThan(0);
  });
  await contract.assertion(contract.expectedIds("assertions")[1], async () => {
    expect(resumed && historyVerified).toBe(true);
    expect(runs).toBe(2);
  });
  await contract.assertion(contract.expectedIds("assertions")[2], async () => {
    expect(cleanupResult.original_history_unchanged).toBe(true);
    expect(cleanupResult.owned_drafts).toBe(1);
  });
});
