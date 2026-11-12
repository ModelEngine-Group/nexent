// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, unlinkSync, existsSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

journey(
  "JIUWEN-CREATOR-RESOURCES-D4-001",
  async ({ page, expect, contract }) => {
    const config = JSON.parse(
      readFileSync(process.env.NEXENT_REAL_CREATOR_RESOURCES_CONFIG!, "utf8"),
    );
    const container = config.container || "nexent-runtime";
    const target =
      "/tmp/creator_resources_" + randomUUID().replaceAll("-", "").slice(0, 12);
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
        "test-e2e/cases/JIUWEN-CREATOR-RESOURCES-D4-001/fixture.py",
      ),
      container + ":" + target + ".py",
    );
    let setup = false,
      state: any,
      cid = 0,
      runs = 0,
      audit: any;
    let recommended = false,
      completed = false,
      history = false,
      cleaned: any;
    const streams: any[] = [];
    page.on("request", (r) => {
      if (r.method() === "POST" && r.url().includes("/nl2agent/run")) runs++;
    });
    contract.deferCleanup(async () => {
      try {
        const result = setup
          ? fixture("cleanup")
          : cleaned || { cleanup: true, original_history_unchanged: true };
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
        fixture("setup", config.auth_source_agent_id);
        setup = true;
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
    const pending = () =>
      page.waitForResponse(
        (r) =>
          r.request().method() === "POST" && r.url().includes("/nl2agent/run"),
        { timeout: 30000 },
      );
    const receive = async (promise: ReturnType<typeof pending>) => {
      const response = await promise;
      expect(response.ok()).toBe(true);
      cid ||=
        response.request().postDataJSON().conversation_id ||
        Number(response.headers()["conversation_id"]);
      const events = (await response.text())
        .split(/\r?\n/)
        .filter((l) => l.startsWith("data:"))
        .map((l) => JSON.parse(l.slice(5)));
      expect(events.filter((e) => e.type === "error")).toEqual([]);
      streams.push(...events);
      return events;
    };
    const parse = (v: any) => (typeof v === "string" ? JSON.parse(v) : v);
    const resourceCard = (events: any[]) =>
      events
        .filter((e) => e.type === "nl2a")
        .map((e) => parse(e.content))
        .find((p) => p.subtype === "installed_resource_binding");
    const query = () =>
      `请创建智能体 ${state.name}，标记 ${state.marker}。只绑定当前已有 Skill「${state.skill.name}」（${state.skill.ref}），不安装新资源，不使用其他工具或知识库。用途：${state.skill.description}。请先完成必要的澄清，然后实际搜索并推荐这个已有 Skill，通过 nl2a_wrapper 展示资源绑定卡，等待我选择绑定和提交之后再生成提示词。`;
    const steps = contract.expectedIds("steps");
    await contract.step(steps[0], async () => {
      await page.goto(base + "/zh/workbench");
      await page
        .getByRole("button", { name: "智能体创建", exact: true })
        .click();
      await page.getByRole("textbox").last().fill(query());
      let next = pending();
      await page.getByRole("button", { name: "发送", exact: true }).click();
      let events = await receive(next);
      if (!resourceCard(events)) {
        const card = page
          .locator("[data-slot='aui-requirement-clarification']")
          .last();
        await expect(card).toBeVisible();
        for (const field of await card.locator("fieldset").all()) {
          for (const text of await field.locator("textarea").all())
            await text.fill(query());
          if (await field.getByRole("radio").count())
            await field.getByRole("radio").first().check();
          if (await field.getByRole("checkbox").count())
            await field.getByRole("checkbox").first().check();
        }
        next = pending();
        await card.getByRole("button", { name: "提交", exact: true }).click();
        events = await receive(next);
      }
      const payload = resourceCard(events);
      expect(payload).toBeDefined();
      const selected = payload.resources.find(
        (r: any) => r.candidate.candidate_ref === state.skill.ref,
      );
      expect(selected).toBeDefined();
      expect(selected.config).toEqual([]);
      expect(
        streams.some(
          (e) =>
            e.type === "tool" && e.tool_name === "nl2a_recommend_resources",
        ),
      ).toBe(true);
      const wrappers = streams.filter(
        (e) => e.type === "tool" && e.tool_name === "nl2a_wrapper",
      );
      expect(
        wrappers.some((e) => {
          const args = parse(e.tool_arguments);
          return args.resource_result?.resources?.some(
            (r: any) =>
              r.candidate.candidate_ref === state.skill.ref &&
              Array.isArray(r.config) &&
              r.config.length === 0,
          );
        }),
      ).toBe(true);
      await expect(
        page.locator(`[data-resource-ref="${state.skill.ref}"]`),
      ).toBeVisible();
      audit = fixture("audit", cid);
      expect(audit.bindings).toEqual([]);
      recommended = true;
    });
    await contract.step(steps[1], async () => {
      for (const row of await page.locator("[data-resource-ref]").all()) {
        const checkbox = row.getByRole("checkbox");
        if (await checkbox.count())
          await checkbox.setChecked(
            (await row.getAttribute("data-resource-ref")) === state.skill.ref,
          );
      }
      await page.getByRole("button", { name: /绑定所选资源/ }).click();
      await expect(
        page.getByRole("button", { name: "继续", exact: true }),
      ).toBeEnabled();
      audit = fixture("audit", cid);
      expect(audit.bindings).toEqual([
        { skill_id: state.skill.id, enabled: true, config_values: {} },
      ]);
      const next = pending();
      await page.getByRole("button", { name: "继续", exact: true }).click();
      const events = await receive(next);
      expect(
        events.some(
          (e) =>
            e.type === "nl2a_state" &&
            parse(e.content).event === "agent_generation_completed" &&
            parse(e.content).agent_id === audit.target_id,
        ),
      ).toBe(true);
      const result = page.locator('[data-slot="agent-creation-result"]');
      await expect(result).toHaveCount(1);
      await expect(result).toHaveAttribute(
        "href",
        `/zh/agents/${audit.target_id}`,
      );
      completed = true;
    });
    await contract.step(steps[2], async () => {
      const before = fixture("audit", cid);
      const count = runs;
      for (let i = 0; i < 2; i++) {
        if (i === 0) await page.goto(`${base}/zh/workbench?thread_id=${cid}`);
        else await page.reload();
        await expect(
          page.locator('[data-slot="agent-creation-result"]'),
        ).toHaveAttribute("href", `/zh/agents/${audit.target_id}`);
        const after = fixture("audit", cid);
        expect(after.bindings).toEqual(before.bindings);
        expect(after.units_hash).toBe(before.units_hash);
        expect(after.messages_hash).toBe(before.messages_hash);
        const response = await page.request.get(
          `${base}/api/conversation/${cid}`,
        );
        expect(response.ok()).toBe(true);
        const parts = (await response.json()).data[0].message
          .filter((m: any) => m.role === "assistant")
          .flatMap((m: any) => m.message);
        expect(parts.filter((p: any) => p.type === "error")).toEqual([]);
        const cards = parts
          .filter((p: any) => p.type === "nl2a")
          .map((p: any) => parse(p.content));
        expect(
          cards.some(
            (p: any) =>
              p.subtype === "installed_resource_binding" &&
              p.resources.some(
                (r: any) =>
                  r.candidate.candidate_ref === state.skill.ref &&
                  Array.isArray(r.config) &&
                  r.config.length === 0,
              ),
          ),
        ).toBe(true);
        expect(runs).toBe(count);
      }
      history = true;
      await page.screenshot({
        path: join(contract.caseDir, "bound-history.png"),
        fullPage: true,
      });
      cleaned = fixture("cleanup");
      setup = false;
      expect(cleaned.owned_conversations).toBe(1);
      expect(cleaned.owned_drafts).toBe(1);
    });
    await contract.assertion(contract.expectedIds("assertions")[0], async () =>
      expect(recommended).toBe(true),
    );
    await contract.assertion(contract.expectedIds("assertions")[1], async () =>
      expect(completed).toBe(true),
    );
    await contract.assertion(
      contract.expectedIds("assertions")[2],
      async () => {
        expect(history).toBe(true);
        expect(cleaned.original_history_unchanged).toBe(true);
      },
    );
  },
);
