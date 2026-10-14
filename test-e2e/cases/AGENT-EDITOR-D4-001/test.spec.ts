import { journey } from "../../infra/automation/d4/runner/journey";
import {
  baseUrl,
  installEditor,
  label,
} from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey("AGENT-EDITOR-D4-001", async ({ page, contract, expect }) => {
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
  fixture.conflicts.add("Already used");
  const create = () =>
    page.getByRole("button", {
      name: label("agent.action.create"),
      exact: true,
    });
  const name = () =>
    page.getByPlaceholder(label("agentConfig.createModal.namePlaceholder"));
  const submit = () =>
    page.getByRole("dialog").getByRole("button", {
      name: label("agentConfig.createModal.submit"),
      exact: true,
    });
  await contract.step(steps[0], async () => {
    await page.goto(`${baseUrl}/zh/agents`);
    await create().click();
    await submit().click();
    await expect(
      page.getByText(label("agent.validation.displayNameRequired"), {
        exact: true,
      }),
    ).toBeVisible();
    expect(fixture.creationAttempts).toEqual([]);
  });
  await contract.step(steps[1], async () => {
    await name().fill("Already used");
    await submit().click();
    await expect(
      page.getByText(label("agent.validation.displayNameDuplicate"), {
        exact: true,
      }),
    ).toBeVisible();
    expect(fixture.creationAttempts).toEqual([]);
    await name().fill("  Unique browser agent  ");
    await submit().click();
    await expect(page).toHaveURL(/\/zh\/agents\/42\?onboarding=1$/);
    expect(fixture.creationAttempts).toHaveLength(1);
    expect(fixture.creationAttempts[0].display_name).toBe(
      "Unique browser agent",
    );
  });
  await contract.step(steps[2], async () => {
    const tour = page.locator(".agent-creation-guide.ant-tour");
    await expect(tour).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(tour).toHaveCount(0);
    await page.reload();
    await expect(page.getByTestId("agent-config-header")).toBeVisible();
    await expect(
      page.getByPlaceholder(label("agent.displayNamePlaceholder")),
    ).toHaveValue("Unique browser agent");
    await expect(tour).toHaveCount(0);
  });
  await contract.assertion(assertions[0], async () => {
    expect(fixture.successfulCreations).toBe(1);
    expect(fixture.creationAttempts).toHaveLength(1);
    expect(fixture.updates).toEqual([]);
    expect(fixture.unexpectedWrites).toEqual([]);
  });
});
