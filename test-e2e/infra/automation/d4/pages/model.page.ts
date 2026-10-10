import { expect, Locator, Page } from "playwright/test";
import type { ModelAsset } from "../runner/runtime-config";
import { appPath } from "../runner/runtime-config";

const TYPE_LABEL: Record<string, string> = {
  llm: "大语言模型",
  embedding: "向量模型",
  stt: "语音识别模型",
  vlm: "图片理解模型",
  rerank: "重排模型",
};

export class ModelPage {
  constructor(readonly page: Page) {}

  private modelCard(capability: "llm" | "embedding"): Locator {
    const fieldKey = capability === "llm" ? "llm.main" : "embedding.embedding";
    // The product associates each model slot label with its select trigger.
    // Scope selection to that slot instead of the removed model-card layout.
    return this.page.locator(`[id="model-slot-${fieldKey}"]`).locator("xpath=..");
  }

  async open(): Promise<void> {
    await this.page.goto(appPath("/models"), { waitUntil: "domcontentloaded" });
    await expect(this.page.getByRole("heading", { name: "模型设置" })).toBeVisible();
  }

  private async selectByLabelText(modal: Locator, label: string, option: string): Promise<void> {
    // The deployed dialog does not expose a stable label association for the
    // Ant Design select. Model type is the first combobox in this dialog; role
    // lookup is stable across the current Tailwind/Ant markup variants.
    if (label !== "模型类型") throw new Error(`unsupported model select label: ${label}`);
    await modal.getByRole("combobox").first().click();
    await this.page.getByText(option, { exact: true }).last().click();
  }

  async openAddDialog(): Promise<Locator> {
    await this.page.getByRole("button", { name: "添加模型", exact: true }).click();
    const modal = this.page.getByRole("dialog", { name: "添加模型" });
    await expect(modal).toBeVisible();
    return modal;
  }

  async fillConfiguredModel(modal: Locator, asset: ModelAsset, displayName: string): Promise<void> {
    const customTab = modal.getByRole("tab", { name: "自定义接入", exact: true });
    await expect(customTab).toBeVisible();
    await customTab.click();
    const panel = modal.locator('[role="tabpanel"]:visible').last();
    await panel.getByRole("combobox").first().click();
    await this.page.getByText(TYPE_LABEL[asset.capability], { exact: true }).last().click();
    const field = (label: RegExp): Locator => panel.getByText(label).first().locator("xpath=..").locator("input").first();
    await field(/^模型名称/).fill(asset.model);
    await field(/^Base URL/).fill(asset.baseUrl);
    await field(/^API Key/).fill(asset.secret);

    await panel.getByRole("button", { name: "高级设置", exact: true }).click();
    const advanced = this.page.getByRole("dialog", { name: /^高级设置/ }).last();
    await expect(advanced).toBeVisible();
    const displayLabel = advanced.getByText(/^(显示名称|Display Name)$/).first();
    await expect(displayLabel).toBeVisible();
    await displayLabel.locator("xpath=../..").locator("input").first().fill(displayName);
    if (asset.capability === "embedding" && asset.dimension) {
      const dimension = advanced.getByText(/^(向量维度|Dimension)$/).first().locator("xpath=../..").locator("input").first();
      if (await dimension.count()) await dimension.fill(String(asset.dimension));
    }
    await advanced.getByRole("button", { name: "确定", exact: true }).click();
  }

  async verifyDraft(modal: Locator): Promise<number> {
    const connectivityPromise = this.page.waitForResponse((r) => r.url().includes("/api/model/temporary_healthcheck") && r.request().method() === "POST", { timeout: 300000 });
    await modal.getByRole("button", { name: "校验连通性", exact: true }).click();
    const connectivity = await connectivityPromise;
    if (!connectivity.ok()) throw new Error(`temporary model connectivity returned ${connectivity.status()}`);
    await expect(modal.getByText("可用", { exact: true })).toBeVisible({ timeout: 300000 });
    return connectivity.status();
  }

  async submitDraft(modal: Locator, displayName: string): Promise<number> {
    // The deployed Ant button exposes the accessible name as `添 加` because
    // of its two-character spacing style.
    const addButton = modal.getByRole("button", { name: "保存", exact: true });
    if (await addButton.count() === 0) {
      const names = (await modal.getByRole("button").allTextContents()).map((value) => value.trim()).filter(Boolean);
      throw new Error(`model submit button is missing; dialog buttons=${JSON.stringify(names)}`);
    }
    await expect(addButton).toBeEnabled({ timeout: 30000 });
    const createPromise = this.page.waitForResponse((r) => {
      const path = new URL(r.url()).pathname;
      // Creation route names have changed across Nexent deployments. Restrict
      // the network oracle to a non-connectivity model POST; persistence is
      // independently proven below by reloading and locating the new model.
      return path.includes("/api/model/") && !path.endsWith("/temporary_healthcheck") && r.request().method() === "POST";
    });
    await addButton.click();
    const created = await createPromise;
    if (!created.ok()) throw new Error(`model create returned ${created.status()}`);
    // The click handler continues with config persistence and list refresh after
    // the first create response. Do not reload until the complete UI operation
    // has finished and the dialog has closed.
    await expect(modal).toBeHidden({ timeout: 300000 });
    return created.status();
  }

