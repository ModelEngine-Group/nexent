// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { readFileSync } from "node:fs";
import type { Page } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";

type Credentials = [email: string, password: string];
type Fixture = {
  origin: string;
  control: string;
  key: string;
  reader: Credentials;
  editor: Credentials;
  publisher: Credentials;
  agent: number;
  display: string;
  model: number;
  skill: string;
  rule: string;
  baseline: number;
  feedback: { skill_id: number };
  target: string;
  targetId: number;
  guard: string;
};

const ID = "EVOLUTION-BUSINESS-JOURNEY-D4-001";
const ANSWER = "[data-slot='aui_assistant-message-root']";

function fixture(): Fixture {
  const manifest = process.env.NEXENT_EVOLUTION_D4_FIXTURE;
  if (!manifest) throw new Error("The isolated evolution fixture needs NEXENT_EVOLUTION_D4_FIXTURE");
  const value: Fixture = JSON.parse(readFileSync(manifest, "utf8"));
  for (const address of [value.origin, value.control]) {
    const url = new URL(address);
    if (url.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(url.hostname)) {
      throw new Error("Evolution fixture URLs must point to loopback");
    }
  }
  return value;
}

async function choose(page: Page, label: string, option: string | RegExp, search?: string) {
  const input = page.getByRole("combobox", { name: label, exact: true });
  await input.focus();
  await input.press("ArrowDown");
  if (search) await input.fill(search);
  const id = await input.getAttribute("aria-controls");
  if (!id) throw new Error("Evaluation selector has no popup");
  await page.locator('[id="' + id + '"]')
    .locator("xpath=ancestor::*[contains(@class,'ant-select-dropdown')][1]")
    .locator(".ant-select-item-option-content").filter({ hasText: option }).first().click();
  await input.press("Escape");
}

