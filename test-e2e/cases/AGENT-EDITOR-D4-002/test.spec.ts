import { journey } from "../../infra/automation/d4/runner/journey";
import {
  baseUrl,
  installEditor,
  label,
} from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey("AGENT-EDITOR-D4-002", async ({ page, contract, expect }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
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
  fixture.rejectNextCreation = true;
  const name = () =>
    page.getByPlaceholder(label("agentConfig.createModal.namePlaceholder"));
  const submit = () =>
    page.getByRole("dialog").getByRole("button", {
      name: label("agentConfig.createModal.submit"),
      exact: true,
    });
  await contract.step(steps[0], async () => {
    await page.goto(`${baseUrl}/zh/agents`);
    await page
      .getByRole("button", { name: label("agent.action.create"), exact: true })
      .click();
    await name().fill("Retained retry name");
    await submit().click();
    await expect.poll(() => fixture.creationAttempts.length).toBe(1);
    await expect(
      page
        .locator(".ant-message-notice-title")
        .filter({ hasText: "Controlled creation rejection" }),
    ).toBeVisible();
    await expect(name()).toHaveValue("Retained retry name");
    await expect(page).toHaveURL(/\/zh\/agents$/);
    expect(fixture.successfulCreations).toBe(0);
  });
  await contract.step(steps[1], async () => {
    await expect(submit()).toBeEnabled();
    await submit().click();
    await expect(page).toHaveURL(/\/zh\/agents\/42\?onboarding=1$/);
    await expect(page.locator(".agent-creation-guide.ant-tour")).toBeVisible();
    await page.keyboard.press("Escape");
  });
  await contract.step(steps[2], async () => {
    await page.reload();
    await expect(
      page.getByPlaceholder(label("agent.displayNamePlaceholder")),
    ).toHaveValue("Retained retry name");
  });
  await contract.assertion(assertions[0], async () => {
    expect(fixture.creationAttempts).toHaveLength(2);
    expect(fixture.successfulCreations).toBe(1);
    expect(fixture.creationAttempts.map((x) => x.display_name)).toEqual([
      "Retained retry name",
      "Retained retry name",
    ]);
    expect(fixture.updates).toEqual([]);
    expect(fixture.unexpectedWrites).toEqual([]);
  });
});
