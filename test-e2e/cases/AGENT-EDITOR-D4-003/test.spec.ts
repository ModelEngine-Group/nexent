// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import {
  baseUrl,
  installEditor,
  label,
} from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey("AGENT-EDITOR-D4-003", async ({ page, contract, expect }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await page.context().addCookies([
    {
      name: "nexent_token_expires_at",
      value: String(Math.floor(Date.now() / 1000) + 3600),
      url: baseUrl,
    },
  ]);
  await page.addInitScript(() => {
    localStorage.setItem("user_info", JSON.stringify({
      id: "fixture-user",
      tenantId: "fixture-tenant",
      email: "fixture@nexent.test",
      role: "SPEED",
    }));
  });
  const fixture = await installEditor(page);
  const steps = contract.expectedIds("steps");
  const assertions = contract.expectedIds("assertions");
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      const response = await page.request.get(baseUrl);
      expect(response.ok()).toBe(true);
    },
  );
  const description = () =>
    page.getByPlaceholder(label("agent.highFidelity.descriptionPlaceholder"));
  const greeting = () =>
    page.getByPlaceholder(label("agent.highFidelity.greetingPlaceholder"));
  const prompt = () => page.locator("#agent-primary-prompt");
  const editedPrompt = "Prompt saved from the expanded editor";
  await contract.step(steps[0], async () => {
    await page.goto(`${baseUrl}/zh/agents/42`);
    await expect(description()).toHaveValue(fixture.draft.description);
    await expect(greeting()).toHaveValue(fixture.draft.greeting_message);
    await expect(prompt()).toHaveValue(fixture.draft.prompt);
    expect(fixture.updates).toEqual([]);
  });
  await contract.step(steps[1], async () => {
    await description().fill("Description saved by the browser journey");
    const guide = page.getByTestId("agent-config-card-welcome").getByRole("button", { name: new RegExp(label("agent.highFidelity.guideTitle")) });
    await guide.click();
    await expect(greeting()).toBeVisible();
    await greeting().fill("Greeting saved by the browser journey");
    await greeting().blur();
    await expect
      .poll(() => fixture.draft.description)
      .toBe("Description saved by the browser journey");
    await expect
      .poll(() => fixture.draft.greeting_message)
      .toBe("Greeting saved by the browser journey");
    await page
      .getByRole("button", { name: label("systemPrompt.button.expand") })
      .click();
    const dialog = page.getByRole("dialog", {
      name: label("agent.field.prompt"),
    });
    const expandedInput = dialog.getByRole("textbox");
    await expect(expandedInput).toHaveValue(fixture.draft.prompt);
    await expandedInput.fill(editedPrompt);
    await expect.poll(() => fixture.draft.prompt).toBe(editedPrompt);
    await expect(dialog).toBeVisible();
    await dialog
      .getByRole("button", { name: label("common.close"), exact: true })
      .click();
    await expect(dialog).toBeHidden();
    await expect(prompt()).toHaveValue(editedPrompt);
    await expect(page.getByTestId("agent-config-header")).toContainText(
      /自动保存于.*\d{2}:\d{2}/,
    );
  });
  await contract.step(steps[2], async () => {
    await page.reload();
    await expect(description()).toHaveValue(
      "Description saved by the browser journey",
    );
    await expect(greeting()).toHaveValue(
      "Greeting saved by the browser journey",
    );
    await expect(prompt()).toHaveValue(editedPrompt);
  });
  await contract.assertion(assertions[0], async () => {
    expect(fixture.updates.length).toBeGreaterThan(0);
    expect(fixture.updates.every((x) => x.agent_id === 42)).toBe(true);
    expect(fixture.draft.model_ids).toEqual([7]);
    expect(fixture.draft.tools.map((x: any) => x.tool_id)).toEqual([9001]);
    expect(fixture.creationAttempts).toEqual([]);
    expect(fixture.unexpectedWrites).toEqual([]);
  });
});
