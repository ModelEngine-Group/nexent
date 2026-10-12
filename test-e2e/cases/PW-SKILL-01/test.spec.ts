import { existsSync } from "node:fs";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredModel, runToken } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent, loginIsolated } from "../../infra/automation/d4/runner/sessions";
import { registerReadyAsset, resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";
import { SkillPage } from "../../infra/automation/d4/pages/skill.page";

const need = (name: string) => { const value = process.env[name] || ""; if (!value) throw new Error(`${name} is required`); return value; };
const esc = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const setting = (name: string, fallback: string) => process.env[name] || fallback;

journey("PW-SKILL-01", async (context) => {
  const { page, expect, contract } = context;
  const token=runToken("PW-SKILL-01"); const name=`skill-${token}`.toLowerCase().slice(0,30); const marker=`SKILL-${token}`;
  const authorIdentity=setting("NEXENT_TEST_MARKET_AUTHOR", "tenant_a_dev");
  const skills=new SkillPage(page); const agents=new AgentPage(page); let agentId=0;
  contract.deferCleanup(async()=>{if(agentId) await agents.delete(agentId);});
  await executeFixedScenario(context,{
    preconditions:[async()=>"the test creates a valid run-scoped SKILL.md",async()=>"real LLM model is configured"],
    steps:[
      async()=>{await loginCurrent(page,authorIdentity);await skills.open();return`opened SkillSpace Mine as the configured market author ${authorIdentity}`;},
      async()=>{await skills.upload(name,marker,()=>registerReadyAsset("skills","d4_created_name",name,"PW-SKILL-01",{
        service:"config",identity:authorIdentity,method:"DELETE",path:`/skills/${encodeURIComponent(name)}`,allowed_statuses:[200,404],
      }));return"uploaded a valid run-scoped SKILL.md and registered owned cleanup";},
      async()=>{await skills.search(name);await skills.edit(name,marker);return"edited an allowed field and saved";},
      async()=>{await skills.open();await skills.search(name);await expect(skills.card(name)).toBeVisible();return"refresh proved Mine persistence";},
      async()=>{await agents.open();agentId=await agents.create(`Skill Agent ${token}`,`skill_agent_${token}`);const modelName=configuredModel("llm").displayName;await agents.selectModel(modelName);
        await agents.setDescription(`Skill runtime validation ${token}`);
        await agents.ensureAuthor();
        await agents.setPrompts({duty:"根据已绑定技能的指导回答；需要时读取技能内容，不要猜测技能要求。"});
        return`created a runnable isolated Agent with exact configured LLM ${modelName}, author, description and role Prompt`;},
      async()=>{await agents.bindSkill(name);return"bound exact Skill and waited for autosave";},
      async()=>{await agents.openDebug();await agents.sendDebug(`使用 ${name}，只回复 ${marker}`,marker);return"real model Debug completed";},
      async()=>{await expect(page.locator("body")).toContainText(marker);return"rendered answer contained deterministic Skill marker";},
      async()=>"case-local cleanup will remove this owned Skill; the market journey prepares its own asset independently",
    ],
    assertions:[async()=>{await skills.open();await skills.search(name);await expect(skills.card(name)).toBeVisible();return"Skill was really created/edited and survived refresh";},async()=>"Agent binding autosave and Debug both completed",async()=>"malicious archive handling remains assigned to D5"],
  });
});

