import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { registerReadyAsset } from "../../infra/automation/d4/runner/assets";
import { a2aProbe } from "../../infra/automation/d4/runner/a2a";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

journey("PW-A2A-DISCOVERY-01", async (context) => {
  const { page, contract, expect } = context;
  const caseId = "PW-A2A-DISCOVERY-01";
  const nonce = `${caseId}-${runToken(caseId)}`;
  const display = `A2A Discovery ${runToken(caseId)}`;
  const agents = new AgentPage(page);
  let settings: { product_url: string };
  let localId = 0;
  let externalId = 0;
  let externalName = "";
  let answer = "";
  let invokedAfter = "";
  let wire: { get_count: number; post_count: number; authenticated: boolean };
  // Validate the field value, not the LLM's choice of localized punctuation.
  const totalField = /total(?:\s*\([^)]*\))?[^0-9\n]{0,24}1283\b/i;
  const modal = () => page.getByRole("dialog", { name: "A2A Agent 发现", exact: true });
  contract.deferCleanup(async () => {
    if (localId && externalId) {
      const response = await page.request.delete("/api/a2a/client/relations", { params: {
        local_agent_id: localId, external_agent_id: externalId,
      } });
      expect([200, 404]).toContain(response.status());
    }
    if (externalId) {
      expect([200, 404]).toContain((await page.request.delete(`/api/a2a/client/agents/${externalId}`)).status());
      expect((await page.request.get(`/api/a2a/client/agents/${externalId}`)).status()).toBe(404);
    }
    if (localId) await agents.delete(localId);
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { settings = await a2aProbe(["config"]); return "controlled A2A Mock is READY and has no outstanding scenario"; },
      async () => { expect(configuredModel("llm").model).not.toBe(""); return "configured real LLM is available; discovery custom header contains only the run nonce"; },
      async () => { await loginCurrent(page, "tenant_a_admin"); await agents.open(); return "editable Agent surface is available to the test administrator"; },
    ],
    steps: [
      async () => {
        localId = await agents.create(display, `a2a_discovery_${runToken(caseId)}`);
        registerReadyAsset("owned_a2a_local", String(localId), String(localId), caseId, {
          service: "config", identity: "tenant_a_admin", method: "DELETE", path: "/agent",
          json: { agent_id: localId }, allowed_statuses: [200, 404],
        });
        await agents.selectModel(configuredModel("llm").displayName);
        await agents.setDescription(`A2A journey ${nonce}`);
        await agents.setPrompts({ duty: "必须委派已绑定的外部 A2A 智能体查询 pedestrian flow；禁止猜测统计值，原样保留外部结果的 total 字段。" });
        await agents.openAdvanced(); await agents.openSection("协作智能体");
        return "created and configured one owned main Draft; opened Advanced collaborators";
      },
      async () => { await page.getByRole("button", { name: "A2A发现", exact: true }).click(); await expect(modal()).toBeVisible(); return "opened the real discovery modal"; },
      async () => {
        await modal().getByPlaceholder("https://example.com/.well-known/agent-xxx.json").fill(`${settings.product_url}/basic/.well-known/agent-card.json?test_run=${nonce}`);
        await modal().getByPlaceholder('{"Authorization": "Bearer <token>"}').fill(JSON.stringify({ "X-Nexent-Test-Run": nonce }));
        return "entered machine-configured product URL and the non-secret custom header";
      },
      async () => {
        const responsePromise = page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("/a2a/client/discover/url"));
        await modal().getByRole("button", { name: "A2A发现", exact: true }).click();
        const response = await responsePromise;
        expect(response.status()).toBe(200);
        const data = (await response.json()).data;
        externalId = Number(data.id); externalName = data.name;
        expect(externalId).toBeGreaterThan(0);
        registerReadyAsset("owned_a2a", String(externalId), String(externalId), caseId, {
          service: "config", identity: "tenant_a_admin", method: "DELETE",
          path: `/a2a/client/agents/${externalId}`, allowed_statuses: [200, 404],
        });
        await expect(modal().getByText(externalName, { exact: true })).toBeVisible();
        return `real discovery returned owned external Agent ${externalId}`;
      },
      async () => {
        const relation = page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("/a2a/client/relations"));
        await modal().getByRole("button", { name: "添加为子 Agent", exact: true }).click();
        expect((await relation).status()).toBe(200);
        registerReadyAsset("owned_a2a_relations", String(localId), String(localId), caseId, {
          service: "config", identity: "tenant_a_admin", method: "DELETE", path: "/a2a/client/relations",
          params: { local_agent_id: localId, external_agent_id: externalId }, allowed_statuses: [200, 404],
        });
        return "selected the discovered Agent through the current Add-as-sub-Agent UI";
      },
      async () => {
        await modal().getByRole("button", { name: "Close", exact: true }).click();
        await page.reload({ waitUntil: "domcontentloaded" }); await agents.select(display);
        await agents.openAdvanced(); await agents.openSection("协作智能体");
        await expect(page.getByText(externalName, { exact: true }).first()).toBeVisible();
        const response = await page.request.get(`/api/a2a/client/relations/${localId}`);
        expect(response.status()).toBe(200);
        expect((await response.json()).data.some((row: any) => row.external_agent_id === externalId)).toBe(true);
        return "relationship is visible and persisted after editor reload";
      },
      async () => { invokedAfter = new Date().toISOString(); answer = await agents.debug("立即调用已绑定的外部 A2A 智能体，查询 pedestrian flow，返回其真实 total 字段。"); return "real LLM Debug delegated to the external Agent and reached its final answer"; },
      async () => { expect(answer).toMatch(totalField); return "Debug contains the deterministic total field value, allowing localized presentation"; },
      async () => {
        wire = await a2aProbe(["wire", "--nonce", nonce, "--after", invokedAfter]);
        expect(wire.get_count).toBeGreaterThan(0); expect(wire.post_count).toBeGreaterThan(0); expect(wire.authenticated).toBe(true);
        return "redacted discovery header and actual runtime invocation wire were archived";
      },
      async () => {
        await agents.select(display); await agents.openAdvanced(); await agents.openSection("协作智能体");
        const removal = page.waitForResponse((r) => r.request().method() === "DELETE" && r.url().includes("/a2a/client/relations"));
        await page.getByRole("button", { name: `移除 ${externalName}`, exact: true }).click();
        expect((await removal).status()).toBe(200);
        await page.reload({ waitUntil: "domcontentloaded" }); await agents.select(display);
        await agents.openAdvanced(); await agents.openSection("协作智能体");
        await expect(page.getByText(externalName, { exact: true })).toHaveCount(0);
        return "removed the relation through UI and confirmed its absence after reload";
      },
    ],
    assertions: [
      async () => { expect(localId).toBeGreaterThan(0); expect(externalId).toBeGreaterThan(0); return "discovery and binding used owned dynamic resources"; },
      async () => { expect(answer).toMatch(totalField); expect(wire.post_count).toBeGreaterThan(0); return "the Journey performed an actual external call, not a fabricated UI answer"; },
      async () => { const response = await page.request.get(`/api/a2a/client/relations/${localId}`); expect(response.status()).toBe(200); expect((await response.json()).data).toEqual([]); return "relationship removal persisted"; },
    ],
  });
});
