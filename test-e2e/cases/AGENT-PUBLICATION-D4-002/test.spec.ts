// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import {
  configuredModel,
  runToken,
} from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";
import { PublicationPage } from "../../infra/automation/d4/pages/publication.page";

journey("AGENT-PUBLICATION-D4-002", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("AGENT-PUBLICATION-D4-002");
  const display = `Publication ${token}`;
  const description = `Preserved draft ${token}`;
  const agents = new AgentPage(page);
  const publication = new PublicationPage(page);
  const initialPageCount = page.context().pages().length;
  const newPages: string[] = [];
  page.context().on("page", (opened) => newPages.push(opened.url()));
  let agentId = 0;
  let editorUrl = "";
  const forbiddenRequests: string[] = [];
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (
      request.method() !== "GET" &&
      /\/(?:agent\/(?:run|nl2agent\/run)|conversation\/create|api-keys(?:\/refresh)?)$/.test(
        pathname,
      )
    )
      forbiddenRequests.push(pathname);
  });
  contract.deferCleanup(async () => {
    if (agentId) await agents.delete(agentId);
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        await agents.open();
        return "real editor and login available";
      },
      async () => {
        agentId = await agents.create(
          display,
          `pub_${token.replace(/[^a-z0-9_]/gi, "_")}`,
        );
        editorUrl = page.url();
        await agents.selectModel(configuredModel("llm").displayName);
        await agents.setDescription(description);
        await agents.setPrompts({
          duty: "Publication access acceptance; do not invoke this agent.",
        });
        await agents.ensureAuthor();
        return "created an owned valid draft without invoking a model";
      },
    ],
    steps: [
      async () => {
        await agents.publishVersion(
          `pub-${token}`,
          "Publication navigation acceptance",
          { expectPublication: true },
        );
        await publication.assertLanding(editorUrl);
        return "owned published agent access details visible";
      },
      async () => {
        const pages = page.context().pages().length;
        await publication.content
          .getByRole("link", { name: "体验", exact: true })
          .click();
        await expect(page).toHaveURL(
          new RegExp(`/zh/newchat\\?agent_id=${agentId}$`),
        );
        await expect(
          page.getByRole("heading", { name: display, exact: true }),
        ).toBeVisible();
        expect(page.context().pages()).toHaveLength(pages);
        expect(newPages).toEqual([]);
        return "preview navigates the existing page and selects the owned agent";
      },
      async () => {
        await page.goto(editorUrl);
        await publication.open();
        const pages = page.context().pages().length;
        await publication.content
          .getByRole("link", { name: /API Key:/ })
          .click();
        await expect(page).toHaveURL(/\/zh\/users$/);
        await expect(
          page.getByText(/API.*Key|API.*密钥/i).first(),
        ).toBeVisible();
        expect(page.context().pages()).toHaveLength(pages);
        expect(newPages).toEqual([]);
        return "API key settings rendered in the existing browser page";
      },
      async () => {
        await page.goto(editorUrl);
        await publication.open();
        await expect(
          publication.content.getByRole("link", { name: "体验", exact: true }),
        ).toHaveAttribute(
          "href",
          new URL(`/zh/newchat?agent_id=${agentId}`, editorUrl).href,
        );
        return "return navigation preserves correct published access link";
      },
    ],
    assertions: [
      async () => {
        await publication.assertLanding(editorUrl);
        expect(page.context().pages()).toHaveLength(initialPageCount);
        return "same page returned from the correctly selected chat agent";
      },
      async () => {
        expect(forbiddenRequests).toEqual([]);
        return "navigation did not invoke an agent or mutate an API key";
      },
    ],
  });
});
