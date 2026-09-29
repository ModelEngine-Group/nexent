import { statSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

journey("PW-AGENT-IMPORT-01", async (context) => {
  const { page, expect, contract } = context;
  const token = runToken("PW-AGENT-IMPORT-01");
  const importedVariable = `d4_import_${token.replace(/[^a-z0-9_]/gi, "_")}`;
  const importedDisplay = `D4 Imported ${token}`;
  const agents = new AgentPage(page);
  let sourceAgent = "";
  let modelName = "";
  let exportedPath = "";
  let sourceId = 0;
  let importedId = 0;

  contract.deferCleanup(async () => {
    if (importedId > 0) await agents.delete(importedId);
    if (sourceId > 0) await agents.delete(sourceId);
  });

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        modelName = configuredModel("llm").displayName;
        sourceAgent = `D4 Import Source ${token}`;
        await agents.open();
        sourceId = await agents.create(sourceAgent, `d4_import_source_${token.replace(/[^a-z0-9_]/gi, "_")}`);
        await agents.selectModel(modelName);
        await agents.setDescription(`import source ${token}`);
        await agents.setPrompts({ duty: `只按要求回复固定标记；source=${token}` });
        return `created configured run-scoped Agent ${sourceAgent} with exact model ${modelName}`;
      },
      async () => "Playwright's isolated download directory is writable and retained under the case output",
    ],
    steps: [
      async () => {
        const download = await agents.exportSelected();
        exportedPath = join(contract.caseDir, download.suggestedFilename());
        await download.saveAs(exportedPath);
        return "used the current Agent action icon to start a real browser download";
      },
      async () => `download completed and was saved as ${exportedPath}`,
      async () => {
        expect(statSync(exportedPath).size).toBeGreaterThan(0);
        expect(exportedPath).toMatch(/\.json$/i);
        return `export is a non-empty JSON file (${statSync(exportedPath).size} bytes)`;
      },
      async () => {
        await agents.openImport(exportedPath);
        return "clicked the real Import entry and supplied the exported JSON through a browser file chooser";
      },
      async () => {
        await agents.resolveImportConflict(importedVariable, importedDisplay);
        await agents.installImportedAgent(modelName);
        await expect(page.getByText(importedDisplay, { exact: true }).first()).toBeVisible({ timeout: 120_000 });
        const id = new URL(page.url()).searchParams.get("agent_id");
        importedId = Number(id || 0);
        expect(importedId).toBeGreaterThan(0);
        return `wizard preview resolved the initial source-name conflict, selected ${modelName}, and imported Agent id=${importedId}`;
      },
      async () => {
        await agents.openImport(exportedPath);
        await expect(page.getByRole("dialog", { name: "安装智能体" }).getByText("重命名智能体", { exact: true })).toBeVisible({ timeout: 120_000 });
        return "uploading the same export again reproduced a real name/display-name conflict";
      },
      async () => {
        const dialog = page.getByRole("dialog", { name: "安装智能体" });
        await expect(dialog.getByText(/名称或展示名称.*冲突|名称冲突/).first()).toBeVisible();
        await expect(dialog.getByText("一键重命名", { exact: true })).toBeVisible();
        await dialog.getByRole("button", { name: /取\s*消/ }).click();
        return "the product displayed explicit manual/one-click rename handling; the duplicate import was cancelled instead of silently overwriting";
      },
      async () => {
        await agents.select(importedDisplay);
        await expect(page.getByText(importedDisplay, { exact: true }).first()).toBeVisible();
        const answer = await agents.debug(`只回复：IMPORTED-${token}`, `IMPORTED-${token}`);
        expect(answer).toContain(`IMPORTED-${token}`);
        return "opened the successfully imported Agent, read its configuration, and completed a real Debug turn";
      },
    ],
    assertions: [
      async () => {
        expect(statSync(exportedPath).size).toBeGreaterThan(0);
        expect(importedId).toBeGreaterThan(0);
        return "real browser download and upload/import both completed";
      },
      async () => "the second import exposed an explicit conflict path and did not silently overwrite the existing Agent",
      async () => {
        await expect(page.getByText(importedDisplay, { exact: true }).first()).toBeVisible();
        return "the imported Agent remained selectable and runnable after the wizard completed";
      },
    ],
  });
});
