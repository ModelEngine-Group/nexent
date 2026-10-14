// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, Page, type Download, type Locator, type Response } from "playwright/test";
import { appPath } from "../runner/runtime-config";

export class AgentPage {
  constructor(readonly page: Page) {}

  async open(): Promise<void> {
    await this.page.goto(appPath("/agents"), { waitUntil: "domcontentloaded" });
    await expect(this.page.getByRole("button", { name: "新建" })).toBeVisible();
  }

  async create(displayName: string, variableName: string): Promise<number> {
    await this.page.getByRole("button", { name: "新建" }).click();
    const modal = this.page.getByRole("dialog", { name: "创建智能体" });
    await modal.getByPlaceholder("请输入智能体名称").fill(displayName);
    const responsePromise = this.page.waitForResponse((r) => r.url().includes("/api/agent/update") && r.request().method() === "POST");
    await modal.getByRole("button", { name: /确\s*定/ }).click();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`agent create returned ${response.status()}`);
    const body = await response.json();
    const id = Number(body?.agent_id || body?.data?.agent_id);
    if (!Number.isInteger(id) || id <= 0) throw new Error("agent create response omitted agent_id");
    try {
      await expect(this.page.getByPlaceholder("请输入智能体名称", { exact: true })).toHaveValue(displayName);
      await this.dismissCreationGuidance();
      // Creation accepts only the display name; edit the variable name on the
      // configuration page and wait for its persisted autosave before returning.
      await this.openSection("基础信息");
      const nameInput = this.page.getByPlaceholder("请输入智能体变量名", { exact: true });
      const [saved] = await Promise.all([
        this.page.waitForResponse((r) => r.url().includes("/api/agent/update") && r.request().method() === "POST" && r.request().postDataJSON()?.name === variableName),
        nameInput.fill(variableName).then(() => nameInput.blur()),
      ]);
      if (!saved.ok()) throw new Error(`agent variable-name autosave returned ${saved.status()}`);
    } catch (error) {
      // Callers cannot register this ID until create returns.
      try { await this.delete(id); } catch (cleanupError) {
        throw new AggregateError([error, cleanupError], `agent ${id} setup and cleanup failed`);
      }
      throw error;
    }
    return id;
  }

  private async dismissCreationGuidance(): Promise<void> {
    // A newly-created Agent opens both the Ant Tour mask and the intelligent
    // generation panel. They are product guidance, not part of manual config,
    // and the Tour mask intentionally intercepts all config pointer events.
    const tourClose = this.page.locator(".ant-tour-close").first();
    await tourClose.waitFor({ state: "visible", timeout: 5000 }).catch(() => undefined);
    if (await tourClose.isVisible().catch(() => false)) await tourClose.click();
    const generationClose = this.page.getByRole("button", { name: "关闭智能生成", exact: true });
    if (await generationClose.isVisible().catch(() => false)) await generationClose.click();
  }

  async select(displayName: string): Promise<void> {
    await this.open();
    const search = this.page.getByPlaceholder("按名称或描述搜索", { exact: true });
    await search.fill(displayName);
    // The card body opens details, not the editor. The editor entry is the
    // card's 配置 action, revealed only on hover/focus-within, scoped to the
    // exact run-owned Agent card so search matches cannot select another ID.
    const card = this.page
      .getByRole("button", { name: displayName, exact: true })
      .locator("xpath=ancestor::article[1]");
    await expect(card).toHaveCount(1);
    await card.hover();
    await card.getByRole("button", { name: "配置", exact: true }).click();
    // The configure action routes to the agent's own editor page.
    await expect(this.page).toHaveURL(/\/agents\/\d+/);
    await expect(this.page.getByPlaceholder("请输入智能体名称", { exact: true })).toHaveValue(displayName);
    await expect(this.page.getByText("模型与提示词", { exact: true }).first()).toBeVisible();
    await this.dismissCreationGuidance();
  }

  async setDescription(description: string): Promise<void> {
    await this.openSection("基础信息");
    const input = this.page.getByPlaceholder("请输入智能体描述");
    await input.fill(description);
    const responsePromise = this.page.waitForResponse((r) => r.url().includes("/api/agent/update") && r.request().method() === "POST");
    await input.blur();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`agent display-info autosave returned ${response.status()}`);
  }

  async ensureAuthor(authorName = "Nexent Test Suite"): Promise<string> {
    await this.openBasic();
    await this.openSection("基础信息");
    const author = this.page.getByPlaceholder("请输入作者名称", { exact: true });
    await expect(author).toBeVisible();
    let persisted = (await author.inputValue()).trim();
    if (!persisted) {
      const saved = this.page.waitForResponse((response) =>
        response.request().method() === "POST" &&
        response.url().includes("/api/agent/update") &&
        response.request().postDataJSON()?.author === authorName,
      );
      await author.fill(authorName);
      await author.blur();
      const response = await saved;
      if (!response.ok()) throw new Error(`Agent author autosave returned ${response.status()}`);
      await this.page.reload({ waitUntil: "domcontentloaded" });
      await this.openSection("基础信息");
      persisted = (await this.page.getByPlaceholder("请输入作者名称", { exact: true }).inputValue()).trim();
    }
    if (!persisted) throw new Error("Agent author is required but was not persisted by the shared-asset setup");
    return persisted;
  }

  async openSection(name: string): Promise<Locator> {
    const title = this.page.getByText(name, { exact: true }).first();
    await expect(title).toBeVisible();
    const trigger = title.locator("xpath=ancestor::button[1]");
    if ((await trigger.getAttribute("data-state")) === "closed") await trigger.click();
    return trigger.locator("xpath=../..");
  }

  async openToolsSkills(): Promise<void> {
    const tab = this.page.getByRole("tab", { name: "工具与技能", exact: true });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
  }

  async openAdvanced(): Promise<void> {
    // The editor is one continuous stack of collapsible section cards now —
    // no Basic/Advanced tabs remain. "Advanced" means the 高级设置 section.
    await this.openSection("高级设置");
  }

  async openBasic(): Promise<void> {
    // The continuous-card editor has no Basic/Advanced tabs and no separate
    // display-info sub-heading; the basic card is identified by its own
    // display-name input.
    await this.openSection("基础信息");
    await expect(this.page.getByPlaceholder("请输入智能体名称", { exact: true })).toBeVisible();
  }

  /** Resolve a tool's numeric id from its semantic name via the tool list API. */
  async toolIdBySemanticName(semanticName: string): Promise<number> {
    const response = await this.page.request.get(
      new URL("/api/tool/list", this.page.url()).toString(),
    );
    if (!response.ok()) throw new Error(`tool list returned ${response.status()}`);
    const payload = await response.json();
    const rows = Array.isArray(payload)
      ? payload
      : Array.isArray(payload?.data)
        ? payload.data
        : [];
    const match = rows.find(
      (row: { name?: string; origin_name?: string }) =>
        (row.origin_name || row.name) === semanticName,
    ) as { id?: unknown; tool_id?: unknown } | undefined;
    const id = Number(match?.tool_id ?? match?.id);
    if (!match || !Number.isFinite(id)) {
      throw new Error(`tool ${semanticName} is missing from /api/tool/list`);
    }
    return id;
  }

  async bindKnowledgeBase(
    knowledgeBaseName: string,
    semanticToolName = "knowledge_base_search",
  ): Promise<Record<string, unknown>> {
    await this.openBasic();
    // Knowledge binding lives in the 知识库管理 section; selection goes
    // through the AddKnowledgeDrawer (rows are CheckMark buttons with
    // aria-pressed, not checkboxes) and the drawer's 确认 drives the real
    // autosave. The autosave is two requests: POST /api/agent/update
    // (enabled tool ids) followed by POST /api/tool/update carrying the
    // tool's own params (index_names / kds_list). The tool-config request is
    // the one that proves the selection, so it is captured and returned.
    await this.openSection("知识库管理");
    const toolId = await this.toolIdBySemanticName(semanticToolName);
    const selectionParam =
      semanticToolName === "aidp_search" ? "kds_list" : "index_names";
    await this.page.getByTestId("agent-knowledge-base-add-entry").click();
    const drawer = this.page.getByRole("dialog");
    await expect(drawer.getByPlaceholder("搜索知识库名称及描述")).toBeVisible();
    await drawer.getByPlaceholder("搜索知识库名称及描述").fill(knowledgeBaseName);
    const item = drawer.getByText(knowledgeBaseName, { exact: true }).last();
    await expect(item).toBeVisible();
    // KnowledgeRow: name span -> header flex -> text column -> row div whose
    // only button is the CheckMark selector.
    const checkMark = item.locator("xpath=ancestor::div[3]").getByRole("button").first();
    await checkMark.click();
    await expect(checkMark).toHaveAttribute("aria-pressed", "true");
    const toolSaves: Record<string, unknown>[] = [];
    const captureToolSave = (response: Response) => {
      const request = response.request();
      if (request.method() !== "POST") return;
      if (!new URL(request.url()).pathname.endsWith("/api/tool/update")) return;
      try {
        toolSaves.push((request.postDataJSON() ?? {}) as Record<string, unknown>);
      } catch {
        // A body-less request cannot carry the selection; skip it.
      }
    };
    this.page.on("response", captureToolSave);
    try {
      await drawer.getByRole("button", { name: "确认", exact: true }).click();
      const selected = this.page.getByTestId("agent-selected-knowledge-base-name").filter({ hasText: knowledgeBaseName });
      await expect(selected).toBeVisible();
      const hasSelection = (payload: Record<string, unknown>) => {
        if (Number(payload.tool_id) !== toolId) return false;
        const params = payload.params as Record<string, unknown> | undefined;
        const value = params?.[selectionParam];
        return typeof value === "string"
          ? value.length > 2
          : Array.isArray(value) && value.length > 0;
      };
      await expect.poll(() => toolSaves.some(hasSelection), { timeout: 30_000 }).toBe(true);
      return toolSaves.filter(hasSelection).pop() ?? {};
    } finally {
      this.page.off("response", captureToolSave);
    }
  }

  /**
   * Release the current draft as a new agent version through the real 发布
   * action. Draft edits (including knowledge bindings) only take effect in
   * conversations after a release, so any journey that continues into a new
   * conversation must publish first.
   */
  async publishDraft(versionName: string, releaseNote: string): Promise<void> {
    const published = this.page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/api\/agent\/\d+\/publish$/.test(new URL(response.url()).pathname),
      { timeout: 60_000 },
    );
    await this.page.getByRole("button", { name: "发布", exact: true }).click();
    const modal = this.page.getByRole("dialog", { name: "发布", exact: true });
    await expect(modal).toBeVisible();
    await modal.getByPlaceholder("请输入版本名称").fill(versionName);
    await modal.getByPlaceholder("请输入发布说明（可选）").fill(releaseNote);
    await modal.getByRole("button", { name: "发布", exact: true }).click();
    const response = await published;
    if (!response.ok()) throw new Error(`agent publish returned ${response.status()}`);
    await expect(
      this.page.getByText("版本发布成功", { exact: true }).first(),
    ).toBeVisible({ timeout: 30_000 });
  }

  async bindInternalCollaborator(displayName: string, expectedVersionName?: string): Promise<void> {
    await this.openAdvanced();
    // Sub-agent binding lives in the 添加子智能体 section; selection goes
    // through the AddAgentDrawer and commits per row toggle (the drawer has
    // no confirm button) through the agent update autosave.
    await this.openSection("添加子智能体");
    await this.page.getByRole("button", { name: "点击添加智能体", exact: true }).click();
    const drawer = this.page.getByRole("dialog");
    await expect(drawer).toBeVisible();
    // The source tabs are plain buttons (internal/external), not role=tab.
    await drawer.getByRole("button", { name: "内部协作智能体", exact: true }).click();
    await drawer.getByPlaceholder("搜索智能体名称或描述").fill(displayName);
    const option = drawer.getByText(displayName, { exact: true });
    await expect(option).toBeVisible();
    // AgentCard: name span -> icon row -> card div whose only button is the
    // CheckMark selector.
    const checkMark = option.locator("xpath=ancestor::div[2]").getByRole("button").first();
    const updated = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
    );
    await checkMark.click();
    const response = await updated;
    if (!response.ok()) throw new Error(`agent collaborator autosave returned ${response.status()}`);
    // The drawer header icon and the footer button share the 关闭 name; the
    // footer one is the intended close action.
    await drawer.getByRole("button", { name: "关闭", exact: true }).last().click();
    const selectedGrid = this.page.getByTestId("agent-selected-child-grid");
    await expect(selectedGrid).toContainText(displayName);
    if (expectedVersionName) {
      // The chip shows the released version number; the hover card carries
      // the version name as 名称：<name>, which is the case's expected signal.
      await selectedGrid.getByText(displayName, { exact: true }).first().hover();
      await expect(
        this.page.getByText(`名称：${expectedVersionName}`, { exact: true }).first(),
      ).toBeVisible({ timeout: 15_000 });
    }
  }

  async setConversationGuide(opening: string, exampleQuestion: string): Promise<void> {
    await this.openSection("首页欢迎信息");
    // The config surface renders the high-fidelity conversation guide: the
    // greeting textarea keeps aria-label 开场白 in both rendering modes (its
    // visible placeholder differs), the preset-question button is 添加问题
    // (legacy: 添加示例问题), and the question input keeps its placeholder.
    const firstUpdate = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
    );
    const openingInput = this.page.getByLabel("开场白", { exact: true });
    await openingInput.fill(opening);
    await openingInput.blur();
    if (!(await firstUpdate).ok()) throw new Error("conversation opening autosave failed");
    await this.page.getByRole("button", { name: /添加(示例)?问题/ }).click();
    const secondUpdate = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
    );
    const example = this.page.getByPlaceholder("请输入示例问题").last();
    await example.fill(exampleQuestion);
    await example.blur();
    if (!(await secondUpdate).ok()) throw new Error("conversation example autosave failed");
  }

  async ensureGuardrailRule(pattern: string): Promise<void> {
    await this.openAdvanced();
    // Guardrail rules moved behind the 更多配置 icon action on the
    // run-strategy card (aria-label 更多配置), which opens the modal.
    await this.page.getByRole("button", { name: "更多配置", exact: true }).click();
    const modal = this.page.getByRole("dialog").filter({ hasText: "安全护栏" });
    await expect(modal).toBeVisible();
    // The modal also carries the protocol-repair switch; the guardrail enable
    // switch is the one sharing the 安全护栏 title row.
    const guardrailSwitch = modal
      .getByText("安全护栏", { exact: true })
      .locator("xpath=ancestor::div[1]")
      .getByRole("switch");
    if ((await guardrailSwitch.getAttribute("aria-checked")) !== "true") {
      const enabled = this.page.waitForResponse(
        (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
      );
      await guardrailSwitch.click();
      if (!(await enabled).ok()) throw new Error("guardrail enable autosave failed");
    }
    await modal.getByRole("button", { name: "添加规则", exact: true }).last().click();
    const saved = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
    );
    const patternInput = modal.getByPlaceholder("如 \\d{17}[\\dXx]").first();
    await patternInput.fill(pattern);
    await patternInput.blur();
    if (!(await saved).ok()) throw new Error("guardrail rule autosave failed");
    await expect(patternInput).toHaveValue(pattern);
    // Close the modal so the header actions (e.g. the debug toggle) become
    // clickable again. antd ignores Escape here, so use its close control.
    await modal.locator(".ant-modal-close").click();
    await expect(modal).toBeHidden();
  }

  async selectModel(displayName: string): Promise<void> {
    const section = await this.openSection("模型与提示词");
    // When a default model is already selected Ant Select does not render its
    // placeholder. Scope the combobox to the role/model section instead.
    const selector = section.getByRole("combobox").first();
    await selector.click();
    const option = this.page.getByText(displayName, { exact: true }).last();
    await expect(option).toBeVisible();
    const responsePromise = this.page.waitForResponse((r) => r.url().includes("/api/agent/update") && r.request().method() === "POST");
    await option.click();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`agent model autosave returned ${response.status()}`);
    if (await this.page.locator(".ant-select-dropdown:visible").count()) {
      await this.page.keyboard.press("Escape");
      await expect(this.page.locator(".ant-select-dropdown:visible")).toHaveCount(0);
    }
  }

  async bindTool(toolName: string): Promise<void> {
    await this.page.getByRole("tab", { name: "工具与技能", exact: true }).click();
    await this.page.getByRole("button", { name: "选择工具", exact: true }).click();
    const dialog = this.page.getByRole("dialog", { name: "选择工具" });
    await dialog.getByRole("tab", { name: "MCP", exact: true }).click();
    await dialog.getByPlaceholder("搜索工具名称、描述或标签…").fill(toolName);
    const row = dialog.getByRole("button").filter({ hasText: toolName }).first();
    await expect(row).toBeVisible();
    const updated = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
    );
    await row.click();
    if (!(await updated).ok()) throw new Error(`tool ${toolName} autosave failed`);
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(this.page.getByText(toolName, { exact: true }).first()).toBeVisible();
  }

  async bindToolFromService(serviceName: string, toolName: string): Promise<void> {
    await this.page.getByRole("tab", { name: "工具与技能", exact: true }).click();
    await this.page.getByRole("button", { name: "选择工具", exact: true }).click();
    const dialog = this.page.getByRole("dialog", { name: "选择工具" });
    await dialog.getByRole("tab", { name: "MCP", exact: true }).click();
    await dialog.getByPlaceholder("搜索工具名称、描述或标签…").fill(toolName);
    const category = dialog.getByRole("button", { name: new RegExp(serviceName) });
    await expect(category).toBeVisible();
    await category.click();
    const row = dialog.getByRole("button").filter({ hasText: toolName }).first();
    await expect(row).toBeVisible();
    const updated = this.page.waitForResponse((response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"));
    await row.click();
    if (!(await updated).ok()) throw new Error(`tool ${toolName} from ${serviceName} autosave failed`);
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
  }

  async bindSkill(skillName: string): Promise<void> {
    await this.page.getByRole("tab", { name: "工具与技能", exact: true }).click();
    await this.page.getByRole("button", { name: "选择技能", exact: true }).click();
    const dialog = this.page.getByRole("dialog", { name: "选择技能" });
    await dialog.getByPlaceholder("按名称、描述或标签搜索").fill(skillName);
    const row = dialog.getByRole("button").filter({ hasText: skillName }).first();
    await expect(row).toBeVisible();
    const updated = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
    );
    await row.click();
    if (!(await updated).ok()) throw new Error(`skill ${skillName} autosave failed`);
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await expect(this.page.getByText(skillName, { exact: true }).first()).toBeVisible();
  }

  async setPrompts(values: { duty?: string; constraint?: string; fewShots?: string }): Promise<void> {
    await this.openSection("模型与提示词");
    for (const [tab, placeholder, value] of [
      ["智能体角色", "请输入智能体的角色、职责和能力", values.duty],
      ["使用要求", "请输入此智能体的使用要求或约束条件", values.constraint],
      ["示例", "请输入示例问答，帮助智能体理解预期行为", values.fewShots],
    ] as const) {
      if (value === undefined) continue;
      await this.page.getByRole("tab", { name: tab }).click();
      const input = this.page.getByPlaceholder(new RegExp(placeholder));
      await input.fill(value);
      const responsePromise = this.page.waitForResponse((r) => r.url().includes("/api/agent/update") && r.request().method() === "POST");
      await input.blur();
      const response = await responsePromise;
      if (!response.ok()) throw new Error(`agent prompt autosave returned ${response.status()}`);
    }
  }

  async expandDutyPrompt(content: string): Promise<void> {
    await this.openSection("模型与提示词");
    await this.page.getByRole("tab", { name: "智能体角色", exact: true }).click();
    await this.page.getByRole("button", { name: "放大查看", exact: true }).click();
    const modal = this.page.getByRole("dialog", { name: "智能体角色" });
    await expect(modal).toBeVisible();
    await modal.getByRole("textbox").fill(content);
    const updated = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
    );
    await modal.getByRole("button", { name: /确\s*定/ }).click();
    const response = await updated;
    if (!response.ok()) throw new Error(`expanded duty prompt autosave returned ${response.status()}`);
    await expect(this.page.getByPlaceholder(/请输入智能体的角色、职责和能力/)).toHaveValue(content);
  }

  /** The editor pane's debug side is a header toggle plus a fixed panel. */
  private debugPanel(): Locator {
    return this.page.locator("[data-testid='agent-debug-panel']");
  }

  async openDebug(): Promise<void> {
    const debugButton = this.page.getByRole("button", { name: "智能体调试", exact: true });
    await expect(debugButton).toBeVisible();
    if ((await debugButton.getAttribute("aria-pressed")) !== "true") {
      await debugButton.click();
    }
    await expect.poll(async () => {
      if (await this.debugPanel().isVisible().catch(() => false)) return "open";
      if (await this.page.locator(".ant-form-item-explain-error:visible").count()) return "invalid";
      return "pending";
    }, { timeout: 30000 }).not.toBe("pending");
    const validationErrors = await this.page.locator(".ant-form-item-explain-error:visible").allTextContents();
    if (validationErrors.length) {
      throw new Error(`Cannot open Debug: Agent form validation failed: ${validationErrors.join("; ")}`);
    }
    await expect(this.debugPanel()).toBeVisible({ timeout: 30000 });
    await expect(this.debugPanel().locator("textarea[placeholder='输入\"/\"快速引用技能及指令']:visible, textarea[placeholder*=\"输入测试问题\"]:visible")).toBeVisible({ timeout: 120000 });
  }

  async sendDebug(prompt: string, expectedMarker?: string): Promise<string> {
    const debugPanel = this.debugPanel();
    await expect(debugPanel).toBeVisible();
    const input = debugPanel.locator("textarea[placeholder='输入\"/\"快速引用技能及指令']:visible, textarea[placeholder*=\"输入测试问题\"]:visible");
    // Empty completed replies can have zero layout height. Count their DOM
    // unit too; visibility must not turn an empty answer into a five-minute wait.
    // Compare and normal histories stay mounted together. Exclude hidden
    // panes, but still count an empty normal reply with zero layout height.
    const messages = debugPanel.locator("[data-slot='aui_assistant-message-root']:not(.hidden *)");
    const before = await messages.count();
    await input.fill(prompt);
    const streamPromise = this.page.waitForResponse((r) => r.request().method() === "POST" && /\/agent\/run$/.test(new URL(r.url()).pathname), { timeout: 300000 });
    const send = debugPanel.getByRole("button", { name: "发送", exact: true });
    await send.click();
    const stream = await streamPromise;
    if (stream.status() >= 500) throw new Error(`agent debug stream returned ${stream.status()}`);
    // Headers and the assistant placeholder precede SSE final_answer. Absence
    // of a Stop icon is also true before streaming mounts; it is not a terminal.
    let streamDone = false;
    let streamError: Error | null = null;
    void stream.finished().then((error) => { streamError = error; streamDone = true; });
    await expect.poll(() => streamDone, { timeout: 300000 }).toBe(true);
    if (streamError) throw new Error(`agent debug stream interrupted: ${streamError}`);
    await expect(messages).toHaveCount(before + 1, { timeout: 300000 });
    const responseText = messages.last().locator("[data-citation-index-map] .aui-md:visible");
    await expect(debugPanel.locator("button:has(svg.lucide-square)")).toHaveCount(0, { timeout: 300000 });
    await expect(send).toBeVisible({ timeout: 300000 });
    // A short UI commit window, never five minutes on a completed empty reply.
    // The selector still excludes reasoning and echoed user instructions.
    await expect.poll(async () => (await responseText.allTextContents()).join("\n").trim(),
      { timeout: 3000 }).not.toBe("").catch(() => undefined);
    const answer = (await responseText.allTextContents()).join("\n").trim();
    if (!answer || (expectedMarker && !answer.includes(expectedMarker))) {
      const error = new Error(!answer ? "agent debug completed without a rendered response"
        : `completed agent debug response omitted required marker ${expectedMarker}`);
      error.name = "ProductFailure"; // Business outcome, not a product/root-cause attribution.
      throw error;
    }
    return answer;
  }

  async debug(prompt: string, expectedMarker?: string): Promise<string> {
    await this.openDebug();
    return this.sendDebug(prompt, expectedMarker);
  }

  async exportSelected(displayName: string): Promise<Download> {
    await this.open();
    await this.page.getByPlaceholder("按名称或描述搜索", { exact: true }).fill(displayName);
    const card = this.page.getByRole("button", { name: displayName, exact: true }).locator("xpath=..");
    await expect(card).toHaveCount(1);
    await card.getByRole("button", { name: "更多操作", exact: true }).click();
    const download = this.page.waitForEvent("download");
    await this.page.getByRole("menuitem", { name: "导出", exact: true }).click();
    return download;
  }

  async copyAgent(displayName: string): Promise<number> {
    await this.open();
    await this.page.getByPlaceholder("按名称或描述搜索", { exact: true }).fill(displayName);
    const card = this.page.getByRole("button", { name: displayName, exact: true }).locator("xpath=..");
    await expect(card).toHaveCount(1);
    await card.getByRole("button", { name: "更多操作", exact: true }).click();
    const created = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
      { timeout: 120_000 },
    );
    await this.page.getByRole("menuitem", { name: "复制", exact: true }).click();
    await this.page.getByRole("dialog").getByRole("button", { name: /确\s*定/ }).click();
    const response = await created;
    if (!response.ok()) throw new Error(`agent copy returned ${response.status()}`);
    const body = await response.json();
    const id = Number(body?.agent_id || body?.data?.agent_id);
    if (!Number.isInteger(id) || id <= 0) throw new Error("agent copy response omitted agent_id");
    await expect(this.page.getByText("智能体复制成功", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
    return id;
  }

  async expectAgentAvailable(displayName: string): Promise<void> {
    let observed: { name?: string; display_name?: string; is_available?: boolean; unavailable_reasons?: string[] } | null = null;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const response = await this.page.request.get("/api/agent/list");
      if (response.ok()) {
        const payload = await response.json();
        // /api/agent/list returns a bare JSON array, not a wrapped object.
        const rows = Array.isArray(payload) ? payload : (Array.isArray(payload?.data) ? payload.data : []);
        const match = rows.find((row: { display_name?: string }) => row.display_name === displayName);
        if (match) {
          if (match.is_available === false) {
            throw new Error(`copied agent ${displayName} was marked unavailable: ${JSON.stringify(match.unavailable_reasons || [])}`);
          }
          observed = match;
          break;
        }
      }
      await this.page.waitForTimeout(1000);
    }
    if (!observed) throw new Error(`copied agent ${displayName} was not returned by /api/agent/list`);
    const reasons = observed.unavailable_reasons || [];
    if (reasons.includes("duplicate_name") || reasons.includes("duplicate_display_name")) {
      throw new Error(`copied agent ${displayName} kept duplicate unavailable reasons: ${JSON.stringify(reasons)}`);
    }
  }

  async openImport(filePath: string): Promise<void> {
    await this.open();
    const chooser = this.page.waitForEvent("filechooser");
    await this.page.getByRole("button", { name: /^导\s*入$/ }).click();
    await (await chooser).setFiles(filePath);
    await expect(this.page.getByRole("dialog", { name: "安装智能体" })).toBeVisible({ timeout: 120_000 });
  }

  async resolveImportConflict(variableName: string, displayName: string): Promise<void> {
    const dialog = this.page.getByRole("dialog", { name: "安装智能体" });
    await expect(dialog.getByText("重命名智能体", { exact: true })).toBeVisible({ timeout: 120_000 });
    const inputs = dialog.getByRole("textbox");
    await expect(inputs).toHaveCount(2);
    await inputs.nth(0).fill(variableName);
    await inputs.nth(1).fill(displayName);
    await expect(dialog.getByText("所有智能体名称冲突已解决。您可以继续下一步。", { exact: true })).toBeVisible({ timeout: 120_000 });
  }

  async installImportedAgent(modelName: string, onImported: (id: number) => void): Promise<number> {
    const dialog = this.page.getByRole("dialog", { name: "安装智能体" });
    await dialog.getByRole("button", { name: "下一步", exact: true }).click();
    await expect(dialog.getByText("选择模型", { exact: true })).toBeVisible();
    await dialog.getByRole("combobox").first().click();
    // Ant Select renders its popup outside the dialog and the option wrapper
    // does not consistently expose role=option. Match the exact configured
    // display name, never a test-invented alias.
    const modelOption = this.page.getByText(modelName, { exact: true }).last();
    await expect(modelOption).toBeVisible();
    await modelOption.click();
    const next = dialog.getByRole("button", { name: "下一步", exact: true });
    for (let step = 0; step < 8 && await next.isVisible(); step += 1) {
      await expect(next).toBeEnabled();
      await next.click();
    }
    await expect(next).toBeHidden();
    const imported = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && /agent.*import|import.*agent/i.test(response.url()),
      { timeout: 300_000 },
    );
    await dialog.getByRole("button", { name: /^安\s*装$/ }).click();
    const response = await imported;
    if (!response.ok()) throw new Error(`agent import returned ${response.status()}`);
    const body = await response.json();
    const id = Number(body?.agent_id || body?.data?.agent_id);
    if (!Number.isInteger(id) || id <= 0) throw new Error("agent import response omitted agent_id");
    // Register ownership before any later navigation or UI assertion can fail.
    onImported(id);
    await expect(dialog).toBeHidden({ timeout: 120_000 });
    return id;
  }

  /** Switch the debug pane between single and compare modes via its header menu. */
  private async setDebugCompareMode(enabled: boolean): Promise<void> {
    const debugPanel = this.debugPanel();
    await debugPanel.getByRole("button", { name: "调试选项", exact: true }).click();
    const item = this.page
      .getByRole("menuitem", { name: enabled ? "对比模式" : "默认模式", exact: true })
      .last();
    await expect(item).toBeVisible();
    await item.click();
  }

  async openDebugCompare(): Promise<void> {
    await this.openDebug();
    await this.setDebugCompareMode(true);
    const debugPanel = this.debugPanel();
    // A selected Ant Select no longer exposes its placeholder. The two
    // comboboxes inside the visible Debug panel are the real compare columns.
    await expect(debugPanel.getByRole("combobox")).toHaveCount(2);
    await expect(debugPanel.locator("textarea[placeholder='输入\"/\"快速引用技能及指令']:visible")).toHaveCount(1);
  }

  async sendDebugCompare(prompt: string, expectedMarker?: string): Promise<string[]> {
    const debugPanel = this.debugPanel();
    // Each compare column owns a separate history. Global DOM indices interleave
    // old and new replies after the first round, so count each column separately.
    const selectors = debugPanel.getByRole("combobox");
    await expect(selectors).toHaveCount(2);
    const columns = [0, 1].map((index) => selectors.nth(index).locator(
      "xpath=ancestor::div[contains(@class, 'flex h-full w-full flex-col')][1]",
    ));
    const histories = columns.map((column) => column.locator("[data-slot='aui_assistant-message-root']:visible"));
    const before = await Promise.all(histories.map((history) => history.count()));
    const composer = debugPanel.locator("textarea[placeholder='输入\"/\"快速引用技能及指令']:visible");
    await composer.fill(prompt);
    await debugPanel.getByRole("button", { name: "发送", exact: true }).click();
    await Promise.all(histories.map((history, index) => expect(history).toHaveCount(before[index] + 1, { timeout: 300000 })));
    const result: string[] = [];
    for (let index = 0; index < histories.length; index += 1) {
      const answer = histories[index].nth(before[index]);
      const responseText = answer.locator("[data-citation-index-map] .aui-md:visible");
      if (expectedMarker) {
        try {
          await expect.poll(async () => (await responseText.allTextContents()).join("\n"), { timeout: 300000 }).toContain(expectedMarker);
        } catch (error) {
          const rendered = (await answer.innerText().catch(() => "")).trim();
          if (rendered && !/连接中|connecting/i.test(rendered)) {
            const productError = new Error(`Compare response did not apply expected marker ${expectedMarker}; rendered=${rendered.slice(0, 1000)}`);
            productError.name = "ProductFailure";
            throw productError;
          }
          throw error;
        }
      }
      result.push((await responseText.allTextContents()).join("\n").trim());
    }
    await expect(debugPanel.locator("button:has(svg.lucide-square)")).toHaveCount(0, { timeout: 300000 });
    await expect(debugPanel.getByRole("button", { name: "发送", exact: true })).toBeVisible({ timeout: 300000 });
    if (result.some((value) => value.length === 0)) throw new Error("compare debug produced an empty rendered answer");
    return result;
  }

  async closeDebugCompare(): Promise<void> {
    await this.setDebugCompareMode(false);
    await expect(this.debugPanel().locator("textarea[placeholder='输入\"/\"快速引用技能及指令']:visible")).toHaveCount(1);
  }

  async publish(): Promise<Locator> {
    await this.page.getByRole("button", { name: "发布", exact: true }).click();
    const modal = this.page.locator("[role='dialog']:visible").filter({ hasText: /版本名称/ });
    await expect(modal).toBeVisible();
    return modal;
  }

  async publishVersion(versionName: string, releaseNote: string): Promise<void> {
    const editorUrl = this.page.url();
    const modal = await this.publish();
    await modal.getByPlaceholder("请输入版本名称").fill(versionName);
    await modal.getByPlaceholder("请输入发布说明（可选）").fill(releaseNote);
    const published = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && /\/api\/agent\/\d+\/publish(?:\?|$)/.test(response.url()),
    );
    // The current product uses an Ant form submit button. Its accessible name
    // is not stable while the dialog animates, but the submit contract is.
    const submit = modal.locator("button[type='submit']");
    await expect(submit).toBeVisible();
    await expect(submit).toBeEnabled();
    await submit.click();
    const response = await published;
    if (!response.ok()) throw new Error(`agent publish returned ${response.status()}`);
    await expect(modal).toBeHidden();
    // Publish may return to the warehouse. Resume the same owned Agent's
    // editor before checking the current-version tag and editing its Draft.
    if (this.page.url() !== editorUrl) {
      await this.page.goto(editorUrl, { waitUntil: "domcontentloaded" });
      await this.dismissCreationGuidance();
    }
    await expect(this.page.getByText(versionName, { exact: true }).first()).toBeVisible();
  }

  async openVersionManage(versionName: string): Promise<void> {
    const tag = this.page.getByText(versionName, { exact: true }).first();
    await expect(tag).toBeVisible();
    await tag.click();
    await expect(this.page.getByRole("heading", { name: "版本管理", exact: true })).toBeVisible();
  }

  async closeVersionManage(): Promise<void> {
    const close = this.page.getByRole("button", { name: /关闭版本管理|关闭调试/ }).last();
    if (await close.count()) await close.click();
    await expect(this.page.getByRole("heading", { name: "版本管理", exact: true })).toBeHidden();
  }

  async expandVersionDetails(versionName: string): Promise<void> {
    const card = this.page.getByText(versionName, { exact: true }).locator("xpath=ancestor::*[contains(@class,'ant-card')][1]");
    await expect(card).toBeVisible();
    const detail = this.page.waitForResponse(
      (response) => response.request().method() === "GET" && /\/api\/agent\/\d+\/versions\/\d+\/detail(?:\?|$)/.test(response.url()),
    );
    await card.getByRole("button").first().click();
    const response = await detail;
    if (!response.ok()) throw new Error(`agent version detail returned ${response.status()}`);
    await expect(card.getByText("配置", { exact: true })).toBeVisible();
  }

  async compareLatestVersions(): Promise<void> {
    const compared = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && /\/api\/agent\/\d+\/versions\/compare(?:\?|$)/.test(response.url()),
    );
    await this.page.getByRole("button", { name: "版本对比", exact: true }).last().click();
    const response = await compared;
    if (!response.ok()) throw new Error(`agent version compare returned ${response.status()}`);
    await expect(this.page.getByRole("dialog", { name: "版本对比" })).toBeVisible();
  }

  async delete(agentId: number): Promise<void> {
    const response = await this.page.request.delete("/api/agent", { data: { agent_id: agentId } });
    if (!response.ok() && response.status() !== 404) throw new Error(`agent cleanup returned ${response.status()}`);
  }
}
