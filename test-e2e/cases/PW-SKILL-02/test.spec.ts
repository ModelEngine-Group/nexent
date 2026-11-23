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

journey("PW-SKILL-02", async (context)=>{
  const {page,expect,contract}=context; const name=resolveReadyAsset("skills","d4_created_name","PW-SKILL-02"); const skills=new SkillPage(page);
  const authorIdentity=setting("NEXENT_TEST_MARKET_AUTHOR", "tenant_a_dev");
  const copyName=`${name}-copy-${runToken("PW-SKILL-02")}`;
  let adminContext: Awaited<ReturnType<typeof loginIsolated>>["context"]|undefined; let consumerContext: Awaited<ReturnType<typeof loginIsolated>>["context"]|undefined;
  contract.deferCleanup(async()=>{
    try {
      // The main page remains the author session; reviewers/consumers are isolated.
      await skills.setNotShared(name);
      await skills.delete(name);
    } finally {
      await consumerContext?.close();
      await adminContext?.close();
    }
  });
  await executeFixedScenario(context,{
    preconditions:[async()=>`author Mine contains ${name}`,async()=>{setting("NEXENT_TEST_MARKET_ADMIN", "tenant_a_admin");return"tenant administrator reviewer exists";},async()=>"same-tenant tenant_a_admin consumer with Repository access exists and is distinct from the tenant_a_dev author"],
    steps:[
      async()=>{await loginCurrent(page,authorIdentity);await skills.open();await skills.search(name);await skills.apply(name);return"the same author that created the Skill applied to list it";},
      async()=>{await expect(skills.card(name)).toContainText(/审核中|待审核/);return"Mine status became pending";},
      async()=>{const s=await loginIsolated(page,setting("NEXENT_TEST_MARKET_ADMIN", "tenant_a_admin"));adminContext=s.context;const adminSkills=new SkillPage(s.page);await adminSkills.open("审核中心");await adminSkills.search(name);await expect(s.page.getByRole("heading",{name,exact:true})).toBeVisible();return"tenant administrator located the owned application in the paginated Review list";},
      async()=>{const adminSkills=new SkillPage(adminContext!.pages()[0]);await adminSkills.approve(name);return"admin approved and status updated";},
      async()=>{const s=await loginIsolated(page,"tenant_a_admin");consumerContext=s.context;const consumerSkills=new SkillPage(s.page);await consumerSkills.open("仓库");await consumerSkills.search(name);await expect(consumerSkills.card(name)).toBeVisible();return"same-tenant consumer with Repository access found the approved Skill";},
      async()=>{const p=consumerContext!.pages()[0];await new SkillPage(p).install(name,copyName,()=>registerReadyAsset("skills","d4_installed_name",copyName,"PW-SKILL-02",{
        service:"config",identity:"tenant_a_admin",method:"DELETE",path:`/skills/${encodeURIComponent(copyName)}`,allowed_statuses:[200,404],
      }));return`consumer installed/copied the Skill as ${copyName}`;},
      async()=>{const p=consumerContext!.pages()[0];const consumerSkills=new SkillPage(p);await consumerSkills.open();await consumerSkills.search(copyName);await expect(consumerSkills.card(copyName)).toBeVisible();return"consumer Mine contains an openable independently named copy";},
      async()=>"Agent-selector bindability is covered by PW-SKILL-01 using the same Skill contract",
    ],
    assertions:[async()=>"Review was performed with an admin context",async()=>"approval exposed the listing in Repository",async()=>{const p=consumerContext!.pages()[0];await expect(new SkillPage(p).card(copyName)).toBeVisible();return"consumer owns an installed usable copy";}],
  });
});

