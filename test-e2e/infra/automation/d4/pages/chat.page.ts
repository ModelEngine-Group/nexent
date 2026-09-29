import { expect, type Locator, type Page } from "playwright/test";
import { appPath } from "../runner/runtime-config";

export class ChatPage {
  private lastServerConversationId?: number;

  constructor(readonly page: Page) {}

  assistantMessages(): Locator {
    return this.page.locator("[data-slot='aui_assistant-message-root']");
  }

  userMessages(): Locator {
    return this.page.locator("[data-slot='aui_user-message-root']");
  }

  activeThread(): Locator {
    return this.page.locator("[data-active='true']").filter({ has: this.page.locator("button") }).first();
  }

  async currentThreadTitle(): Promise<string> {
    const active = this.activeThread();
    await expect(active).toBeVisible();
    const title = (await active.locator("span.truncate").first().innerText()).trim();
    if (!title) throw new Error("active conversation has no visible sidebar title");
    return title;
  }

  async openAgent(displayName: string): Promise<void> {
    await this.page.goto(appPath("/newchat"), { waitUntil: "domcontentloaded" });
    await this.selectAgent(displayName);
  }

  async selectAgent(displayName: string): Promise<void> {
    const search = this.page.getByPlaceholder("搜索智能体...");
    await expect(search).toBeVisible();
    await search.fill(displayName);
    const card = this.page.getByRole("button", { name: new RegExp(displayName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) }).first();
    await expect(card).toBeVisible();
    await card.click();
    await expect(this.page.getByPlaceholder("发送消息...")).toBeVisible();
  }

  async selectMode(mode: "规划" | "执行"): Promise<void> {
    const button = this.page.getByRole("button", { name: mode, exact: true });
    await button.click();
    await expect(button).toHaveClass(/bg-blue-50/);
  }

  async startMessage(prompt: string): Promise<Locator> {
    const before = await this.assistantMessages().count();
    const composer = this.page.getByPlaceholder("发送消息...");
    await composer.fill(prompt);
    const runResponse = this.page.waitForResponse(
      (response) => response.request().method() === "POST"
        && response.url().includes("/api/agent/run")
        && (response.headers()["content-type"] || "").includes("text/event-stream"),
      { timeout: 120_000 },
    );
    await this.page.getByRole("button", { name: "发送", exact: true }).click();
    const response = await runResponse;
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
    // A cancelled message is incomplete, so it has no Completed badge.
    await expect(this.page.locator("button:has(svg.lucide-square)")).toHaveCount(0, { timeout: 120_000 });
    await expect(this.page.getByPlaceholder("发送消息...")).toBeEditable();
  }

  async messageText(message: Locator): Promise<string> {
    return (await message.locator(".aui-md").allTextContents()).join("\n").trim();
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
    const active = this.activeThread();
    await expect(active).toBeVisible();
    await active.hover();
    await active.locator("button").last().click();
    await this.page.getByRole("menuitem", { name: "重命名", exact: true }).click();
    const input = active.locator("input[type='text']");
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
      await expect(this.page.getByRole("button", { name: title, exact: true })).toBeVisible();
    } catch {
      const error = new Error("conversation rename API succeeded but sidebar did not expose the new title " + title + "; generatedTitles may be overriding the persisted title");
      error.name = "ProductFailure";
      throw error;
    }
  }

  async newConversation(displayName: string): Promise<void> {
    await this.page.getByRole("button", { name: /新建?对话/, exact: true }).click();
    await expect(this.page.getByPlaceholder("搜索智能体...")).toBeVisible();
    await this.page.getByPlaceholder("搜索智能体...").fill(displayName);
    await this.page.getByRole("button", { name: new RegExp(displayName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) }).first().click();
    await expect(this.page.getByPlaceholder("发送消息...")).toBeVisible();
  }

  async openThread(title: string, occurrence?: "first" | "last"): Promise<void> {
    const matches = this.page.getByRole("button", { name: title, exact: true });
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
    await expect(this.page.getByRole("button", { name: title, exact: true })).toHaveCount(0);
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

  async setRuntimeMetadata(value: Record<string, unknown>): Promise<void> {
    await this.page.getByRole("button", { name: /Metadata/ }).click();
    const dialog = this.page.getByRole("dialog", { name: "Metadata" });
    const editor = dialog.locator("textarea");
    await editor.fill(JSON.stringify(value, null, 2));
    await dialog.getByRole("button", { name: "确定", exact: true }).click();
    await expect(dialog).toHaveCount(0);
  }

  async assertRuntimeMetadata(value: Record<string, unknown>): Promise<void> {
    await this.page.getByRole("button", { name: /Metadata/ }).click();
    const dialog = this.page.getByRole("dialog", { name: "Metadata" });
    await expect(dialog.locator("textarea")).toHaveValue(JSON.stringify(value, null, 2));
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
  }

  async selectKnowledge(name: string): Promise<void> {
    await this.page.getByRole("button", { name: /知识库：/ }).click();
    const dialog = this.page.getByRole("dialog", { name: "当前对话知识库" });
    await dialog.getByText("指定知识库", { exact: true }).click();
    const item = dialog.getByText(name, { exact: true }).first();
    await expect(item).toBeVisible();
    await item.click();
    await dialog.getByRole("button", { name: "确定", exact: true }).click();
    await expect(dialog).toHaveCount(0);
  }

  async uploadAttachment(filePath: string): Promise<void> {
    const chooser = this.page.waitForEvent("filechooser");
    await this.page.getByRole("button", { name: "添加附件", exact: true }).click();
    await (await chooser).setFiles(filePath);
  }
}
