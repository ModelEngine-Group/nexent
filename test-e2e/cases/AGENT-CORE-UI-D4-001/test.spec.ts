// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { journey } from "../../infra/automation/d4/runner/journey";
import { baseUrl, installEditor, label } from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey("AGENT-CORE-UI-D4-001", async ({ page, contract, expect }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const fixture = await installEditor(page);
  Object.assign(fixture.draft, { agent_core: "smolagents", enable_context_manager: true,
    provide_run_summary: true, enable_protocol_repair_retry: true });
  const original = JSON.parse(JSON.stringify(fixture.draft));
  let core = "jiuwen";
  let rejectNext = false;
  let rejections = 0;
  let readonlyWrites = -1;
  const deployment = (target: typeof page) => target.route("**/api/tenant_config/deployment_version", route => route.fulfill({
    contentType: "application/json", body: JSON.stringify({deployment_version:"speed",app_version:"test",agent_core:core,status:"success"}),
  }));
  await deployment(page);
  await page.route("**/api/agent/update", async route => {
    if (!rejectNext) return route.fallback();
    rejectNext = false; rejections++;
    await route.fulfill({status:400,contentType:"application/json",body:JSON.stringify({detail:"Controlled CM save failure"})});
  });
  const settings = async (target = page) => {
    const heading = target.getByText(label("agent.core.contextManager"), {exact:true});
    await expect(heading).toBeAttached();
    if (!(await heading.isVisible())) await target.getByText(label("agent.highFidelity.advancedTitle"),{exact:true}).click();
  };
  const cm = () => page.getByRole("switch",{name:label("agent.core.contextManager")});
  const steps = contract.expectedIds("steps");
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    expect((await page.request.get(baseUrl)).ok()).toBe(true);
  });
  await contract.step(steps[0], async () => {
    await page.goto(`${baseUrl}/zh/agents/42`); await settings();
    await expect(page.locator("#agent-core")).toHaveCount(0);
    await expect(page.getByText(label("agent.core.label"), {exact:true})).toHaveCount(0);
    await expect(page.getByRole("checkbox",{name:label("agent.highFidelity.runSummary"),exact:true})).toBeDisabled();
    expect(fixture.updates).toEqual([]);
  });
  await contract.step(steps[1], async () => {
    await expect(cm()).toBeEnabled(); await cm().click();
    await expect.poll(() => fixture.draft.enable_context_manager).toBe(false);
    await page.reload(); await settings(); await expect(cm()).not.toBeChecked();
    await expect(page.locator("#agent-core")).toHaveCount(0);
  });
  await contract.step(steps[2], async () => {
    rejectNext = true; await cm().click();
    await expect(page.getByText("Controlled CM save failure",{exact:false})).toBeVisible();
    await expect(cm()).not.toBeChecked();
    await cm().click(); await expect.poll(() => fixture.draft.enable_context_manager).toBe(true);
  });
  await contract.step(steps[3], async () => {
    core = "smolagents"; await page.reload(); await settings();
    await expect(page.locator("#agent-core")).toHaveCount(0);
    await expect(page.getByRole("checkbox",{name:label("agent.highFidelity.runSummary"),exact:true})).toBeEnabled();
    const readonly = await page.context().newPage();
    const readFixture = await installEditor(readonly,"READ_ONLY"); await deployment(readonly);
    await readonly.goto(`${baseUrl}/zh/agents/42`); await settings(readonly);
    await expect(readonly.locator("#agent-core")).toHaveCount(0);
    await expect(readonly.getByRole("switch",{name:label("agent.core.contextManager")})).toBeDisabled();
    readonlyWrites = readFixture.updates.length + readFixture.unexpectedWrites.length;
    await readonly.close();
  });
  const assertions = contract.expectedIds("assertions");
  await contract.assertion(assertions[0], async () => {
    expect(fixture.unexpectedWrites).toEqual([]); expect(fixture.creationAttempts).toEqual([]);
    expect(fixture.draft.tools).toEqual(original.tools); expect(fixture.draft.skills).toEqual(original.skills);
  });
  await contract.assertion(assertions[1], async () => {
    expect(fixture.draft.enable_context_manager).toBe(true);
    expect(fixture.updates.length).toBe(2);
    expect(fixture.updates.every(update => update.agent_core === undefined)).toBe(true);
  });
  await contract.assertion(assertions[2], async () => {
    expect(rejections).toBe(1); expect(fixture.draft.agent_core).toBe(original.agent_core);
    expect(fixture.draft.provide_run_summary).toBe(original.provide_run_summary);
  });
  await contract.assertion(assertions[3], async () => { expect(readonlyWrites).toBe(0); });
});
