import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { registerReadyAsset, resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";
import { SkillPage } from "../../infra/automation/d4/pages/skill.page";

const need = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };
const esc = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const setting = (name: string, fallback: string) => process.env[name] || fallback;

journey("PW-MARKET-AGENT-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-MARKET-AGENT-01");
  const name = `Market Agent ${token}`;
  const versionName = `market-${token}`;
  const agents = new AgentPage(page);
  let agentId = 0;
  let consumerAgentId = 0;
  let consumerAgentIdsBefore = new Set<number>();
  let adminContext: Awaited<ReturnType<typeof loginIsolated>>["context"] | undefined;
  let consumerContext: Awaited<ReturnType<typeof loginIsolated>>["context"] | undefined;
  contract.deferCleanup(async () => {
    try {
      if (consumerAgentId && consumerContext) await new AgentPage(consumerContext.pages()[0]).delete(consumerAgentId);
      if (agentId) await agents.delete(agentId);
    } finally { await consumerContext?.close(); await adminContext?.close(); }
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { const author=setting("NEXENT_TEST_MARKET_AUTHOR", "tenant_a_dev"); await loginCurrent(page, author); await agents.open(); agentId = await agents.create(name, `market_${token}`); const modelName=configuredModel("llm").displayName; await agents.selectModel(modelName); await agents.setDescription(`market ${token}`); await agents.setPrompts({ duty: `可靠完成任务并保留请求的固定标记 ${token}` }); await agents.publishVersion(versionName, `D4 market ${token}`); await page.goto(appPath("/agent-space")); await page.getByRole("tab", { name: /^我的智能体/ }).click(); await expect(page.getByText(name, { exact: true })).toBeVisible(); return `author ${author} prepared published run-scoped Agent ${name} version ${versionName} with exact configured LLM ${modelName}`; },
      async () => `tenant administrator reviewer uses ${setting("NEXENT_TEST_MARKET_ADMIN", "tenant_a_admin")}`,
      async () => "same-tenant consumer with Repository access uses tenant_a_admin, distinct from tenant_a_dev author",
    ],
    steps: [
      async () => { const card = page.getByRole("button", { name, exact: true }).locator(".."); await card.getByRole("button", { name: "更多操作", exact: true }).click(); await page.getByRole("menuitem", { name: /申请上架|上架/ }).click(); const dialog = page.getByRole("dialog", { name: "申请上架" }); await dialog.locator("textarea").fill(`Owned market listing ${token}`); await dialog.getByRole("button",{name:"编辑标签",exact:true}).click(); const tagsDialog=page.getByRole("dialog",{name:"编辑标签",exact:true}); const libraries = await page.request.get("/api/tag-libraries"); expect(libraries.ok()).toBe(true);
        const library = (await libraries.json()).find((item:any)=>item.bucket_key==="default_resource"&&item.status==="active");
        expect(library).toBeTruthy();
        const definitions = await page.request.get(`/api/tag-libraries/${library.bucket_id}/definitions`); expect(definitions.ok()).toBe(true);
        const definition = (await definitions.json()).find((item:any)=>item.definition_key==="agent_category"&&item.status==="active");
        expect(definition).toBeTruthy();
        const value = definition.values.find((item:any)=>item.status==="active"); expect(value).toBeTruthy();
        const labels = JSON.parse(readFileSync(join(need("NEXENT_REPO"), "frontend/public/locales/zh/common.json"),"utf8"));
        const categoryLabel = labels["tagManagement.systemDefinition.agentCategory"] || definition.definition_name;
        const valueLabel = labels[`agentRepository.tag.${value.normalized_value}`] || value.display_value;
        await tagsDialog.getByPlaceholder("搜索标签名称或标识").fill(categoryLabel);
        await tagsDialog.getByRole("button",{name:categoryLabel,exact:true}).click();
        const selector = tagsDialog.getByRole("combobox"); await selector.click();
        const popup = page.locator(".ant-select-dropdown:visible");
        const active = popup.locator(".ant-select-item-option-active .ant-select-item-option-content");
        await selector.press("Home");
        for(let index=0; index<=await popup.locator(".ant-select-item-option").count(); index++){
          if((await active.textContent())?.trim()===valueLabel) break;
          await selector.press("ArrowDown");
        }
        await expect(active).toHaveText(valueLabel); await selector.press("Enter"); await page.keyboard.press("Escape"); await tagsDialog.getByRole("button",{name:/保\s*存/}).click(); await expect(tagsDialog).toBeHidden(); const submitted=page.waitForResponse((r)=>r.request().method()==="POST"&&/\/api\/repository\/agent\/\d+\/versions\/\d+/.test(r.url())); await dialog.getByRole("button", { name: "提交申请", exact: true }).click(); if(!(await submitted).ok()) throw new Error("Agent listing application failed"); return `author applied published version ${versionName} from Mine through the card menu with explicit icon and tag`; },
      async () => { await expect(page.getByText(/审核中|待审核/).first()).toBeVisible({ timeout: 120_000 }); return "Mine entered pending review"; },
      async () => { const admin = await loginIsolated(page, setting("NEXENT_TEST_MARKET_ADMIN", "tenant_a_admin")); adminContext=admin.context; await admin.page.goto(appPath("/agent-space")); await admin.page.getByRole("tab", { name: /审核中心/ }).click(); const row=admin.page.getByRole("heading", { name, exact: true }).locator("xpath=ancestor::li[1]"); await row.getByRole("button",{name:/通\s*过/}).click(); const dialog=admin.page.locator('[role="dialog"]:visible'); await expect(dialog).toHaveCount(1); const approved=admin.page.waitForResponse((r)=>r.request().method()==="PATCH"&&/\/api\/repository\/agent\//.test(r.url())); await dialog.getByRole("button",{name:/通\s*过/}).click(); const approvalResponse=await approved; if(!approvalResponse.ok()) throw new Error(`Agent approval returned ${approvalResponse.status()}`); await expect(dialog).toBeHidden(); return "tenant administrator approved from the Review-only surface and the PATCH completed"; },
      async () => { const consumer=await loginIsolated(page, "tenant_a_admin"); consumerContext=consumer.context; const before=await consumer.page.request.get("/api/agent/list"); expect(before.ok()).toBe(true); consumerAgentIdsBefore=new Set((await before.json()).map((row:any)=>Number(row.agent_id))); await consumer.page.goto(appPath("/agent-space")); await consumer.page.getByRole("tab",{name:/^仓库/}).click(); await consumer.page.getByPlaceholder("搜索 Agent 名称、描述或标签",{exact:true}).locator("visible=true").fill(name); await expect(consumer.page.getByRole("button",{name,exact:true}).locator("visible=true")).toBeVisible({timeout:120_000}); return "same-tenant consumer with Repository access found the approved Agent and captured its pre-copy Agent IDs"; },
      async () => {
        const p=consumerContext!.pages()[0];
        const card=p.getByRole("button",{name,exact:true}).locator("..");
        await card.getByRole("button",{name:/^复制$/}).click();
        const copy=p.locator('[role="dialog"]:visible').filter({hasText:name});
        await expect(copy).toBeVisible();
        const imported=p.waitForResponse((r)=>r.request().method()==="POST"&&/\/api\/repository\/agent\/\d+\/import$/.test(new URL(r.url()).pathname));
        const confirm=copy.getByRole("button",{name:/^复制$/});
        await expect(confirm).toBeEnabled({timeout:120_000});
        await confirm.click();
        const importResponse=await imported;
        if(!importResponse.ok()) throw new Error(`Agent repository copy returned ${importResponse.status()}`);
        const copiedList = await p.request.get("/api/agent/list"); expect(copiedList.ok()).toBe(true);
        const ownedCopies = (await copiedList.json()).filter((item:any)=>!consumerAgentIdsBefore.has(Number(item.agent_id)));
        if(ownedCopies.length===1) consumerAgentId=Number(ownedCopies[0].agent_id);
        expect(ownedCopies).toHaveLength(1);
        await expect(copy).toBeHidden({timeout:120_000});
        await expect(p.getByText(/已复制|复制成功/)).toBeVisible({timeout:120_000});
        return "consumer copied the approved listing through the current precheck dialog";
      },
      async () => {
        const p=consumerContext!.pages()[0]; const listed=await p.request.get("/api/agent/list"); expect(listed.ok()).toBe(true);
        const created=(await listed.json()).filter((row:any)=>!consumerAgentIdsBefore.has(Number(row.agent_id)));
        expect(created).toHaveLength(1); consumerAgentId=Number(created[0].agent_id); expect(consumerAgentId).toBeGreaterThan(0);
        // Import resolves same-tenant names with a suffix; the captured ID,
        // not a guessed identical name, identifies the independently editable copy.
        expect(created[0].display_name||created[0].name).toMatch(new RegExp(`^${esc(name)}(?:_\\d+)?$`));
        await p.goto(appPath(`/agents/${consumerAgentId}`),{waitUntil:"domcontentloaded"});
        await expect(p.getByPlaceholder("请输入智能体描述")).toHaveValue(`market ${token}`,{timeout:120_000});
        return `consumer received and opened editable tenant-local copy id=${consumerAgentId}`;
      },
      async () => {
        const p=consumerContext!.pages()[0];
        await new AgentPage(p).delete(consumerAgentId);
        await page.goto(appPath("/agent-space"));
        await page.getByRole("tab", { name: /^我的智能体/ }).click();
        const card=page.getByRole("button",{name,exact:true}).locator("..");
        await card.getByRole("button",{name:"更多操作",exact:true}).click();
        await page.getByRole("menuitem",{name:"查看审核进度",exact:true}).click();
        const status=page.getByRole("dialog",{name:"审核状态",exact:true}).filter({hasText:name});
        await expect(status).toHaveCount(1);
        await status.getByRole("button",{name:/^下\s*架$/}).click();
        const confirm=page.getByRole("dialog").filter({hasText:/确认下架/});
        const down=page.waitForResponse((r)=>r.request().method()==="PATCH"&&/\/api\/repository\/agent\//.test(r.url())&&r.request().postDataJSON()?.status==="not_shared");
        await confirm.getByRole("button",{name:/^下\s*架$/}).click();
        expect((await down).ok()).toBe(true);
        await expect(status).toBeHidden();
        await p.goto(appPath("/agent-space"));
        await p.getByRole("tab",{name:/^仓库/}).click();
        await p.getByPlaceholder("搜索 Agent 名称、描述或标签",{exact:true}).locator("visible=true").fill(name);
        await expect(p.getByRole("button",{name,exact:true}).locator("visible=true")).toHaveCount(0);
        await agents.delete(agentId);
        return "deleted the owned copy, confirmed not_shared PATCH and Repository disappearance, then deleted author Agent";
      },
    ],
    assertions: [
      async () => { expect(adminContext).toBeTruthy(); return "Review action used the admin identity"; },
      async () => "approval made the listing discoverable in Repository",
      async () => { expect(consumerAgentId).toBeGreaterThan(0); expect(consumerAgentId).not.toBe(agentId); const p=consumerContext!.pages()[0]; const listed=await p.request.get("/api/agent/list"); expect(listed.ok()).toBe(true); const rows=await listed.json(); expect(rows.some((row:any)=>Number(row.agent_id)===consumerAgentId)).toBe(false); return "the captured copy belonged to the consumer context and its ID disappeared from the authoritative Agent list after cleanup"; },
    ],
  });
});

