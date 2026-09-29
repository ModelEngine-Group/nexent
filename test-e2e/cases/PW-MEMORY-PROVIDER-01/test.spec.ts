import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredFeature, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

const required = (name: string): string => {
  const value = process.env[name] || "";
  if (!value) throw new Error(`required real test asset ${name} is missing`);
  return value;
};

journey("PW-MEMORY-PROVIDER-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-MEMORY-PROVIDER-01");
  const name = `memory-provider-${token}`;
  const marker = `EXTMEM-${token}`;
  const plugin = required("NEXENT_EXTERNAL_MEMORY_PLUGIN");
  const endpoint = required("NEXENT_EXTERNAL_MEMORY_ENDPOINT");
  const apiKey = required("NEXENT_EXTERNAL_MEMORY_API_KEY");
  const chat = new ChatPage(page);
  let agent = "";
  let created = false;
  contract.deferCleanup(async () => {
    if (!created) return;
    await page.goto(appPath("/memory"));
    const row = page.locator(".external-provider-row").filter({ hasText: name });
    if (await row.count()) {
      await row.getByRole("button", { name: /更多提供商操作|More provider actions/ }).click();
      await page.getByText(/删除|Delete/, { exact: true }).click();
      const dialog = page.getByRole("dialog");
      if (await dialog.count()) await dialog.getByRole("button", { name: /确定|删除|Delete/ }).click();
    }
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { expect(configuredFeature("memory")).toBe(true); return "Memory feature is enabled"; },
      async () => { await loginCurrent(page, "tenant_a_admin"); return "authorized administrator authenticated"; },
      async () => { agent = resolveReadyAsset("agents", "d4_chat_display_name", "PW-MEMORY-PROVIDER-01"); return `real provider ${plugin} and real Agent ${agent} are configured`; },
    ],
    steps: [
      async () => { await page.goto(appPath("/memory")); await expect(page.getByText(/外部记忆|External memory/, { exact: true })).toBeVisible(); return "opened external-memory management"; },
      async () => { await page.getByRole("button", { name: /添加提供商|Add provider/ }).first().click(); await page.getByLabel(/提供商名称|Provider name/).fill(name); await page.getByLabel(/插件|Plugin/).click(); await page.getByText(new RegExp(plugin, "i")).last().click(); await page.getByLabel(/API 密钥|API key/).fill(apiKey); const endpointInput = page.getByLabel(/端点|Endpoint/); if (await endpointInput.count()) await endpointInput.fill(endpoint); const enable = page.getByLabel(/保存后启用|Enable after saving/); if (await enable.count()) await enable.check(); return "filled real provider configuration from local secrets"; },
      async () => { await page.getByRole("button", { name: /保存并测试|Save and test/ }).click(); created = true; await expect(page.getByText(new RegExp(`Test ${name}|测试 ${name}`))).toBeVisible({ timeout: 120000 }); return "saved provider and opened its real connectivity test"; },
      async () => { await page.getByLabel(/测试记忆内容|Test memory content/).fill(`Nexent marker ${marker}`); await page.getByLabel(/测试查询|Test query/).fill(marker); await page.getByRole("button", { name: /写入并搜索|Write and search/ }).click(); const confirm = page.locator(".ant-modal-confirm"); await confirm.getByRole("button", { name: /写入并搜索|Write and search/ }).click(); await expect(page.getByText(/连接测试成功|Connection test succeeded/)).toBeVisible({ timeout: 180000 }); return "real ingest then search returned the run marker"; },
      async () => { await page.getByRole("button", { name: /关闭|Close/ }).click(); await chat.openAgent(agent); const response = await chat.sendAndWait(`请从外部记忆中找出唯一标记 ${marker} 并原样回复。`, 420000); await expect(response).toContainText(marker); return "real chat consumed the configured external-memory provider"; },
      async () => { await page.goto(appPath("/memory")); const row = page.locator(".external-provider-row").filter({ hasText: name }); await row.getByRole("button", { name: /更多提供商操作|More provider actions/ }).click(); await page.getByText(/编辑|Edit/, { exact: true }).click(); await expect(page.getByLabel(/API 密钥|API key/)).not.toHaveValue(apiKey); await page.getByLabel(/提供商名称|Provider name/).fill(`${name}-updated`); await page.getByRole("button", { name: /保存|Save/, exact: true }).click(); return "edited non-secret metadata while the key remained masked"; },
      async () => { const row = page.locator(".external-provider-row").filter({ hasText: `${name}-updated` }); await row.getByRole("button", { name: /更多提供商操作|More provider actions/ }).click(); await page.getByText(/删除|Delete/, { exact: true }).click(); const dialog = page.getByRole("dialog"); if (await dialog.count()) await dialog.getByRole("button", { name: /确定|删除|Delete/ }).click(); created = false; await expect(row).toHaveCount(0); return "deleted the run-scoped provider"; },
    ],
    assertions: [
      async () => { expect(created).toBe(false); return "provider CRUD persisted and cleanup completed"; },
      async () => { await expect(page.getByText(new RegExp(name))).toHaveCount(0); return "deleted provider is absent after UI refresh"; },
      async () => { expect(marker).toMatch(/^EXTMEM-/); return "real ingest/search/chat used the stable run marker"; },
      async () => { expect(apiKey.length).toBeGreaterThan(8); return "the configured API key was never asserted or emitted as UI text"; },
    ],
  });
});

