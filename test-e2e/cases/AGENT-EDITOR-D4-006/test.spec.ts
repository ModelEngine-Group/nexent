import { journey } from "../../infra/automation/d4/runner/journey";
import {
  baseUrl,
  installEditor,
  label,
} from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey("AGENT-EDITOR-D4-006", async ({ page, contract, expect }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const fixture = await installEditor(page);
  const steps = contract.expectedIds("steps");
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      expect((await page.request.get(baseUrl)).ok()).toBe(true);
    },
  );
  const open = () =>
    page
      .getByRole("button", { name: label("agent.action.create"), exact: true })
      .click();
  const close = () =>
    page
      .getByRole("button", {
        name: label("agentConfig.createModal.close"),
        exact: true,
      })
      .click();
  await contract.step(steps[0], async () => {
    await page.goto(`${baseUrl}/zh/agents`);
    await open();
    await expect(
      page.getByText(label("agentConfig.createModal.templates.empty"), {
        exact: true,
      }),
    ).toBeVisible();
    await expect(page.getByText("心肌病筛查助手", { exact: true })).toHaveCount(
      0,
    );
    expect(fixture.creationAttempts).toEqual([]);
    expect(fixture.templateReads).toBeGreaterThan(0);
    await close();
  });
  await contract.step(steps[1], async () => {
    fixture.rejectNextTemplateRead = true;
    await open();
    await expect(page.getByRole("dialog").getByRole("alert")).toContainText(
      label("agentConfig.createModal.templates.loadFailed"),
    );
    fixture.templateAgents = [
      {
        agent_id: 72,
        name: "API-only template",
        display_name: "API catalog title",
        description: "API catalog description",
        tags: ["Finance"],
        is_main_agent: true,
      },
      {
        agent_id: 73,
        name: "Untagged template",
        description: "No tag description",
        tags: [],
        is_main_agent: true,
      },
    ];
    await page
      .getByRole("button", { name: label("common.retry"), exact: true })
      .click();
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByText("API catalog title", { exact: true }),
    ).toBeVisible();
    await expect(
      dialog.getByText("API catalog description", { exact: true }),
    ).toBeVisible();
    await expect(dialog.getByText("Finance", { exact: true })).toBeVisible();
    await expect(
      dialog.getByText("Untagged template", { exact: true }),
    ).toBeVisible();
    await expect(dialog.getByText("医疗", { exact: true })).toHaveCount(0);
    expect(fixture.creationAttempts).toEqual([]);
  });
  await contract.step(steps[2], async () => {
    await page.getByRole("button", { name: /API catalog title/ }).click();
    await page
      .getByPlaceholder(label("agentConfig.createModal.namePlaceholder"))
      .fill("  From API catalog  ");
    await page
      .getByRole("dialog")
      .getByRole("button", {
        name: label("agentConfig.createModal.submit"),
        exact: true,
      })
      .click();
    await expect(page).toHaveURL(/\/zh\/agents\/42\?onboarding=1$/);
    expect(fixture.creationAttempts).toHaveLength(1);
    expect(fixture.creationAttempts[0]).toMatchObject({
      display_name: "From API catalog",
      description: "API catalog description",
    });
  });
  await contract.assertion(contract.expectedIds("assertions")[0], async () => {
    expect(fixture.successfulCreations).toBe(1);
    expect(fixture.creationAttempts).toHaveLength(1);
    expect(fixture.updates).toEqual([]);
    expect(fixture.unexpectedWrites).toEqual([]);
  });
});
