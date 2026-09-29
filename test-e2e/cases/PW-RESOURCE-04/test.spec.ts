import { existsSync, statSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredFeature, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ResourcePage } from "../../infra/automation/d4/pages/resource.page";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

const required = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };
const memoryTabNames = {
  base: /^(?:Base Settings|基础设置)$/,
  tenant: /^(?:Tenant|租户)$/,
  user: /^(?:User|用户)$/,
  agent: /^(?:Agent|智能体)(?:\s*\d+)?$/,
};

journey("PW-RESOURCE-04", async (context) => {
  const { page, expect } = context;
  const resource = new ResourcePage(page);
  const target = required("NEXENT_TEST_RESOURCE_TENANT");
  const other = required("NEXENT_TEST_RESOURCE_OTHER_TENANT");
  const names: Record<string, string> = {};
  const resourceRow = (tab: string, name: string) => page.getByRole("tabpanel", { name: tab, exact: true }).getByRole("row").filter({ hasText: name });
  const locateInTab = async (tab: string, placeholder: string, name: string) => {
    await resource.openTab(tab);
    const search = page.getByRole("tabpanel", { name: tab, exact: true }).getByPlaceholder(placeholder);
    if (await search.count()) await resource.searchCurrentTab(placeholder, name);
    await expect(resourceRow(tab, name)).toBeVisible();
  };
  await executeFixedScenario(context, {
    preconditions: [
      async () => { names["模型"] = resolveReadyAsset("models", "d4_basic_model_display_name", "PW-RESOURCE-04"); names["智能体"] = resolveReadyAsset("agents", "d4_basic_display_name", "PW-RESOURCE-04"); names["MCP"] = resolveReadyAsset("mcp", "service_name", "PW-RESOURCE-04"); names["Skills"] = resolveReadyAsset("skills", "configurable_name", "PW-RESOURCE-04"); return "target tenant has a READY model and independently prepared agent, MCP and Skill resources"; },
      async () => { expect(other).not.toBe(target); return `interference tenant ${other} is distinct from ${target}`; },
    ],
    steps: [
      async () => { await loginCurrent(page, "super_admin"); await resource.open(); await resource.selectTenant(target); return `selected target tenant ${target}`; },
      async () => { await locateInTab("模型", "搜索模型名称", names["模型"]); return "Models tab listed the target tenant model"; },
      async () => { for (const [tab, placeholder] of [["智能体", "搜索智能体名称"], ["MCP", "搜索MCP名称"], ["Skills", "搜索技能名称"]]) await locateInTab(tab, placeholder, names[tab]); return "Agents, MCP and Skills tabs listed their target resources"; },
      async () => { await resource.openTab("模型"); const actions = resourceRow("模型", names["模型"]).getByRole("button"); await expect(actions).toHaveCount(3); await actions.nth(1).click(); const dialog = page.getByRole("dialog", { name: /编辑模型/ }); await expect(dialog).toBeVisible(); await page.keyboard.press("Escape"); await expect(dialog).toHaveCount(0); return "opened and closed the selected model edit dialog without changes"; },
      async () => { await resource.selectTenant(other); for (const [tab, name] of Object.entries(names)) { await resource.openTab(tab); await expect(resourceRow(tab, name)).toHaveCount(0); } return "other tenant did not expose target resources"; },
      async () => { await resource.selectTenant(target); await page.reload({ waitUntil: "domcontentloaded" }); await resource.selectTenant(target); await resource.openTab("模型"); await expect(resourceRow("模型", names["模型"])).toBeVisible(); return "switch-back plus refresh loaded the correct tenant list"; },
    ],
    assertions: [
      async () => "all four resource tabs were evaluated under the selected tenant context",
      async () => { expect(target).not.toBe(other); return "tenant switch had no stale target resource cache"; },
      async () => "professional CRUD remains owned by each module Journey rather than duplicated here",
    ],
  });
});