journey(ID, async (scenario) => {
  const { page, expect, contract } = scenario;
  let config: Fixture;
  let sid: string;
  let editor: Page;
  let publisher: Page;
  let oldChat: Page;
  let newChat: Page;
  let experiment: number;
  let confirmation: number;
  let published: number;
  const executions: { id: string; version: number }[] = [];

  async function control(path: string, data?: unknown) {
    const response = await fetch(config.control + path, {
      method: data === undefined ? "GET" : "POST",
      headers: { "X-Evolution-Fixture-Key": config.key, "Content-Type": "application/json" },
      body: data === undefined ? undefined : JSON.stringify(data),
      signal: AbortSignal.timeout(150_000),
    });
    expect(response.status).toBe(200);
    return response.json();
  }

  async function signIn(target: Page, [email, password]: Credentials) {
    const login = await target.context().request.post(config.origin + "/api/user/signin", {
      data: { email, password },
    });
    expect(login.status()).toBe(200);
    const { user } = (await login.json()).data;
    await target.context().addInitScript((value) => localStorage.setItem("user_info", JSON.stringify(value)), {
      id: user.id, email: user.email, role: user.role,
    });
    await target.addLocatorHandler(target.getByRole("dialog").filter({ hasText: "尚未配置向量模型" }), async (dialog) => {
      await dialog.getByRole("button", { name: "关闭记忆" }).click();
    });
  }

  async function separatePage(credentials: Credentials) {
    const browser = page.context().browser();
    if (!browser) throw new Error("Chromium context unavailable");
    const isolated = await browser.newContext({ locale: "zh-CN" });
    contract.deferCleanup(() => isolated.close());
    const next = await isolated.newPage();
    next.on("response", (response) => {
      if (response.status() >= 500) {
        contract.addUnexpected5xx(String(response.status()) + " " + new URL(response.url()).pathname);
      }
    });
    await signIn(next, credentials);
    return next;
  }

  async function openChat(target: Page) {
    await target.goto(config.origin + "/zh/newchat?agent_id=" + config.agent, { waitUntil: "domcontentloaded" });
    await expect(target.getByText("pilot-fixture", { exact: true }).first()).toBeVisible();
  }

  async function send(target: Page, query: string, answer: string | RegExp) {
    const count = await target.locator(ANSWER).count();
    await target.getByRole("textbox", { name: "对话输入", exact: true }).fill(query);
    const pending = target.waitForResponse((r) => new URL(r.url()).pathname === "/api/agent/run" &&
      r.request().method() === "POST" && r.request().postDataJSON()?.query === query);
    await target.getByRole("button", { name: "发送", exact: true }).click();
    const response = await pending;
    expect(response.status()).toBe(200);
    const message = target.locator(ANSWER).nth(count);
    await expect(message.getByText(answer).first()).toBeVisible();
    return { message, execution: await response.headerValue("x-agentos-run-id") };
  }

  async function evaluate(ticket: Page, version: number, expected: string) {
    const reply = await send(ticket, "请核对交接。事项编号=U570；负责人=未指定。", expected);
    expect(reply.execution).toMatch(/^[a-zA-Z0-9_-]{10,128}$/);
    executions.push({ id: reply.execution!, version });
  }

  async function release(action: "promote" | "rollback") {
    const label = action === "promote" ? "晋升并用于新会话" : "回退新会话的默认版本";
    const response = publisher.waitForResponse((r) => new URL(r.url()).pathname.endsWith("/" + confirmation + "/" + action) &&
      r.request().method() === "POST");
    await publisher.getByRole("textbox", { name: "填写本次上线、回退或停用的原因" }).fill(ID);
    await publisher.getByRole("button", { name: label, exact: true }).click();
    const result = await response;
    expect(result.status()).toBe(200);
    return (await result.json()).data;
  }

  await executeFixedScenario(scenario, {
    preconditions: [
      async () => {
        config = fixture();
        await signIn(page, config.reader);
        editor = await separatePage(config.editor);
        publisher = await separatePage(config.publisher);
        return "signed in three separate Nexent browser contexts in the isolated pilot";
      },
      async () => {
        expect(await control("/ready")).toEqual({ ready: true });
        contract.deferCleanup(async () => {
          expect(await control("/finish", {})).toEqual({ restored: true, active_logins: 0 });
        });
        return "independent fixture and teardown are available on loopback";
      },
    ],
    steps: [
      async () => {
        await openChat(page);
        const { message } = await send(page, "以后这个 Skill 要保留没有负责人的交接事项，负责人写待分配。", /已登记建议 S-[1-9]\d*/);
        sid = (await message.innerText()).match(/S-[1-9]\d*/)?.[0] ?? "";
        expect(sid).toBeTruthy();
        const status = await send(page, sid, /维护人评审/);
        await expect(status.message.getByRole("link", { name: "对比评测" })).toHaveCount(0);
        await expect(status.message.getByRole("button", { name: "编辑候选" })).toHaveCount(0);
        return "submitted and retrieved the suggestion in its original business chat";
      },
      async () => {
        const api = editor.context().request;
        const root = config.origin + "/api/agent-evolution";
        const workspace = await api.get(root + "/agents/" + config.agent + "/versions/1/workspace");
        expect(workspace.status()).toBe(200);
        const suggestion = (await workspace.json()).data.suggestions.find(
          (item: { suggestion_id: number }) => item.suggestion_id === Number(sid.slice(2)),
        );
        expect(suggestion?.skill_id).toBe(config.feedback.skill_id);
        const generate = async (suggestionId: number, goal: string) => {
          const handoff = await api.post(root + "/experiments/" + config.baseline + "/feedback", {
            data: { ...config.feedback, goal, suggestion_id: suggestionId },
          });
          expect(handoff.status()).toBe(200);
          const { feedback_id: feedback } = (await handoff.json()).data;
          const result = await api.post(root + "/feedback/" + feedback + "/candidates", { data: { model_id: config.model } });
          expect(result.status()).toBe(200);
          return (await result.json()).data;
        };
        const candidate = await generate(suggestion.suggestion_id, suggestion.expected_behavior);
        expect(candidate.method).toBe("S2");
        expect(candidate.edit.new).not.toBe(candidate.edit.old);
        await openChat(editor);
        const own = await send(editor, "以后这个 Skill 要保留没有负责人的交接事项，负责人写待分配。", /已登记建议 S-[1-9]\d*/);
        const ownId = (await own.message.innerText()).match(/S-([1-9]\d*)/)?.[1];
        expect(ownId).toBeTruthy();
        await expect(own.message.getByRole("link", { name: "对比评测" })).toBeVisible();
        await expect(own.message.getByRole("button", { name: "编辑候选" })).toHaveCount(0);
        const ownCandidate = await generate(Number(ownId), suggestion.expected_behavior);
        const refreshed = await send(editor, `S-${ownId}`, /已生成候选，等待对比评测/);
        await refreshed.message.getByRole("button", { name: "编辑候选" }).click();
        const dialog = editor.getByRole("dialog", { name: "编辑候选" });
        const replacement = ownCandidate.edit.new + "\n保留原有的事项编号。";
        await expect(dialog.getByRole("textbox", { name: "修改后的步骤" })).toHaveValue(ownCandidate.edit.new);
        await dialog.getByRole("textbox", { name: "修改后的步骤" }).fill(replacement);
        const saving = editor.waitForResponse((r) => r.url().endsWith(`/skill-candidates/${ownCandidate.candidate_id}`) &&
          r.request().method() === "POST");
        await dialog.getByRole("button", { name: "保存为新候选" }).click();
        const saved = await saving;
        expect(saved.status()).toBe(200);
        const revised = (await saved.json()).data.candidate_id;
        expect(revised).not.toBe(ownCandidate.candidate_id);
        await expect(dialog.getByText(`已保存候选 #${revised}，可以重新对比评测。`)).toBeVisible();
        await dialog.getByRole("button", { name: "关闭", exact: true }).last().click();
        const compare = refreshed.message.getByRole("link", { name: "对比评测" });
        await expect(compare).toHaveAttribute("href", new RegExp(`candidate_id=${revised}(?:&|$)`));
        await compare.click();
        await expect(editor.getByRole("combobox", { name: "选择候选" })).toBeVisible();
        await expect(editor.getByText(`#${revised} · ${config.skill}`, { exact: true })).toBeVisible();
        await editor.goto(config.origin + "/zh/evaluation", { waitUntil: "domcontentloaded" });
        await editor.getByText("候选对比", { exact: true }).first().click();
        await choose(editor, "智能体", config.display);
        await choose(editor, "版本", /^V1(?:\s|$)/, "V1 ");
        for (const [label, value] of [
          ["关联业务用户的建议（需选目标题和保护题）", sid + " ·"],
          ["选择候选", "#" + candidate.candidate_id + " · " + config.skill],
          ["业务题", config.target], ["业务题", config.guard], ["建议的目标题（其他已选题用于回归）", "新交接"],
        ] as const) await choose(editor, label, value);
        await editor.getByRole("checkbox", { name: "按预设条件筛选候选" }).check();
        await choose(editor, "选择要改善的专项题", config.target);
        await choose(editor, "选择已发布评估器", config.rule);
        const submitted = editor.waitForResponse((r) => r.url() === root + "/experiments" && r.request().method() === "POST");
        await editor.getByRole("button", { name: "开始对比", exact: true }).click();
        const response = await submitted;
        expect(response.status()).toBe(202);
        const request = response.request().postDataJSON();
        expect(request.version_no).toBe(1);
        expect(request.suggestion_id).toBe(Number(sid.slice(2)));
        expect(request.suggestion_target_case_id).toBe(config.targetId);
        experiment = (await response.json()).data.experiment_id;
        const finished = await editor.waitForResponse(async (r) => r.url() === root + "/experiments/" + experiment &&
          r.status() === 200 && (await r.json()).data?.status === "finished", { timeout: 120_000 });
        const report = (await finished.json()).data;
        expect(report.valid_pairs).toBe(3);
        expect(report.counts).toMatchObject({ improved: 1, both_pass: 2, regressed: 0 });
        expect(report.screening.status).toBe("eligible");
        const status = await send(page, sid, /保护题全部通过/);
        await expect(status.message.getByRole("link", { name: "对比评测" })).toHaveCount(0);
        await expect(status.message.getByRole("button", { name: "编辑候选" })).toHaveCount(0);
        const nomination = editor.waitForResponse((r) =>
          r.url() === root + "/experiments/" + experiment + "/confirmation-candidate" && r.request().method() === "POST");
        await editor.getByRole("button", { name: "提交候选给独立评测人", exact: true }).click();
        const receipt = await nomination;
        expect(receipt.status()).toBe(200);
        expect((await receipt.json()).data.experiment_id).toBe(experiment);
        return "authorized receipt opened a newly revised candidate; the business candidate improved its target and was nominated";
      },
      async () => {
        const result = await control("/confirm", { suggestion_id: Number(sid.slice(2)) });
        confirmation = result.lock;
        expect(result.experiment).toBe(experiment);
        expect(result.confirmation).toMatchObject({ decision: "passed", valid_pairs: 2, improved: 1, regressed: 0 });
        await editor.getByRole("button", { name: "查看独立评测进度", exact: true }).click();
        await expect(editor.getByText(/独立评测通过/).first()).toBeVisible();
        await expect(editor.getByText(/FORMAL-PRIVATE-HANDOFF/)).toHaveCount(0);
        const denied = await editor.context().request.get(config.origin +
          "/api/agent-evolution/confirmation-locks/" + confirmation + "/release");
        expect(denied.status()).toBe(403);
        await send(page, sid, /已通过独立确认/);
        return "independent worker used two held-out cases, editor saw only the summary and was denied release access";
      },
      async () => {
        oldChat = await separatePage(config.reader);
        await openChat(oldChat);
        await evaluate(oldChat, 1, "无已分配事项");
        await publisher.goto(config.origin + "/zh/evaluation/releases/" + confirmation, { waitUntil: "domcontentloaded" });
        published = (await release("promote")).new_version;
        expect(published).toBeGreaterThan(1);
        await expect(publisher.getByText("已发布 V" + published, { exact: true })).toBeVisible();
        await send(page, sid, new RegExp("发布 V" + published));
        newChat = await separatePage(config.reader);
        await openChat(newChat);
        await evaluate(newChat, published, "U570 待分配");
        await evaluate(oldChat, 1, "无已分配事项");
        return "publisher promoted the tested version; new and existing chat outputs followed their bindings";
      },
      async () => {
        const receipt = await release("rollback");
        expect(receipt.new_version).toBe(published);
        expect(receipt.rollback_at).toBeTruthy();
        await expect(publisher.getByText("已从 V" + published + " 回退", { exact: true })).toBeVisible();
        await send(page, sid, /已回退/);
        const restored = await separatePage(config.reader);
        await openChat(restored);
        await evaluate(restored, 1, "无已分配事项");
        await evaluate(newChat, published, "U570 待分配");
        return "publisher rolled back; new chats used V1, and existing chats kept the published version";
      },
    ],
    assertions: [
      async () => {
        const receipt = await control("/verify", { experiment, confirmation, suggestion_id: Number(sid.slice(2)), executions });
        expect(receipt.suggestion_linked).toBe(true);
        return "one suggestion is linked to the experiment, confirmation and publication record";
      },
      async () => {
        const root = config.origin + "/api/agent-evolution/confirmation-locks/" + confirmation;
        const locked = await editor.context().request.get(root);
        expect(locked.status()).toBe(403);
        const summary = await editor.context().request.get(config.origin +
          "/api/agent-evolution/experiments/" + experiment + "/confirmation-results");
        expect(summary.status()).toBe(200);
        expect(JSON.stringify(await summary.json())).not.toContain("FORMAL-PRIVATE-HANDOFF");
        return "the editor can read the verdict but cannot read the independent run protocol or materials";
      },
      async () => {
        const receipt = await control("/verify", { experiment, confirmation, suggestion_id: Number(sid.slice(2)), executions });
        expect(receipt.default_version).toBe(1);
        expect(receipt.versions).toEqual([1, published, 1, 1, published]);
        return "execution receipts prove the five version bindings; the default is restored";
      },
    ],
  });
});
