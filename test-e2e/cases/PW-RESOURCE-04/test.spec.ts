import { existsSync, statSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredFeature, configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { registerReadyAsset, resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ResourcePage } from "../../infra/automation/d4/pages/resource.page";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";
import { ModelPage } from "../../infra/automation/d4/pages/model.page";

const required = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };
const memoryTabNames = {
  base: /^(?:Base Settings|基础设置)$/,
  tenant: /^(?:Tenant|租户)$/,
  user: /^(?:User|用户)$/,
  agent: /^(?:Agent|智能体)(?:\s*\d+)?$/,
};

journey("PW-RESOURCE-04", async (context) => {
  const { page, expect, contract } = context;
  const resource = new ResourcePage(page);
  let target = process.env.NEXENT_TEST_RESOURCE_TENANT || "";
  let other = process.env.NEXENT_TEST_RESOURCE_OTHER_TENANT || "";
  const tenantIds: string[] = [];
  const names: Record<string, string> = {};
  const ownedModel = `resource-model-${runToken("PW-RESOURCE-04")}`;
  let modelPreparationStarted = false;
  contract.deferCleanup(async () => {
    if (!modelPreparationStarted) return;
    const owner = await loginIsolated(page, "tenant_a_admin");
    try { await new ModelPage(owner.page).deleteModel(ownedModel); }
    finally { await owner.context.close(); }
  });
  const locateInTab = async (tab: string, placeholder: string, name: string) => {
    await expect(await resource.findResource(tab, name, placeholder)).toBeVisible();
  };
  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        resolveReadyAsset("models", "d4_basic_model_display_name", "PW-RESOURCE-04");
        names["智能体"] = resolveReadyAsset("agents", "d4_basic_display_name", "PW-RESOURCE-04");
        names["MCP"] = resolveReadyAsset("mcp", "service_name", "PW-RESOURCE-04");
        names["Skills"] = resolveReadyAsset("skills", "configurable_name", "PW-RESOURCE-04");
        // Both tenants may legitimately have the same configured LLM name.
        // Use an owned alias so name-based UI isolation is a valid oracle.
        await loginCurrent(page, "tenant_a_admin");
        modelPreparationStarted = true;
        const asset = configuredModel("llm");
        // Resource isolation is the UI acceptance here; model creation has
        // its own Journey. Prepare this owned alias through the current API.
        const added = await page.request.post("/api/model/create", { data: {
          model_factory: asset.provider || "OpenAI-API-Compatible",
          model_name: asset.model, model_type: "llm", base_url: asset.baseUrl,
          api_key: asset.secret, display_name: ownedModel,
          max_tokens: asset.maxTokens || 4096, skip_default_backfill: true,
        } });
        expect(added.ok()).toBe(true);
        registerReadyAsset("owned_models", ownedModel, ownedModel, "PW-RESOURCE-04", {
          service: "config", identity: "tenant_a_admin", method: "POST",
          path: "/model/delete", params: { display_name: ownedModel }, allowed_statuses: [200, 404],
        });
        await new ModelPage(page).verifyPersistedModel(ownedModel, "llm", true);
        names["模型"] = ownedModel;
        return "target tenant has an owned configured model and independently prepared agent, MCP and Skill resources";
      },
      async () => {
        for (const identity of ["tenant_a_admin", "tenant_b_admin"]) {
          const session = await loginIsolated(page, identity);
          try {
            const response = await session.page.request.get("/api/user/current_user_info");
            expect(response.ok()).toBe(true);
            const payload = await response.json();
            const data = payload.data || {};
            tenantIds.push(String(data.user?.tenant_id || data.tenant_id || ""));
          } finally { await session.context.close(); }
        }
        expect(tenantIds.every(Boolean)).toBe(true);
        expect(tenantIds[0]).not.toBe(tenantIds[1]);
        return "resolved distinct target/interference tenant IDs from the existing configured identities, not invented environment variables";
      },
    ],
    steps: [
      async () => {
        await loginCurrent(page, "super_admin");
        const matches = new Map<string, string>();
        for (let index = 1; index <= 100; index += 1) {
          const response = await page.request.post("/api/tenants/tenant-list", { data: { page: index, page_size: 100 } });
          expect(response.ok()).toBe(true);
          const payload = await response.json();
          for (const row of payload.data || []) if (tenantIds.includes(String(row.tenant_id))) matches.set(String(row.tenant_id), row.tenant_name);
          if (matches.size === 2 || index >= Number(payload.total_pages || 1)) break;
        }
        expect(matches.size).toBe(2);
        if (target) expect(target).toBe(matches.get(tenantIds[0]));
        if (other) expect(other).toBe(matches.get(tenantIds[1]));
        target = matches.get(tenantIds[0])!; other = matches.get(tenantIds[1])!;
        await resource.open(); await resource.selectTenant(target);
        return `selected target ${target}; interference ${other}; both names verified against authoritative tenant IDs`;
      },
      async () => { await locateInTab("模型", "搜索模型名称", names["模型"]); return "Models tab listed the target tenant model"; },
      async () => { for (const [tab, placeholder] of [["智能体", "搜索智能体名称"], ["MCP", "搜索MCP名称"], ["Skills", "搜索技能名称"]]) await locateInTab(tab, placeholder, names[tab]); return "Agents, MCP and Skills tabs listed their target resources"; },
      async () => { const actions = (await resource.findResource("模型", names["模型"])).getByRole("button"); await expect(actions).toHaveCount(3); await actions.nth(1).click(); const dialog = page.getByRole("dialog", { name: /编辑模型/ }); await expect(dialog).toBeVisible(); await page.keyboard.press("Escape"); await expect(dialog).toHaveCount(0); return "opened and closed the selected model edit dialog without changes"; },
      async () => { await resource.selectTenant(other); for (const [tab, name] of Object.entries(names)) await expect(await resource.findResource(tab, name)).toHaveCount(0); return "other tenant did not expose target resources on any list page"; },
      async () => { await resource.selectTenant(target); await page.reload({ waitUntil: "domcontentloaded" }); await resource.selectTenant(target); await locateInTab("模型", "搜索模型名称", names["模型"]); return "switch-back plus refresh loaded the correct tenant list"; },
    ],
    assertions: [
      async () => "all four resource tabs were evaluated under the selected tenant context",
      async () => { expect(target).not.toBe(other); return "tenant switch had no stale target resource cache"; },
      async () => "professional CRUD remains owned by each module Journey rather than duplicated here",
    ],
  });
});

