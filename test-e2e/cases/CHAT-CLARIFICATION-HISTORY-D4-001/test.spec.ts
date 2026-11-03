// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { expect, test } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { prepareWorkbench } from "../../infra/automation/d4/fixtures/workbench-controls";

test.use({ viewport: {width:1440,height:1100} });

const form = {schema_version:1, questions:[
  {id:"goal",type:"text",title:"Goal?",required:true},
  {id:"period",type:"single_choice",title:"Period?",required:true,options:[{id:"month",label:"This month"},{id:"year",label:"This year"}]},
  {id:"metrics",type:"multiple_choice",title:"Metrics?",required:true,allow_other:true,options:[{id:"sales",label:"Sales"},{id:"profit",label:"Profit"}]},
]};
const original = [
  {role:"user",message_id:1,message:"Analyze sales",status:"completed"},
  {role:"assistant",message_id:2,status:"completed",message:[{type:"human_interaction",unit_index:7,content:JSON.stringify(form)}]},
];

journey("CHAT-CLARIFICATION-HISTORY-D4-001", async ({page,contract}) => {
  page.on("pageerror", error => { throw error; });
  const rows = [123,124].map(id => ({conversation_id:id,conversation_title:`Clarification ${id}`,agent_id:7,create_time:Date.now(),update_time:Date.now()}));
  const requests: Array<Record<string,any>> = [];
  let saved = [...original];
  const json = (body:unknown) => ({status:200,contentType:"application/json",body:JSON.stringify(body)});
  await prepareWorkbench(page,1,{histories:rows});
  await page.route(/\/api\/conversation\/(123|124)$/, route => {
    const index = route.request().url().endsWith("123") ? 0 : 1;
    return route.fulfill(json({code:0,data:[{...rows[index],message:index === 0 ? saved : original}]}));
  });
  await page.route("**/api/agent/run", async route => {
    const body = route.request().postDataJSON();
    requests.push(body);
    if (requests.length === 1) return route.fulfill({status:200,headers:{"X-Stream-Status":"conflict"},contentType:"text/event-stream",body:""});
    saved = [...original,
      {role:"user",message_id:3,message:body.query,status:"completed",clarification_response:{...body.clarification_response,source_message_id:2}},
      {role:"assistant",message_id:4,status:"completed",message:[{type:"final_answer",content:"Analysis complete"}]},
    ] as typeof saved;
    return route.fulfill({status:200,headers:{conversation_id:"123"},contentType:"text/event-stream",body:'data: {"type":"final_answer","content":"Analysis complete","unit_index":0}\n\ndata: {"type":"complete","content":""}\n\n'});
  });
  const base = process.env.NEXENT_BASE_URL ?? "http://localhost:3100";
  const open = (id:number) => page.goto(`${base}/en/newchat?conversation_id=${id}`);
  const card = page.locator('[data-slot="clarification-message"]');
  const assertSaved = async () => {
    await expect(card.getByRole("textbox",{name:"Goal?"})).toHaveValue("Asia Pacific");
    await expect(card.getByRole("radio",{name:"This month"})).toBeChecked();
    await expect(card.getByRole("checkbox",{name:"Sales"})).toBeChecked();
    await expect(card.getByRole("checkbox",{name:"Profit"})).toBeChecked();
    await expect(card.getByRole("textbox",{name:"Other"})).toHaveValue("Compare last quarter");
    await expect(card.getByRole("button",{name:"Submitted",exact:true})).toBeDisabled();
    await expect(card.getByRole("textbox",{name:"Goal?"})).toBeDisabled();
  };
  for (const id of contract.expectedIds("preconditions")) await contract.precondition(id,async () => {
    await open(123);
    await expect(card).toBeVisible();
    expect(requests).toHaveLength(0);
  });
  await contract.step(contract.expectedIds("steps")[0],async () => {
    await card.getByRole("textbox",{name:"Goal?"}).fill("Asia Pacific");
    await card.getByRole("radio",{name:"This month"}).check();
    await card.getByRole("checkbox",{name:"Sales"}).check();
    await card.getByRole("checkbox",{name:"Profit"}).check();
    await card.getByRole("textbox",{name:"Other"}).fill("Compare last quarter");
    await card.getByRole("button",{name:"Submit and continue"}).click();
    await expect(card.getByRole("alert")).toBeVisible();
    await expect(card.getByRole("textbox",{name:"Goal?"})).toHaveValue("Asia Pacific");
    await expect(card.getByRole("button",{name:"Submit and continue"})).toBeEnabled();
    await card.getByRole("button",{name:"Submit and continue"}).click();
    await expect(page.getByText("Analysis complete",{exact:true})).toBeVisible();
    expect(requests).toHaveLength(2);
    expect(requests[1].query).toContain("Asia Pacific");
    expect(requests[1].query).toContain("This month");
    expect(requests[1].clarification_response).toMatchObject({schema_version:1,unit_index:7,answers:[
      {questionId:"goal",value:"Asia Pacific",otherText:null},
      {questionId:"period",value:"month",otherText:null},
      {questionId:"metrics",value:["sales","profit"],otherText:"Compare last quarter"},
    ]});
    await assertSaved();
  });
  await contract.step(contract.expectedIds("steps")[1],async () => {
    await page.reload();
    await assertSaved();
    await open(124);
    await expect(card.getByRole("textbox",{name:"Goal?"})).toHaveValue("");
    await open(123);
    await assertSaved();
    expect(requests).toHaveLength(2);
  });
  await contract.step(contract.expectedIds("steps")[2],async () => {
    await open(124);
    await expect(card.getByRole("textbox",{name:"Goal?"})).toHaveValue("");
    await expect(card.getByRole("radio",{name:"This month"})).not.toBeChecked();
    await expect(card.getByRole("checkbox",{name:"Sales"})).not.toBeChecked();
    await expect(card.getByRole("button",{name:"Submit and continue"})).toBeDisabled();
    await expect(card.getByRole("textbox",{name:"Goal?"})).toBeEditable();
  });
  for (const id of contract.expectedIds("assertions")) await contract.assertion(id,async () => {
    expect(requests).toHaveLength(2);
    expect(requests.every(request => request.conversation_id === 123)).toBe(true);
    expect((saved[2] as Record<string,any>).clarification_response.source_message_id).toBe(2);
    expect(requests[1].query).toContain("Compare last quarter");
  });
});
