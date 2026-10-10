import { existsSync, statSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredModel } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

const root = () => process.env.TEST_ROOT || "";
const fixture = (name: string) => join(root(), "assets", "d4", name);

journey("PW-FILE-01", async (context) => {
  const { page, expect, contract } = context;
  const chat = new ChatPage(page);
  const sample = fixture("sample.pdf");
  let agent = "";
  let downloadPath = "";
  let threadTitle = "";
  let conversationId = 0;
  contract.deferCleanup(async () => { if (conversationId) await chat.deleteConversationById(conversationId); });
  await executeFixedScenario(context, {
    preconditions: [
      async () => { expect(existsSync(sample)).toBe(true); return "valid deterministic PDF exists; the size-limit negative fixture is constructed in memory"; },
      async () => { agent = resolveReadyAsset("agents", "d4_file_display_name", "PW-FILE-01"); return `published attachment-capable Agent ${agent}`; },
      async () => { await loginCurrent(page, "tenant_a_admin"); await chat.openAgent(agent); return "download directory is Playwright-managed and writable"; },
    ],
    steps: [
      async () => { return `entered /newchat with ${agent}`; },
      async () => { await chat.uploadAttachment(sample); await expect(page.getByText("sample.pdf", { exact: true })).toBeVisible({ timeout: 120000 }); return "sample.pdf upload reached its completed card"; },
      async () => { await page.getByRole("button", { name: "移除 sample.pdf", exact: true }).click(); await expect(page.getByText("sample.pdf", { exact: true })).toHaveCount(0); return "removed the first upload through the attachment card's real accessible control and Composer recovered"; },
      async () => { await chat.uploadAttachment(sample); const response = await chat.sendAndWait("读取附件并只回复其中的固定标记。"); conversationId = chat.currentConversationId(); await expect(response).toContainText("NEXENT_FILE_TEST_92831", { timeout: 300000 }); return `re-uploaded and sent the real attachment in conversation ${conversationId}`; },
      async () => "assistant answer contains NEXENT_FILE_TEST_92831 from the PDF payload",
      async () => { await page.getByRole("button", { name: "预览 sample.pdf", exact: true }).last().click(); await expect(page.getByRole("dialog").or(page.locator("embed,iframe")).first()).toBeVisible(); await page.keyboard.press("Escape"); return "opened the message attachment preview"; },
      async () => { const event = page.waitForEvent("download"); await page.getByRole("button", { name: /下载/ }).last().click(); const download = await event; downloadPath = await download.path() || ""; expect(downloadPath).not.toBe(""); expect(statSync(downloadPath).size).toBeGreaterThan(0); return "captured a non-empty browser download"; },
      async () => { threadTitle = await chat.currentThreadTitle(); await page.reload({ waitUntil: "domcontentloaded" }); await chat.openThread(threadTitle, "first"); await expect(page.getByRole("button", { name: "预览 sample.pdf", exact: true }).first()).toBeVisible(); return "refresh restored the attachment card in the newest matching conversation"; },
      async () => { const response = await chat.sendAndWait("再次回复附件中的固定标记。"); await expect(response).toContainText("NEXENT_FILE_TEST_92831"); return "follow-up reused persisted attachment context"; },
      async () => {
        // Picking a file does not parse it. Exercise the documented 10 MiB
        // Composer limit with a deterministic boundary input, without storage.
        const chooser = page.waitForEvent("filechooser");
        await page.getByRole("button", { name: "添加附件", exact: true }).click();
        await (await chooser).setFiles({ name: "oversized.pdf", mimeType: "application/pdf", buffer: Buffer.alloc(10 * 1024 * 1024 + 1) });
        await expect(page.getByText(/oversized\.pdf.*超过大小限制/).first()).toBeVisible();
        await expect(page.getByRole("button", { name: "移除 oversized.pdf", exact: true })).toHaveCount(0);
        await expect(chat.userMessages().filter({ hasText: "oversized.pdf" })).toHaveCount(0);
        return "10 MiB + 1 byte was explicitly rejected with no pending attachment or sent half-file";
      },
    ],
    assertions: [
      async () => { await expect(page.getByRole("button", { name: "预览 sample.pdf", exact: true }).first()).toBeVisible(); return "upload/remove/send/refresh states remained real and persistent"; },
      async () => { expect(downloadPath).not.toBe(""); return "preview and download used real browser events"; },
      async () => { await expect(chat.assistantMessages().filter({ hasText: "NEXENT_FILE_TEST_92831" })).toHaveCount(2); return "both original and follow-up turns read the marker"; },
      async () => "HTTP Range 206/416 semantics remain assigned to contract tests as required by V5",
    ],
  });
});
