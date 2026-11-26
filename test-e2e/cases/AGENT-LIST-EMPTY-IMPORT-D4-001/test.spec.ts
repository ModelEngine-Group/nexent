// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import {
  baseUrl,
  installEditor,
  label,
} from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey(
  "AGENT-LIST-EMPTY-IMPORT-D4-001",
  async ({ page, contract, expect }) => {
    await page.context().addCookies([
      {
        name: "nexent_token_expires_at",
        value: String(Math.floor(Date.now() / 1000) + 3600),
        url: baseUrl,
      },
    ]);
    const fixture = await installEditor(page);
    await page.route("**/api/user/current_user_info", (route) =>
      route.fulfill({
        json: {
          data: {
            user: {
              user_id: "fixture-user",
              tenant_id: "fixture-tenant",
              user_email: "fixture@nexent.test",
              user_role: "SPEED",
              auth_provider: "local",
              group_ids: [],
              permissions: [],
              accessiblePages: ["/agents", "/agent-space"],
            },
          },
        },
      }),
    );
    await page.route("**/api/repository/agent?*", (route) =>
      route.fulfill({
        json: { items: [], pagination: { page: 1, page_size: 10, total: 0 } },
      }),
    );
    const [precondition] = contract.expectedIds("preconditions");
    const [configuration, repository] = contract.expectedIds("steps");
    const [assertion] = contract.expectedIds("assertions");
    const chooseFileAndCancel = async () => {
      const chooserPromise = page.waitForEvent("filechooser");
      await page
        .getByRole("button", {
          name: label("agentConfig.button.import"),
          exact: true,
        })
        .click();
      const chooser = await chooserPromise;
      await chooser.setFiles({
        name: "fixture-agent.json",
        mimeType: "application/json",
        buffer: Buffer.from(
          JSON.stringify({
            agent_id: 42,
            agent_info: {
              42: {
                name: "fixture_agent",
                display_name: "Imported fixture",
                prompt: "Help with test questions.",
              },
            },
          }),
        ),
      });
      const wizard = page.getByRole("dialog", {
        name: label("market.install.title"),
      });
      await expect(wizard).toBeVisible();
      await wizard
        .getByRole("button", { name: label("common.cancel"), exact: true })
        .click();
      await expect(wizard).toBeHidden();
    };
    await contract.precondition(precondition, async () => {
      expect((await page.request.get(baseUrl)).ok()).toBe(true);
    });
    await contract.step(configuration, async () => {
      await page.goto(`${baseUrl}/zh/agents`);
      await expect(
        page.getByText(label("agentConfig.empty.noAgents")),
      ).toBeVisible();
      await expect(
        page.getByRole("button", {
          name: label("agent.action.create"),
          exact: true,
        }),
      ).toBeVisible();
      await chooseFileAndCancel();
    });
    await contract.step(repository, async () => {
      await page.goto(`${baseUrl}/zh/agent-space`);
      await expect(
        page.getByText(label("agentRepository.page.empty")),
      ).toBeVisible();
      await chooseFileAndCancel();
    });
    await contract.assertion(assertion, async () => {
      expect(fixture.updates).toEqual([]);
      expect(fixture.creationAttempts).toEqual([]);
      expect(fixture.unexpectedWrites).not.toContain("/agent/import");
    });
  },
);
