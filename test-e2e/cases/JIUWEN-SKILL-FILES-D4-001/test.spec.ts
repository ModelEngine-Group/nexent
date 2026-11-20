// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { journey } from "../../infra/automation/d4/runner/journey";
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, unlinkSync, existsSync } from "node:fs";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

journey("JIUWEN-SKILL-FILES-D4-001", async ({ page, contract, expect }) => {
  const input = JSON.parse(readFileSync(process.env.NEXENT_SKILL_FILES_CONFIG!, "utf8"));
  const base = process.env.NEXENT_BASE_URL || "http://127.0.0.1:3000";
  const container = input.container || "nexent-runtime";
  const unique = randomUUID().replaceAll("-", "").slice(0, 12);
  const target = `/tmp/nexent_skill_files_${unique}`;
  const local = join(contract.caseDir, "private-state.json");
  const outcomes: any[] = [];
  let state: any;
  let runCount = 0;
  const docker = (...args: string[]) => {
    try { return execFileSync("docker", args, {encoding:"utf8",timeout:120000,stdio:["ignore","pipe","pipe"]}); }
    catch (error) { throw new Error(String((error as any).stdout || "").split(/\r?\n/).find(l=>l.startsWith("FIXTURE_FAILURE=")) || "Owned fixture command failed"); }
  };
  const fixture = (mode: string, ...args: string[]) => JSON.parse(docker("exec", "-e", "PYTHONPATH=/opt/backend",
    "-w", "/opt/backend", container, "/opt/backend/.venv/bin/python", target+".py", mode, target+".json", ...args).trim().split(/\r?\n/).at(-1)!);
  const save = () => writeFileSync(join(contract.caseDir,"real-outcomes.json"),JSON.stringify(outcomes,null,2));
  docker("cp", join(process.env.NEXENT_REPO!,"test-e2e/cases/JIUWEN-SKILL-FILES-D4-001/fixture.py"),container+":"+target+".py");
  contract.deferCleanup(async () => {
    try { if (!state?.cleaned) { const result=fixture("cleanup");outcomes.push(result);save();expect(result.source_unchanged).toBe(true); } }
    finally { if(existsSync(local))unlinkSync(local);docker("exec",container,"/opt/backend/.venv/bin/python","-c",`from pathlib import Path; Path('${target}.py').unlink(missing_ok=True)`); }
  });
  page.on("request",r=>{if(r.method()==="POST"&&new URL(r.url()).pathname==="/api/agent/run")runCount++;});
  await contract.precondition(contract.expectedIds("preconditions")[0],async()=>{
    const result=fixture("setup",String(input.source_agent_id),input.user_id);
    docker("cp",container+":"+target+".json",local);state=JSON.parse(readFileSync(local,"utf8"));
    await page.context().addCookies([
      {name:"nexent_access_token",value:state.access_token,url:base,httpOnly:true,sameSite:"Lax",expires:state.expires_at},
      {name:"nexent_token_expires_at",value:String(state.expires_at),url:base,sameSite:"Lax",expires:state.expires_at}]);
    outcomes.push(result);save();return "Authorized docx Skill source cloned with equivalent configuration.";
  });
  const roots=()=>page.locator('[data-slot="aui_assistant-message-root"]');
  const finals=(row:any)=>row.locator(".aui-md").evaluateAll((nodes:Element[])=>nodes
    .filter(n=>!n.closest(".aui-reasoning-root")&&!n.closest("[data-subagent-run-id]"))
    .map(n=>(n as HTMLElement).innerText));
  const send=async(query:string,model:number)=>{
    await page.getByRole("textbox").last().fill(query);
    const wire=page.waitForResponse(r=>r.request().method()==="POST"&&new URL(r.url()).pathname==="/api/agent/run");
    await page.getByRole("button",{name:"发送",exact:true}).click();
    const response=await wire;expect(response.status()).toBe(200);
    const request=response.request().postDataJSON();expect(request.agent_id).toBe(state.agent_id);
    expect(request.agent_core).toBeUndefined();expect(request.model_id).toBe(model);
    const conversation=request.conversation_id??Number(response.headers()["conversation_id"]);
    const events=(await response.body()).toString("utf8").split(/\r?\n/).filter(l=>l.startsWith("data:")).map(l=>JSON.parse(l.slice(5).trim()));
    expect(events.filter(e=>e.type==="error")).toEqual([]);
    const terminal=events.filter(e=>e.type==="run_terminal"&&!e.invocation_id);
    expect(terminal).toHaveLength(1);expect(terminal[0].status).toBe("completed");
    expect(terminal[0].final_content).not.toMatch(/completed_action_history|historical_attachments|<\/?final_answer\b/);
    await expect(roots().last().locator('[data-slot="aui_assistant-message-completion-indicator"]')).toBeVisible({timeout:30000});
    return {conversation,events,final:terminal[0].final_content};
  };
  const completed:any[]=[];
  const steps=contract.expectedIds("steps");
  await contract.step(steps[0],async()=>{expect(outcomes[0].docx_skill).toBe(true);expect(outcomes[0].equivalent_configuration).toBe(true);});
  await contract.step(steps[1],async()=>{
    for(const model of input.model_ids){
      fixture("select-model",String(model));
      await page.goto(`${base}/zh/newchat?agent_id=${state.agent_id}`);
      await expect(page.getByRole("textbox").last()).toBeVisible();
      const marker="SKILL_DOCX_"+unique+"_"+model;
      const generated=await send(`帮我随便生成一个docx文件，简单写点内容就行。文件名为 skill_${model}.docx，正文包含验收编号${marker}。请实际生成并上传，最终回复下载链接和编号。`,model);
      const calls=generated.events.filter(e=>e.type==="tool");
      expect(calls.some(e=>e.tool_name==="read_skill_md")).toBe(true);
      expect(calls.some(e=>e.tool_name==="nexent_execute_python")).toBe(true);
      expect(calls.filter(e=>e.tool_name==="download_from_s3")).toHaveLength(0);
      expect(generated.final).toContain(marker);expect(generated.final).toMatch(/s3:\/\/[^\s)]+\.docx/);
      expect(fixture("verify-docx",String(generated.conversation),marker).downloaded_docx_verified).toBe(true);
      let before:any;
      await expect.poll(()=>{before=fixture("check",String(generated.conversation));return before.messages.filter((m:any)=>m.role==="assistant"&&m.status==="completed").length;},{timeout:30000}).toBe(1);
      await page.goto(`${base}/zh/newchat?thread_id=${generated.conversation}`);
      await expect(roots()).toHaveCount(1);
      const follow=await send("只根据本会话已完成的任务，回复生成的文件名和验收编号。不要调用工具，不要重新生成或上传文件。",model);
      expect(follow.conversation).toBe(generated.conversation);expect(follow.final).toContain(marker);
      expect(follow.events.filter(e=>e.type==="tool")).toHaveLength(0);
      let after:any;
      await expect.poll(()=>{after=fixture("check",String(generated.conversation));return after.messages.filter((m:any)=>m.role==="assistant"&&m.status==="completed").length;},{timeout:30000}).toBe(2);
      expect(after.messages.slice(0,2)).toEqual(before.messages);
      completed.push({model,conversation:generated.conversation,marker,history:after.messages});
      outcomes.push({model,downloaded_docx_verified:true,no_skill_download:true,no_followup_replay:true,tool_names:calls.map(e=>e.tool_name)});save();
    }
  });
  await contract.step(steps[2],async()=>{
    for(const item of completed){
      const before=runCount;
      await page.goto(`${base}/zh/newchat?thread_id=${item.conversation}`);await expect(roots()).toHaveCount(2);
      for(const row of await roots().all()){
        await expect.poll(async()=> (await finals(row)).some((s:string)=>s.includes(item.marker))).toBe(true);
        const texts=await finals(row);expect(texts).toHaveLength(1);expect(texts[0]).toContain(item.marker);
        expect(texts[0]).not.toMatch(/completed_action_history|historical_attachments|<\/?final_answer\b/);
      }
      expect(runCount).toBe(before);expect(fixture("check",String(item.conversation)).messages).toEqual(item.history);
      await expect(page.locator("[data-runtime-output]")).toHaveCount(0);
    }
    outcomes.push({history_reload:true,no_run_on_load:true,common_renderer:true});save();
  });
  const assertions=contract.expectedIds("assertions");
  await contract.assertion(assertions[0],async()=>{expect(completed).toHaveLength(input.model_ids.length);});
  await contract.assertion(assertions[1],async()=>{expect(runCount).toBe(input.model_ids.length*2);expect(outcomes.at(-1).history_reload).toBe(true);});
  await contract.assertion(assertions[2],async()=>{const result=fixture("cleanup");expect(result.source_unchanged).toBe(true);outcomes.push(result);save();
    state.cleaned=true;});
});
