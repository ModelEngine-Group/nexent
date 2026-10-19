import { journey } from "../../infra/automation/d4/runner/journey";
import { baseUrl, installEditor, label } from "../../infra/automation/d4/fixtures/agent-editor-workflows";

journey("JIUWEN-CONTEXT-D4-001", async ({ page, contract, expect }) => {
  const fixture = await installEditor(page);
  Object.assign(fixture.draft, { agent_core: "smolagents", enable_context_manager: false });
  const messages: any[] = [
    { role: "user", message_id: 1, message_index: 1, status: "completed", message: "Analyze the original file" },
    { role: "assistant", message_id: 2, message_index: 2, status: "completed", message: [
      { type: "tool", content: JSON.stringify({ tool_name: "historical_tool", tool_arguments: { a: 1 } }), unit_index: 0, tool_call_id: "old-call" },
      { type: "execution_logs", content: "SAVED_TOOL_FACT", unit_index: 1, tool_call_id: "old-call" },
      { type: "final_answer", content: "OLD_CONVERSATION_ALPHA", unit_index: 2 },
    ] },
  ];
  const runs: any[] = [];
  await page.route("**/api/**", async (route) => {
    const endpoint = new URL(route.request().url()).pathname.replace(/^.*\/api/, "");
    const respond = (data: unknown) => route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(data)});
    if (endpoint === "/memory/config/load") return respond({MEMORY_SWITCH:"N"});
    if (endpoint === "/conversation/list") return respond({code:0,data:{items:[{
      conversation_id:101,conversation_title:"Existing conversation",agent_id:42,create_time:Date.now(),update_time:Date.now(),
    }],metadata:{total:1,today:1,last_7_days:0,older:0}}});
    if (endpoint === "/conversation/101") return respond({code:0,data:[{
      conversation_id:101,conversation_title:"Existing conversation",agent_id:42,chat_mode:"execution",
      create_time:Date.now(),runtime_metadata:{},runtime_metadata_version:0,message:messages,
    }]});
    if (endpoint === "/agent/run") {
      const request=route.request().postDataJSON();
      runs.push({request,core:fixture.draft.agent_core,cm:fixture.draft.enable_context_manager});
      const answer=runs.length===1?"CONTINUED_ALPHA":"CONTINUED_BACK_ALPHA";
      messages.push({role:"user",message_id:messages.length+1,message_index:messages.length+1,status:"completed",message:request.query});
      messages.push({role:"assistant",message_id:messages.length+1,message_index:messages.length+1,status:"completed",
        message:[{type:"final_answer",content:answer,unit_index:0}]});
      const events=[{type:"agent_new_run",content:request.query},{type:"final_answer",content:answer},{type:"agent_finish",content:""}];
      return route.fulfill({status:200,contentType:"text/event-stream",headers:{conversation_id:"101"},
        body:events.map(value=>`data: ${JSON.stringify(value)}\n\n`).join("")});
    }
    return route.fallback();
  });
  const openOld = async () => {
    await page.goto(`${baseUrl}/zh/newchat?thread_id=101`);
    await expect(page.getByText("OLD_CONVERSATION_ALPHA",{exact:false}).first()).toBeVisible();
    const memoryDialog=page.getByRole("dialog",{name:"尚未配置向量模型"});
    if (await memoryDialog.isVisible()) await memoryDialog.getByRole("button",{name:"关闭记忆"}).click();
  };
  const configure = async (core: string, cm: boolean) => {
    await page.goto(`${baseUrl}/zh/agents/42`);
    await expect(page.getByText(label("agent.core.label"),{exact:true})).toBeAttached();
    if (!(await page.getByText(label("agent.core.label"),{exact:true}).isVisible())) {
      await page.getByText(label("agent.highFidelity.advancedTitle"),{exact:true}).click();
    }
    await page.locator(".ant-select").filter({has:page.locator("#agent-core")}).click();
    await page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter({hasText:new RegExp(`^${core}$`)}).click();
    const toggle=page.getByRole("switch",{name:label("agent.core.contextManager")});
    await expect(toggle).toBeEnabled();
    await toggle.click();
    await expect.poll(()=>fixture.draft.enable_context_manager).toBe(cm);
    await page.reload();
    await expect(page.getByText(label("agent.core.label"),{exact:true})).toBeAttached();
    if (!(await page.getByText(label("agent.core.label"),{exact:true}).isVisible())) {
      await page.getByText(label("agent.highFidelity.advancedTitle"),{exact:true}).click();
    }
    await expect(page.getByRole("switch",{name:label("agent.core.contextManager")})).toHaveAttribute("aria-checked",String(cm));
  };
  await contract.precondition(contract.expectedIds("preconditions")[0],async()=>{
    expect((await page.request.get(baseUrl)).ok()).toBe(true);
  });
  const steps=contract.expectedIds("steps");
  await contract.step(steps[0],async()=>{
    await openOld();
    expect(runs).toHaveLength(0);
    await configure("Jiuwen",true);
    await openOld();
    expect(runs).toHaveLength(0);
  });
  await contract.step(steps[1],async()=>{
    await page.getByRole("textbox").fill("RECALL_CURRENT_ONLY");
    await page.getByRole("button",{name:"发送",exact:true}).click();
    await expect(page.getByText("CONTINUED_ALPHA",{exact:false}).first()).toBeVisible();
    expect(runs).toHaveLength(1);
    expect(runs[0].core).toBe("jiuwen");
    expect(runs[0].cm).toBe(true);
    expect(runs[0].request.conversation_id).toBe(101);
    expect(runs[0].request.agent_core).toBeUndefined();
    await configure("smolagents",false);
    await openOld();
    await expect(page.getByText("CONTINUED_ALPHA",{exact:false}).first()).toBeVisible();
    expect(runs).toHaveLength(1);
    await page.getByRole("textbox").fill("RECALL_BACK_ONLY");
    await page.getByRole("button",{name:"发送",exact:true}).click();
    await expect(page.getByText("CONTINUED_BACK_ALPHA",{exact:false}).first()).toBeVisible();
    expect(runs).toHaveLength(2);
    expect(runs[1].core).toBe("smolagents");
    expect(runs[1].cm).toBe(false);
    expect(runs[1].request.conversation_id).toBe(101);
  });
  const assertions=contract.expectedIds("assertions");
  await contract.assertion(assertions[0],async()=>{
    expect(messages[0].message).toBe("Analyze the original file");
    expect(JSON.stringify(messages[1])).toContain("old-call");
    expect(fixture.updates.some(value=>value.agent_core==="jiuwen")).toBe(true);
  });
  await contract.assertion(assertions[1],async()=>{
    expect(runs.map(value=>value.request.query)).toEqual(["RECALL_CURRENT_ONLY","RECALL_BACK_ONLY"]);
    expect(fixture.unexpectedWrites).toEqual([]);
  });
});
