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

journey("AGENT-PUBLICATION-D4-001", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("AGENT-PUBLICATION-D4-001");
  const display = `Publication ${token}`;
  const description = `Preserved draft ${token}`;
  const agents = new AgentPage(page);
  const publication = new PublicationPage(page);
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
        await publication.open();
        await expect(page.getByTestId("agent-publication-empty")).toBeVisible();
        await expect(publication.content).toHaveCount(0);
        await expect(
          page.getByRole("link", { name: "体验", exact: true }),
        ).toHaveCount(0);
        return "draft exposes only the empty publication state";
      },
      async () => {
        await publication.configure();
        await expect(
          page.getByRole("textbox", { name: "智能体描述", exact: true }),
        ).toHaveValue(description);
        await page
          .getByRole("button", { name: "智能体调试", exact: true })
          .click();
        await expect(
          page.getByRole("button", { name: "智能体调试", exact: true }),
        ).toHaveAttribute("aria-pressed", "true");
        await expect(
          page
            .getByTestId("agent-config-header")
            .getByRole("button", { name: "智能体配置", exact: true }),
        ).toHaveAttribute("aria-pressed", "false");
        await publication.open();
        await expect(
          page.getByRole("button", { name: "智能体调试", exact: true }),
        ).toHaveAttribute("aria-pressed", "false");
        await publication.configure();
        await expect(
          page.getByRole("textbox", { name: "智能体描述", exact: true }),
        ).toHaveValue(description);
        return "configuration survives configure/debug/publication transitions";
      },
      async () => {
        await agents.publishVersion(
          `pub-${token}`,
          "Publication display acceptance",
          { expectPublication: true },
        );
        await publication.assertLanding(editorUrl);
        for (const title of ["体验与分享", "API 调用", "A2A 链接"]) {
          await expect(
            publication.content.getByRole("button", {
              name: new RegExp(`^${title}`),
            }),
          ).toHaveAttribute("aria-expanded", "true");
        }
        await expect(publication.content.locator("details")).toHaveAttribute(
          "open",
          "",
        );
        await expect(publication.content.locator("pre")).toContainText("curl");
        return "same-route publication opens all sections and the curl example";
      },
      async () => {
        for (const [title, child] of [
          [
            "体验与分享",
            publication.content.getByRole("link", {
              name: "体验",
              exact: true,
            }),
          ],
          ["API 调用", publication.content.locator("pre")],
          [
            "A2A 链接",
            publication.content.getByText(
              "其他智能体可通过标准协议发现并调用本 Agent",
              { exact: true },
            ),
          ],
        ] as const) {
          const toggle = publication.content.getByRole("button", {
            name: new RegExp(`^${title}`),
          });
          await toggle.click();
          await expect(toggle).toHaveAttribute("aria-expanded", "false");
          await expect(child).toBeHidden();
          for (const other of ["体验与分享", "API 调用", "A2A 链接"].filter(
            (value) => value !== title,
          )) {
            await expect(
              publication.content.getByRole("button", {
                name: new RegExp(`^${other}`),
              }),
            ).toHaveAttribute("aria-expanded", "true");
          }
          await toggle.click();
          await expect(toggle).toHaveAttribute("aria-expanded", "true");
          await expect(child).toBeVisible();
        }
        return "all three sections independently collapse and reopen";
      },
    ],
    assertions: [
      async () => {
        await publication.configure();
        await expect(
          page.getByRole("textbox", { name: "智能体描述", exact: true }),
        ).toHaveValue(description);
        expect(forbiddenRequests).toEqual([]);
        return "draft values preserved and no invocation or key mutation";
      },
      async () => {
        await publication.open();
        await expect(publication.content.locator("details")).toHaveAttribute(
          "open",
          "",
        );
        await expect(publication.content.locator("pre")).toBeVisible();
        return "published access content remains usable with expanded example";
      },
    ],
  });
});
