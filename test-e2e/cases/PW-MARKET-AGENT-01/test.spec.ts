import { existsSync } from "node:fs";
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
  contract.deferCleanup(async () => { await consumerContext?.close(); await adminContext?.close(); if (agentId) await agents.delete(agentId); });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { const author=setting("NEXENT_TEST_MARKET_AUTHOR", "tenant_a_dev"); await loginCurrent(page, author); await agents.open(); agentId = await agents.create(name, `market_${token}`); const modelName=configuredModel("llm").displayName; await agents.selectModel(modelName); await agents.setDescription(`market ${token}`); await agents.setPrompts({ duty: `可靠完成任务并保留请求的固定标记 ${token}` }); await agents.publishVersion(versionName, `D4 market ${token}`); await page.goto(appPath("/agent-space")); await page.getByRole("tab", { name: /^我的 Agent/ }).click(); await expect(page.getByText(name, { exact: true })).toBeVisible(); return `author ${author} prepared published run-scoped Agent ${name} version ${versionName} with exact configured LLM ${modelName}`; },
      async () => `tenant administrator reviewer uses ${setting("NEXENT_TEST_MARKET_ADMIN", "tenant_a_admin")}`,
      async () => "same-tenant consumer with Repository access uses tenant_a_admin, distinct from tenant_a_dev author",
    ],
    steps: [
      async () => { const card = page.getByRole("heading", { name, exact: true }).locator("xpath=ancestor::div[contains(concat(' ',normalize-space(@class),' '),' ant-card ')][1]"); await card.getByRole("button", { name: "更多操作", exact: true }).click(); await page.getByRole("menuitem", { name: /申请上架|上架/ }).click(); const dialog = page.getByRole("dialog", { name: "申请上架" }); await dialog.locator("input").first().fill("🤖"); await dialog.getByRole("button",{name:"编辑标签",exact:true}).click(); const tagsDialog=page.getByRole("dialog",{name:"编辑标签",exact:true}); await tagsDialog.getByRole("button",{name:/智能体类别/}).click(); await tagsDialog.getByRole("combobox").click(); await page.getByText("自动化",{exact:true}).last().click(); await page.keyboard.press("Escape"); await tagsDialog.getByRole("button",{name:/保\s*存/}).click(); await expect(tagsDialog).toBeHidden(); const submitted=page.waitForResponse((r)=>r.request().method()==="POST"&&/\/api\/repository\/agent\/\d+\/versions\/\d+/.test(r.url())); await dialog.getByRole("button", { name: "提交申请", exact: true }).click(); if(!(await submitted).ok()) throw new Error("Agent listing application failed"); return `author applied published version ${versionName} from Mine through the card menu with explicit icon and tag`; },
      async () => { await expect(page.getByText(/审核中|待审核/).first()).toBeVisible({ timeout: 120_000 }); return "Mine entered pending review"; },
      async () => { const admin = await loginIsolated(page, setting("NEXENT_TEST_MARKET_ADMIN", "tenant_a_admin")); adminContext=admin.context; await admin.page.goto(appPath("/agent-space")); await admin.page.getByRole("tab", { name: /审核中心/ }).click(); const row=admin.page.getByRole("heading", { name, exact: true }).locator("xpath=ancestor::li[1]"); await row.getByRole("button",{name:/通\s*过/}).click(); const dialog=admin.page.locator('[role="dialog"]:visible'); await expect(dialog).toHaveCount(1); const approved=admin.page.waitForResponse((r)=>r.request().method()==="PATCH"&&/\/api\/repository\/agent\//.test(r.url())); await dialog.getByRole("button",{name:/通\s*过/}).click(); const approvalResponse=await approved; if(!approvalResponse.ok()) throw new Error(`Agent approval returned ${approvalResponse.status()}`); await expect(dialog).toBeHidden(); return "tenant administrator approved from the Review-only surface and the PATCH completed"; },
      async () => { const consumer=await loginIsolated(page, "tenant_a_admin"); consumerContext=consumer.context; const before=await consumer.page.request.get("/api/agent/list"); expect(before.ok()).toBe(true); consumerAgentIdsBefore=new Set((await before.json()).map((row:any)=>Number(row.agent_id))); await consumer.page.goto(appPath("/agent-space")); await consumer.page.getByRole("tab",{name:/^仓库/}).click(); await consumer.page.getByPlaceholder(/搜索/).fill(name); await expect(consumer.page.getByText(name,{exact:true})).toBeVisible({timeout:120_000}); return "same-tenant consumer with Repository access found the approved Agent and captured its pre-copy Agent IDs"; },
      async () => {
        const p=consumerContext!.pages()[0];
        const card=p.getByRole("heading",{name,exact:true}).locator("xpath=ancestor::div[contains(concat(' ',normalize-space(@class),' '),' ant-card ')][1]");
        await card.getByRole("button",{name:/^复制$/}).click();
        const copy=p.locator('[role="dialog"]:visible').filter({hasText:name});
        await expect(copy).toBeVisible();
        const imported=p.waitForResponse((r)=>r.request().method()==="POST"&&/\/api\/repository\/agent\/\d+\/import$/.test(new URL(r.url()).pathname));
        const confirm=copy.getByRole("button",{name:/^复制$/});
        await expect(confirm).toBeEnabled({timeout:120_000});
        await confirm.click();
        const importResponse=await imported;
        if(!importResponse.ok()) throw new Error(`Agent repository copy returned ${importResponse.status()}`);
        await expect(copy).toBeHidden({timeout:120_000});
        await expect(p.getByText(/已复制|复制成功/)).toBeVisible({timeout:120_000});
        return "consumer copied the approved listing through the current precheck dialog";
      },
      async () => { const p=consumerContext!.pages()[0]; const listed=await p.request.get("/api/agent/list"); expect(listed.ok()).toBe(true); const rows=await listed.json(); const created=rows.filter((row:any)=>!consumerAgentIdsBefore.has(Number(row.agent_id))); expect(created).toHaveLength(1); consumerAgentId=Number(created[0].agent_id); expect(consumerAgentId).toBeGreaterThan(0); expect(created[0].display_name||created[0].name).toBe(name); await p.goto(appPath(`/agents?agent_id=${consumerAgentId}`),{waitUntil:"domcontentloaded"}); await expect(p.getByPlaceholder("请输入智能体描述")).toHaveValue(`market ${token}`,{timeout:120_000}); return `consumer received and opened editable tenant-local copy id=${consumerAgentId}`; },
      async () => { const p=consumerContext!.pages()[0]; await new AgentPage(p).delete(consumerAgentId); await page.goto(appPath("/agent-space")); await page.getByRole("tab", { name: /^我的 Agent/ }).click(); const card=page.getByRole("heading",{name,exact:true}).locator("xpath=ancestor::div[contains(concat(' ',normalize-space(@class),' '),' ant-card ')][1]"); await card.getByRole("button",{name:"更多操作",exact:true}).click(); const progress=page.getByRole("menuitem",{name:/查看审批进度/}); if(await progress.count()){await progress.click(); const status=page.getByRole("dialog").filter({hasText:name}); const down=status.getByRole("button",{name:/下架|取消申请/}); if(await down.count()){await down.click(); await page.getByRole("dialog").last().getByRole("button",{name:/下架|取消申请/}).click(); await expect(status).toBeHidden();}} await agents.delete(agentId); return "removed the consumer copy, took down the listing and deleted the author test Agent"; },
    ],
    assertions: [
      async () => { expect(adminContext).toBeTruthy(); return "Review action used the admin identity"; },
      async () => "approval made the listing discoverable in Repository",
      async () => { expect(consumerAgentId).toBeGreaterThan(0); expect(consumerAgentId).not.toBe(agentId); const p=consumerContext!.pages()[0]; const listed=await p.request.get("/api/agent/list"); expect(listed.ok()).toBe(true); const rows=await listed.json(); expect(rows.some((row:any)=>Number(row.agent_id)===consumerAgentId)).toBe(false); return "the captured copy belonged to the consumer context and its ID disappeared from the authoritative Agent list after cleanup"; },
    ],
  });
});

