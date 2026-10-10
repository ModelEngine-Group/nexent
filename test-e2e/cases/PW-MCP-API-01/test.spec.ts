import { existsSync, readFileSync } from "node:fs";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { registerReadyAsset } from "../../infra/automation/d4/runner/assets";
import { McpPage } from "../../infra/automation/d4/pages/mcp.page";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

const need = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };

journey("PW-MCP-API-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-MCP-API-01");
  const name = `mcp-api-${token}`.slice(0, 20);
  const base = need("NEXENT_TEST_ASSETS_URL");
  const probeBase = process.env.NEXENT_TEST_ASSETS_LOCAL_URL || base;
  const wire = need("NEXENT_TEST_API_WIRE_LOG");
  const mcp = new McpPage(page);
  const agents = new AgentPage(page);
  const openapi = JSON.stringify({ openapi: "3.0.0", info: { title: "Nexent Controlled API", version: "1.0.0" }, paths: { "/test-api/code": { get: { operationId: "get_api_test_code", responses: { "200": { description: "fixed marker" } } } } } });
  let offset = 0;
  let agentId = 0;
  let convertedToolName = "";
  let creationAttempted = false;
  contract.deferCleanup(async () => {
    if (!creationAttempted) return;
    const id = await mcp.findId(name);
    if (id !== null) {
      const response = await page.request.delete(`/api/mcp/${id}`);
      if (![200, 404].includes(response.status())) throw new Error(`MCP cleanup returned ${response.status()}`);
    }
  });
  contract.deferCleanup(async () => { if (agentId) await agents.delete(agentId); });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { const response = await page.request.get(`${probeBase}/test-api/code`); expect(await response.json()).toEqual({ code: "API-NX-92831" }); return "controlled Test HTTP API and OpenAPI contract are reachable from the local runner"; },
      async () => { offset = existsSync(wire) ? readFileSync(wire, "utf8").length : 0; return "API-to-MCP dependencies and wire evidence are available"; },
    ],
    steps: [
      async () => { await loginCurrent(page, "tenant_a_admin"); await mcp.openMine(); return "opened Mine→Add API type"; },
      async () => { creationAttempted = true; await mcp.addApi(name, base, openapi); return "filled controlled API URL, OpenAPI JSON and run-scoped name"; },
      async () => { await expect(mcp.card(name)).toBeVisible({ timeout: 300000 }); const mcpId = await mcp.resolveId(name); registerReadyAsset("mcp", "d4_api_cleanup_id", String(mcpId), "PW-MCP-API-01", { service: "config", identity: "tenant_a_admin", method: "DELETE", path: `/mcp/${mcpId}`, allowed_statuses: [200, 404] }); return `API conversion/creation completed as service id=${mcpId} with batch cleanup registered`; },
      async () => { await mcp.health(name); await mcp.openTools(name, "get_api_test_code"); return "health passed and converted Tool is visible"; },
      async () => {
        const listed = await page.request.get("/api/tool/list");
        expect(listed.ok()).toBe(true);
        const payload = await listed.json();
        const tools = Array.isArray(payload) ? payload : payload.data || payload.tools || [];
        // OpenAPI tools use the shared outer-apis category and a mounted name.
        // Resolve the current service's actual name instead of inventing it.
        const matches = tools.filter((tool: any) => tool.source === "mcp" && tool.usage === "outer-apis"
          && String(tool.origin_name || tool.name).includes(name)
          && String(tool.origin_name || tool.name).includes("get_api_test_code"));
        expect(matches).toHaveLength(1);
        convertedToolName = String(matches[0].origin_name || matches[0].name);
        await agents.open();
        agentId = await agents.create(`MCP API ${token}`, `mcp_api_${token}`);
        const modelName = configuredModel("llm").displayName;
        await agents.selectModel(modelName);
        await agents.setDescription(`API MCP validation ${token}`);
        await agents.setPrompts({ duty: `必须调用 ${convertedToolName} 工具，并原样返回工具结果 ${token}` });
        await agents.bindToolFromService("outer-apis", convertedToolName);
        return `created an isolated Agent with configured LLM ${modelName} and the current service's converted Tool ${convertedToolName}`;
      },
      async () => { await page.reload({ waitUntil: "domcontentloaded" }); await agents.select(`MCP API ${token}`); await agents.openDebug(); await agents.sendDebug(`必须调用 ${convertedToolName}，并只回复工具结果。`, "API-NX-92831"); return "reloaded the exact Draft and completed real LLM→converted Tool→controlled API invocation"; },
      async () => { const delta = readFileSync(wire, "utf8").slice(offset); expect(delta).toContain("API-NX-92831"); return "Test API wire and result marker agree"; },
      async () => { await mcp.delete(name); return "deleted the run-scoped API MCP"; },
    ],
    assertions: [
      async () => "API type created a visible converted Tool",
      async () => { expect(readFileSync(wire, "utf8").slice(offset)).toContain("get_api_test_code"); return "the controlled API received a real invocation"; },
      async () => "schema and parameter edge mapping remain assigned to contract tests",
    ],
  });
});

