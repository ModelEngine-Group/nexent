import { expect, Locator, Page } from "playwright/test";
import { appPath } from "../runner/runtime-config";

export type CreatedKnowledge = {
  id: string;
  createStatus: number;
  processStatus: number;
};

export class KnowledgePage {
  constructor(readonly page: Page) {}

  async open(requireConfiguredEmbedding = true): Promise<void> {
    await this.page.goto(appPath("/knowledges"), { waitUntil: "domcontentloaded" });
    if (requireConfiguredEmbedding) {
      await expect(this.page.getByRole("heading", { name: "知识库", exact: true })).toBeVisible();
      await expect(this.createButton()).toBeVisible();
      return;
    }
    await expect(this.page.getByRole("heading", { name: "知识库", exact: true })
      .or(this.page.getByText(/尚未配置向量模型|需要配置向量化模型/)).first()).toBeVisible();
  }

  async beginCreate(name: string, embeddingDisplayName: string): Promise<void> {
    await this.createButton().click();
    const nameInput = this.page.getByPlaceholder("例如：产品知识中心", { exact: true });
    await expect(nameInput).toBeVisible();
    await nameInput.fill(name);
    const dialog = nameInput.locator("xpath=ancestor::*[@role='dialog'][1]");
    const modelSelector = dialog.getByText(/^向量模型\s*\*?$/)
      .locator("xpath=..").getByRole("combobox");
    await modelSelector.click();
    const option = this.page.getByText(embeddingDisplayName, { exact: true }).last();
    await expect(option).toBeVisible();
    await option.click();
  }

  private createButton(): Locator {
    // Knowledge cards also have role=button and include a creation date.
    // Only the native toolbar action can start the creation journey.
    return this.page.locator("button").filter({ hasText: /^\s*创\s*建\s*$/ });
  }

  private uploadInput(): Locator {
    return this.page.locator("input[type='file'][accept*='.txt']").last();
  }

  async createByUpload(name: string, embeddingDisplayName: string, filePath: string,
    onCreated?: (id: string) => void): Promise<CreatedKnowledge> {
    await this.beginCreate(name, embeddingDisplayName);
    return this.finishCreateByUpload(name, [filePath], onCreated);
  }

  async finishCreateByUpload(name: string, filePaths: string[],
    onCreated?: (id: string) => void): Promise<CreatedKnowledge> {
    const encoded = encodeURIComponent(name);
    const createPromise = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes(`/api/indices/${encoded}`),
      { timeout: 300000 },
    );
    const processPromise = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/file/process"),
      { timeout: 300000 },
    );
    await this.uploadInput().setInputFiles(filePaths);
    const submit = this.page.getByRole("dialog").getByRole("button", { name: "创建并进入", exact: true });
    await expect(submit).toBeEnabled();
    await submit.click();
    const created = await createPromise;
    if (!created.ok()) throw new Error(`knowledge create returned ${created.status()}`);
    const payload = await created.json();
    const id = String(payload?.id || payload?.data?.id || name);
    // Register ownership before processing can fail, so case cleanup can recover.
    onCreated?.(id);
    const processed = await processPromise;
    if (processed.status() !== 201) throw new Error(`knowledge process returned ${processed.status()}`);
    return { id, createStatus: created.status(), processStatus: processed.status() };
  }

  async select(name: string): Promise<void> {
    const search = this.page.getByPlaceholder("搜索知识库名称");
    await search.fill(name);
    const row = this.page.locator("[data-knowledge-base-row]").filter({ hasText: name }).first();
    await expect(row).toBeVisible();
    await row.click();
    await expect(this.page.getByText(name, { exact: true }).last()).toBeVisible();
  }

  async upload(filePaths: string[]): Promise<number> {
    const processPromise = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/file/process"),
      { timeout: 300000 },
    );
    await this.uploadInput().setInputFiles(filePaths);
    const processed = await processPromise;
    if (processed.status() !== 201) throw new Error(`knowledge process returned ${processed.status()}`);
    return processed.status();
  }

  async waitUntilReady(filename: string): Promise<void> {
    const match = filename.match(/^(.*?)(\.[^.]+)$/);
    const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const filenamePattern = match
      ? new RegExp(`${escape(match[1])}(?:_\\d+)?${escape(match[2])}`)
      : new RegExp(escape(filename));
    // The product appends _N when an object name already exists. Treat that as
    // the same uploaded asset while still scoping status checks to its row.
    const row = this.page.locator("tr").filter({ hasText: filenamePattern }).first();
    await expect(row).toBeVisible({ timeout: 600000 });
    for (let attempt = 0; attempt < 120; attempt += 1) {
      // The status cell includes the success checkmark in its accessible name.
      if (await row.getByRole("cell", { name: /^(?:✓\s*)?已就绪$/ }).isVisible().catch(() => false)) return;
      const failed = row.getByText(/处理失败|解析失败|向量化失败|上传失败|失败/).first();
      if (await failed.isVisible().catch(() => false)) {
        const error = new Error(`${filename} entered product failure state: ${(await failed.innerText()).trim()}`);
        error.name = "ProductFailure";
        throw error;
      }
      await this.page.waitForTimeout(5000);
    }
    const error = new Error(`${filename} did not reach 已就绪 within 10 minutes`);
    error.name = "ProductFailure";
    throw error;
  }

  async retrieve(query: string, expectedMarker: string): Promise<{ status: number; body: unknown }> {
    await this.page.getByRole("button", { name: "分片详情", exact: true }).click();
    const input = this.page.getByPlaceholder("召回检索...");
    await expect(input).toBeVisible();
    const responsePromise = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/indices/search/hybrid"),
      { timeout: 300000 },
    );
    await input.fill(query);
    await input.press("Enter");
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`knowledge hybrid search returned ${response.status()}`);
    const body = await response.json();
    const serialized = JSON.stringify(body);
    if (!serialized.includes(expectedMarker)) throw new Error(`hybrid search response omitted marker ${expectedMarker}`);
    // Search renders one document tab at a time; Top-K does not require the
    // matching document to be the first-ranked, initially selected result.
    const resultTab = this.page.getByRole("tab", { name: new RegExp(expectedMarker, "i") });
    if (await resultTab.count()) await resultTab.click();
    await expect(this.page.getByText(new RegExp(expectedMarker)).first()).toBeVisible();
    return { status: response.status(), body };
  }

  async summarizeIfAvailable(): Promise<string> {
    const overview = this.page.getByRole("button", { name: "概览", exact: true });
    if (!(await overview.count())) return "summary entry is not exposed by this product configuration";
    await overview.click();
    const summarize = this.page.getByRole("button", { name: "立即总结", exact: true });
    await expect(summarize).toBeVisible();
    await expect(summarize).toBeEnabled({ timeout: 60000 });
    await summarize.click();
    await expect(summarize).toBeEnabled({ timeout: 300000 });
    const body = await this.page.locator("body").innerText();
    if (/知识库总结失败|未生成知识库总结/.test(body)) throw new Error("knowledge summary reported failure");
    return "the exposed summary action completed and returned to its enabled state";
  }

  async delete(id: string): Promise<void> {
    const response = await this.page.request.delete(`/api/indices/${encodeURIComponent(id)}`);
    if (!response.ok() && response.status() !== 404) throw new Error(`knowledge cleanup returned ${response.status()}`);
  }
}
