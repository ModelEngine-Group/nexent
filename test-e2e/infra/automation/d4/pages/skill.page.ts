// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, type Locator, type Page } from "playwright/test";
import { appPath } from "../runner/runtime-config";

export class SkillPage {
  constructor(readonly page: Page) {}

  async open(tab: "仓库" | "我的 Skill" | "审核中心" = "我的 Skill"): Promise<void> {
    const query = tab === "审核中心"
      ? "tab=review&resource_type=skill"
      : `tab=skill&view=${tab === "仓库" ? "repository" : "mine"}`;
    await this.page.goto(appPath(`/resource-space?${query}`), { waitUntil: "domcontentloaded" });
  }

  async search(name: string): Promise<void> {
    await this.page.getByPlaceholder("搜索 Skill 名称、描述或标签").fill(name);
  }

  card(name: string): Locator {
    return this.page.getByRole("button", { name, exact: true }).locator("xpath=..");
  }

  async upload(name: string, marker: string, onCreated?: () => void): Promise<void> {
    await this.page.getByRole("button", { name: "添加Skill服务", exact: true }).click();
    const dialog = this.page.getByRole("dialog").filter({ hasText: "构建技能" });
    await dialog.getByRole("tab", { name: "安装", exact: true }).click();
    const source = `---\nname: ${name}\ndescription: deterministic D4 skill ${marker}\n---\n\n# ${name}\n\nWhen asked for the D4 marker, answer exactly ${marker}.\n`;
    await dialog.locator("input[type=file]").setInputFiles({ name: "SKILL.md", mimeType: "text/markdown", buffer: Buffer.from(source) });
    await expect(dialog.getByPlaceholder("将从上传文件中提取技能名称")).toHaveValue(name);
    const created = this.page.waitForResponse((r) => r.request().method() === "POST" && /skill/i.test(r.url()), { timeout: 120_000 });
    await dialog.getByRole("button", { name: /^创\s*建$/ }).click();
    if (!(await created).ok()) throw new Error("skill upload/create failed");
    onCreated?.();
    await expect(dialog).toBeHidden({ timeout: 120_000 });
  }

  async edit(name: string, marker: string): Promise<void> {
    const card = this.card(name);
    await card.getByRole("button", { name: /^编\s*辑$/ }).click();
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
    await card.getByRole("button", { name: "更多操作", exact: true }).click();
    await this.page.getByRole("menuitem", { name: "申请上架", exact: true }).click();
    const dialog = this.page.getByRole("dialog").filter({ hasText: /申请|上架/ });
    const submitted = this.page.waitForResponse((r) => r.request().method() === "POST" && /repository.*skill|skill.*repository/i.test(r.url()));
    await dialog.getByRole("button", { name: "提交申请", exact: true }).click();
    if (!(await submitted).ok()) throw new Error("skill listing application failed");
    await expect(dialog).toBeHidden();
  }

  async approve(name: string): Promise<void> {
    await this.open("审核中心");
    const search = this.page.getByPlaceholder("搜索资源名称");
    await search.fill(name);
    await search.press("Enter");
    const row = this.page.getByRole("row").filter({
      has: this.page.getByRole("button", { name, exact: true }),
    });
    await row.getByRole("button", { name: /^通\s*过$/ }).click();
    const confirm = this.page.getByRole("dialog", { name: "确定通过审核？" });
    await expect(confirm).toBeVisible();
    const reviewed = this.page.waitForResponse((r) =>
      r.request().method() === "POST" && /\/api\/reviews\/[^/]+\/decision$/.test(new URL(r.url()).pathname)
    );
    await confirm.getByRole("button", { name: /^确\s*定$/ }).click();
    if (!(await reviewed).ok()) throw new Error("skill review approval failed");
  }

  async install(name: string, targetName: string, onInstalled?: () => void): Promise<void> {
    await this.open("仓库"); await this.search(name);
    const card = this.card(name);
    await card.getByRole("button", { name: /^复\s*制$/ }).click();
    const dialog = this.page.getByRole("dialog").filter({ hasText: "复制为我的 Skill" });
    await dialog.getByPlaceholder("请输入 Skill 名称").fill(targetName);
    const installed = this.page.waitForResponse((r) => r.request().method() === "POST" && /skill.*install|install.*skill/i.test(r.url()));
    await dialog.getByRole("button", { name: /^复\s*制$/ }).click();
    if (!(await installed).ok()) throw new Error("skill copy/install failed");
    onInstalled?.();
    await expect(dialog).toBeHidden();
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
    const action = statusDialog.getByRole("button", { name: /下\s*架|取消申请/ });
    if (!(await action.count())) {
      await statusDialog.getByRole("button", { name: "关闭", exact: true }).click();
      return;
    }
    await action.click();
    const confirm = this.page.getByRole("dialog").last();
    const response = this.page.waitForResponse(
      (r) => ["POST", "PATCH"].includes(r.request().method()) && /repository.*skill|skill.*repository/i.test(r.url()),
    );
    await confirm.getByRole("button", { name: /下\s*架|取消申请/ }).click();
    if (!(await response).ok()) throw new Error("skill unpublish/withdraw failed");
    await expect(statusDialog).toBeHidden();
  }

  async delete(name: string): Promise<void> {
    await this.open("我的 Skill"); await this.search(name);
    const card = this.card(name);
    if (!(await card.count())) return;
    await card.getByRole("button", { name: /更多/ }).click();
    await this.page.getByRole("menuitem", { name: "删除", exact: true }).click();
    await this.page.getByRole("dialog").getByRole("button", { name: /^(删\s*除|确\s*定)$/ }).click();
    await expect(card).toHaveCount(0);
  }
}
