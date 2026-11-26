// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, type Locator, type Page } from "playwright/test";
import { appPath } from "../runner/runtime-config";

/**
 * Page object for the AIDP branch of /knowledges (frontend
 * ext_components/aidp). Deliberately separate from the Local-mode
 * KnowledgePage: the two branches are mutually exclusive by deployment
 * configuration and must never share locators that guess the mode.
 *
 * Locator provenance (zh locale values from frontend/public/locales/zh):
 * - list create button "新建知识库"            AidpKnowledgeList.tsx:624 (createKb)
 * - list search placeholder "搜索知识库名称"    AidpKnowledgeList.tsx:602 (searchPlaceholder)
 * - card article[role=button] + more menu      AidpKnowledgeList.tsx:283,273 (moreOperations)
 * - delete menu item "删除"                     AidpKnowledgeList.tsx:253 (common.delete)
 * - delete confirm ok "删除知识库"              AidpKnowledgeConfiguration.tsx:187
 * - create page title "创建知识库"              AidpCreateKbPage.tsx:348 (createPageTitle)
 * - create submit "创建知识库"                  AidpCreateKbPage.tsx:440 (createSubmit)
 * - create success "知识库已创建"               AidpCreateKbPage.tsx:295 (createKbSuccess)
 * - name placeholder "知识库名称"               AidpCreateKbSections.tsx:228 (kbNamePlaceholder)
 * - description placeholder "请输入知识库描述"   AidpCreateKbSections.tsx:247 (kbDescriptionPlaceholder)
 * - permission select "组内权限" / PRIVATE      AidpKnowledgeBaseModalParts.tsx:128,156
 * - collapsible panels aidp-create-*-panel      AidpCreateKbSections.tsx:150,469,562,643
 * - chunk mode cards 智能分片 / 法律条文         AidpChunkModeChoices.tsx:39,50
 * - slider spinbutton aria-labels               AidpSliderNumberField.tsx:59 + Sections ariaLabel
 * - detail tabs 已上传文件 / 详细信息            AidpKnowledgeFilesPage.tsx:668,672
 * - detail config heading "配置参数"            AidpKnowledgeDetailInformation.tsx:133
 * - detail row labels + edit aria-labels        AidpKnowledgeDetailInformation.tsx:146,157,154,161
 * - setting saved "配置已更新"                  AidpKnowledgeInformationTab.tsx:357 (detailSettingSaved)
 * - overlap range error 1%-40%                  AidpKnowledgeInformationTab.tsx:622 (createOverlapPercentRange)
 */

/** Canonical numeric string of a slider input (display may carry precision zeros). */
function numericText(raw: string): string {
  const value = Number(raw);
  if (Number.isNaN(value)) {
    throw new Error(`slider input did not hold a numeric value: ${JSON.stringify(raw)}`);
  }
  return String(value);
}

export class AidpKnowledgePage {
  constructor(readonly page: Page) {}

  /** Open /knowledges and prove the AIDP branch is active. */
  async open(): Promise<void> {
    await this.page.goto(appPath("/knowledges"), { waitUntil: "domcontentloaded" });
    // Positive marker: the AIDP-only onboarding guide (guideWhatIs) renders
    // at the top of the AIDP list and exists nowhere in the Local branch.
    // Negative marker: the Local-only personal storage-capacity bar must not
    // appear. Note both branches reuse "知识库列表"/"搜索知识库名称" texts, so
    // neither can discriminate the mode.
    await expect(this.page.getByText("什么是知识库？", { exact: true }).first()).toBeVisible();
    await expect(this.page.getByText("存储容量")).toHaveCount(0);
  }

  /**
   * Select the named knowledge base and enter its file-management view.
   * The current AIDP list has no retrieval input; this step proves the
   * selected resource, not a search contract.
   */
  async selectKnowledgeBase(name: string): Promise<void> {
    const search = this.page.getByPlaceholder("搜索知识库名称");
    if (await search.isVisible().catch(() => false)) {
      await search.fill(name);
    }
    const card = this.page.locator("article[role='button']").filter({
      has: this.page.getByText(name, { exact: true }),
    });
    await expect(card).toHaveCount(1);
    await card.click();
    // File management view: the breadcrumb offers the way back and the
    // header carries the selected KB's own name.
    await expect(this.page.getByRole("button", { name: "知识库", exact: true }).first()).toBeVisible();
    await expect(this.page.getByRole("heading", { name })).toBeVisible();
  }

