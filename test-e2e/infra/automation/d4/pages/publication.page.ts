// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, type Page } from "playwright/test";

export class PublicationPage {
  constructor(readonly page: Page) {}

  get content() {
    return this.page.getByTestId("agent-publication-content");
  }

  async open(): Promise<void> {
    const tab = this.page
      .getByTestId("agent-config-header")
      .getByRole("button", {
        name: "智能体发布",
        exact: true,
      });
    await tab.click();
    await expect(tab).toHaveAttribute("aria-pressed", "true");
  }

  async configure(): Promise<void> {
    await this.page
      .getByTestId("agent-config-header")
      .getByRole("button", { name: "智能体配置", exact: true })
      .click();
    await expect(
      this.page
        .getByTestId("agent-config-header")
        .getByRole("button", { name: "智能体配置", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
  }

  async assertLanding(editorUrl: string): Promise<void> {
    const expected = new URL(editorUrl);
    await expect(this.page).toHaveURL(
      (url) =>
        url.origin === expected.origin && url.pathname === expected.pathname,
    );
    await expect(
      this.page
        .getByTestId("agent-config-header")
        .getByRole("button", { name: "智能体发布", exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(this.content).toBeVisible();
    await expect(this.page.getByTestId("agent-publication-empty")).toHaveCount(
      0,
    );
  }
}
