import { expect, Page, type Download, type Locator } from "playwright/test";
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
      await expect(this.page.getByText(displayName, { exact: true }).first()).toBeVisible();
      await this.dismissCreationGuidance();
      // Creation accepts only the display name; edit the variable name on the
      // configuration page and wait for its persisted autosave before returning.
      await this.openSection("展示信息");
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
    await this.page.getByText("选择智能体", { exact: true }).click();
    const search = this.page.getByPlaceholder("按名称或描述搜索", { exact: true });
    await search.fill(displayName);
    await this.page.getByRole("menuitem").filter({ has: this.page.getByText(displayName, { exact: true }) }).click();
    await expect(this.page.getByText("模型与提示词", { exact: true }).first()).toBeVisible();
    await this.dismissCreationGuidance();
  }

  async setDescription(description: string): Promise<void> {
    await this.openSection("展示信息");
    const input = this.page.getByPlaceholder("请输入智能体描述");
    await input.fill(description);
    const responsePromise = this.page.waitForResponse((r) => r.url().includes("/api/agent/update") && r.request().method() === "POST");
    await input.blur();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`agent display-info autosave returned ${response.status()}`);
  }

  async ensureAuthor(authorName = "Nexent Test Suite"): Promise<string> {
    await this.openBasic();
    await this.openSection("展示信息");
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
      await this.openSection("展示信息");
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

  async openAdvanced(): Promise<void> {
    const tab = this.page.getByRole("tab", { name: /高级设置|高级配置/ });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-selected", "true");
  }

  async openBasic(): Promise<void> {
    await this.page.getByRole("tab", { name: /基本设置|基础配置/, exact: true }).click();
    await expect(this.page.getByText("展示信息", { exact: true }).first()).toBeVisible();
  }

  async bindKnowledgeBase(knowledgeBaseName: string): Promise<void> {
    await this.openBasic();
    await this.openSection("知识库");
    await this.page.getByRole("button", { name: "选择知识库", exact: true }).click();
    const modal = this.page.getByRole("dialog", { name: "选择知识库" });
    await expect(modal).toBeVisible();
    const search = modal.getByPlaceholder("搜索知识库名称");
    await search.fill(knowledgeBaseName);
    const item = modal.getByText(knowledgeBaseName, { exact: true }).last();
    await expect(item).toBeVisible();
    await modal.getByRole("checkbox").check();
    const updatePromise = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
    );
    await modal.getByRole("button", { name: /确\s*定/, exact: true }).click();
    const updated = await updatePromise;
    if (!updated.ok()) throw new Error(`agent knowledge autosave returned ${updated.status()}`);
    await expect(this.page.getByText(knowledgeBaseName, { exact: true }).first()).toBeVisible();
  }

  async bindInternalCollaborator(displayName: string, expectedVersionName?: string): Promise<void> {
    await this.openAdvanced();
    await this.openSection("协作智能体");
    await this.page.getByRole("button", { name: "选择智能体", exact: true }).click();
    const modal = this.page.getByRole("dialog", { name: "选择协作智能体" });
    await expect(modal).toBeVisible();
    await modal.getByRole("tab", { name: "内部协作智能体", exact: true }).click();
    await modal.getByPlaceholder("搜索智能体名称或描述").fill(displayName);
    const option = modal.getByText(displayName, { exact: true });
    await expect(option).toBeVisible();
    if (expectedVersionName) {
      const optionRow = option.locator("xpath=ancestor::*[self::button or @role='button'][1]");
      await expect(optionRow).toContainText(expectedVersionName);
    }
    await option.click();
    const updated = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
    );
    await modal.getByRole("button", { name: /确\s*定/, exact: true }).click();
    const response = await updated;
    if (!response.ok()) throw new Error(`agent collaborator autosave returned ${response.status()}`);
    await expect(this.page.getByText(displayName, { exact: true }).first()).toBeVisible();
  }

  async setConversationGuide(opening: string, exampleQuestion: string): Promise<void> {
    await this.openBasic();
    await this.openSection("会话引导");
    const firstUpdate = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
    );
    const openingInput = this.page.getByPlaceholder("请输入用户首次进入会话时看到的开场白");
    await openingInput.fill(opening);
    await openingInput.blur();
    if (!(await firstUpdate).ok()) throw new Error("conversation opening autosave failed");
    await this.page.getByRole("button", { name: "添加示例问题", exact: true }).click();
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
    const section = await this.openSection("安全护栏");
    const guardrailSwitch = section.getByRole("switch");
    if ((await guardrailSwitch.getAttribute("aria-checked")) !== "true") {
      const enabled = this.page.waitForResponse(
        (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
      );
      await guardrailSwitch.click();
      if (!(await enabled).ok()) throw new Error("guardrail enable autosave failed");
    }
    await this.page.getByRole("button", { name: "添加规则", exact: true }).last().click();
    const saved = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/agent/update"),
    );
    const patternInput = this.page.getByPlaceholder("如 \\d{17}[\\dXx]").first();
    await patternInput.fill(pattern);
    await patternInput.blur();
    if (!(await saved).ok()) throw new Error("guardrail rule autosave failed");
    await expect(patternInput).toHaveValue(pattern);
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

  async openDebug(): Promise<void> {
    const debugPanel = this.page.getByRole("heading", { name: /^(调试|Debug)$/ })
      .locator("xpath=ancestor::section[1]");
    if (!(await debugPanel.isVisible().catch(() => false))) {
      await this.page.getByRole("button", { name: /^(调试|Debug)$/, exact: true }).click();
    }
    await expect.poll(async () => {
      if (await debugPanel.isVisible().catch(() => false)) return "open";
      if (await this.page.locator(".ant-form-item-explain-error:visible").count()) return "invalid";
      return "pending";
    }, { timeout: 30000 }).not.toBe("pending");
    const validationErrors = await this.page.locator(".ant-form-item-explain-error:visible").allTextContents();
    if (validationErrors.length) {
      throw new Error(`Cannot open Debug: Agent form validation failed: ${validationErrors.join("; ")}`);
    }
    await expect(debugPanel).toBeVisible({ timeout: 30000 });
    await expect(debugPanel.locator('textarea[placeholder="发送消息..."]:visible, textarea[placeholder*="输入测试问题"]:visible')).toBeVisible({ timeout: 120000 });
  }

  async sendDebug(prompt: string, expectedMarker?: string): Promise<string> {
    const debugPanel = this.page.getByRole("heading", { name: /^(调试|Debug)$/ })
      .locator("xpath=ancestor::section[1]");
    await expect(debugPanel).toBeVisible();
    const input = debugPanel.locator('textarea[placeholder="发送消息..."]:visible, textarea[placeholder*="输入测试问题"]:visible');
    const messages = debugPanel.locator("[data-slot='aui_assistant-message-root']:visible");
    const before = await messages.count();
    await input.fill(prompt);
    const streamPromise = this.page.waitForResponse((r) => r.request().method() === "POST" && /agent|chat|conversation/.test(r.url()), { timeout: 300000 });
    const send = debugPanel.getByRole("button", { name: "发送", exact: true });
    await send.click();
    const stream = await streamPromise;
    if (stream.status() >= 500) throw new Error(`agent debug stream returned ${stream.status()}`);
    await expect(messages).toHaveCount(before + 1, { timeout: 300000 });
    if (expectedMarker) await expect(messages.last().getByText(expectedMarker, { exact: true })).toBeVisible({ timeout: 300000 });
    await expect(debugPanel.locator("button:has(svg.lucide-square)")).toHaveCount(0, { timeout: 300000 });
    await expect(send).toBeVisible({ timeout: 300000 });
    const answer = (await messages.last().innerText()).trim();
    if (!answer) throw new Error("agent debug completed without a rendered response");
    if (expectedMarker && !answer.includes(expectedMarker)) throw new Error(`agent debug response omitted marker ${expectedMarker}`);
    return answer;
  }

  async debug(prompt: string, expectedMarker?: string): Promise<string> {
    await this.openDebug();
    return this.sendDebug(prompt, expectedMarker);
  }

  async exportSelected(): Promise<Download> {
    const download = this.page.waitForEvent("download");
    await this.page.locator("button:has(svg.lucide-file-output)").click();
    return download;
  }

  async openImport(filePath: string): Promise<void> {
    const chooser = this.page.waitForEvent("filechooser");
    await this.page.getByRole("button", { name: "导入", exact: true }).click();
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

  async installImportedAgent(modelName: string): Promise<void> {
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
    while (await dialog.getByRole("button", { name: "下一步", exact: true }).count()) {
      await dialog.getByRole("button", { name: "下一步", exact: true }).click();
    }
    const imported = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && /agent.*import|import.*agent/i.test(response.url()),
      { timeout: 300_000 },
    );
    await dialog.getByRole("button", { name: "安装", exact: true }).click();
    const response = await imported;
    if (!response.ok()) throw new Error(`agent import returned ${response.status()}`);
    await expect(dialog).toBeHidden({ timeout: 120_000 });
  }

  async openDebugCompare(): Promise<void> {
    await this.openDebug();
    const debugPanel = this.page.locator("section:not(.hidden)", {
      has: this.page.getByRole("heading", { name: /^(调试|Debug)$/ }),
    });
    const compareControl = debugPanel
      .locator("div.flex.items-center.gap-2.text-sm.text-gray-600")
      .filter({ hasText: "对比模式" })
      .first();
    await expect(compareControl).toBeVisible();
    const toggle = compareControl.getByRole("switch");
    if ((await toggle.getAttribute("aria-checked")) !== "true") await toggle.click();
    // A selected Ant Select no longer exposes its placeholder. The two
    // comboboxes inside the visible Debug panel are the real compare columns.
    await expect(debugPanel.getByRole("combobox")).toHaveCount(2);
    await expect(debugPanel.locator('textarea[placeholder="发送消息..."]:visible')).toHaveCount(1);
  }

  async sendDebugCompare(prompt: string, expectedMarker?: string): Promise<string[]> {
    const debugPanel = this.page.locator("section:not(.hidden)", {
      has: this.page.getByRole("heading", { name: /^(调试|Debug)$/ }),
    });
    const messages = debugPanel.locator("[data-slot='aui_assistant-message-root']:visible");
    const before = await messages.count();
    const composer = debugPanel.locator('textarea[placeholder="发送消息..."]:visible');
    await composer.fill(prompt);
    await debugPanel.getByRole("button", { name: "发送", exact: true }).click();
    await expect(messages).toHaveCount(before + 2, { timeout: 300000 });
    const result: string[] = [];
    for (let index = before; index < before + 2; index += 1) {
      const answer = messages.nth(index);
      if (expectedMarker) {
        try {
          await expect(answer).toContainText(expectedMarker, { timeout: 300000 });
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
      result.push((await answer.innerText()).trim());
    }
    await expect(debugPanel.locator("button:has(svg.lucide-square)")).toHaveCount(0, { timeout: 300000 });
    await expect(debugPanel.getByRole("button", { name: "发送", exact: true })).toBeVisible({ timeout: 300000 });
    if (result.some((value) => value.length === 0)) throw new Error("compare debug produced an empty rendered answer");
    return result;
  }

  async closeDebugCompare(): Promise<void> {
    const debugPanel = this.page.locator("section:not(.hidden)", {
      has: this.page.getByRole("heading", { name: /^(调试|Debug)$/ }),
    });
    const compareControl = debugPanel
      .locator("div.flex.items-center.gap-2.text-sm.text-gray-600")
      .filter({ hasText: "对比模式" })
      .first();
    const toggle = compareControl.getByRole("switch");
    if ((await toggle.getAttribute("aria-checked")) === "true") await toggle.click();
    await expect(this.page.getByPlaceholder("发送消息...").last()).toBeVisible();
  }

  async publish(): Promise<Locator> {
    await this.page.getByRole("button", { name: "发布", exact: true }).click();
    const modal = this.page.locator("[role='dialog']:visible").filter({ hasText: /版本名称/ });
    await expect(modal).toBeVisible();
    return modal;
  }

  async publishVersion(versionName: string, releaseNote: string): Promise<void> {
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
