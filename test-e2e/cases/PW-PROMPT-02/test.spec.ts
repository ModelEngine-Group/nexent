import type { Locator } from "playwright/test";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { configuredModel, runToken, testAssetPath } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { ModelPage } from "../../infra/automation/d4/pages/model.page";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";
import { registerReadyAsset } from "../../infra/automation/d4/runner/assets";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { KnowledgePage } from "../../infra/automation/d4/pages/knowledge.page";

journey("PW-PROMPT-02", async (context) => {
  const { page, expect } = context;
  const token = runToken("PW-PROMPT-02");
  const oldMarker = `D4_OLD_${token}`;
  const newMarker = `D4_NEW_${token}`;
  const question = `请回复当前配置要求的唯一状态标记 ${token}`;
  const agents = new AgentPage(page);
  const models = new ModelPage(page);
  const llmAsset = configuredModel("llm");
  const compareModelName = llmAsset.candidates.find((name) => name !== llmAsset.displayName);
  let targetAgent = "";
  let firstRound: string[] = [];
  let secondRound: string[] = [];
  let normalAnswer = "";

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        expect(compareModelName, "Compare Mode requires a second real LLM candidate in config/models.yaml").toBeTruthy();
        const compareAsset = { ...llmAsset, model: compareModelName!, displayName: compareModelName! };
        await models.open();
        if (await models.modelExists(compareModelName!, "llm")) {
          await models.alignPersistedModel(compareAsset, compareModelName!, "llm");
          await models.verifyPersistedModel(compareModelName!, "llm");
        } else {
          const added = await models.addConfiguredModel(compareAsset, compareModelName!);
          expect(added.connectivityStatus).toBe(200);
          expect(added.createStatus).toBe(200);
          await models.expectModel(compareModelName!, "llm");
        }
        targetAgent = resolveReadyAsset("agents", "d4_llm_agent_display_name", "PW-PROMPT-02");
        await agents.open();
        await agents.select(targetAgent);
        expect(llmAsset.secret.length).toBeGreaterThan(8);
        return `selected ${targetAgent} and verified two configured real LLMs: ${llmAsset.displayName}/${compareModelName}`;
      },
      async () => {
        const author = await agents.ensureAuthor();
        return `confirmed persisted author ${author} before Debug form validation`;
      },
      async () => {
        expect(question).toContain(token);
        return `prepared one fixed badcase question and distinct old/new marker oracles ${oldMarker}/${newMarker}`;
      },
    ],
    steps: [
      async () => {
        await agents.setPrompts({ duty: `任何问题都只回复固定标记 ${oldMarker}` });
        await agents.openDebug();
        return "opened the real Debug panel after persisting the first-round Prompt";
      },
      async () => {
        await agents.openDebugCompare();
        return "enabled the visible top Compare Mode switch and rendered two model selectors";
      },
      async () => {
        firstRound = await agents.sendDebugCompare(question, oldMarker);
        expect(firstRound).toHaveLength(2);
        for (const answer of firstRound) expect(answer).toContain(oldMarker);
        return `first compare round produced two isolated rendered answers containing ${oldMarker}`;
      },
      async () => {
        await agents.setPrompts({ duty: `任何问题都只回复固定标记 ${newMarker}` });
        return `updated the behavior-affecting duty Prompt to ${newMarker} and observed autosave`;
      },
      async () => {
        secondRound = await agents.sendDebugCompare(question, newMarker);
        expect(secondRound).toHaveLength(2);
        for (const answer of secondRound) expect(answer).toContain(newMarker);
        return "reran the identical badcase in the same Compare UI after the Prompt autosave";
      },
      async () => {
        expect(firstRound.join("\n")).toContain(oldMarker);
        expect(secondRound.join("\n")).toContain(newMarker);
        expect(secondRound.join("\n")).not.toBe(firstRound.join("\n"));
        expect(await page.locator("[data-slot='aui_assistant-message-root']").count()).toBeGreaterThanOrEqual(4);
        return "both rounds remain separately rendered and the second did not overwrite the first";
      },
      async () => {
        for (const answer of secondRound) expect(answer).toContain(newMarker);
        return `the second-round structural oracle passed on both model columns with ${newMarker}`;
      },
      async () => {
        await agents.closeDebugCompare();
        normalAnswer = await agents.sendDebug(`只回复 ${newMarker}`, newMarker);
        return "disabled Compare Mode and completed one normal Debug run with the updated Prompt";
      },
    ],
    assertions: [
      async () => {
        expect(firstRound).toHaveLength(2);
        expect(secondRound).toHaveLength(2);
        return "Compare Mode was a real visible UI state with two independent model outputs per round";
      },
      async () => {
        for (const answer of secondRound) expect(answer).toContain(newMarker);
        return "the second compare round used the newly autosaved Prompt";
      },
      async () => {
        expect(firstRound.join("\n")).toContain(oldMarker);
        expect(secondRound.join("\n")).toContain(newMarker);
        expect(normalAnswer).toContain(newMarker);
        return "old/new outputs stayed distinguishable and normal Debug remained usable after Compare Mode closed";
      },
    ],
  });
});
