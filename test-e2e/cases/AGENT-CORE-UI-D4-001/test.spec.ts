import { journey } from "../../infra/automation/d4/runner/journey";
import { baseUrl, installEditor, label } from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey("AGENT-CORE-UI-D4-001", async ({ page, contract, expect }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  const fixture = await installEditor(page);
  Object.assign(fixture.draft, {
    agent_core: "smolagents", enable_context_manager: true, provide_run_summary: true,
    enable_protocol_repair_retry: true,
    sub_agent_id_list: [8], sub_agent_relations: [{agent_id:8,version_no:1}], external_sub_agent_id_list:[9],
    verification_config:{enabled:true,guardrail_config:{enabled:true,rules:[],default_action:"pass"}},
  });
  const original = JSON.parse(JSON.stringify(fixture.draft));
  let rejectNext = false;
  let rejections = 0;
  let readonlyWrites = -1;
  await page.route("**/api/agent/update", async (route) => {
    if (!rejectNext) return route.fallback();
    rejectNext = false;
    rejections++;
    await route.fulfill({status:400,contentType:"application/json",body:JSON.stringify({detail:"Controlled Core save failure"})});
  });
  const steps=contract.expectedIds("steps");
  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    expect((await page.request.get(baseUrl)).ok()).toBe(true);
  });
  const openSettings = async () => {
    await expect(page.getByText(label("agent.core.label"), {exact:true})).toBeAttached();
    if (!(await page.getByText(label("agent.core.label"), {exact:true}).isVisible())) {
      await page.getByText(label("agent.highFidelity.advancedTitle"),{exact:true}).click();
    }
  };
  const select = async (name:string) => {
    await page.locator(".ant-select").filter({has:page.locator("#agent-core")}).click();
    await page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter({hasText:new RegExp(`^${name}$`)}).click();
  };
  await contract.step(steps[0], async () => {
    await page.goto(`${baseUrl}/zh/agents/42`);
    await openSettings();
    await select("Jiuwen");
    await expect.poll(()=>fixture.updates.some(x=>x.agent_core==="jiuwen")).toBe(true);
    const update=fixture.updates.find(x=>x.agent_core==="jiuwen")!;
    expect(update).toEqual({agent_id:42,agent_core:"jiuwen"});
    expect(fixture.draft.enable_context_manager).toBe(true);
    expect(fixture.draft.provide_run_summary).toBe(true);
    expect(fixture.draft.verification_config.enabled).toBe(true);
    expect(fixture.draft.sub_agent_relations).toEqual(original.sub_agent_relations);
    expect(fixture.draft.external_sub_agent_id_list).toEqual(original.external_sub_agent_id_list);
    expect(fixture.draft.tools).toEqual(original.tools);
    expect(fixture.draft.skills).toEqual(original.skills);
    expect(fixture.draft.model_ids).toEqual(original.model_ids);
    expect(fixture.draft.duty_prompt).toBe(original.duty_prompt);
    expect(fixture.draft.sub_agent_id_list).toEqual(original.sub_agent_id_list);
  });
  await contract.step(steps[1], async () => {
    await page.reload(); await openSettings();
    await expect(page.getByText(label("agent.core.jiuwenHint"),{exact:true})).toBeVisible();
    await expect(page.getByRole("button",{name:label("agentConfig.layout.addAgent"),exact:true})).toBeEnabled();
    await expect(page.getByRole("button",{name:label("agentConfig.layout.thirdPartyAgent"),exact:true})).toBeEnabled();
    await expect(page.getByRole("switch",{name:label("agent.core.contextManager")})).toBeEnabled();
    await expect(page.getByRole("switch",{name:label("agent.core.contextManager")})).toBeChecked();
    await expect(page.getByRole("checkbox",{name:label("agent.highFidelity.runSummary"),exact:true})).toBeDisabled();
    await expect(page.getByRole("checkbox",{name:label("agent.highFidelity.runSummary"),exact:true})).toBeChecked();
    await expect(page.getByRole("checkbox",{name:label("agent.highFidelity.selfValidate"),exact:true})).toBeDisabled();
    await expect(page.getByRole("checkbox",{name:label("agent.highFidelity.selfValidate"),exact:true})).toBeChecked();
    await page.getByRole("button",{name:label("agent.highFidelity.moreSettings"),exact:true}).click();
    const more=page.getByRole("dialog");
    await expect(more.getByRole("switch").nth(0)).toBeDisabled();
    await expect(more.getByRole("switch").nth(1)).toBeDisabled();
    await page.keyboard.press("Escape");
    await expect(more).not.toBeVisible();
    const header=page.getByTestId("agent-config-header");
    await header.getByRole("button",{name:label("agent.highFidelity.debugMode"),exact:true}).click();
    await page.getByRole("button",{name:label("agent.debug.options"),exact:true}).click();
    await expect(page.getByRole("menuitem",{name:label("chat.composer.planning"),exact:true})).toHaveAttribute("aria-disabled","true");
    await page.keyboard.press("Escape");
    await header.getByRole("button",{name:label("agent.highFidelity.configureMode"),exact:true}).click();
    await openSettings();
    await select("smolagents");
    await expect.poll(()=>fixture.draft.agent_core).toBe("smolagents");
    const context=page.getByRole("switch",{name:label("agent.core.contextManager")});
    await expect(context).toBeEnabled(); await expect(context).toBeChecked();
    await expect.poll(()=>fixture.draft.enable_context_manager).toBe(true);
    expect(fixture.draft.sub_agent_id_list).toEqual(original.sub_agent_id_list);
  });
  await contract.step(steps[2], async () => {
    rejectNext=true; await select("Jiuwen");
    await expect(page.getByText("Controlled Core save failure",{exact:false})).toBeVisible();
    expect(fixture.draft.agent_core).toBe("smolagents");
    await expect(page.getByRole("switch",{name:label("agent.core.contextManager")})).toBeEnabled();
    await select("Jiuwen");
    await expect.poll(()=>fixture.draft.agent_core).toBe("jiuwen");
  });
  await contract.step(steps[3], async () => {
    const readonly=await page.context().newPage();
    const readonlyFixture=await installEditor(readonly,"READ_ONLY");
    Object.assign(readonlyFixture.draft,{agent_core:"jiuwen",enable_context_manager:false});
    await readonly.goto(`${baseUrl}/zh/agents/42`);
    await readonly.getByText(label("agent.highFidelity.advancedTitle"),{exact:true}).click();
    await expect(readonly.locator("#agent-core")).toBeDisabled();
    await expect(readonly.getByRole("button",{name:label("agentConfig.layout.addAgent"),exact:true})).toBeDisabled();
    await expect(readonly.getByRole("button",{name:label("agentConfig.layout.thirdPartyAgent"),exact:true})).toBeDisabled();
    expect(readonlyFixture.updates).toEqual([]);
    expect(readonlyFixture.unexpectedWrites).toEqual([]);
    readonlyWrites=readonlyFixture.updates.length+readonlyFixture.unexpectedWrites.length;
    await readonly.close();
  });
  const assertions=contract.expectedIds("assertions");
  await contract.assertion(assertions[0],async()=>{
    expect(fixture.unexpectedWrites).toEqual([]);
    expect(fixture.creationAttempts).toEqual([]);
    expect(fixture.draft.tools).toEqual(original.tools);
    expect(fixture.draft.skills).toEqual(original.skills);
  });
  await contract.assertion(assertions[1],async()=>{
    expect(fixture.updates.some(x=>x.agent_core==="smolagents")).toBe(true);
    expect(fixture.draft.enable_context_manager).toBe(true);
    expect(fixture.updates.every(x=>x.enable_context_manager===undefined)).toBe(true);
    expect(fixture.draft.sub_agent_id_list).toEqual(original.sub_agent_id_list);
  });
  await contract.assertion(assertions[2],async()=>{
    expect(rejections).toBe(1);
    expect(fixture.draft.agent_core).toBe("jiuwen");
  });
  await contract.assertion(assertions[3],async()=>{
    expect(readonlyWrites).toBe(0);
  });
});
