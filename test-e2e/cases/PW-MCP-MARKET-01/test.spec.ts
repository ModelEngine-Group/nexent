import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { registerReadyAsset } from "../../infra/automation/d4/runner/assets";
import { McpPage } from "../../infra/automation/d4/pages/mcp.page";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

const need = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };

journey("PW-MCP-MARKET-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-MCP-MARKET-01");
  const name = `mcp-market-${token}`.slice(0, 20);
  const installedName = `${name}-copy`;
  const remoteUrl = need("NEXENT_TEST_MCP_URL");
  const author = new McpPage(page);
  let adminContext: Awaited<ReturnType<typeof loginIsolated>>["context"] | undefined;
  let consumerContext: Awaited<ReturnType<typeof loginIsolated>>["context"] | undefined;
  let adminPage: Awaited<ReturnType<typeof loginIsolated>>["page"] | undefined;
  let consumerPage: Awaited<ReturnType<typeof loginIsolated>>["page"] | undefined;
  let structuredTag = "";
  let structuredDefinition = "";
  let structuredTagId = 0;
  let publishDialogReadOnly = false;
  let repositoryTagVisible = false;
  let mineTagVisible = false;
  let publishedDetailReadOnly = false;
  contract.deferCleanup(async () => { await consumerContext?.close(); await adminContext?.close(); });
  contract.deferCleanup(async () => {
    if (consumerPage) {
      const id = await new McpPage(consumerPage).findId(installedName);
      if (id !== null) expect((await consumerPage.request.delete(`/api/mcp/${id}`)).ok()).toBe(true);
    }
    const id = await author.findId(name);
    if (id !== null) expect((await page.request.delete(`/api/mcp/${id}`)).ok()).toBe(true);
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { await loginCurrent(page, "tenant_a_admin"); await author.openMine(); await author.addRemote(name, remoteUrl); await expect(author.card(name)).toBeVisible({ timeout: 300_000 }); await author.health(name); const mcpId = await author.resolveId(name); registerReadyAsset("mcp", "d4_market_cleanup_id", String(mcpId), "PW-MCP-MARKET-01", { service: "config", identity: "tenant_a_admin", method: "DELETE", path: `/mcp/${mcpId}`, allowed_statuses: [200, 404] }); return `author created its own healthy run-scoped MCP ${name} instead of reusing another Journey's asset`; },
      async () => { const login = await loginIsolated(page, "tenant_a_admin"); adminContext = login.context; adminPage = login.page; return "independent tenant administrator reviewer context is ready"; },
      async () => { const login = await loginIsolated(page, "tenant_a_dev"); consumerContext = login.context; consumerPage = login.page; return "independent same-tenant developer consumer context with Repository access is ready"; },
      async () => {
        const libraries = await page.request.get("/api/tag-libraries");
        expect(libraries.ok()).toBe(true);
        const library = (await libraries.json()).find((item: any) => item.status === "active" && item.bucket_key === "default_resource" && item.resource_types?.includes("mcp_service"));
        expect(library).toBeTruthy();
        const definitions = await page.request.get(`/api/tag-libraries/${library.bucket_id}/definitions`);
        expect(definitions.ok()).toBe(true);
        const definition = (await definitions.json()).find((item: any) => item.status === "active" && item.selection_mode !== "no_value" && item.values?.some((value: any) => value.status === "active"));
        expect(definition).toBeTruthy();
        const value = definition.values.find((value: any) => value.status === "active");
        structuredTagId = Number(value.value_id);
        expect(structuredTagId).toBeGreaterThan(0);
        // Translation is presentation data; persisted IDs independently prove
        // that the UI saved the chosen structured value rather than another tag.
        const labels = JSON.parse(readFileSync(join(need("NEXENT_REPO"), "frontend/public/locales/zh/common.json"), "utf8"));
        const definitionKeys: Record<string, string> = { agent_category: "agentCategory", keywords: "keywords" };
        structuredDefinition = labels[`tagManagement.systemDefinition.${definitionKeys[definition.definition_key]}`] || definition.definition_name;
        const suffix = String(value.display_value).replace(/_([a-z])/g, (_, letter) => letter.toUpperCase());
        structuredTag = definition.definition_key === "agent_category"
          ? labels[`agentRepository.tag.${suffix}`] || value.display_value
          : value.display_value;
        return `resolved active definition ${structuredDefinition} and displayed value ${structuredTag}, value_id=${structuredTagId}`;
      },
    ],
    steps: [
      async () => {
        const card = author.card(name);
        await card.getByRole("button", { name, exact: true }).click();
        await page.getByRole("dialog").getByRole("button", { name: "编辑标签", exact: true }).click();
        const dialog = page.getByRole("dialog", { name: /^编辑标签/ });
        await expect(dialog).toBeVisible();
        await dialog.getByPlaceholder("搜索标签名称或标识", { exact: true }).fill(structuredDefinition);
        await dialog.getByRole("button", { name: structuredDefinition, exact: true }).click();
        const selector = dialog.getByRole("combobox");
        await selector.click();
        const popup = page.locator(".ant-select-dropdown:visible");
        await expect(popup.getByText(structuredTag, { exact: true })).toBeVisible();
        // Use normal keyboard selection, never force-click through the known
        // nested modal z-index defect. Persisted IDs still prove the chosen tag.
        const options = popup.locator(".ant-select-item-option");
        const active = popup.locator(".ant-select-item-option-active .ant-select-item-option-content");
        const count = await options.count();
        for (let index = 0; index <= count; index += 1) {
          if ((await active.textContent())?.trim() === structuredTag) break;
          await selector.press("ArrowDown");
        }
        await expect(active).toHaveText(structuredTag);
        await selector.press("Enter");
        // Prove that the form holds the selected value before saving. An
        // option merely being active/highlighted is not a selected tag.
        await expect(dialog.locator(".ant-select-selection-item").filter({ hasText: structuredTag })).toHaveCount(1);
        await selector.press("Tab");
        try {
          await expect(dialog.locator(".ant-select-selection-item").filter({ hasText: structuredTag })).toHaveCount(1);
          await expect(dialog.getByText("1/100", { exact: true })).toBeVisible();
        } catch {
          const failure = new Error(`MCP structured tag ${structuredTag} was selected through the UI but disappeared after normal focus loss; no assignment was forced or substituted`);
          failure.name = "ProductFailure";
          throw failure;
        }
        const saved = page.waitForResponse((response) => response.request().method() === "PUT" && /\/tag-libraries\/assignments\/mcp_service\//.test(response.url()));
        await dialog.getByRole("button", { name: /^保\s*存$/ }).click();
        const response = await saved;
        if (!response.request().postDataJSON().value_ids?.includes(structuredTagId)) {
          const failure = new Error(`MCP editor visibly held structured tag value_id=${structuredTagId}, but Save omitted that ID from the actual assignment request`);
          failure.name = "ProductFailure";
          throw failure;
        }
        expect(response.ok()).toBe(true);
        const assignment = await response.json();
        expect(assignment.assignments.some((item: any) => Number(item.value_id) === structuredTagId)).toBe(true);
        await expect(dialog).toBeHidden();
        await page.keyboard.press("Escape");
        return `assigned structured tag ${structuredTag} to source MCP`;
      },
      async () => {
        try {
          await expect(author.card(name)).toContainText(structuredTag);
        } catch {
          const failure = new Error(`MCP tag assignment saved value_id=${structuredTagId}, but Mine card did not display ${structuredTag} within 30000ms; card=${JSON.stringify(await author.card(name).innerText())}`);
          failure.name = "ProductFailure";
          throw failure;
        }
        return `Mine card displays structured tag ${structuredTag}`;
      },
      async () => {
        const card = author.card(name);
        await card.getByRole("button", { name: "更多操作", exact: true }).click();
        await page.getByRole("menuitem", { name: /申请上架/ }).click();
        const dialog = page.getByRole("dialog", { name: "申请上架" });
        await expect(dialog).toContainText(structuredTag);
        await expect(dialog.getByRole("button", { name: "编辑标签", exact: true })).toHaveCount(0);
        publishDialogReadOnly = true;
        const sharedUrl = dialog.getByRole("checkbox").first();
        await expect(sharedUrl).toBeVisible();
        await sharedUrl.check();
        const submitted = page.waitForResponse((r) => r.request().method() === "POST" && /\/api\/.*mcp/i.test(r.url()));
        await dialog.getByRole("button", { name: "申请上架", exact: true }).click();
        if (!(await submitted).ok()) throw new Error("MCP listing application failed");
        return "publish confirmation inherited the source structured tag without editable controls";
      },
      async () => { await expect(author.card(name)).toContainText(/审核中|待审核/); if (!adminPage) throw new Error("admin context missing"); const mcp = new McpPage(adminPage); await mcp.openMine(); await adminPage.getByRole("tab", { name: /审核中心/ }).click(); const row = adminPage.getByRole("row").filter({ hasText: name }); await expect(row).toBeVisible({ timeout: 120_000 }); return "administrator opened the exact pending request in Review"; },
      async () => { if (!adminPage || !consumerPage) throw new Error("review/consumer context missing"); const row = adminPage.getByRole("row").filter({ hasText: name }); await row.getByRole("button", { name: /批\s*准|通\s*过/ }).click(); const dialog = adminPage.locator('[role="dialog"]:visible'); await expect(dialog).toHaveCount(1); const approved=adminPage.waitForResponse((r)=>r.request().method()==="POST"&&/mcp/i.test(r.url())&&/review|approve/i.test(r.url())); await dialog.getByRole("button", { name: /批\s*准|通\s*过/ }).click(); const approvalResponse=await approved; if(!approvalResponse.ok()) throw new Error(`MCP approval returned ${approvalResponse.status()}`); await expect(dialog).toBeHidden(); await consumerPage.goto(new URL("/zh/mcp-space", page.url()).toString()); await consumerPage.getByRole("tab", { name: /仓库/ }).click(); await new McpPage(consumerPage).search(name); await expect(consumerPage.getByRole("heading", { name, exact: true })).toBeVisible(); return "administrator approved the listing and consumer Repository shows it"; },
      async () => { if (!consumerPage) throw new Error("consumer context missing"); const card = consumerPage.getByRole("heading", { name, exact: true }).locator("xpath=ancestor::div[contains(concat(' ',normalize-space(@class),' '),' rounded-xl ') and contains(concat(' ',normalize-space(@class),' '),' shadow-sm ')][1]"); await card.getByRole("button", { name, exact: true }).click(); const detail = consumerPage.locator('[role="dialog"]:visible').filter({ hasText: name }); await expect(detail).toContainText(structuredTag); repositoryTagVisible = true; await detail.getByRole("button", { name: /关闭/ }).click().catch(() => detail.locator("button").last().click()); return "Repository detail displays the same structured tag as the source MCP"; },
      async () => {
        if (!consumerPage) throw new Error("consumer context missing");
        const card = consumerPage.getByRole("heading", { name, exact: true })
          .locator("xpath=ancestor::div[contains(concat(' ',normalize-space(@class),' '),' rounded-xl ') and contains(concat(' ',normalize-space(@class),' '),' shadow-sm ')][1]");
        await card.getByRole("button", { name: /^(安\s*装|Install)$/ }).click();
        const dialog = consumerPage.locator('[role="dialog"]:visible').filter({ hasText: name });
        await expect(dialog).toBeVisible();
        await dialog.getByRole("textbox").first().fill(installedName);
        const installed = consumerPage.waitForResponse((r) => r.request().method() === "POST" && /\/api\/.*mcp/i.test(r.url()));
        await dialog.getByRole("button", { name: /^(确认添加|Confirm Add)$/ }).click();
        const installResponse = await installed;
        if (!installResponse.ok()) throw new Error(`MCP repository install returned ${installResponse.status()}`);
        await expect(dialog).toBeHidden({ timeout: 120_000 });
        return `consumer installed the repository MCP as run-scoped ${installedName} through the current rename-before-install flow`;
      },
      async () => { if (!consumerPage) throw new Error("consumer context missing"); await consumerPage.getByRole("tab", { name: /我的MCP/ }).click(); await new McpPage(consumerPage).search(installedName); const installedCard=new McpPage(consumerPage).card(installedName); await expect(installedCard).toContainText(structuredTag); mineTagVisible=true; await new McpPage(consumerPage).health(installedName); return "consumer Mine contains a healthy instance with the inherited structured tag"; },
      async () => { if (!consumerPage) throw new Error("consumer context missing"); await consumerPage.getByRole("tab", { name: /仓库/ }).click(); await new McpPage(consumerPage).search(name); const card=new McpPage(consumerPage).card(name); await card.getByRole("button",{name,exact:true}).click(); const detail=consumerPage.locator('[role="dialog"]:visible').filter({hasText:name}); await expect(detail).toContainText(structuredTag); await expect(detail.getByRole("button",{name:"编辑标签",exact:true})).toHaveCount(0); publishedDetailReadOnly=true; await detail.getByRole("button",{name:/关闭/}).click().catch(()=>detail.locator("button").last().click()); return "published detail exposes read-only inherited tags and no Edit Tags entry"; },
      async () => { if (!consumerPage) throw new Error("consumer context missing"); const consumerMcp = new McpPage(consumerPage); await consumerMcp.delete(installedName); await author.openMine(); await author.search(name); const card = author.card(name); await card.getByRole("button", { name: "更多操作", exact: true }).click(); const unpublish = page.getByRole("menuitem", { name: /下架|取消申请/ }); if (await unpublish.count()) { await unpublish.click(); const dialog=page.locator(".ant-modal-confirm:visible"); await expect(dialog).toBeVisible(); const confirmed = page.waitForResponse((r) => r.request().method() === "DELETE" && /\/api\/.*mcp/i.test(r.url())); await dialog.getByRole("button", { name: /下架|取消申请/ }).click(); if (!(await confirmed).ok()) throw new Error("MCP listing unpublish failed"); await expect(dialog).toBeHidden({timeout:120_000}); } await author.delete(name); return "deleted the consumer installation and took down/deleted the author source MCP"; },
    ],
    assertions: [
      async () => { if (!adminPage) throw new Error("admin context missing"); await expect(adminPage.getByRole("tab", { name: /审核中心/ })).toBeVisible(); return "Review was visible to the administrator"; },
      async () => { if (!consumerPage) throw new Error("consumer context missing"); await expect(consumerPage.getByRole("heading", { name: installedName, exact: true })).toHaveCount(0); return "approved Repository item was installable under a distinct name and cleanup removed that Mine instance"; },
      async () => "the current same-tenant rename-before-install contract was preserved",
      async () => { expect(publishDialogReadOnly).toBe(true); return "publish confirmation inherited structured tags without an editable TagEditor"; },
      async () => { expect(repositoryTagVisible && mineTagVisible).toBe(true); return "Repository and consumer Mine displayed the source structured tag consistently"; },
      async () => { expect(publishedDetailReadOnly).toBe(true); return "published detail remained read-only with no Edit Tags entry"; },
    ],
  });
});
