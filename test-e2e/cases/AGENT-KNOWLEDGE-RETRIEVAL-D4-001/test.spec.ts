// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import {
  baseUrl,
  installEditor,
  label,
} from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey(
  "AGENT-KNOWLEDGE-RETRIEVAL-D4-001",
  async ({ page, contract, expect }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.context().addCookies([
      {
        name: "nexent_token_expires_at",
        value: String(Math.floor(Date.now() / 1000) + 3600),
        url: baseUrl,
      },
    ]);
    const fixture = await installEditor(page);
    const [knowledgeTool] = fixture.draft.tools;
    Object.assign(knowledgeTool, {
      source: "local",
      params: [
        ...knowledgeTool.params,
        { name: "top_k", type: "number", optional: true, default: 5 },
      ],
    });
    const initialDraft = structuredClone(fixture.draft);
    const requests: unknown[] = [];
    await page.route("**/api/tool/validate", async (route) => {
      requests.push(route.request().postDataJSON());
      await route.fulfill({
        json: JSON.stringify({
          results: [
            { title: "Fixture document", text: "The fixture retrieval hit." },
          ],
        }),
      });
    });

    const [precondition] = contract.expectedIds("preconditions");
    const [prepare, run] = contract.expectedIds("steps");
    const [assertion] = contract.expectedIds("assertions");
    const dialog = page.getByRole("dialog").filter({
      hasText: label("agent.knowledge.test.title"),
    });
    const runButton = dialog.getByRole("button", {
      name: label("agent.knowledge.test.run"),
    });
    await contract.precondition(precondition, async () => {
      expect((await page.request.get(baseUrl)).ok()).toBe(true);
    });
    await contract.step(prepare, async () => {
      await page.goto(`${baseUrl}/zh/agents/42`);
      await page
        .getByTestId("agent-config-card-knowledge")
        .getByRole("button", { name: label("agent.knowledge.test.title") })
        .click();
      const testColumn = dialog.locator('[data-config-part="test-column"]');
      await expect(testColumn).toHaveCSS(
        "background-color",
        "rgb(250, 250, 250)",
      );
      await expect(
        testColumn.locator('[data-config-part="test-inputs"]'),
      ).toHaveCSS("padding", "20px 24px");
      await expect(
        testColumn.locator('[data-config-part="test-result"]'),
      ).toHaveCSS("border-top-width", "1px");
      await expect(dialog.getByText("Fixture Knowledge Base")).toBeVisible();
      await expect(runButton).toBeDisabled();
      await dialog
        .getByPlaceholder(label("agent.knowledge.test.query"))
        .fill("benefits");
      await expect(runButton).toBeEnabled();
      const formMode = dialog.getByText(label("toolConfig.toolTest.form"), {
        exact: true,
      });
      const jsonMode = dialog.getByText("JSON", { exact: true });
      const setJsonScope = async (ids: string[]) => {
        await jsonMode.click();
        await dialog
          .getByRole("textbox")
          .fill(JSON.stringify({ query: "benefits", index_names: ids }));
        await formMode.click();
      };
      await setJsonScope([]);
      await expect(dialog.getByText("Fixture Knowledge Base")).toHaveCount(0);
      await expect(runButton).toBeDisabled();
      await setJsonScope(["fixture-kb"]);
      await expect(dialog.getByText("Fixture Knowledge Base")).toBeVisible();
      await expect(runButton).toBeEnabled();
      expect(requests).toEqual([]);
    });
    await contract.step(run, async () => {
      await runButton.click();
      await expect(dialog.getByText(/The fixture retrieval hit/)).toBeVisible();
      await expect(dialog.getByText(/Fixture document/)).toBeVisible();
      await dialog
        .locator('[data-config-part="header"]')
        .getByRole("button", { name: label("common.close") })
        .click();
      await expect(dialog).toBeHidden();
    });
    await contract.assertion(assertion, async () => {
      expect(requests).toEqual([
        expect.objectContaining({
          name: "knowledge_base_search",
          source: "local",
          inputs: { query: "benefits", index_names: ["fixture-kb"] },
          params: { top_k: 5, index_names: ["fixture-kb"] },
        }),
      ]);
      expect(fixture.draft).toEqual(initialDraft);
      expect(fixture.updates).toEqual([]);
      expect(fixture.creationAttempts).toEqual([]);
      expect(fixture.unexpectedWrites).toEqual([]);
    });
  },
);
