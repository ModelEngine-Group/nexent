// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, unlinkSync, existsSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

journey("JIUWEN-SKILL-CREATOR-D4-001", async ({ page, expect, contract }) => {
  const config = JSON.parse(
    readFileSync(process.env.NEXENT_REAL_SKILL_CREATOR_CONFIG!, "utf8"),
  );
  const container = config.container || "nexent-runtime";
  const target =
    "/tmp/skill_history_" + randomUUID().replaceAll("-", "").slice(0, 12);
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
      "test-e2e/cases/JIUWEN-SKILL-CREATOR-D4-001/fixture.py",
    ),
    container + ":" + target + ".py",
  );
  let setup = false,
    state: any,
    cid = 0,
    runs = 0,
    audit: any;
  let saved = false,
    historyVerified = false,
    liveSummary = "",
    cleanupResult: any;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/nl2skill/run"))
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
      expect(
        (
          await (
            await page.request.get(
              base + "/api/tenant_config/deployment_version",
            )
          ).json()
        ).agent_core,
      ).toBe("jiuwen");
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
    page.getByRole("button", { name: "SKILL.md", exact: true }).first();
  const checkFile = async () => {
    await expect(
      page.getByRole("button", { name: "SKILL.md", exact: true }),
    ).toHaveCount(1);
    await expect(card()).toBeVisible();
    if ((await card().getAttribute("aria-expanded")) !== "true")
      await card().click();
    await expect(card().locator("..")).toContainText(state.marker);
    await expect(
      page.getByText("NEXENT_TERMINAL_MISSING", { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByText("JIUWEN_FINAL_OUTPUT_INVALID", { exact: true }),
    ).toHaveCount(0);
  };
  await contract.step(steps[0], async () => {
    await page.goto(base + "/zh/workbench");
    await page.getByRole("button", { name: "技能创建", exact: true }).click();
    const query = `创建一个名为 ${state.name} 的简单 Skill。SKILL.md 必须有合法 YAML frontmatter（name 为 ${state.name}，description 为测试文本摘要技能），正文包含唯一标记 ${state.marker}，指导提取用户文本中的关键词。另生成 references/example.md，内容也包含此标记。直接生成完整文件，不要调用工具，不要追加复杂内容。`;
    await page.getByRole("textbox").last().fill(query);
    const pending = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" && r.url().includes("/nl2skill/run"),
      { timeout: 30000 },
    );
    await page.getByRole("button", { name: "发送", exact: true }).click();
    const response = await pending;
    expect(response.status()).toBe(200);
    cid =
      response.request().postDataJSON().conversation_id ||
      Number(response.headers()["conversation_id"]);
    const events = (await response.body())
      .toString("utf8")
      .split(/\r?\n/)
      .filter((l) => l.startsWith("data:"))
      .map((l) => JSON.parse(l.slice(5)));
    expect(events.some((e) => e.type === "done")).toBe(true);
    expect(events.filter((e) => e.type === "error")).toEqual([]);
    liveSummary = events
      .filter((e) => e.type === "summary")
      .map((e) => e.content)
      .join("");
    expect(liveSummary.trim().length).toBeGreaterThan(0);
    await expect
      .poll(() => Object.keys(fixture("audit", cid).files).length)
      .toBeGreaterThan(1);
    audit = fixture("audit", cid);
    expect(audit.mode).toBe("skill_create");
    expect(audit.files["SKILL.md"]).toContain(state.marker);
    await checkFile();
  });
  await contract.step(steps[1], async () => {
    await page.getByRole("button", { name: "保存 Skill", exact: true }).click();
    await expect(page.getByText("Skill 已保存", { exact: true })).toBeVisible();
    saved = true;
    for (let i = 0; i < 2; i++) {
      if (i === 0) await page.goto(`${base}/zh/workbench?thread_id=${cid}`);
      else await page.reload();
      await checkFile();
      const restored = fixture("audit", cid);
      expect(restored.files).toEqual(audit.files);
      expect(restored.messages_hash).toBe(audit.messages_hash);
      expect(restored.units_hash).toBe(audit.units_hash);
      const response = await page.request.get(
        `${base}/api/conversation/${cid}`,
      );
      expect(response.status()).toBe(200);
      const body = await response.json();
      const files: Record<string, string> = {};
      let summary = "";
      for (const message of body.data[0].message) {
        if (message.role !== "assistant") continue;
        for (const part of message.message) {
          if (part.type === "summary") summary += part.content;
          if (!["skill_body", "file_content"].includes(part.type)) continue;
          const event = JSON.parse(part.content);
          const path = part.type === "skill_body" ? "SKILL.md" : event.path;
          files[path] = (files[path] || "") + event.content;
          expect(event.runtime_mode).toBeUndefined();
        }
      }
      expect(files).toEqual(audit.files);
      expect(summary).toBe(liveSummary);
      expect(runs).toBe(1);
    }
    await page.screenshot({
      path: join(contract.caseDir, "restored-skill.png"),
      fullPage: true,
    });
    if (config.existing_conversation_id) {
      await page.goto(
        `${base}/zh/workbench?thread_id=${config.existing_conversation_id}`,
      );
      await expect(card()).toBeVisible();
      if ((await card().getAttribute("aria-expanded")) !== "true")
        await card().click();
      await expect
        .poll(async () => (await card().locator("..").innerText()).length)
        .toBeGreaterThan(80);
      await expect(
        page.getByText("NEXENT_TERMINAL_MISSING", { exact: true }),
      ).toHaveCount(0);
      expect(runs).toBe(1);
      await page.screenshot({
        path: join(contract.caseDir, "existing-restored-skill.png"),
        fullPage: true,
      });
    }
  });
  historyVerified = true;
  await contract.step(steps[2], async () => {
    const result = fixture("cleanup");
    cleanupResult = result;
    setup = false;
    expect(result.cleanup).toBe(true);
    expect(result.original_history_unchanged).toBe(true);
    expect(result.owned_skills).toBe(1);
    expect(result.owned_conversations).toBe(1);
    writeFileSync(
      join(contract.caseDir, "owned-cleanup.json"),
      JSON.stringify(result),
    );
  });
  await contract.assertion(contract.expectedIds("assertions")[0], async () => {
    expect(saved).toBe(true);
    expect(audit.files["SKILL.md"]).toContain(state.marker);
  });
  await contract.assertion(contract.expectedIds("assertions")[1], async () => {
    expect(historyVerified).toBe(true);
    expect(runs).toBe(1);
  });
  await contract.assertion(contract.expectedIds("assertions")[2], async () => {
    expect(cleanupResult.original_history_unchanged).toBe(true);
    expect(cleanupResult.owned_conversations).toBe(1);
    expect(cleanupResult.owned_skills).toBe(1);
  });
});
