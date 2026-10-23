import { journey } from "../../infra/automation/d4/runner/journey";
import {
  baseUrl,
  installEditor,
  label,
} from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey("AGENT-EDITOR-D4-005", async ({ page, contract, expect }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  const fixture = await installEditor(page, "READ_ONLY");
  const steps = contract.expectedIds("steps");
  const assertions = contract.expectedIds("assertions");
  await contract.precondition(
    contract.expectedIds("preconditions")[0],
    async () => {
      const response = await page.request.get(baseUrl);
      expect(response.ok()).toBe(true);
    },
  );
  const header = () => page.getByTestId("agent-config-header");
  const checkProtected = async () => {
    await expect(
      page.getByPlaceholder(label("agent.displayNamePlaceholder")),
    ).toBeDisabled();
    await expect(
      page.getByPlaceholder(label("agent.highFidelity.greetingPlaceholder")),
    ).toBeDisabled();
    await expect(
      page.getByRole("button", {
        name: label("agentConfig.layout.addTool"),
        exact: true,
      }),
    ).toBeDisabled();
    await expect(
      header().getByRole("button", {
        name: label("agent.config.button.publish"),
        exact: true,
      }),
    ).toBeDisabled();
  };
  await contract.step(steps[0], async () => {
    await page.goto(`${baseUrl}/zh/agents/42`);
    await expect(header()).toBeVisible();
    await checkProtected();
  });
  await contract.step(steps[1], async () => {
    await header()
      .getByRole("button", {
        name: label("agent.highFidelity.debugMode"),
        exact: true,
      })
      .click();
    await expect(page.getByTestId("agent-debug-pane")).toBeVisible();
    expect(fixture.unexpectedWrites).toEqual([]);
  });
  await contract.step(steps[2], async () => {
    const configure = header().getByRole("button", {
      name: label("agent.highFidelity.configureMode"),
      exact: true,
    });
    await expect(configure).toBeEnabled();
    await configure.click();
    await checkProtected();
    await page.reload();
    await checkProtected();
    await expect(
      page.getByPlaceholder(label("agent.displayNamePlaceholder")),
    ).toHaveValue(fixture.draft.display_name);
  });
  await contract.assertion(assertions[0], async () => {
    expect(fixture.updates).toEqual([]);
    expect(fixture.creationAttempts).toEqual([]);
    expect(fixture.unexpectedWrites).toEqual([]);
  });
});
