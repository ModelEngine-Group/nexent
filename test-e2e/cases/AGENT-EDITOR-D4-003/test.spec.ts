import { journey } from "../../infra/automation/d4/runner/journey";
import {
  baseUrl,
  installEditor,
  label,
} from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey("AGENT-EDITOR-D4-003", async ({ page, contract, expect }) => {
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
  const description = () =>
    page.getByPlaceholder(label("agent.highFidelity.descriptionPlaceholder"));
  const greeting = () =>
    page.getByPlaceholder(label("agent.highFidelity.greetingPlaceholder"));
  await contract.step(steps[0], async () => {
    await page.goto(`${baseUrl}/zh/agents/42`);
    await expect(description()).toHaveValue(fixture.draft.description);
    await expect(greeting()).toHaveValue(fixture.draft.greeting_message);
    expect(fixture.updates).toEqual([]);
  });
  await contract.step(steps[1], async () => {
    await description().fill("Description saved by the browser journey");
    await greeting().fill("Greeting saved by the browser journey");
    await greeting().blur();
    await expect
      .poll(() => fixture.draft.description)
      .toBe("Description saved by the browser journey");
    await expect
      .poll(() => fixture.draft.greeting_message)
      .toBe("Greeting saved by the browser journey");
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
