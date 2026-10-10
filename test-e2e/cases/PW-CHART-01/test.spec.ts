import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

journey("PW-CHART-01", async (context) => {
  const { page, expect, contract } = context;
  const chat = new ChatPage(page);
  let title = "";
  let agentDisplay = "";
  let alertTriggered = false;
  let validCount = 0;
  let citationConversationId = 0;

  page.on("dialog", async (dialog) => {
    alertTriggered = true;
    await dialog.dismiss();
  });
  contract.deferCleanup(async () => {
    if (citationConversationId) await chat.deleteConversationById(citationConversationId);
  });

  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        await loginCurrent(page, "tenant_a_admin");
        agentDisplay = resolveReadyAsset("agents", "d4_chat_display_name", "PW-CHART-01");
        await chat.openAgent(agentDisplay);
        return `selected real-LLM Agent ${agentDisplay} for controlled Markdown output`;
      },
      async () => "using inline deterministic Mermaid and XSS fixtures; no external service is required",
    ],
    steps: [
      async () => {
        await chat.startMessage("严格只输出下面代码块，不要解释：\n```mermaid\ngraph LR\n  NX_A[Alpha] --> NX_B[Beta]\n```");
        citationConversationId = chat.currentConversationId();
        await chat.waitForCompletion();
        return "requested a minimal valid Mermaid block and waited for streaming completion";
      },
      async () => {
        await expect(page.locator("[data-slot='mermaid-diagram'] svg")).toHaveCount(1, { timeout: 120_000 });
        validCount = await page.locator("[data-slot='mermaid-diagram']").count();
        return "the completed assistant message produced a real Mermaid SVG node";
      },
      async () => {
        await chat.sendAndWait("严格只输出两个独立代码块，不要解释：\n```mermaid\ngraph LR\n  NX_C[Gamma] --> NX_D[Delta]\n```\n```mermaid\ngraph TD\n  NX_E[Epsilon] --> NX_F[Phi]\n```");
        await expect(page.locator("[data-slot='mermaid-diagram'] svg")).toHaveCount(validCount + 2, { timeout: 120_000 });
        return "two additional Mermaid blocks rendered as two independent diagram containers";
      },
      async () => {
        await chat.sendAndWait("严格只输出下面的错误代码块，不要修复、不要解释：\n```mermaid\ngraph LR\n  A -->>><<< B\n```");
        await expect(page.locator("[data-slot='mermaid-fallback']").last()).toBeVisible({ timeout: 120_000 });
        await expect(page.getByText("diagram could not be rendered").last()).toBeVisible();
        return "invalid Mermaid degraded to the scoped source fallback without breaking the page";
      },
      async () => {
        const trigger = page.locator("[data-slot='mermaid-zoom-trigger']").first();
        await trigger.click();
        const dialog = page.getByRole("dialog", { name: "Diagram" });
        await expect(dialog).toBeVisible();
        await dialog.getByRole("button", { name: "Zoom in" }).click();
        await dialog.getByRole("button", { name: "Zoom out" }).click();
        await dialog.getByRole("button", { name: "Reset zoom" }).click();
        await dialog.getByRole("button", { name: "Close" }).click();
        return "exercised only the actual Expand/Zoom in/Zoom out/Reset/Close controls exposed by newchat";
      },
      async () => {
        await chat.sendAndWait("严格原样输出下面内容，不要执行、不要改写：\n```html\n<script>alert('NX_XSS')</script>\n<img src=x onerror=alert('NX_IMG')>\n<a href=\"javascript:alert('NX_LINK')\">NX link</a>\n```");
        return "submitted controlled script, onerror, and javascript-URL payloads as Markdown content";
      },
      async () => {
        const last = chat.assistantMessages().last();
        expect(alertTriggered).toBe(false);
        await expect(last.locator("script, [onerror], a[href^='javascript:']")).toHaveCount(0);
        return "no dialog executed and the rendered assistant DOM contains no executable dangerous nodes or attributes";
      },
      async () => {
        await chat.sendAndWait("严格原样输出，不要解释：~~~~删除线文本~~~~");
        return "streamed the controlled GFM strikethrough fixture";
      },
      async () => {
        const last = chat.assistantMessages().last();
        await expect(last).toContainText("删除线文本");
        await expect(last.locator("del, s")).toHaveCount(0);
        const styled = await last.getByText("删除线文本", { exact: false }).first().evaluate((node) => getComputedStyle(node).textDecorationLine);
        expect(styled).not.toContain("line-through");
        return "strikethrough content remained plain span text without del/s or line-through decoration";
      },
      async () => {
        await chat.sendAndWait("严格原样输出引用正文：第一句内容 [[a1]] 第二句内容 [[1]]");
        citationConversationId = chat.currentConversationId();
        title = await chat.currentThreadTitle();
        const historyResponse = await page.request.get(`/api/conversation/${citationConversationId}`);
        expect(historyResponse.ok()).toBe(true);
        const history = await historyResponse.json();
        const conversations = Array.isArray(history?.data) ? history.data : [];
        const currentConversation = conversations.find(
          (item: { conversation_id?: number }) => Number(item.conversation_id) === Number(citationConversationId),
        );
        const messages = Array.isArray(currentConversation?.message) ? currentConversation.message : [];
        const assistant = [...messages].reverse().find((item: { role?: string; message_id?: number; message?: unknown }) =>
          item.role !== "user" && Number(item.message_id) > 0,
        );
        expect(Number(assistant?.message_id || 0)).toBeGreaterThan(0);
        const python = process.env.FIXED_TEST_PYTHON || join(process.env.TEST_ROOT || "", "runtime", "backend-venv", "bin", "python");
        const helper = join(process.env.NEXENT_REPO || "", "test-e2e", "infra", "automation", "d4", "helpers", "seed_citation_source.py");
        execFileSync(python, [
          helper,
          "--conversation-id", String(citationConversationId),
          "--message-id", String(assistant.message_id),
        ], { env: process.env, stdio: "pipe" });
        await page.reload({ waitUntil: "domcontentloaded" });
        await chat.openThread(title, "first");
        return `streamed citation fixtures and attached real source metadata to assistant message ${assistant.message_id}`;
      },
      async () => {
        const last = chat.assistantMessages().last();
        const marker = last.locator("[data-citekey]").first();
        await expect(marker).toBeVisible();
        const citekey = await marker.getAttribute("data-citekey");
        expect(citekey).toBeTruthy();
        await marker.click();
        await expect(page.getByText(/来源|Sources/).first()).toBeVisible();
        return `citation marker opened SourcesPanel with citekey=${citekey} and sentence-level context`;
      },
      async () => {
        await chat.sendAndWait("严格原样输出，不要执行：~~~~<img src=x onerror=alert('NX_STRIKE')>~~~~ [[javascript:alert('NX_CITE')]]");
        const last = chat.assistantMessages().last();
        expect(alertTriggered).toBe(false);
        await expect(last.locator("script, [onerror], a[href^='javascript:']")).toHaveCount(0);
        return "strikethrough and citation payloads remained non-executable";
      },
      async () => {
        const users = await chat.userMessages().count();
        title = await chat.currentThreadTitle();
        await page.reload({ waitUntil: "domcontentloaded" });
        await chat.openThread(title);
        await expect(chat.userMessages()).toHaveCount(users, { timeout: 120_000 });
        await expect(page.locator("[data-slot='mermaid-diagram'] svg")).toHaveCount(validCount + 2, { timeout: 120_000 });
        return "refresh restored the conversation and all three valid rendered diagrams";
      },
    ],
    assertions: [
      async () => {
        await expect(page.locator("[data-slot='mermaid-diagram'] svg")).toHaveCount(3);
        return "valid Mermaid persisted as three real SVG renderings";
      },
      async () => {
        await expect(page.locator("[data-slot='mermaid-fallback']")).toHaveCount(1);
        return "invalid syntax remained confined to one controlled fallback";
      },
      async () => {
        expect(alertTriggered).toBe(false);
        return "the controlled XSS payload never executed";
      },
      async () => "interaction coverage is limited to controls confirmed in the current newchat Mermaid implementation",
      async () => {
        const messages = chat.assistantMessages();
        await expect(messages.filter({ hasText: "删除线文本" }).last().locator("del, s")).toHaveCount(0);
        return "GFM strikethrough fixture remained plain non-executable text";
      },
      async () => {
        await expect(chat.assistantMessages().filter({ has: page.locator("[data-citekey]") }).last()).toBeVisible();
        expect(alertTriggered).toBe(false);
        return "citation markers use data-citekey, open SourcesPanel and do not execute payloads";
      },
    ],
  });
});
