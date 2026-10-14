import { expect, type Page } from "playwright/test";
import { appPath } from "../runner/runtime-config";

/**
 * Page object for the AIDP branch of /knowledges (frontend
 * ext_components/aidp). Deliberately separate from the Local-mode
 * KnowledgePage: the two branches are mutually exclusive by deployment
 * configuration and must never share locators that guess the mode.
 */
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
}
