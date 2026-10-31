// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import { executeFixedScenario } from "../../infra/automation/d4/runner/scenario";
import {
  configuredModel,
  runToken,
} from "../../infra/automation/d4/runner/runtime-config";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { registerReadyAsset } from "../../infra/automation/d4/runner/assets";
import { a2aProbe } from "../../infra/automation/d4/runner/a2a";
import { PublicationPage } from "../../infra/automation/d4/pages/publication.page";
import { AgentPage } from "../../infra/automation/d4/pages/agent.page";

journey("PW-A2A-PUBLISH-01", async (context) => {
  const { page, contract, expect } = context;
  const caseId = "PW-A2A-PUBLISH-01";
  const nonce = `${caseId}-${runToken(caseId)}`;
  const display = `A2A Publish ${runToken(caseId)}`;
  const marker = `A2A_PUBLISHED_${runToken(caseId)}`;
  const agents = new AgentPage(page);
  const publicationPage = new PublicationPage(page);
  let editorUrl = "";
  let agentId = 0;
  let endpoint = "";
  let version = "";
  let card: any;
  let called = false;
  let northboundUrl = "";
  contract.deferCleanup(async () => {
    if (!agentId) return;
    await agents.delete(agentId);
  });
  await executeFixedScenario(context, {
    preconditions: [
      async () => {
        expect(configuredModel("llm").model).not.toBe("");
        await loginCurrent(page, "tenant_a_admin");
        await agents.open();
        return "configured real LLM and editable Agent page are available";
      },
      async () => {
        const settings = await a2aProbe(["northbound-config"]);
        northboundUrl = settings.northbound_url;
        return "loaded the configured real Northbound service URL without a Mock dependency";
      },
      async () => {
        expect(northboundUrl).toMatch(/^https?:\/\//);
        return "independent Python client uses configured endpoints and does not expose credentials to browser traces";
      },
    ],
    steps: [
      async () => {
        agentId = await agents.create(
          display,
          `a2a_publish_${runToken(caseId)}`,
        );
        registerReadyAsset(
          "owned_a2a_local",
          String(agentId),
          String(agentId),
          caseId,
          {
            service: "config",
            identity: "tenant_a_admin",
            method: "DELETE",
            path: "/agent",
            json: { agent_id: agentId },
            allowed_statuses: [200, 404],
          },
        );
        await agents.selectModel(configuredModel("llm").displayName);
        await agents.setDescription(`Published A2A smoke ${nonce}`);
        await agents.setPrompts({
          duty: `严格按用户要求输出标记，测试标记是 ${marker}。`,
        });
        await agents.ensureAuthor();
        editorUrl = page.url();
        const unregistered = page.waitForResponse(
          (r) =>
            r
              .url()
              .includes(`/api/a2a/management/agents/${agentId}/settings`) &&
            r.request().method() === "GET",
        );
        await agents.publishVersion(
          `ordinary-${runToken(caseId)}`,
          "Unregistered A2A guidance",
          { expectPublication: true },
        );
        expect((await unregistered).status()).toBe(404);
        await expect(
          publicationPage.content.getByText(/此已发布智能体尚未启用 A2A/),
        ).toBeVisible();
        await expect(
          publicationPage.content.getByLabel("Agent Card URL", { exact: true }),
        ).toHaveCount(0);
        await expect(
          publicationPage.content.getByRole("button", {
            name: "重试",
            exact: true,
          }),
        ).toHaveCount(0);
        await publicationPage.configure();
        await agents.openAdvanced();
        await expect(
          page.getByRole("checkbox", { name: "启用A2A", exact: true }),
        ).toBeVisible();
        return "created a valid owned Draft and located the current A2A checkbox under Advanced";
      },
      async () => {
        const toggle = page.getByRole("checkbox", {
          name: "启用A2A",
          exact: true,
        });
        await expect(toggle).toBeVisible();
        if (!(await toggle.isChecked())) {
          const saved = page.waitForResponse(
            (r) =>
              r.request().method() === "POST" &&
              r.url().includes("/api/agent/update") &&
              r.request().postDataJSON()?.is_a2a === true,
          );
          await toggle.click();
          expect((await saved).status()).toBe(200);
        }
        return "enabled A2A through UI and awaited the actual autosave response";
      },
      async () => {
        const publication = page.waitForResponse(
          (r) =>
            r.request().method() === "POST" &&
            r.url().includes(`/api/agent/${agentId}/publish`),
        );
        await agents.publishVersion(
          `a2a-${runToken(caseId)}`,
          "Owned A2A external smoke",
          { expectPublication: true },
        );
        const body = await (await publication).json();
        const data = body.data || body;
        endpoint = String(
          data.a2a_agent_card?.endpoint_id || data.a2a_agent?.endpoint_id || "",
        );
        version = String(data.version_no || "");
        expect(endpoint).not.toBe("");
        expect(version).not.toBe("");
        return "published a real version and captured its dynamic A2A endpoint";
      },
      async () => {
        const response = await page.request.get(
          `/api/a2a/management/agents/${agentId}/settings`,
        );
        expect(response.status()).toBe(200);
        const row = (await response.json()).data;
        expect(row.endpoint_id).toBe(endpoint);
        expect(String(row.version)).toBe(version);
        await publicationPage.assertLanding(editorUrl);
        await expect(
          publicationPage.content.getByLabel("Agent Card URL", { exact: true }),
        ).toHaveValue(`/nb/a2a/${endpoint}/.well-known/agent-card.json`);
        await expect(
          publicationPage.content.getByLabel("本地开发 Docker", {
            exact: true,
          }),
        ).toHaveValue("http://localhost:5013/api");
        await expect(
          publicationPage.content.getByLabel("本地开发 K8s", { exact: true }),
        ).toHaveValue("http://localhost:30013/api");
        expect(row.supported_interfaces.length).toBeGreaterThan(0);
        for (const entry of row.supported_interfaces) {
          if (/http\+json|httprest/i.test(entry.protocolBinding)) {
            const base = entry.url.replace(/\/$/, "");
            for (const path of [
              "/message:send",
              "/message:stream",
              "/tasks/{task_id}",
            ])
              await expect(
                publicationPage.content
                  .getByText(`${base}${path}`, { exact: false })
                  .last(),
              ).toBeVisible();
          } else if (/json-?rpc/i.test(entry.protocolBinding)) {
            await expect(
              publicationPage.content
                .getByText(entry.url, { exact: false })
                .last(),
            ).toBeVisible();
            await expect(
              publicationPage.content.getByText(
                'SendStreamingMessage: method="SendStreamingMessage"',
                { exact: false },
              ),
            ).toBeVisible();
          }
        }
        return "A2A registration, displayed card and advertised interface endpoints agree";
      },
      async () => {
        card = await a2aProbe([
          "card",
          "--endpoint",
          endpoint,
          "--version",
          version,
        ]);
        return "independent client discovered the actual published Agent Card";
      },
      async () => {
        expect(String(card.version)).toBe(version);
        expect(card.interfaces.length).toBeGreaterThan(0);
        expect(
          card.interfaces.some((row: any) => row.url.includes(endpoint)),
        ).toBe(true);
        return "the Card exposes this exact endpoint and published version";
      },
      async () => {
        const result = await a2aProbe([
          "call",
          "--endpoint",
          endpoint,
          "--version",
          version,
          "--nonce",
          nonce,
          "--marker",
          marker,
        ]);
        expect(result.marker_verified).toBe(true);
        called = true;
        return "independent authenticated external call returned the required real-model marker";
      },
      async () => {
        const settingsPath = `**/api/a2a/management/agents/${agentId}/settings`;
        await publicationPage.configure();
        let failedRequests = 0;
        await page.route(settingsPath, async (route) => {
          failedRequests += 1;
          await route.abort("failed");
        });
        try {
          await publicationPage.open();
          await expect(
            publicationPage.content.getByText("接入信息加载失败，请重试。", {
              exact: true,
            }),
          ).toBeVisible();
          expect(failedRequests).toBeGreaterThan(0);
        } finally {
          await page.unroute(settingsPath);
        }
        await publicationPage.content
          .getByRole("button", { name: "重试", exact: true })
          .click();
        await expect(
          publicationPage.content.getByLabel("Agent Card URL", { exact: true }),
        ).toHaveValue(`/nb/a2a/${endpoint}/.well-known/agent-card.json`);
        await expect(
          publicationPage.content.getByText("接入信息加载失败，请重试。", {
            exact: true,
          }),
        ).toHaveCount(0);
        return "transport failure displayed retry and recovered the same endpoint after restoring transport";
      },
    ],
    assertions: [
      async () => {
        expect(agentId).toBeGreaterThan(0);
        expect(endpoint).not.toBe("");
        expect(String(card.version)).toBe(version);
        return "publication and A2A registration refer to the same owned version";
      },
      async () => {
        expect(called).toBe(true);
        return "external discovery and invocation both completed against the real service";
      },
      async () => {
        await publicationPage.assertLanding(editorUrl);
        await expect(
          publicationPage.content.getByLabel("Agent Card URL", { exact: true }),
        ).toHaveValue(`/nb/a2a/${endpoint}/.well-known/agent-card.json`);
        return "404 guidance and retry recovery preserved correct access details";
      },
    ],
  });
});