  /** Verify a document is listed in the current file-management view. */
  async expectDocument(fileName: string): Promise<void> {
    await expect(this.page.getByText(fileName, { exact: true }).first()).toBeVisible();
  }

  // ---- Create page helpers ----

  /** Expand a collapsible create-page section by its stable panel id. */
  private async expandCreateSection(panel: "chunk" | "vector" | "retrieval"): Promise<void> {
    const toggle = this.page.locator(`button[aria-controls='aidp-create-${panel}-panel']`);
    await expect(toggle).toBeVisible();
    if ((await toggle.getAttribute("aria-expanded")) !== "true") {
      await toggle.click();
    }
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
  }

  /** Read the canonical numeric value held by a slider's spinbutton input. */
  private async readSlider(name: string): Promise<string> {
    const input = this.page.getByRole("spinbutton", { name, exact: true });
    await expect(input).toBeVisible();
    return numericText(await input.inputValue());
  }

  /** Type a value into a slider spinbutton and commit it via blur (changeOnBlur). */
  private async setSlider(name: string, value: number): Promise<void> {
    const input = this.page.getByRole("spinbutton", { name, exact: true });
    await expect(input).toBeVisible();
    await input.click();
    await input.fill(String(value));
    await input.press("Tab");
  }

  /** Pick an antd Select option by its exact visible label. */
  private async selectOption(combobox: Locator, label: string): Promise<void> {
    await combobox.click();
    const option = this.page
      .locator(".ant-select-dropdown:visible .ant-select-item-option")
      .filter({ has: this.page.getByText(label, { exact: true }) });
    await expect(option).toHaveCount(1);
    await option.click();
    await expect(this.page.locator(".ant-select-dropdown:visible")).toHaveCount(0);
  }

  /**
   * Open the create page and read the AIDP chunk defaults without editing.
   * Returns canonical numeric strings (chunkTokens / overlapPercent / topk /
   * similarity); the overlap display carries a precision zero ("10.0") which
   * is normalized to its numeric value "10".
   */
  async openCreatePageAndReadChunkDefaults(): Promise<{
    chunkTokens: string;
    overlapPercent: string;
    topk: string;
    similarity: string;
  }> {
    await this.page.goto(appPath("/knowledges/create"), { waitUntil: "domcontentloaded" });
    await expect(this.page.getByText("创建知识库", { exact: true }).first()).toBeVisible();
    await this.expandCreateSection("chunk");
    const chunkTokens = await this.readSlider("文本切片最长token");
    const overlapPercent = await this.readSlider("相邻切片重叠字符百分比");
    await this.expandCreateSection("retrieval");
    const topk = await this.readSlider("向量检索TOP K值");
    const similarity = await this.readSlider("相似度阈值");
    return { chunkTokens, overlapPercent, topk, similarity };
  }

  /**
   * Open the create page and prove the ext mock model template exposes the
   * given embedding model as a selectable option (precondition evidence).
   */
  async expectCreatePageEmbeddingModel(label: string): Promise<void> {
    await this.page.goto(appPath("/knowledges/create"), { waitUntil: "domcontentloaded" });
    await this.expandCreateSection("vector");
    const embedding = this.page
      .locator(".ant-form-item")
      .filter({ hasText: "向量化模型" })
      .getByRole("combobox");
    await embedding.click();
    const option = this.page
      .locator(".ant-select-dropdown:visible .ant-select-item-option")
      .filter({ has: this.page.getByText(label, { exact: true }) });
    await expect(option).toHaveCount(1);
    await this.page.keyboard.press("Escape");
    await expect(this.page.locator(".ant-select-dropdown:visible")).toHaveCount(0);
  }

