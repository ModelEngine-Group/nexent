import { journey } from "../../infra/automation/d4/runner/journey";
import {
  baseUrl,
  installEditor,
  label,
} from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey("AGENT-EDITOR-D4-004", async ({ page, contract, expect }) => {
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
  const original = structuredClone(fixture.draft);
  await contract.step(steps[0], async () => {
    await page.goto(`${baseUrl}/zh/agents/42`);
    await expect(page.getByTestId("agent-config-header")).toBeVisible();
    await expect(
      page.getByTestId("agent-selected-knowledge-base-fixture-kb"),
    ).toContainText("Fixture Knowledge Base");
    await expect(page.getByTestId("agent-selected-model-7")).toBeVisible();
  });
  await contract.step(steps[1], async () => {
    for (const key of [
      "agent.highFidelity.addModel",
      "agentConfig.layout.addKnowledgeBase",
      "agentConfig.layout.addSkill",
      "agentConfig.layout.addTool",
      "agentConfig.layout.addAgent",
    ]) {
      const entry = page
        .getByRole("button", { name: label(key), exact: true })
        .first();
      await entry.scrollIntoViewIfNeeded();
      await entry.click();
      const dialog = page.getByRole("dialog");
      await expect(dialog).toBeVisible();
      await dialog
        .getByRole("button", { name: /关闭|Close/ })
        .first()
        .click();
      await expect(dialog).toHaveCount(0);
      await expect(page.locator(".ant-drawer-mask:visible")).toHaveCount(0);
    }
  });
  await contract.step(steps[2], async () => {
    await page.reload();
    await expect(
      page.getByTestId("agent-selected-knowledge-base-fixture-kb"),
    ).toBeVisible();
    await expect(page.getByTestId("agent-selected-model-7")).toBeVisible();
  });
  await contract.assertion(assertions[0], async () => {
    expect(fixture.draft).toEqual(original);
    expect(fixture.updates).toEqual([]);
    expect(fixture.creationAttempts).toEqual([]);
    expect(fixture.unexpectedWrites).toEqual([]);
    await expect(page.getByRole("dialog")).toHaveCount(0);
  });
});
