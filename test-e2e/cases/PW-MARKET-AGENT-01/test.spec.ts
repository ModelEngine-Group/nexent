// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

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
  let reviewId = "";
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
      async () => { const author=setting("NEXENT_TEST_MARKET_AUTHOR", "tenant_a_dev"); await loginCurrent(page, author); await agents.open(); agentId = await agents.create(name, `market_${token}`); const modelName=configuredModel("llm").displayName; await agents.selectModel(modelName); await agents.setDescription(`market ${token}`); await agents.setPrompts({ duty: `可靠完成任务并保留请求的固定标记 ${token}` }); await agents.publishVersion(versionName, `D4 market ${token}`); await page.goto(appPath("/agents"),{waitUntil:"domcontentloaded"}); await expect(page.getByRole("button", { name, exact: true })).toBeVisible(); return `author ${author} prepared published run-scoped Agent ${name} version ${versionName} with exact configured LLM ${modelName}`; },
      async () => `tenant administrator reviewer uses ${setting("NEXENT_TEST_MARKET_ADMIN", "tenant_a_admin")}`,
      async () => "same-tenant consumer with Repository access uses tenant_a_admin, distinct from tenant_a_dev author",
    ],
    steps: [
      async () => { const card = page.getByRole("button", { name, exact: true }).locator(".."); await card.getByRole("button", { name: "更多操作", exact: true }).click(); await page.getByRole("menuitem", { name: "申请上架", exact: true }).click(); const dialog = page.getByRole("dialog", { name: "申请上架" }); await dialog.locator("textarea").fill(`Owned market listing ${token}`); await dialog.getByRole("button",{name:"编辑标签",exact:true}).click(); const tagsDialog=page.getByRole("dialog",{name:"编辑标签",exact:true}); const libraries = await page.request.get("/api/tag-libraries"); expect(libraries.ok()).toBe(true);
        const library = (await libraries.json()).find((item:any)=>item.bucket_key==="default_resource"&&item.status==="active");
        expect(library).toBeTruthy();
        const definitions = await page.request.get(`/api/tag-libraries/${library.bucket_id}/definitions`); expect(definitions.ok()).toBe(true);
        const definition = (await definitions.json()).find((item:any)=>item.definition_key==="agent_category"&&item.status==="active");
        expect(definition).toBeTruthy();
        const value = definition.values.find((item:any)=>item.status==="active"); expect(value).toBeTruthy();
        const labels = JSON.parse(readFileSync(join(process.env.NEXENT_REPO || ".", "frontend/public/locales/zh/common.json"),"utf8"));
        const categoryLabel = labels["tagManagement.systemDefinition.agentCategory"] || definition.definition_name;
        const valueLabel = labels[`agentRepository.tag.${value.normalized_value}`] || value.display_value;
        await tagsDialog.getByRole("searchbox", { name: "搜索标签名称、标识或显示值", exact: true }).fill(categoryLabel);
        await tagsDialog.getByRole("button",{name:categoryLabel,exact:true}).click();
        const selector = tagsDialog.getByRole("combobox"); await selector.click();
        const popup = page.locator(".ant-select-dropdown:visible");
        const active = popup.locator(".ant-select-item-option-active .ant-select-item-option-content");
        await selector.press("Home");
        for(let index=0; index<=await popup.locator(".ant-select-item-option").count(); index++){
          if((await active.textContent())?.trim()===valueLabel) break;
          await selector.press("ArrowDown");
        }
        await expect(active).toHaveText(valueLabel); await selector.press("Enter"); await page.keyboard.press("Escape"); await tagsDialog.getByRole("button",{name:/保\s*存/}).click(); await expect(tagsDialog).toBeHidden(); const submitted=page.waitForResponse((r)=>r.request().method()==="POST"&&/\/api\/reviews$/.test(new URL(r.url()).pathname)); await dialog.getByRole("button", { name: "提交申请", exact: true }).click(); const response=await submitted; if(!response.ok()) throw new Error("Agent listing application failed"); const review=await response.json(); reviewId=String(review?.review_id||review?.data?.review_id||""); return `author applied published version ${versionName} from the agent management card menu with explicit tag through POST /api/reviews`; },
      async () => { const card = page.getByRole("button", { name, exact: true }).locator(".."); await card.getByRole("button", { name: "更多操作", exact: true }).click(); await page.getByRole("menuitem", { name: "审核中心", exact: true }).click({ timeout: 120_000 }); if (reviewId) await expect(page).toHaveURL(new RegExp(`review_id=${reviewId}`)); const detail=page.locator('[role="dialog"]:visible').filter({ hasText: name }); await expect(detail).toBeVisible({ timeout: 120_000 }); await expect(detail).toContainText("待审核"); return "author confirmed the application entered pending review from the review detail the card menu links to"; },
      async () => { const admin = await loginIsolated(page, setting("NEXENT_TEST_MARKET_ADMIN", "tenant_a_admin")); adminContext=admin.context; await admin.page.goto(appPath("/resource-space?tab=review"),{waitUntil:"domcontentloaded"}); const row=admin.page.locator(".resource-review-table tbody tr").filter({ hasText: name }); await expect(row).toBeVisible({ timeout: 120_000 }); const decided=admin.page.waitForResponse((r)=>r.request().method()==="POST"&&/\/api\/reviews\/[^/]+\/decision$/.test(new URL(r.url()).pathname)); await row.getByRole("button",{name:"通过",exact:true}).click(); const confirm=admin.page.locator('[role="dialog"]:visible').filter({ hasText: "确定通过审核" }); await expect(confirm).toBeVisible(); await confirm.getByRole("button",{name:"确定",exact:true}).click(); const decisionResponse=await decided; if(!decisionResponse.ok()) throw new Error(`Agent approval returned ${decisionResponse.status()}`); await expect(confirm).toBeHidden(); return "tenant administrator approved from the unified review center and the decision POST completed"; },
      async () => { const consumer=await loginIsolated(page, "tenant_a_admin"); consumerContext=consumer.context; const before=await consumer.page.request.get("/api/agent/list"); expect(before.ok()).toBe(true); consumerAgentIdsBefore=new Set((await before.json()).map((row:any)=>Number(row.agent_id))); await consumer.page.goto(appPath("/resource-space?tab=agent"),{waitUntil:"domcontentloaded"}); await consumer.page.getByPlaceholder("搜索 Agent 名称、描述或标签",{exact:true}).fill(name); await expect(consumer.page.getByRole("heading",{name,exact:true})).toBeVisible({timeout:120_000}); return "same-tenant consumer with Repository access found the approved Agent and captured its pre-copy Agent IDs"; },
      async () => {
        const p=consumerContext!.pages()[0];
        const card=p.getByRole("heading",{name,exact:true}).locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' group ')][1]");
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
        await new AgentPage(p).openSection("基础信息");
        await expect(p.getByRole("textbox", { name: "智能体描述", exact: true })).toHaveValue(`market ${token}`,{timeout:120_000});
        return `consumer received and opened editable tenant-local copy id=${consumerAgentId}`;
      },
      async () => {
        await new AgentPage(consumerContext!.pages()[0]).delete(consumerAgentId);
        await page.goto(appPath("/resource-space?tab=agent"),{waitUntil:"domcontentloaded"});
        await page.getByPlaceholder("搜索 Agent 名称、描述或标签",{exact:true}).fill(name);
        const heading=page.getByRole("heading",{name,exact:true});
        await expect(heading).toBeVisible({timeout:120_000});
        const card=heading.locator("xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' group ')][1]");
        await card.getByRole("button",{name:"下架",exact:true}).click();
        const confirm=page.locator('[role="dialog"]:visible').filter({hasText:"确认下架"});
        await expect(confirm).toBeVisible();
        const down=page.waitForResponse((r)=>r.request().method()==="PATCH"&&/\/api\/repository\/agent\/\d+\/status$/.test(new URL(r.url()).pathname)&&r.request().postDataJSON()?.status==="not_shared");
        await confirm.getByRole("button",{name:"下架",exact:true}).click();
        expect((await down).ok()).toBe(true);
        await expect(heading).toHaveCount(0,{timeout:120_000});
        await agents.delete(agentId);
        return "the developer took down their own listing using the card icon and the listing disappeared";
      },
    ],
    assertions: [
      async () => { expect(adminContext).toBeTruthy(); return "Review action used the admin identity"; },
      async () => "approval made the listing discoverable in the repository tab of the unified resource repository",
      async () => { expect(consumerAgentId).toBeGreaterThan(0); expect(consumerAgentId).not.toBe(agentId); const p=consumerContext!.pages()[0]; const listed=await p.request.get("/api/agent/list"); expect(listed.ok()).toBe(true); const rows=await listed.json(); expect(rows.some((row:any)=>Number(row.agent_id)===consumerAgentId)).toBe(false); return "the captured copy belonged to the consumer context and its ID disappeared from the authoritative Agent list after cleanup"; },
    ],
  });
});