  /** Prove the create page chunk mode cards render and smart splitting is preselected. */
  async expectChunkModeCards(): Promise<void> {
    await this.expandCreateSection("chunk");
    await expect(this.page.getByText("智能分片", { exact: true })).toBeVisible();
    await expect(this.page.getByText("法律条文", { exact: true })).toBeVisible();
    const smartCard = this.page
      .locator("label.ant-radio-wrapper")
      .filter({ has: this.page.getByText("智能分片", { exact: true }) });
    await expect(smartCard.locator("input[type='radio']")).toBeChecked();
  }

  /**
   * Fill and submit the create form for a run-owned knowledge base.
   * Selects PRIVATE scope (a safe, deletable default) and explicitly chooses
   * the embedding model by its visible label so the parameter drives selection.
   */
  async createKnowledgeBase(input: {
    name: string;
    description: string;
    embeddingModelLabel: string;
  }): Promise<void> {
    await this.page.getByPlaceholder("知识库名称").fill(input.name);
    await this.page.getByPlaceholder("请输入知识库描述").fill(input.description);

    // Tenant admins default to READ_ONLY; force PRIVATE so no group grant is
    // required and the run-owned KB stays cleanly deletable.
    const permission = this.page
      .locator(".ant-form-item")
      .filter({ hasText: "组内权限" })
      .getByRole("combobox");
    await this.selectOption(permission, "私有 — 仅创建者可见");

    // The embedding model lives in the collapsed vector section.
    await this.expandCreateSection("vector");
    const embedding = this.page
      .locator(".ant-form-item")
      .filter({ hasText: "向量化模型" })
      .getByRole("combobox");
    await this.selectOption(embedding, input.embeddingModelLabel);

    await this.page.getByRole("button", { name: "创建知识库", exact: true }).click();
    await expect(this.page.getByText("知识库已创建", { exact: true })).toBeVisible();
    // Creation lands on the dedicated detail route for the new KB.
    await this.page.waitForURL(/\/knowledges\/detail\?kb=/);
    await expect(this.page.getByRole("heading", { name: input.name })).toBeVisible();
  }

  // ---- Detail information tab ----

  /** Switch the detail view to the information tab and wait for the config grid. */
  async openInformationTab(): Promise<void> {
    await this.page.getByRole("tab", { name: "详细信息", exact: true }).click();
    await expect(this.page.getByRole("heading", { name: "配置参数", exact: true })).toBeVisible();
  }

  /**
   * Read the stored chunk rows from the configuration grid, proving the token
   * field precedes the overlap field (create order) and neither is a dash
   * placeholder. chunkToken keeps the "NNN Token" display; chunkOverlap keeps
   * the "NN.N%" display.
   */
  async readInformationChunkRows(): Promise<{ chunkToken: string; chunkOverlap: string }> {
    const config = this.page
      .locator("section")
      .filter({ has: this.page.getByRole("heading", { name: "配置参数", exact: true }) });
    const tokenValue = config
      .locator("dt")
      .filter({ hasText: "文本切片最长token" })
      .locator("xpath=following-sibling::dd[1]");
    const overlapValue = config
      .locator("dt")
      .filter({ hasText: "相邻切片重叠字符百分比" })
      .locator("xpath=following-sibling::dd[1]");
    await expect(tokenValue).toBeVisible();
    await expect(overlapValue).toBeVisible();

    // Create order: the token field must appear before the overlap field.
    const order = await this.page.evaluate(() => {
      const labels = Array.from(document.querySelectorAll("dt")).map((node) => node.textContent || "");
      return {
        token: labels.findIndex((text) => text.includes("文本切片最长token")),
        overlap: labels.findIndex((text) => text.includes("相邻切片重叠字符百分比")),
      };
    });
    if (order.token < 0 || order.overlap < 0 || order.token >= order.overlap) {
      throw new Error(`information chunk rows are out of create order: ${JSON.stringify(order)}`);
    }

    return {
      chunkToken: (await tokenValue.innerText()).trim(),
      chunkOverlap: (await overlapValue.innerText()).trim(),
    };
  }

  /** The setting-edit modal dialog identified by its localized title. */
  private settingDialog(title: string): Locator {
    return this.page.getByRole("dialog", { name: title, exact: true });
  }

