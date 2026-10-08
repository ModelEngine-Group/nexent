import { existsSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import { appPath, configuredModel } from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { resolveReadyAsset } from "../../infra/automation/d4/runner/assets";
import { ChatPage } from "../../infra/automation/d4/pages/chat.page";

const root = () => process.env.TEST_ROOT || "";
const fixture = (name: string) => join(root(), "assets", "d4", name);

journey("PW-MEDIA-STT-01", async (context) => {
  const { page, expect, contract } = context;
  const chat = new ChatPage(page);
  const wav = process.env.NEXENT_TEST_STT_WAV || join(root(), "assets", "audio", "stt_zh_number.wav");
  let agent = "";
  let transcript = "";
  let conversationId = 0;
  contract.deferCleanup(async () => { if (conversationId) await chat.deleteConversationById(conversationId); });
  const sttSocketEvents: string[] = [];
  page.on("websocket", (socket) => {
    if (!/dashscope|api-ws|realtime|\/stt/i.test(socket.url())) return;
    sttSocketEvents.push(`opened:${socket.url().replace(/[?].*$/, "")}`);
    socket.on("framereceived", ({ payload }) => {
      const safePayload = typeof payload === "string" ? payload.slice(0, 800) : `<binary:${payload.byteLength}>`;
      sttSocketEvents.push(`received:${safePayload}`);
    });
    socket.on("socketerror", (error) => sttSocketEvents.push(`error:${String(error).slice(0, 500)}`));
    socket.on("close", () => sttSocketEvents.push("closed"));
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        if (process.env.NEXENT_TEST_STT_READY === "0") {
          const error = new Error(process.env.NEXENT_TEST_STT_FAILURE || "configured STT dependency is unavailable") as Error & { dependencyCaseId?: string };
          error.name = "DependencyFailure";
          error.dependencyCaseId = "D0-STT";
          throw error;
        }
        expect(existsSync(wav)).toBe(true);
        return `real WAV fixture exists: ${wav}`;
      },
      async () => { expect(process.env.NEXENT_TEST_BROWSER_FAKE_AUDIO || "").toBe(wav); return "browser fake-audio capture is explicitly bound to the fixed WAV"; },
      async () => { agent = resolveReadyAsset("agents", "d4_chat_display_name", "PW-MEDIA-STT-01"); return `READY published real-LLM Agent ${agent}`; },
    ],
    steps: [
      async () => { await loginCurrent(page, "tenant_a_admin"); await page.goto(appPath("/models")); await expect(page.getByText("语音识别模型", { exact: true })).toBeVisible(); return "STT model configuration page is present after real connectivity preflight"; },
      async () => { await chat.openAgent(agent); return `opened /newchat with ${agent}`; },
      async () => { const mic = page.locator("button:has(svg.lucide-mic)"); await expect(mic).toBeVisible(); await expect(mic).toBeEnabled(); await mic.click(); return "opened the Composer voice input through its real Mic icon button"; },
      async () => {
        await expect(page.locator("button:has(svg.lucide-mic-off)")).toBeVisible({ timeout: 60000 });
        const marker = /9\D*2\D*8\D*3\D*1|九\D*二\D*八\D*三\D*一/;
        await expect.poll(() => sttSocketEvents.filter(event => event.startsWith("received:")).join("\n"), { timeout: 120000 }).toMatch(marker);
        // A received final frame can precede its React composer update. Do not
        // stop capture on an older non-empty but truncated transcription.
        try {
          await expect(page.getByPlaceholder("发送消息...")).toHaveValue(marker, { timeout: 120000 });
        } catch {
          writeFileSync(join(contract.caseDir, "stt-websocket.json"), JSON.stringify(sttSocketEvents, null, 2), "utf8");
          const received = await page.getByPlaceholder("发送消息...").inputValue();
          const failure = new Error(`real STT wire returned the complete 92831 marker but Composer did not apply it within 120000ms without stopping capture; value=${JSON.stringify(received)}; evidence=stt-websocket.json`);
          failure.name = "ProductFailure";
          throw failure;
        }
        return `real STT wire and Composer both received the fixed WAV number marker: ${wav}`;
      },
      async () => { const stop = page.locator("button:has(svg.lucide-mic-off)"); if (await stop.isVisible()) await stop.click(); await expect(page.locator("button:has(svg.lucide-mic)")).toBeEnabled(); const composer = page.getByPlaceholder("发送消息..."); try { await expect(composer).not.toHaveValue("", { timeout: 180000 }); } catch { throw new Error(`STT returned no Composer text; websocket evidence=${JSON.stringify(sttSocketEvents)}`); } transcript = await composer.inputValue(); return `transcription completed: ${transcript}; websocket events=${sttSocketEvents.length}`; },
      async () => { if (!/Nex[ea]nt/i.test(transcript) || !/9\D*2\D*8\D*3\D*1|九\D*二\D*八\D*三\D*一/.test(transcript)) { const error = new Error(`STT Composer transcript failed the fixed keyword/number oracle: ${JSON.stringify(transcript)}; websocket evidence=${JSON.stringify(sttSocketEvents)}`); error.name = "ProductFailure"; throw error; } return "transcript satisfies the V5 keyword/CER oracle with punctuation and number-format tolerance"; },
      async () => {
        const run = page.waitForResponse(r => r.request().method() === "POST" && r.url().includes("/api/agent/run") && (r.headers()["content-type"] || "").includes("text/event-stream"));
        await page.getByRole("button", { name: "发送", exact: true }).click();
        const response = await run;
        const headers = await response.allHeaders();
        conversationId = Number(headers.conversation_id || response.request().postDataJSON()?.conversation_id);
        expect(Number.isInteger(conversationId) && conversationId > 0).toBe(true);
        await chat.waitForCompletion();
        return "transcribed text was sent and Chat completed with its server conversation id captured for cleanup";
      },
      async () => { await page.locator("button:has(svg.lucide-mic)").click(); await expect(page.locator("button:has(svg.lucide-mic-off)")).toBeVisible(); await page.locator("button:has(svg.lucide-mic-off)").click(); await expect(page.locator("button:has(svg.lucide-mic)")).toBeEnabled(); return "voice input reopened and returned to an enabled Mic state without a stale session"; },
    ],
    assertions: [
      async () => { expect(transcript).toMatch(/Nex[ea]nt/i); return "the configured real STT produced the required content within the declared CER tolerance"; },
      async () => { await expect(page.getByPlaceholder("发送消息...")).toBeVisible(); return "transcription entered the ordinary send path"; },
      async () => { await expect(page.locator("button:has(svg.lucide-mic)")).toBeEnabled(); return "voice connection terminated and Composer is not hung"; },
    ],
  });
});

