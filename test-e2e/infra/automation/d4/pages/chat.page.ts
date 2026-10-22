// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, type FileChooser, type Locator, type Page, type Response } from "playwright/test";
import { appendFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { appPath } from "../runner/runtime-config";

/** A path or a full setFiles payload (name/mimeType/buffer). */
type AttachmentPayload = string | Parameters<FileChooser["setFiles"]>[0];

export class ChatPage {
  private lastServerConversationId?: number;
  private stoppedConversationId?: number;

  constructor(readonly page: Page) {}

  assistantMessages(): Locator {
    return this.page.locator("[data-slot='aui_assistant-message-root']");
  }

  userMessages(): Locator {
    return this.page.locator("[data-slot='aui_user-message-root']");
  }

  composerInput(): Locator {
    return this.page.locator("[data-workbench-composer], .aui-lexical-input");
  }

  async composerText(): Promise<string> {
    return this.composerInput().evaluate(element =>
      element instanceof HTMLTextAreaElement || element instanceof HTMLInputElement
        ? element.value : element.textContent ?? "");
  }

  activeThread(): Locator {
    return this.page.locator("[data-active='true']").filter({ has: this.page.locator("button") }).first();
  }

  async currentThreadTitle(): Promise<string> {
    // Resolve the owned server ID before reload; a title refresh can replace
    // the transient local sidebar item while the same conversation is open.
    const title = await this.persistedThreadTitle(this.currentConversationId());
    await expect(this.threadButton(title)).toHaveCount(1);
    await expect(this.threadButton(title)).toBeVisible();
    return title;
  }

  async openAgent(displayName: string): Promise<void> {
    await this.page.goto(appPath("/newchat"), { waitUntil: "domcontentloaded" });
    // Navigation can restore the previous Agent chat; open discovery explicitly.
    const search = this.page.getByPlaceholder("搜索智能体名称");
    const discovery = this.page.getByRole("button", { name: "发现智能体", exact: true });
    await expect(search.or(discovery)).toBeVisible();
    if (!(await search.isVisible())) await discovery.click();
    await this.selectAgent(displayName);
  }

  async selectAgent(displayName: string): Promise<void> {
    // The discover-agents landing search is 搜索智能体名称 now. The card's
    // accessible name mixes the agent name, description, tag and the
    // 更多操作 menu, so scope by the exact name text inside the card
    // instead of matching the first button whose name merely contains it.
    const search = this.page.getByPlaceholder("搜索智能体名称");
    await expect(search).toBeVisible();
    await search.fill(displayName);
    const card = this.page.locator("div[role='button']").filter({
      has: this.page.getByText(displayName, { exact: true }),
    });
    await expect(card).toHaveCount(1);
    await card.click();
    // Landing selection is complete when the discover page is replaced by
    // the conversation view with a usable composer.
    await expect(this.page.getByRole("heading", { name: "发现智能体" })).toBeHidden();
    await expect(this.page.locator("[data-workbench-composer], .aui-lexical-input")).toBeVisible();
  }

  async selectMode(mode: "规划" | "执行"): Promise<void> {
    const label = `${mode}模式`;
    const trigger = this.page.getByRole("button", { name: /^(规划|执行)模式$/, exact: true })
      .and(this.page.locator('button[aria-haspopup="dialog"]'));
    await expect(trigger).toBeVisible();
    if ((await trigger.innerText()).trim() !== label) {
      await trigger.click();
      await this.page.getByRole("dialog").getByRole("button", { name: label, exact: true }).click();
    }
    await expect(trigger).toHaveText(label);
  }

  /** Poll the composer until its text matches, for async transcription and streamed input. */
  async expectComposerText(pattern: string | RegExp, timeout = 30_000): Promise<void> {
    await expect.poll(async () => this.composerText(), { timeout }).toMatch(pattern);
  }

  async startMessage(prompt: string): Promise<Locator> {
    const before = await this.assistantMessages().count();
    const composer = this.composerInput();
    const started = Date.now();
    let response: Response;
    for (let attempt = 1; ; attempt += 1) {
      await composer.fill(prompt);
      const runResponse = this.page.waitForResponse(
        response => response.request().method() === "POST"
          && response.url().includes("/api/agent/run")
          && response.request().postDataJSON()?.query === prompt,
        { timeout: 120_000 },
      );
      await this.page.getByRole("button", { name: "发送", exact: true }).click();
      response = await runResponse;
      if (response.headers()["x-stream-status"] !== "conflict") break;
      const recoveringOwnedStop = this.stoppedConversationId !== undefined
        && Number(response.request().postDataJSON()?.conversation_id) === this.stoppedConversationId;
      const root = process.env.RESULT_DIR;
      if (root) {
        mkdirSync(join(root, "runtime"), { recursive: true });
        appendFileSync(join(root, "runtime/send-recovery.jsonl"), JSON.stringify({
          kind: "agent_run_conflict", after_owned_stop: recoveringOwnedStop,
          conversation_id: this.lastServerConversationId, attempt, elapsed_ms: Date.now() - started,
        }) + "\n");
      }
      // Stop publishes history before the physical worker releases its lease.
      // Only this explicit pre-admission rejection permits a bounded retry;
      // an accepted run or any other error is never resubmitted here.
      if (!recoveringOwnedStop || Date.now() - started >= 60_000) {
        const error = new Error("Previous owned run did not release its execution lease within the bounded Stop recovery window");
        error.name = "ProductFailure";
        throw error;
      }
      await expect(this.assistantMessages()).toHaveCount(before);
      await expect.poll(() => this.composerText()).toBe(prompt);
      await this.page.waitForTimeout(1000);
    }
    this.stoppedConversationId = undefined;
    if (!response.ok() || !(response.headers()["content-type"] || "").includes("text/event-stream")) {
      const error = new Error(`Agent run did not return an accepted SSE response: HTTP ${response.status()}`);
      error.name = "ProductFailure";
      throw error;
    }
    const headers = await response.allHeaders();
    let rawConversationId = headers["conversation_id"];
    if (!rawConversationId) {
      const requestBody = response.request().postDataJSON() as { conversation_id?: number } | null;
      rawConversationId = requestBody?.conversation_id === undefined ? undefined : String(requestBody.conversation_id);
    }
    const conversationId = Number(rawConversationId);
    if (Number.isInteger(conversationId) && conversationId > 0) {
      this.lastServerConversationId = conversationId;
    }
    await expect(this.assistantMessages()).toHaveCount(before + 1, { timeout: 120_000 });
    return this.assistantMessages().nth(before);
  }

  currentConversationId(): number {
    if (!this.lastServerConversationId) {
      throw new Error("agent/run did not expose a valid conversation_id response header");
    }
    return this.lastServerConversationId;
  }

  async persistedThreadTitle(conversationId: number): Promise<string> {
    const response = await this.page.request.get(`/api/conversation/${conversationId}`);
    expect(response.status()).toBe(200);
    const payload = await response.json();
    expect(payload.code).toBe(0);
    expect(Array.isArray(payload.data)).toBe(true);
    expect(payload.data).toHaveLength(1);
    const history = payload.data[0];
    expect(String(history.conversation_id)).toBe(String(conversationId));
    expect(typeof history.conversation_title).toBe("string");
    return history.conversation_title;
  }

  async deleteConversationById(conversationId: number): Promise<void> {
    const endpoint = new URL(`/api/conversation/${conversationId}`, this.page.url()).toString();
    const response = await this.page.request.delete(endpoint);
    if (!response.ok()) {
      throw new Error(`conversation ${conversationId} cleanup failed: HTTP ${response.status()}`);
    }
    const body = await response.json().catch(() => ({}));
    if (body?.code !== 0) {
      throw new Error(`conversation ${conversationId} cleanup failed: ${JSON.stringify(body)}`);
    }
  }

  async waitForCompletion(timeout = 300_000): Promise<void> {
    const last = this.assistantMessages().last();
    await expect(last).toContainText(/已完成|Completed|失败|Error/i, { timeout });
    await expect(this.page.locator("button:has(svg.lucide-square)")).toHaveCount(0, { timeout });
  }

  async sendAndWait(prompt: string, timeout = 300_000): Promise<Locator> {
    const message = await this.startMessage(prompt);
    await this.waitForCompletion(timeout);
    await expect(message).not.toHaveText("");
    return message;
  }

  async stopGeneration(): Promise<void> {
    const stop = this.page.locator("button:has(svg.lucide-square)").first();
    await expect(stop).toBeVisible({ timeout: 120_000 });
    const stopped = this.page.waitForResponse(
      (response) => response.request().method() === "GET" && response.url().includes("/api/agent/stop/"),
      { timeout: 120_000 },
    );
    await stop.click();
    const response = await stopped;
    const body = await response.json().catch(() => ({}));
    if (!response.ok() || body?.status !== "success") {
      throw new Error("agent stop failed: HTTP " + response.status() + " body=" + JSON.stringify(body));
    }
    this.stoppedConversationId = this.currentConversationId();
    // A cancelled message is incomplete, so it has no Completed badge.
    await expect(this.page.locator("button:has(svg.lucide-square)")).toHaveCount(0, { timeout: 120_000 });
    await expect(this.page.locator("[data-workbench-composer], .aui-lexical-input")).toBeEditable();
    // Stop acknowledgement precedes persistence/worker finalization. Wait for
    // the owned stream's terminal history before continuing or reconnecting.
    await expect.poll(async () => {
      const response = await this.page.request.get(`/api/conversation/${this.currentConversationId()}`);
      if (!response.ok()) return "history_unavailable";
      const payload = await response.json();
      const history = payload.data?.[0];
      if (history?.streaming_message?.status === "streaming") return "streaming";
      const assistant = history?.message?.filter((item: any) => item.role === "assistant").at(-1);
      return assistant?.status || "missing";
    }, { timeout: 60000, intervals: [500, 1000, 2000] }).toMatch(/^(stopped|completed|failed)$/);
  }

  async persistedMessages(): Promise<Array<{ role: string; status: string; message: unknown }>> {
    const response = await this.page.request.get(`/api/conversation/${this.currentConversationId()}`);
    expect(response.ok()).toBe(true);
    const payload = await response.json();
    expect(payload.code).toBe(0);
    const history = payload.data?.[0];
    expect(history).toBeTruthy();
    expect(history.streaming_message?.status).not.toBe("streaming");
    expect(Array.isArray(history.message)).toBe(true);
    return history.message.map((item: any) => ({ role: item.role, status: item.status, message: item.message }));
  }

  async captureConversationState(path: string, marker: string): Promise<void> {
    const response = await this.page.request.get(`/api/conversation/${this.currentConversationId()}`);
    const payload = await response.json().catch(() => ({}));
    const history = payload.data?.[0];
    const messages = (history?.message || []).map((item: any) => {
      const parts = Array.isArray(item.message) ? item.message : [];
      const final = parts.filter((part: any) => part.type === "final_answer").map((part: any) => String(part.content || "")).join("");
      const text = typeof item.message === "string" ? item.message : parts.map((part: any) => String(part.content || "")).join("");
      return {role:item.role, status:item.status, unit_types:parts.map((part:any)=>part.type),
        contains_expected_marker:text.includes(marker), final_contains_expected_marker:final.includes(marker),
        final_is_success:final.trim()==="success", final_length:final.length};
    });
    writeFileSync(path, JSON.stringify({conversation_id:this.currentConversationId(), http_status:response.status(), code:payload.code,
      streaming_status:history?.streaming_message?.status || null, messages,
      ui_user_count:await this.userMessages().count(), ui_assistant_count:await this.assistantMessages().count()},null,2)+"\n");
  }

  async messageText(message: Locator): Promise<string> {
    return (await message.locator("[data-citation-index-map] .aui-md:visible").allTextContents()).join("\n").trim();
  }

  async assertTextStopsChanging(message: Locator): Promise<string> {
    let stopped = await this.messageText(message);
    let stableSamples = 0;
    await expect.poll(async () => {
      const current = await this.messageText(message);
      stableSamples = current === stopped ? stableSamples + 1 : 0;
      stopped = current;
      return stableSamples;
    }, {
      timeout: 10_000,
      intervals: [1000],
    }).toBeGreaterThanOrEqual(4);
    return stopped;
  }

  async renameActiveThread(title: string): Promise<void> {
    // Resolve the persisted row after a new local thread becomes server-owned.
    await this.openThread(await this.currentThreadTitle());
    const active = this.activeThread();
    await expect(active).toBeVisible();
    await active.hover();
    await active.locator("button").last().click();
    await this.page.getByRole("menuitem", { name: "重命名", exact: true }).click();
    const input = active.getByRole("textbox", { name: "重命名", exact: true });
    await expect(input).toBeVisible();
    await input.fill(title);
    const renamed = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/conversation/rename"),
    );
    await input.press("Enter");
    const response = await renamed;
    const body = await response.json().catch(() => ({}));
    if (!response.ok() || body?.code !== 0) {
      throw new Error(`conversation rename failed: HTTP ${response.status()} body=${JSON.stringify(body)}`);
    }
    try {
      await expect(this.threadButton(title)).toBeVisible();
    } catch {
      const error = new Error("conversation rename API succeeded but the sidebar title did not update to " + title);
      error.name = "ProductFailure";
      throw error;
    }
  }

  async newConversation(displayName: string): Promise<void> {
    // A history item can also be named New Chat. Scope to the creation icon.
    const create = this.page.getByRole("button", { name: /新建?对话/, exact: true })
      .filter({ has: this.page.locator("svg.lucide-square-pen") });
    await expect(create).toHaveCount(1);
    await create.click();
    // New Chat resets this conversation while retaining the selected Agent.
    await expect(this.page.getByRole("heading", { name: displayName, exact: true })).toBeVisible();
    await expect(this.composerInput()).toBeEditable();
    await expect(this.userMessages()).toHaveCount(0);
    await expect(this.assistantMessages()).toHaveCount(0);
  }

  threadButton(title: string): Locator {
    // Status badges contribute to the button's accessible name. Match only
    // the exact title node inside history rows, not badges or creation actions.
    return this.page.locator('[class~="group/item"]').getByRole("button")
      // Generated titles may contain newlines; exact text matching normalizes
      // layout whitespace whereas the previous anchored raw regex did not.
      .filter({ has: this.page.getByText(title, { exact: true }) });
  }

  async openThread(title: string, occurrence?: "first" | "last"): Promise<void> {
    const matches = this.threadButton(title);
    const target = occurrence === "first" ? matches.first() : occurrence === "last" ? matches.last() : matches;
    await target.click();
    await expect(this.activeThread()).toContainText(title);
  }

  async deleteThread(title: string): Promise<void> {
    await this.openThread(title);
    const active = this.activeThread();
    await active.hover();
    await active.locator("button").last().click();
    await this.page.getByRole("menuitem", { name: "删除", exact: true }).click();
    const dialog = this.page.getByRole("dialog");
    await expect(dialog.getByText("确定要删除这个对话吗？此操作无法撤销。")).toBeVisible();
    await dialog.getByRole("button", { name: /确\s*定|删\s*除/ }).last().click();
    await expect(this.threadButton(title)).toHaveCount(0);
  }

  async deleteActiveThread(): Promise<void> {
    const active = this.activeThread();
    await expect(active).toBeVisible();
    await active.hover();
    await active.locator("button").last().click();
    await this.page.getByRole("menuitem", { name: "删除", exact: true }).click();
    const dialog = this.page.getByRole("dialog");
    await expect(dialog.getByText("确定要删除这个对话吗？此操作无法撤销。")).toBeVisible();
    await dialog.getByRole("button", { name: /确\s*定|删\s*除/ }).last().click();
    await expect(dialog).toHaveCount(0);
  }

  metadataButton(): Locator {
    // RuntimeMetadataEditor appends a key-count badge after saving. Match the
    // complete label (with optional badge) and the real editor's Braces icon;
    // sidebar conversation titles, including an exact "Metadata", are excluded.
    return this.page.getByRole("button", { name: /^Metadata(?:\s*\(\d+\))?$/ })
      .filter({ has: this.page.locator("svg.lucide-braces") });
  }

  async setRuntimeMetadata(value: Record<string, unknown>): Promise<void> {
    await this.metadataButton().click();
    const dialog = this.page.getByRole("dialog", { name: "Metadata" });
    const editor = dialog.locator("textarea");
    await editor.fill(JSON.stringify(value, null, 2));
    await dialog.getByRole("button", { name: "确定", exact: true }).click();
    await expect(dialog).toHaveCount(0);
  }

  async assertRuntimeMetadata(value: Record<string, unknown>): Promise<void> {
    await this.metadataButton().click();
    const dialog = this.page.getByRole("dialog", { name: "Metadata" });
    await expect(dialog.locator("textarea")).toHaveValue(JSON.stringify(value, null, 2));
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
  }

  async selectKnowledge(name: string): Promise<void> {
    await this.page.getByRole("button", { name: "知识库", exact: true }).click();
    const dialog = this.page.getByRole("dialog", { name: "当前对话知识库" });
    // The current scope modal selects ResourceCards directly, not a mode radio.
    await dialog.getByRole("searchbox").fill(name);
    const item = dialog.getByRole("option", { name, exact: true });
    await expect(item).toBeVisible();
    if ((await item.getAttribute("aria-selected")) !== "true") await item.click();
    await expect(item).toHaveAttribute("aria-selected", "true");
    await dialog.getByRole("button", { name: "确认", exact: true }).click();
    await expect(dialog).toBeHidden();
  }

  async assertKnowledgeSelected(name: string, selected: boolean): Promise<void> {
    await this.page.getByRole("button", { name: "知识库", exact: true }).click();
    const dialog = this.page.getByRole("dialog", { name: "当前对话知识库" });
    await dialog.getByRole("searchbox").fill(name);
    await expect(dialog.getByRole("option", { name, exact: true }))
      .toHaveAttribute("aria-selected", String(selected));
    // Inspection must not save or change the conversation's scope.
    await dialog.getByRole("button", { name: "关闭", exact: true }).last().click();
    await expect(dialog).toBeHidden();
  }

  async uploadAttachment(payload: AttachmentPayload): Promise<void> {
    // No `[data-composer-action-trigger]` any more; the tooltip gives it a name.
    const attachButton = this.page.getByRole("button", { name: "添加附件", exact: true });
    await expect(attachButton).toBeVisible();
    const chooser = this.page.waitForEvent("filechooser");
    await attachButton.click();
    await (await chooser).setFiles(payload);
    await expect(this.page.locator("[data-workbench-composer], .aui-lexical-input")).toBeVisible();
  }
}
