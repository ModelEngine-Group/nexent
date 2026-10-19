import { journey } from "../../infra/automation/d4/runner/journey";
import { baseUrl, installEditor } from "../../infra/automation/d4/fixtures/agent-editor-workflows";
import { join } from "node:path";

journey("JIUWEN-OUTPUT-D4-001", async ({page,contract,expect})=>{
  const fixture=await installEditor(page);
  Object.assign(fixture.draft,{agent_core:"jiuwen",enable_context_manager:true});
  const messages:any[]=[{role:"user",message_id:1,message_index:1,status:"completed",message:"Old task"},
    {role:"assistant",message_id:2,message_index:2,status:"completed",message:[{type:"model_output_thinking",content:"LEGACY_PROCESS",unit_index:0},{type:"tool",content:"",tool_name:"legacy_tool",tool_arguments:{value:1},tool_call_id:"legacy-call",unit_index:1},{type:"execution_logs",content:"LEGACY_RESULT",tool_call_id:"legacy-call",unit_index:2},{type:"final_answer",content:"LEGACY_ANSWER",unit_index:3}]}];
  const events:any[]=[];
  const seq:Record<string,number>={};
  const add=(type:string,content:string,extra:Record<string,unknown>={})=>{
    const turn=String(extra.turn_id || "root");
    const event={schema_version:1,runtime_mode:"native_agent",agent_core:"jiuwen",type,content,turn_id:turn,sequence:seq[turn]=(seq[turn]||0)+1,...extra};
    events.push(event);return event;
  };
  add("model_output","INTERMEDIATE_ONE",{block_id:"one",phase:"partial"});
  add("model_output_deep_thinking","EXPLICIT_REASONING",{block_id:"one",phase:"partial"});
  add("model_output","INTERMEDIATE_TWO",{block_id:"two",phase:"partial"});
  add("step_observation","",{block_id:"one",step_number:1,duration:.2,usage:{origin:"unknown",input_tokens:null,output_tokens:null}});
  for(const [name,result] of [["local_tool","LOCAL_RESULT"],["mcp_tool","MCP_RESULT"],["run_skill_script","SKILL_RESULT"]]){
    add("tool","",{tool_name:name,tool_arguments:{value:1},local_call_id:name,provider_call_id:"provider_"+name});
    add("tool_result",result,{local_call_id:name,provider_call_id:"provider_"+name,result,is_error:false});
  }
  add("tool","",{tool_name:"failing_tool",tool_arguments:{},local_call_id:"error-call"});
  add("tool_result","RECOVERABLE_ERROR",{local_call_id:"error-call",result:"RECOVERABLE_ERROR",is_error:true});
  for(const [id,name,result] of [["child","Child agent","CHILD_ANSWER"],["remote","A2A agent","A2A_RESULT"]]){
    events.push({type:"subagent_start",invocation_id:id,content:JSON.stringify({invocation_id:id,agent_name:name,task:"Subtask"})});
    if(id==="child"){
      add("model_output",result,{turn_id:id,invocation_id:id,block_id:id});
      add("run_terminal","",{turn_id:id,invocation_id:id,status:"completed",end_reason:"runner_answer",final_content:result,final_block_ids:[id]});
    }else events.push({type:"final_answer",invocation_id:id,content:result});
    events.push({type:"subagent_end",invocation_id:id,content:JSON.stringify({invocation_id:id})});
  }
  add("model_output","FINAL_ONCE",{block_id:"final"});
  events.push({type:"final_answer",content:"FINAL_ONCE"});
  add("run_terminal","",{status:"completed",end_reason:"runner_answer",final_content:"FINAL_ONCE",final_block_ids:["final"]});
  const addFault=(status:string)=>{
    messages.push({role:"user",message_id:messages.length+1,message_index:messages.length+1,status:"completed",message:"Fault "+status});
    const turn="fault-"+status;
    messages.push({role:"assistant",message_id:messages.length+1,message_index:messages.length+1,status,message:[
      {type:"model_output",content:JSON.stringify({schema_version:1,runtime_mode:"native_agent",agent_core:"jiuwen",turn_id:turn,sequence:1,type:"model_output",block_id:turn,content:"PARTIAL_"+status})},
      {type:"run_terminal",content:JSON.stringify({schema_version:1,runtime_mode:"native_agent",agent_core:"jiuwen",turn_id:turn,sequence:2,type:"run_terminal",status,end_reason:status,content:"",final_content:"",final_block_ids:[]})},
    ]});
  };
  let runs=0;
  await page.route("**/api/**",async route=>{
    const path=new URL(route.request().url()).pathname.replace(/^.*\/api/,"");
    const respond=(data:unknown)=>route.fulfill({status:200,contentType:"application/json",body:JSON.stringify(data)});
    if(path==="/memory/config/load")return respond({MEMORY_SWITCH:"N"});
    if(path==="/conversation/list")return respond({code:0,data:{items:[{conversation_id:101,conversation_title:"Output contract",agent_id:42,create_time:Date.now(),update_time:Date.now()}],metadata:{total:1,today:1,last_7_days:0,older:0}}});
    if(path==="/conversation/101")return respond({code:0,data:[{conversation_id:101,conversation_title:"Output contract",agent_id:42,chat_mode:"execution",create_time:Date.now(),runtime_metadata:{},runtime_metadata_version:0,message:messages}]});
    if(path==="/agent/run"){
      runs++;
      messages.push({role:"user",message_id:3,message_index:3,status:"completed",message:"Current task"});
      messages.push({role:"assistant",message_id:4,message_index:4,status:"completed",message:events.map((event,index)=>({...event,unit_index:index,content:event.runtime_mode?JSON.stringify(event):event.content}))});
      return route.fulfill({status:200,contentType:"text/event-stream",headers:{conversation_id:"101"},body:events.map(event=>`data: ${JSON.stringify(event)}\n\n`).join("")});
    }
    return route.fallback();
  });
  await contract.precondition(contract.expectedIds("preconditions")[0],async()=>{expect((await page.request.get(baseUrl)).ok()).toBe(true);});
  const openGroups=async(container:any)=>{
    for(const button of await container.getByRole("button",{name:/^\d+ (tool|subagent) calls?$/}).all())
      if(await button.getAttribute("data-state")==="closed")await button.click();
    for(const group of await container.locator("[data-subagent-run-id]").all()){
      const trigger=group.getByRole("button").first();
      if(await trigger.getAttribute("data-state")==="closed")await trigger.click();
    }
    const closed=container.locator('.aui-reasoning-root button[data-state="closed"]');
    for(let remaining=await closed.count();remaining>0;remaining--)await closed.first().click();
  };
  const messageFor=(text:string)=>page.locator('[data-slot="aui_assistant-message-root"]').filter({has:page.getByText(text,{exact:true})}).first();
  const verify=async()=>{
    const runtime=messageFor("FINAL_ONCE");
    await expect(page.locator("[data-runtime-output]")).toHaveCount(0);
    await expect(runtime.getByText("FINAL_ONCE",{exact:true})).toHaveCount(1);
    await openGroups(runtime);
    await expect(runtime.getByText(/INTERMEDIATE_ONE/).first()).toBeVisible();
    await expect(runtime.getByText(/EXPLICIT_REASONING/).first()).toBeVisible();
    await expect(runtime.getByText(/INTERMEDIATE_TWO/).first()).toBeVisible();
    await expect(runtime.getByText("CHILD_ANSWER",{exact:true})).toBeVisible();
    await expect(runtime.getByText("A2A_RESULT",{exact:true})).toBeVisible();
    await expect(runtime.locator('[data-token-usage="summary"]')).toContainText("输入 未知 / 输出 未知");
    for(const [name,result] of [["local_tool","LOCAL_RESULT"],["mcp_tool","MCP_RESULT"],["run_skill_script","SKILL_RESULT"]]){
      const button=runtime.getByRole("button",{name:`Used tool: ${name}`,exact:true});
      if(await button.getAttribute("data-state")==="closed")await button.click();
      await expect(runtime.getByText(result,{exact:true})).toBeVisible();
    }
    const errorButton=runtime.getByRole("button",{name:"Used tool: failing_tool",exact:true});
    if(await errorButton.getAttribute("data-state")==="closed")await errorButton.click();
    const errorTool=errorButton.locator("..");
    await expect(errorTool.getByText("Error:",{exact:true})).toBeVisible();
    await expect(errorTool.getByText("RECOVERABLE_ERROR",{exact:true}).first()).toBeVisible();
    const first=await runtime.getByText(/INTERMEDIATE_ONE/).first().boundingBox();
    const last=await runtime.getByText(/INTERMEDIATE_TWO/).first().boundingBox();
    expect(first!.y).toBeLessThan(last!.y);
    expect(await runtime.locator('.aui-reasoning-root').filter({hasText:"FINAL_ONCE"}).count()).toBe(0);
    const legacy=messageFor("LEGACY_ANSWER");
    await openGroups(legacy);
    await expect(legacy.locator('.aui-reasoning-root')).toHaveCount(1);
    await expect(legacy.getByRole("button",{name:"Used tool: legacy_tool",exact:true})).toBeVisible();
    await expect(runtime.locator('.aui-reasoning-root').first()).toBeVisible();
    return runtime;
  };
  const steps=contract.expectedIds("steps");
  await contract.step(steps[0],async()=>{
    await page.goto(`${baseUrl}/zh/newchat?thread_id=101`);
    await expect(page.getByText("LEGACY_ANSWER",{exact:true})).toBeVisible();
    await page.getByRole("textbox").fill("Current task");
    await page.getByRole("button",{name:"发送",exact:true}).click();
    await verify();
  });
  await contract.step(steps[1],async()=>{
    addFault("failed");addFault("stopped");
    messages.push({role:"user",message_id:messages.length+1,message_index:messages.length+1,status:"completed",message:"Simple task"});
    const simple={schema_version:1,runtime_mode:"native_agent",agent_core:"jiuwen",turn_id:"simple"};
    messages.push({role:"assistant",message_id:messages.length+1,message_index:messages.length+1,status:"completed",message:[
      {type:"model_output",content:JSON.stringify({...simple,type:"model_output",sequence:1,block_id:"simple",content:"SIMPLE_FINAL"})},
      {type:"step_observation",content:JSON.stringify({...simple,type:"step_observation",sequence:2,block_id:"simple",content:"",step_number:1,duration:.1})},
      {type:"run_terminal",content:JSON.stringify({...simple,type:"run_terminal",sequence:3,status:"completed",end_reason:"runner_answer",final_content:"SIMPLE_FINAL",final_block_ids:["simple"],content:""})},
    ]});
    messages.push({role:"user",message_id:messages.length+1,message_index:messages.length+1,status:"completed",message:"No usage task"});
    const noUsage={schema_version:1,runtime_mode:"native_agent",agent_core:"jiuwen",turn_id:"no-usage"};
    messages.push({role:"assistant",message_id:messages.length+1,message_index:messages.length+1,status:"completed",message:[
      {type:"model_output",content:JSON.stringify({...noUsage,type:"model_output",sequence:1,block_id:"no-usage",content:"NO_USAGE_FINAL"})},
      {type:"run_terminal",content:JSON.stringify({...noUsage,type:"run_terminal",sequence:2,status:"completed",final_content:"NO_USAGE_FINAL",final_block_ids:["no-usage"],content:""})},
    ]});
    messages.push({role:"user",message_id:messages.length+1,message_index:messages.length+1,status:"completed",message:"Mixed Core task"});
    const childEnvelope={schema_version:1,runtime_mode:"native_agent",agent_core:"jiuwen",turn_id:"mixed-child",invocation_id:"mixed-child"};
    messages.push({role:"assistant",message_id:messages.length+1,message_index:messages.length+1,status:"completed",message:[
      {type:"model_output_thinking",content:"LEGACY_BEFORE_CHILD"},
      {type:"subagent_start",invocation_id:"mixed-child",content:JSON.stringify({invocation_id:"mixed-child",agent_name:"Native failing child",agent_id:99,task:"Child task"})},
      {type:"model_output",invocation_id:"mixed-child",content:JSON.stringify({...childEnvelope,type:"model_output",sequence:1,block_id:"mixed-partial",content:"CHILD_PARTIAL_FAILED"})},
      {type:"run_terminal",invocation_id:"mixed-child",content:JSON.stringify({...childEnvelope,type:"run_terminal",sequence:2,status:"failed",end_reason:"MODEL_STREAM_INCOMPLETE",final_content:"",final_block_ids:[],content:""})},
      {type:"subagent_end",invocation_id:"mixed-child",content:JSON.stringify({invocation_id:"mixed-child"})},
      {type:"final_answer",content:"CODE_PARENT_FINAL"},
    ]});
    fixture.draft.agent_core="smolagents";
    await page.reload();await verify();
    await openGroups(page.locator('[data-slot="aui_assistant-message-root"]'));
    for(const partial of ["PARTIAL_failed","PARTIAL_stopped"]){
      const process=page.locator('[data-slot="aui_assistant-message-root"]').filter({hasText:partial}).first();
      await openGroups(process);
      await expect(process.getByText(partial,{exact:true})).toBeVisible();
      await expect(process.locator('[data-slot="aui_assistant-message-completion-indicator"]')).toHaveCount(0);
    }
    await expect(page.getByText("LEGACY_ANSWER",{exact:true})).toBeVisible();
    const simpleMessage=messageFor("SIMPLE_FINAL");
    await expect(simpleMessage.locator(".aui-reasoning-root")).toHaveCount(0);
    await expect(simpleMessage.locator('[data-token-usage="summary"]')).toContainText("输入 未知 / 输出 未知");
    await expect(simpleMessage.getByText("SIMPLE_FINAL",{exact:true})).toHaveCount(1);
    const noUsageMessage=messageFor("NO_USAGE_FINAL");
    await expect(noUsageMessage.locator('[data-token-usage="summary"]')).toHaveCount(0);
    await expect(noUsageMessage.locator(".aui-reasoning-root")).toHaveCount(0);
    await expect(page.getByText("CODE_PARENT_FINAL",{exact:true})).toBeVisible();
    const mixedTrigger=page.getByRole("button",{name:"1 subagent call",exact:true});
    if(await mixedTrigger.getAttribute("data-state")==="closed")await mixedTrigger.click();
    const childGroup=page.locator("[data-subagent-run-id]").filter({hasText:"Native failing child"});
    if(await childGroup.getByRole("button").first().getAttribute("data-state")==="closed")await childGroup.getByRole("button").first().click();
    await openGroups(childGroup);
    await expect(childGroup.getByText("CHILD_PARTIAL_FAILED",{exact:true})).toBeVisible();
    await expect(childGroup.getByText("执行失败",{exact:true}).first()).toBeVisible();
    await expect(childGroup.getByText("Completed",{exact:true})).toHaveCount(0);
    await page.screenshot({path:join(contract.caseDir,"runtime-output.png"),fullPage:true});
  });
  const assertions=contract.expectedIds("assertions");
  await contract.assertion(assertions[0],async()=>{expect(runs).toBe(1);expect(fixture.unexpectedWrites).toEqual([]);});
  await contract.assertion(assertions[1],async()=>{await expect(page.getByText("FINAL_ONCE",{exact:true})).toHaveCount(1);});
});
