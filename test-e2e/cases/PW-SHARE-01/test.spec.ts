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

journey("PW-SHARE-01",async(context)=>{
  const {page,expect,contract}=context;const token=runToken("PW-SHARE-01");const marker=`SHARE-${token}`;const late=`PRIVATE-${token}`;const chat=new ChatPage(page);const pdf=process.env.NEXENT_TEST_HOME?`${process.env.NEXENT_TEST_HOME}/assets/d4/sample.pdf`:"";let publicContext:Awaited<ReturnType<typeof loginIsolated>>["context"]|undefined;let shareUrl="";let conversationId=0;
  contract.deferCleanup(async()=>{await publicContext?.close();if(conversationId>0)await chat.deleteConversationById(conversationId);});
  await executeFixedScenario(context,{
    preconditions:[async()=>{expect(existsSync(pdf)).toBe(true);return"controlled PDF fixture exists";},async()=>"the test conversation will contain text and an attachment"],
    steps:[
      async()=>{await loginCurrent(page,"tenant_a_admin");await chat.openAgent(resolveReadyAsset("agents","d4_chat_display_name","PW-SHARE-01"));const chooser=page.waitForEvent("filechooser");await page.getByRole("button",{name:/上传文件|附件/}).click();await(await chooser).setFiles(pdf);await chat.sendAndWait(`请确认快照标记 ${marker}`);conversationId=chat.currentConversationId();await page.getByRole("button",{name:"分享对话",exact:true}).click();await page.getByRole("checkbox").first().check();return"opened share mode and selected the message group";},
      async()=>{const [response]=await Promise.all([page.waitForResponse(r=>r.request().method()==="POST"&&/\/api\/share\/conversation\/\d+/.test(r.url())),page.getByRole("button",{name:"复制链接",exact:true}).click()]);expect(response.ok()).toBe(true);const body=await response.json();const id=body.data?.share_id;conversationId=Number(response.url().match(/conversation\/(\d+)/)?.[1]);if(!id||!conversationId)throw new Error("share create response omitted share/conversation id");shareUrl=new URL(appPath(`/share/${id}`),page.url()).toString();return"created and recorded the share URL";},
      async()=>{const browser=page.context().browser();if(!browser)throw new Error("browser unavailable");publicContext=await browser.newContext({locale:"zh-CN"});const publicPage=await publicContext.newPage();await publicPage.goto(shareUrl,{waitUntil:"domcontentloaded"});return"anonymous context opened the public URL";},
      async()=>{const p=publicContext!.pages()[0];await expect(p.getByText(`请确认快照标记 ${marker}`,{exact:true})).toBeVisible();await expect(p.getByPlaceholder("发送消息...")).toHaveCount(0);return"public page rendered snapshot in read-only mode";},
      async()=>{const p=publicContext!.pages()[0];const attachment=p.getByText("sample.pdf",{exact:false}).first();await expect(attachment).toBeVisible();await attachment.click();const button=p.getByRole("button",{name:/下载/}).last();await expect(button).toBeVisible();const download=p.waitForEvent("download");await button.click();const artifact=await download;expect(artifact.suggestedFilename()).toMatch(/sample\.pdf/i);return"public attachment preview opened and a real sample.pdf browser download completed";},
      async()=>{await expect(page.getByRole("button",{name:"复制链接",exact:true})).toHaveCount(0);await chat.sendAndWait(`新增未分享消息 ${late}`);return"owner appended a post-snapshot message";},
      async()=>{const p=publicContext!.pages()[0];await p.reload({waitUntil:"domcontentloaded"});await expect(p.getByText(late,{exact:false})).toHaveCount(0);return"public refresh did not leak later content";},
      async()=>{const expired=await page.request.post(`/api/share/conversation/${conversationId}`,{data:{mode:"all",selected_user_message_ids:[],render_version:"newchat",expire_time:"2000-01-01T00:00:00Z"}});expect(expired.ok()).toBe(true);const body=await expired.json();const id=body.data?.share_id;if(!id)throw new Error("expired share response omitted share_id");shareUrl=new URL(appPath(`/share/${id}`),page.url()).toString();return"created a controlled already-expired share through the product API contract";},
      async()=>{const p=publicContext!.pages()[0];const sharePath=new URL(shareUrl).pathname.replace(/^\/[^/]+\/share\//,"/api/share/");const [snapshot]=await Promise.all([p.waitForResponse(r=>r.request().method()==="GET"&&new URL(r.url()).pathname===sharePath),p.goto(shareUrl,{waitUntil:"domcontentloaded"})]);if(snapshot.status()!==404){const error=new Error(`Expired share must return HTTP 404; got ${snapshot.status()}`);error.name="ProductFailure";throw error;}await expect(p.getByText(/过期|无效|无法打开|expired/i)).toBeVisible();return"expired public URL rendered invalid/expired state";},
    ],
    assertions:[async()=>"the anonymous page exposed only selected snapshot content",async()=>"attachment preview/download used the public share surface",async()=>"expired share was unreadable",async()=>"Range and token tampering remain assigned to contract/security stages"],
  });
});