  /**
   * Open the chunk-mode (切片方式) editor from the information tab and prove
   * it reuses the create page chunk mode cards (smart splitting / legal
   * clauses). This is the modal that actually renders AidpChunkModeChoices;
   * the chunk-token modal only carries the token slider. Close without
   * writing: this step proves card reuse, not a configuration change.
   */
  async openChunkModeEditor(): Promise<void> {
    await this.page.getByRole("button", { name: "编辑切片方式", exact: true }).click();
    const dialog = this.settingDialog("编辑切片方式");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByText("智能分片", { exact: true })).toBeVisible();
    await expect(dialog.getByText("法律条文", { exact: true })).toBeVisible();
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
    await expect(dialog).toBeHidden();
  }

  /** Open the chunk-token editor, set the token value and save, waiting for the success toast. */
  async saveChunkToken(value: number): Promise<void> {
    await this.page.getByRole("button", { name: "编辑文本切片最长token", exact: true }).click();
    const dialog = this.settingDialog("编辑文本切片最长token");
    await expect(dialog).toBeVisible();
    await this.setSlider("文本切片最长token", value);
    await dialog.getByRole("button", { name: "确定", exact: true }).click();
    await expect(this.page.getByText("配置已更新", { exact: true })).toBeVisible();
    await expect(dialog).toBeHidden();
  }

  /**
   * Type an out-of-range overlap (60%) into the overlap editor and prove the
   * UI constrains it to the valid ceiling (AIDP_OVERLAP_PERCENT_MAX = 40,
   * always below half the chunk) on blur, so an invalid value can never reach
   * the configuration. Cancel without writing; the stored configuration keeps
   * its last good values. The explicit half-of-chunk rejection at the backend
   * boundary is proven by the D2 contract case.
   */
  async openOverlapEditorAndExpectOutOfRangeConstrained(): Promise<void> {
    await this.page.getByRole("button", { name: "编辑相邻切片重叠字符百分比", exact: true }).click();
    const dialog = this.settingDialog("编辑相邻切片重叠字符百分比");
    await expect(dialog).toBeVisible();
    await this.setSlider("相邻切片重叠字符百分比", 60);
    const input = this.page.getByRole("spinbutton", { name: "相邻切片重叠字符百分比", exact: true });
    // The field renders with one decimal (precision 1); compare numerically.
    const constrained = Number(await input.inputValue());
    if (constrained !== 40) {
      throw new Error(
        `out-of-range overlap must be constrained to the 40% UI ceiling, got ${constrained}`
      );
    }
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
    await expect(dialog).toBeHidden();
  }

  // ---- List cleanup ----

  /** Return to the knowledge base list and search for the run-owned name. */
  async returnToListAndSearch(name: string): Promise<void> {
    await this.page.getByRole("button", { name: "知识库", exact: true }).first().click();
    await this.page.waitForURL(/\/knowledges(?:\?|$)/);
    await expect(this.page.getByText("什么是知识库？", { exact: true }).first()).toBeVisible();
    await this.page.getByPlaceholder("搜索知识库名称").fill(name);
  }

  /** Delete the named knowledge base through the card menu and confirm dialog. */
  async deleteKnowledgeBase(name: string): Promise<void> {
    const card = this.page.locator("article[role='button']").filter({
      has: this.page.getByText(name, { exact: true }),
    });
    await expect(card).toHaveCount(1);
    await card.getByRole("button", { name: "更多操作", exact: true }).click();
    await this.page.getByRole("menuitem", { name: "删除", exact: true }).click();
    const confirm = this.page.getByRole("dialog").filter({ hasText: "删除知识库" });
    await expect(confirm).toBeVisible();
    await confirm.getByRole("button", { name: "删除知识库", exact: true }).click();
    await expect(this.page.getByText("知识库已删除", { exact: true })).toBeVisible();
  }

  /** Prove the run-owned knowledge base no longer appears in the searched list. */
  async expectKnowledgeBaseAbsent(name: string): Promise<void> {
    const search = this.page.getByPlaceholder("搜索知识库名称");
    await expect(search).toBeVisible();
    if ((await search.inputValue()) !== name) {
      await search.fill(name);
    }
    const card = this.page.locator("article[role='button']").filter({
      has: this.page.getByText(name, { exact: true }),
    });
    await expect(card).toHaveCount(0);
  }
}