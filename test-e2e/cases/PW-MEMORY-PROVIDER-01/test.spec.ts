import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredFeature, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

const required = (name: string): string => {
  const value = process.env[name] || "";
  if (!value) { const error = new Error(`required real test asset ${name} is missing`); error.name = "DependencyFailure"; throw error; }
  return value;
};

journey("PW-MEMORY-PROVIDER-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-MEMORY-PROVIDER-01");
  const name = `memory-provider-${token}`;
  const marker = `EXTMEM-${token}`;
  const lookup = `MEMLOOKUP-${token}`;
  let plugin = "";
  let endpoint = "";
  let apiKey = "";
  const chat = new ChatPage(page);
  let agent = "";
  let created = false;
  let ingestVerified = false;
  let retrievedAnswer = "";
  let maskedCredentialVerified = false;
  contract.deferCleanup(async () => {
    if (!created) return;
    await page.goto(appPath("/memory"));
    const row = page.locator(".external-provider-row").filter({ hasText: name });
    if (await row.count()) {
      await row.getByRole("button", { name: /更多\s*(?:Provider|提供商)\s*操作|More provider actions/i }).click();
      await page.getByText(/删除|Delete/, { exact: true }).click();
      const dialog = page.getByRole("dialog");
      if (await dialog.count()) await dialog.getByRole("button", { name: /确定|删除|Delete/ }).click();
    }
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { expect(configuredFeature("memory")).toBe(true); return "Memory feature is enabled"; },
      async () => { await loginCurrent(page, "tenant_a_admin"); return "authorized administrator authenticated"; },
      async () => { plugin = required("NEXENT_EXTERNAL_MEMORY_PLUGIN"); endpoint = required("NEXENT_EXTERNAL_MEMORY_ENDPOINT"); apiKey = required("NEXENT_EXTERNAL_MEMORY_API_KEY"); agent = resolveReadyAsset("agents", "d4_chat_display_name", "PW-MEMORY-PROVIDER-01"); return `real provider ${plugin} and real Agent ${agent} are configured`; },
    ],
    steps: [
      async () => { await page.goto(appPath("/memory")); await expect(page.getByText(/^(?:外部记忆|External memory)$/)).toBeVisible(); return "opened external-memory management"; },
      async () => {
        await page.getByRole("button", { name: /添加\s*(?:Provider|提供商)|Add provider/i }).first().click();
        await page.getByLabel(/提供商名称|Provider\s*(?:名称|name)/i).fill(name);
        await page.getByLabel(/插件|Plugin/).click();
        await page.getByText(new RegExp(`^${plugin.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} \\(v`, "i")).last().click();
        // Fail before sending credentials if the endpoint field cannot be resolved.
        const endpointInput = page.getByLabel(/API Base URL|API 基础 URL|端点|Endpoint/i);
        await expect(endpointInput).toBeVisible();
        await endpointInput.fill(endpoint);
        await expect(endpointInput).toHaveValue(endpoint);
        await page.getByLabel(/API 密钥|API\s*key/i).fill(apiKey);
        const enable = page.getByLabel(/保存后启用|Enable after saving/);
        await expect(enable).toBeVisible();
        if (await enable.getAttribute("aria-checked") !== "true") await enable.click();
        await expect(enable).toHaveAttribute("aria-checked", "true");
        return "filled the configured provider endpoint and enabled it using local credentials";
      },
      async () => { await page.getByRole("button", { name: /保存并测试|Save and test/ }).click(); created = true; await expect(page.getByText(new RegExp(`Test ${name}|测试 ${name}`))).toBeVisible({ timeout: 120000 }); return "saved provider and opened its real connectivity test"; },
      async () => {
        await page.getByLabel(/测试记忆内容|Test memory content/).fill(`Nexent lookup ${lookup} has the unique answer ${marker}`);
        await page.getByLabel(/测试查询|Test query/).fill(lookup);
        await page.getByRole("button", { name: /写入并(?:搜索|检索)|Write and search/ }).click();
        const confirm = page.locator(".ant-modal-confirm");
        const ingestResponse = page.waitForResponse((response) => /\/memory\/providers\/\d+\/test-ingest/.test(response.url()) && response.request().method() === "POST");
        const searchResponse = page.waitForResponse((response) => /\/memory\/providers\/\d+\/test-search/.test(response.url()) && response.request().method() === "POST");
        await confirm.getByRole("button", { name: /写入并(?:搜索|检索)|Write and search/ }).click();
        const ingest = await ingestResponse;
        const search = await searchResponse;
        expect(ingest.status()).toBe(200);
        expect(search.status()).toBe(200);
        const ingested = await ingest.json();
        const found = await search.json();
        expect(ingested.accepted_count).toBeGreaterThan(0);
        expect(ingested.rejected_count).toBe(0);
        expect(found.items.some((item: { content: string }) => item.content.includes(marker))).toBe(true);
        await expect(page.getByText(/连接测试成功|Connection test succeeded/)).toBeVisible({ timeout: 180000 });
        ingestVerified = true;
        return "provider ingest accepted the memory and search returned its stored answer";
      },
      async () => { await page.getByRole("button", { name: /关闭|Close/ }).click(); await chat.openAgent(agent); const response = await chat.sendAndWait(`请从外部记忆中查询 ${lookup} 对应的 unique answer，原样回复答案。不要猜测；找不到就明确说未找到。`, 420000); await expect(response).toContainText(marker); retrievedAnswer = await response.innerText(); return "chat returned the stored answer that was absent from the user question"; },
      async () => { await page.goto(appPath("/memory")); const row = page.locator(".external-provider-row").filter({ hasText: name }); await row.getByRole("button", { name: /更多\s*(?:Provider|提供商)\s*操作|More provider actions/i }).click(); await page.getByText(/编辑|Edit/, { exact: true }).click(); await expect(page.getByLabel(/API 密钥|API\s*key/i)).toHaveValue(/^(?:••••••••)?$/); expect((await page.content()).includes(apiKey)).toBe(false); maskedCredentialVerified = true; await page.getByLabel(/提供商名称|Provider\s*(?:名称|name)/i).fill(`${name}-updated`); await page.getByRole("button", { name: /保存|Save/, exact: true }).click(); await page.reload(); await expect(page.locator(".external-provider-row").filter({ hasText: `${name}-updated` })).toBeVisible(); return "edited non-secret metadata persisted after refresh while the saved key was not returned"; },
      async () => { const row = page.locator(".external-provider-row").filter({ hasText: `${name}-updated` }); await row.getByRole("button", { name: /更多\s*(?:Provider|提供商)\s*操作|More provider actions/i }).click(); await page.getByText(/删除|Delete/, { exact: true }).click(); const dialog = page.getByRole("dialog"); if (await dialog.count()) await dialog.getByRole("button", { name: /确定|删除|Delete/ }).click(); created = false; await page.reload(); await expect(row).toHaveCount(0); return "deleted the run-scoped provider and verified absence after refresh"; },
    ],
    assertions: [
      async () => { expect(created).toBe(false); return "provider CRUD persisted and cleanup completed"; },
      async () => { expect(ingestVerified).toBe(true); return "real product ingest and search responses proved the stored memory was retrieved"; },
      async () => { expect(retrievedAnswer).toContain(marker); return "real Agent response contained the answer absent from its input"; },
      async () => { expect(maskedCredentialVerified).toBe(true); expect((await page.content()).includes(apiKey)).toBe(false); return "saved credential was masked and is absent from the final DOM; artifact secrecy requires separate audit"; },
    ],
  });
});

