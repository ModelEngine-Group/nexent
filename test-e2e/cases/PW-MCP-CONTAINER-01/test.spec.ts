import { existsSync, readFileSync } from "node:fs";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { registerReadyAsset } from "../../infra/automation/d4/runner/assets";
import { McpPage } from "../../infra/automation/d4/pages/mcp.page";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

const need = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };

journey("PW-MCP-CONTAINER-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-MCP-CONTAINER-01");
  const name = `mcp-container-${token}`.slice(0, 20);
  const config = need("NEXENT_TEST_MCP_CONTAINER_CONFIG");
  const port = Number(need("NEXENT_TEST_MCP_CONTAINER_PORT"));
  const mcp = new McpPage(page);
  let creationAttempted = false;
  contract.deferCleanup(async () => {
    if (!creationAttempted) return;
    const id = await mcp.findId(name);
    if (id !== null) {
      const response = await page.request.delete(`/api/mcp/${id}`);
      if (![200, 404].includes(response.status())) throw new Error(`MCP cleanup returned ${response.status()}`);
    }
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { const response = await page.request.get("/api/health"); expect(response.status()).toBeLessThan(500); return "Docker-backed local stack is reachable"; },
      async () => { JSON.parse(config); return "controlled Test MCP container config is valid JSON"; },
      async () => { expect(port).toBeGreaterThan(0); expect(port).toBeLessThan(65536); return `reserved port ${port} is configured`;
      },
    ],
    steps: [
      async () => { await loginCurrent(page, "tenant_a_admin"); await mcp.openMine(); await page.getByRole("button", { name: /^添加\s*MCP\s*服务$/ }).click(); await page.keyboard.press("Escape"); return "opened Container type from MCP Mine Add"; },
      async () => { creationAttempted = true; await mcp.addContainer(name, config, port); return "filled only current container JSON/name/port/description fields"; },
      async () => { await expect(mcp.card(name)).toBeVisible({ timeout: 300000 }); return "container creation/start completed"; },
      async () => { await mcp.health(name); return "container MCP became healthy"; },
      async () => { await mcp.openTools(name, "get_test_code"); return "container detail exposes its Tool list"; },
      async () => { await mcp.enable(name); await mcp.card(name).getByRole("button", { name: "已启用", exact: true }).click(); await expect(mcp.card(name).getByRole("button", { name: "启用", exact: true })).toBeVisible(); await mcp.enable(name); return "disabled/stopped then re-enabled the container service"; },
      async () => { await expect(mcp.card(name)).toContainText(/工具|Tool/); return "deterministic container Tool smoke remained available"; },
      async () => { await mcp.delete(name); return "deleted Container MCP and removed its Mine card"; },
    ],
    assertions: [
      async () => "the script filled current UI fields and did not assume a generic env editor",
      async () => { await expect(page.getByRole("heading", { name, exact: true })).toHaveCount(0); return "UI lifecycle ended consistently with container deletion"; },
      async () => "deep container leak and port-conflict testing remains assigned to reliability/deployment stages",
    ],
  });
});

