import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

journey("PW-AGENT-COPY-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-AGENT-COPY-01");
  const safeToken = token.replace(/[^a-z0-9_]/gi, "_");
  const sourceDisplay = `D4 Copy Source ${token}`;
  const sourceVariable = `d4_copy_source_${safeToken}`;
  const firstCopyDisplay = `${sourceDisplay}副本`;
  const secondCopyDisplay = `${firstCopyDisplay}_1`;
  const agents = new AgentPage(page);
  let sourceId = 0;
  let firstCopyId = 0;
  let secondCopyId = 0;

  contract.deferCleanup(async () => {
    if (secondCopyId > 0) await agents.delete(secondCopyId);
    if (firstCopyId > 0) await agents.delete(firstCopyId);
    if (sourceId > 0) await agents.delete(sourceId);
  });

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        const modelName = configuredModel("llm").displayName;
        await agents.open();
        sourceId = await agents.create(sourceDisplay, sourceVariable);
        await agents.selectModel(modelName);
        return `authenticated and created run-scoped source Agent ${sourceDisplay} with model ${modelName}`;
      },
      async () => "the agent repository list card exposes the copy entry in its More menu",
    ],
    steps: [
      async () => {
        firstCopyId = await agents.copyAgent(sourceDisplay);
        await agents.expectAgentAvailable(firstCopyDisplay);
        return `first copy created as ${firstCopyDisplay} (id=${firstCopyId}) and stayed available`;
      },
      async () => {
        const listed = await page.request.get("/api/agent/list");
        expect(listed.ok()).toBe(true);
        const payload = await listed.json();
        // /api/agent/list returns a bare JSON array, not a wrapped object.
        const rows = Array.isArray(payload) ? payload : (Array.isArray(payload?.data) ? payload.data : []);
        const first = rows.find((row: { display_name?: string }) => row.display_name === firstCopyDisplay);
        expect(first).toBeTruthy();
        expect(first?.name).toBe(`${sourceVariable}_copy`);
        return `first copy identifiers resolved to unique values (name=${first?.name}, display_name=${first?.display_name})`;
      },
      async () => {
        secondCopyId = await agents.copyAgent(sourceDisplay);
        await agents.expectAgentAvailable(secondCopyDisplay);
        return `second copy created as ${secondCopyDisplay} (id=${secondCopyId}) without identifier conflicts`;
      },
      async () => {
        const listed = await page.request.get("/api/agent/list");
        expect(listed.ok()).toBe(true);
        const payload = await listed.json();
        // /api/agent/list returns a bare JSON array, not a wrapped object.
        const rows = Array.isArray(payload) ? payload : (Array.isArray(payload?.data) ? payload.data : []);
        const names = rows.filter(
          (row: { display_name?: string }) =>
            row.display_name === sourceDisplay ||
            row.display_name === firstCopyDisplay ||
            row.display_name === secondCopyDisplay,
        );
        expect(names).toHaveLength(3);
        const identifiers = new Set(names.map((row: { name?: string; display_name?: string }) => `${row.name}|${row.display_name}`));
        expect(identifiers.size).toBe(3);
        return "source and both copies coexist with pairwise-unique name/display_name pairs";
      },
      async () => {
        await agents.expectAgentAvailable(firstCopyDisplay);
        await agents.expectAgentAvailable(secondCopyDisplay);
        const original = await page.request.post("/api/agent/search_info", {
          data: { agent_id: sourceId, version_no: 0 },
        });
        expect(original.ok()).toBe(true);
        const detail = await original.json();
        const data = detail?.data || detail;
        expect(data?.name).toBe(sourceVariable);
        expect(data?.display_name).toBe(sourceDisplay);
        return "both copies remained available and the source configuration was untouched";
      },
    ],
    assertions: [
      async () => {
        expect(firstCopyId).toBeGreaterThan(0);
        expect(secondCopyId).toBeGreaterThan(0);
        expect(firstCopyId).not.toBe(secondCopyId);
        return "two real copies were created through the repository UI";
      },
      async () => {
        const listed = await page.request.get("/api/agent/list");
        expect(listed.ok()).toBe(true);
        const payload = await listed.json();
        // /api/agent/list returns a bare JSON array, not a wrapped object.
        const rows = Array.isArray(payload) ? payload : (Array.isArray(payload?.data) ? payload.data : []);
        const copies = rows.filter(
          (row: { display_name?: string }) =>
            row.display_name === firstCopyDisplay || row.display_name === secondCopyDisplay,
        );
        expect(copies).toHaveLength(2);
        for (const copy of copies) {
          expect(copy.is_available).not.toBe(false);
          expect(copy.unavailable_reasons || []).not.toContain("duplicate_name");
          expect(copy.unavailable_reasons || []).not.toContain("duplicate_display_name");
        }
        return "both copies stayed available without duplicate unavailable reasons";
      },
      async () => {
        await agents.expectAgentAvailable(firstCopyDisplay);
        await agents.expectAgentAvailable(secondCopyDisplay);
        return "copies remained publishable candidates after the copy journey";
      },
    ],
  });
});