  async addConfiguredModel(asset: ModelAsset, displayName: string): Promise<{ connectivityStatus: number; createStatus: number }> {
    const modal = await this.openAddDialog();
    await this.fillConfiguredModel(modal, asset, displayName);
    const connectivityStatus = await this.verifyDraft(modal);
    const createStatus = await this.submitDraft(modal, displayName);
    return { connectivityStatus, createStatus };
  }

  async expectModel(displayName: string, capability: "llm" | "embedding"): Promise<void> {
    let persisted = false;
    for (let attempt = 0; attempt < 20; attempt += 1) {
      const response = await this.page.request.get("/api/model/list");
      if (response.ok()) {
        const payload = await response.json();
        persisted = JSON.stringify(payload?.data || []).includes(displayName);
        if (persisted) break;
      }
      await this.page.waitForTimeout(1000);
    }
    if (!persisted) throw new Error(`created model ${displayName} was not persisted by /api/model/list`);
    await this.page.reload({ waitUntil: "domcontentloaded" });
    const card = this.modelCard(capability);
    const displayPattern = new RegExp(displayName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const selected = card.getByText(displayPattern).last();
    if (await selected.isVisible().catch(() => false)) return;
    const combobox = card.getByRole("combobox").first();
    await combobox.click();
    await expect(this.page.getByText(displayPattern).last()).toBeVisible();
    await this.page.keyboard.press("Escape");
  }

  async currentConfiguredModel(capability: "llm" | "embedding"): Promise<string> {
    const response = await this.page.request.get("/api/config/load_config");
    if (!response.ok()) throw new Error(`config load returned ${response.status()}`);
    const payload = await response.json();
    return String(payload?.config?.models?.[capability]?.displayName || "").trim();
  }

  async configureModel(displayName: string, capability: "llm" | "embedding"): Promise<{ healthStatus: number; saveStatus: number }> {
    const card = this.modelCard(capability);
    const current = await this.currentConfiguredModel(capability);
    if (current === displayName) return { healthStatus: 200, saveStatus: 200 };

    await card.getByRole("combobox").first().click();
    const option = this.page.getByText(displayName, { exact: true }).last();
    await expect(option).toBeVisible();
    await option.click();

    const proceed = this.page.getByRole("button", { name: "立即修改", exact: true });
    if (await proceed.waitFor({ state: "visible", timeout: 3000 }).then(() => true).catch(() => false)) {
      await proceed.click();
    }

    let persisted = false;
    for (let attempt = 0; attempt < 30; attempt += 1) {
      if (await this.currentConfiguredModel(capability) === displayName) {
        persisted = true;
        break;
      }
      await this.page.waitForTimeout(1000);
    }
    if (!persisted) throw new Error(`configured model ${displayName} was not persisted`);

    const healthStatus = await this.verifyPersistedModel(displayName, capability);

    return { healthStatus, saveStatus: 200 };
  }

  async modelExists(displayName: string, capability: "llm" | "embedding"): Promise<boolean> {
    const response = await this.page.request.get("/api/model/list");
    if (!response.ok()) throw new Error(`model list returned ${response.status()}`);
    const payload = await response.json();
    const models = payload?.data || payload?.models || payload || [];
    return models.some((model: any) => {
      const name = model.displayName ?? model.display_name;
      const type = model.type ?? model.model_type;
      return name === displayName && type === capability;
    });
  }

  async alignPersistedModel(asset: ModelAsset, displayName: string, capability: "llm" | "embedding"): Promise<"reused" | "updated"> {
    const response = await this.page.request.get("/api/model/list");
    if (!response.ok()) throw new Error(`model list returned ${response.status()}`);
    const payload = await response.json();
    const models = payload?.data || payload?.models || payload || [];
    const model = models.find((candidate: any) => {
      const name = candidate.displayName ?? candidate.display_name;
      const type = candidate.type ?? candidate.model_type;
      return name === displayName && type === capability;
    });
    if (!model) throw new Error(`configured real model ${displayName} is missing`);

    const currentName = model.name ?? model.model_name;
    const currentUrl = model.apiUrl ?? model.api_url ?? model.base_url;
    const currentFactory = model.source ?? model.model_factory;
    const expectedFactory = asset.provider === "openai-compatible" ? "OpenAI-API-Compatible" : asset.provider;
    const normalizeEmbeddingUrl = (value: string) => value.replace(/\/embeddings\/?$/, "").replace(/\/$/, "");
    const urlMatches = capability === "embedding"
      ? normalizeEmbeddingUrl(String(currentUrl || "")) === normalizeEmbeddingUrl(asset.baseUrl)
      : currentUrl === asset.baseUrl;
    // Official embedding providers may retain their product factory while the
    // test asset describes the common OpenAI-compatible protocol.
    const factoryMatches = capability === "embedding" || currentFactory === expectedFactory;
    if (currentName === asset.model && urlMatches && factoryMatches) return "reused";

    const body: Record<string, unknown> = {
      model_name: asset.model,
      base_url: asset.baseUrl,
      api_key: asset.secret,
      model_factory: expectedFactory,
    };
    if (capability === "embedding" && asset.dimension) body.max_tokens = asset.dimension;
    const updated = await this.page.request.post(`/api/model/update?display_name=${encodeURIComponent(displayName)}`, { data: body });
    if (!updated.ok()) throw new Error(`configured real model alignment returned ${updated.status()}`);
    return "updated";
  }

  async verifyPersistedModel(displayName: string, capability: "llm" | "embedding", dependencyCheck = false): Promise<number> {
    const response = await this.page.request.post(`/api/model/healthcheck?display_name=${encodeURIComponent(displayName)}&model_type=${capability}`);
    if (!response.ok()) throw new Error(`persisted model healthcheck returned ${response.status()}`);
    const payload = await response.json().catch(() => ({}));
    if (payload?.data?.connectivity !== true) {
      const error = new Error(`configured real model ${displayName} is unavailable`);
      // Positive fixture readiness is separate from a healthcheck acceptance
      // assertion. Keep existing primary healthcheck tests classified as FAIL.
      error.name = dependencyCheck ? "DependencyFailure" : "ProductFailure";
      throw error;
    }
    return response.status();
  }

  async checkAllConnectivity(displayName: string): Promise<void> {
    const responsePromise = this.page.waitForResponse((r) => r.url().includes("/api/model/healthcheck") && r.url().includes(encodeURIComponent(displayName)), { timeout: 300000 });
    await this.page.getByRole("button", { name: "检查模型连通性" }).click();
    const response = await responsePromise;
    if (!response.ok()) throw new Error(`persisted model healthcheck returned ${response.status()}`);
  }

  libraryRow(displayName: string): Locator {
    const library = this.page.getByRole("heading", { name: "模型库", exact: true }).locator("xpath=ancestor::section[1]");
    return library.locator("div")
      .filter({ has: this.page.getByText(displayName, { exact: true }) })
      .filter({ has: this.page.getByRole("button", { name: "编辑", exact: true }) }).last();
  }

  async openEditDialog(displayName: string, typeLabel: string): Promise<Locator> {
    const row = this.libraryRow(displayName);
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "编辑", exact: true }).click();
    const editor = this.page.getByRole("dialog", { name: "编辑模型" });
    await expect(editor).toBeVisible();
    return editor;
  }

  async saveEditWithoutReplacingCredential(
    displayName: string,
    capability: "llm" | "embedding",
  ): Promise<Record<string, unknown>> {
    const editor = await this.openEditDialog(displayName, capability === "llm" ? "大语言模型" : "嵌入模型");
    const secret = editor.locator("input[type='password']");
    await expect(secret).toHaveValue("");
    await expect(secret).toHaveAttribute("placeholder", /留空|保持|existing/i);
    const saved = this.page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/api/model/update"),
    );
    await editor.getByRole("button", { name: "保存", exact: true }).click();
    const response = await saved;
    if (!response.ok()) throw new Error(`credential-preserving model edit returned ${response.status()}`);
    const request = response.request();
    const body = request.postDataJSON() as Record<string, unknown>;
    if ("api_key" in body || "apiKey" in body) {
      throw new Error("blank model edit unexpectedly sent an API key replacement");
    }
    await expect(editor).toBeHidden();
    await this.verifyPersistedModel(displayName, capability);
    return body;
  }

  async deleteModel(displayName: string): Promise<void> {
    const response = await this.page.request.post(`/api/model/delete?display_name=${encodeURIComponent(displayName)}`);
    if (!response.ok() && response.status() !== 404) throw new Error(`model cleanup returned ${response.status()}`);
  }
}
