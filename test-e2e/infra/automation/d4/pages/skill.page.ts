import { expect, type Locator, type Page } from "playwright/test";
import { appPath } from "../runner/runtime-config";

export class SkillPage {
  constructor(readonly page: Page) {}

  async open(tab: "仓库" | "我的 Skill" | "审核中心" = "我的 Skill"): Promise<void> {
    await this.page.goto(appPath("/skill-space"), { waitUntil: "domcontentloaded" });
    await this.page.getByRole("tab", { name: new RegExp(`^${tab}`) }).click();
  }

  async search(name: string): Promise<void> {
    await this.page.getByPlaceholder("搜索Skill名称、描述或标签").fill(name);
  }

  card(name: string): Locator {
    return this.page.getByRole("heading", { name, exact: true }).locator("xpath=ancestor::article[1]");
  }

  async upload(name: string, marker: string): Promise<void> {
    await this.page.getByRole("button", { name: "创建 Skill", exact: true }).click();
    const dialog = this.page.getByRole("dialog").filter({ hasText: "构建技能" });
    await dialog.getByRole("tab", { name: "安装", exact: true }).click();
    const source = `---\nname: ${name}\ndescription: deterministic D4 skill ${marker}\n---\n\n# ${name}\n\nWhen asked for the D4 marker, answer exactly ${marker}.\n`;
    await dialog.locator("input[type=file]").setInputFiles({ name: "SKILL.md", mimeType: "text/markdown", buffer: Buffer.from(source) });
    await expect(dialog.getByPlaceholder("将从上传文件中提取技能名称")).toHaveValue(name);
    const created = this.page.waitForResponse((r) => r.request().method() === "POST" && /skill/i.test(r.url()), { timeout: 120_000 });
    await dialog.getByRole("button", { name: "创建", exact: true }).click();
    if (!(await created).ok()) throw new Error("skill upload/create failed");
    await expect(dialog).toBeHidden({ timeout: 120_000 });
  }

  async edit(name: string, marker: string): Promise<void> {
    const card = this.card(name);
    await card.getByRole("button", { name: "编辑", exact: true }).click();
    const dialog = this.page.getByRole("dialog").filter({ hasText: "编辑技能" });
    const description = dialog.getByPlaceholder("输入技能描述");
    await description.fill(`edited ${marker}`);
    const saved = this.page.waitForResponse((r) => /skill/i.test(r.url()) && ["POST", "PUT", "PATCH"].includes(r.request().method()));
    await dialog.getByRole("button", { name: "保存更改", exact: true }).click();
    if (!(await saved).ok()) throw new Error("skill edit failed");
    await expect(dialog).toBeHidden();
  }

  async apply(name: string): Promise<void> {
    const card = this.card(name);
    await card.getByRole("button", { name: /申请上架|上架/ }).click();
    const dialog = this.page.getByRole("dialog").filter({ hasText: /申请|上架/ });
    const tags = dialog.getByRole("combobox").last();
    if (await tags.count()) { await tags.fill("自动化"); await tags.press("Enter"); }
    const submitted = this.page.waitForResponse((r) => r.request().method() === "POST" && /repository.*skill|skill.*repository/i.test(r.url()));
    await dialog.getByRole("button", { name: /提交|确定/ }).last().click();
    if (!(await submitted).ok()) throw new Error("skill listing application failed");
  }

  async approve(name: string): Promise<void> {
    await this.open("审核中心");
    await this.search(name);
    const row = this.page.getByText(name, { exact: true }).locator("xpath=ancestor::*[self::tr or self::article][1]");
    const reviewed = this.page.waitForResponse((r) => ["POST", "PATCH"].includes(r.request().method()) && /repository.*skill|skill.*repository/i.test(r.url()));
    await row.getByRole("button", { name: "通过", exact: true }).click();
    const confirm = this.page.getByRole("dialog");
    if (await confirm.count()) await confirm.getByRole("button", { name: /通过|确定/ }).last().click();
    if (!(await reviewed).ok()) throw new Error("skill review approval failed");
  }

  async install(name: string): Promise<void> {
    await this.open("仓库"); await this.search(name);
    const card = this.card(name);
    await card.getByRole("button", { name: /安装|复制/ }).click();
    const dialog = this.page.getByRole("dialog");
    if (await dialog.count()) await dialog.getByRole("button", { name: /安装|复制为我的 Skill|确定/ }).last().click();
    await expect(this.page.getByText(/安装成功|复制成功/)).toBeVisible({ timeout: 120_000 });
  }

  async setNotShared(name: string): Promise<void> {
    await this.open("我的 Skill");
    await this.search(name);
    const card = this.card(name);
    if (!(await card.count())) return;
    await card.getByRole("button", { name: "更多操作", exact: true }).click();
    const review = this.page.getByRole("menuitem", { name: "查看审批进度", exact: true });
    if (!(await review.count())) return;
    await review.click();
    const statusDialog = this.page.getByRole("dialog").filter({ hasText: name });
    await expect(statusDialog).toBeVisible();
    const action = statusDialog.getByRole("button", { name: /下架|取消申请/ });
    if (!(await action.count())) {
      await statusDialog.getByRole("button", { name: "关闭", exact: true }).click();
      return;
    }
    await action.click();
    const confirm = this.page.getByRole("dialog").last();
    const response = this.page.waitForResponse(
      (r) => ["POST", "PATCH"].includes(r.request().method()) && /repository.*skill|skill.*repository/i.test(r.url()),
    );
    await confirm.getByRole("button", { name: /下架|取消申请/ }).click();
    if (!(await response).ok()) throw new Error("skill unpublish/withdraw failed");
    await expect(statusDialog).toBeHidden();
  }

  async delete(name: string): Promise<void> {
    await this.open("我的 Skill"); await this.search(name);
    const card = this.card(name);
    if (!(await card.count())) return;
    await card.getByRole("button", { name: /更多/ }).click();
    await this.page.getByRole("menuitem", { name: "删除", exact: true }).click();
    await this.page.getByRole("dialog").getByRole("button", { name: /删除|确定/ }).last().click();
    await expect(card).toHaveCount(0);
  }
}
