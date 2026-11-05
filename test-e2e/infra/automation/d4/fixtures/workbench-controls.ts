// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import type { Page } from "playwright/test";

export interface WorkbenchPinServer {
  scopes: Map<string, number[]>;
  rejectSave: boolean;
}

/** Controlled tenant APIs; no runtime generation or persistent writes are needed. */
export async function prepareWorkbench(page: Page, resourceCount = 1, options: { histories?: Array<Record<string, any>>; reasoning?: boolean; longDescriptions?: boolean; modelEffort?: string; agentEffort?: string; pinServer?: WorkbenchPinServer; samplingDefaults?: {temperature:number;top_p:number}; agentSamplingDefaults?: {temperature?:number;top_p?:number} } = {}) {
  const pinServer = options.pinServer ?? { scopes: new Map<string, number[]>(), rejectSave: false };
  const authorization = { permissions: ["agent:create", "skill:create"], userId: "workbench-fixture", tenantId: "workbench-tenant" };
  const writes: string[] = [];
  const filters: Array<Record<string, any>> = [];
  const agent = { id: "7", agent_id: 7, name: "Internal Analyst", display_name: "Internal Analyst", description: options.longDescriptions ? "Long resource description ".repeat(80) : "Internal tenant agent", current_version_no: 3, is_available: true, model_ids: options.reasoning ? [1, 2, 3] : [1], model_names: options.reasoning ? ["Fixture Model", "Plain Model", "Automatic Model"] : ["Fixture Model"], model_params_override: options.reasoning || options.agentSamplingDefaults ? { "1": { ...options.agentSamplingDefaults, ...(options.reasoning ? {extra_params: { enable_thinking: false, ...(options.agentEffort ? { reasoning_effort: options.agentEffort } : {}) }} : {}) } } : undefined };
  const capabilities = { agent_id: 1, version_no: 1, sources: {
    local: { enabled: true, max_select: 20, requires_same_embedding_model: false, default_summary: "", default_knowledge_ids: [], default_range_values: [] },
    aidp: { enabled: false, max_select: 20, default_summary: "", default_knowledge_ids: [], default_range_values: [] },
  } };
  await page.route("**/api/**", async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname;
    const body = request.postDataJSON();
    if (pathname.endsWith("/filter")) filters.push(body);
    else if (request.method() !== "GET" && pathname !== "/api/groups/list" && pathname !== "/api/conversation/list" && !pathname.endsWith("/preview")) writes.push(pathname);
    let result: unknown = {};
    if (pathname === "/api/tenant_config/deployment_version") result = { deployment_version: "speed", app_version: "test", status: "success", enable_agent_workbench: true };
    else if (pathname === "/api/user/current_user_info") result = { data: { user: { user_id: authorization.userId, tenant_id: authorization.tenantId, user_email: "fixture@nexent.test", user_role: "SPEED", auth_provider: "local", groupIds: [], permissions: authorization.permissions, accessibleRoutes: ["/", "/agents", "/workbench", "/newchat", "/skill-space", "/knowledge"] } } };
    else if (pathname === "/api/agent/workbench/bootstrap") result = { data: { schema_version: 3, modes: Object.fromEntries(["generic_chat", "single_agent_chat", "multi_agent_chat", "agent_create", "skill_create"].map(mode => [mode, { enabled: true }])), generic_agent: { agent_id: 1, version_no: 1, display_name: "Assistant", default_skill_resources: [] } } };
    else if (pathname === "/api/memory/config/load") result = { MEMORY_SWITCH: "N" };
    else if (pathname === "/api/agent/published_list") result = Array.from({ length: resourceCount }, (_, i) => ({ ...agent, id: String(7 + i), agent_id: 7 + i, name: i ? `Internal Analyst ${i}` : agent.name, display_name: i ? `Internal Analyst ${i}` : agent.display_name }));
    else if (pathname.endsWith("knowledge-capabilities")) result = { code: 0, data: capabilities };
    else if (pathname === "/api/agent/workbench/capabilities/preview") result = { data: { agent_id: 7, version_no: 3, default_skill_mounts: [], default_skill_resources: [], knowledge: capabilities } };
    else if (pathname === "/api/model/list") result = { data: [
      { ...options.samplingDefaults, model_id: 1, model_name: "fixture-model", display_name: "Fixture Model", model_type: "llm", model_factory: "openai", connect_status: "available",
        ...(options.reasoning ? { extra_params: { enable_thinking: false, ...(options.modelEffort ? { reasoning_effort: options.modelEffort } : {}) }, reasoning_capability: { status: "supported", control: "effort", levels: ["none", "minimal", "low", "medium", "high", "xhigh", "max"], controls: [{ type: "effort", values: ["none", "minimal", "low", "medium", "high", "xhigh", "max"] }], source: "catalog" } } : {}) },
      ...(options.reasoning ? [{ model_id: 2, model_name: "plain-model", display_name: "Plain Model", model_type: "llm", model_factory: "openai", connect_status: "available", reasoning_capability: { status: "unsupported", control: "effort", levels: [], source: "catalog" } }] : []),
      ...(options.reasoning ? [{model_id: 3, model_name: "automatic-model", display_name:"Automatic Model", model_type:"llm", model_factory:"openai", connect_status:"available", extra_params:{enable_thinking:false}, reasoning_capability:{status:"supported", control:"effort", levels:["low","high"], default:"high", controls:[{type:"effort",values:["low","high"]}],source:"catalog"}}] : []),
    ] };
    else if (pathname === "/api/skills") result = { skills: Array.from({ length: resourceCount }, (_, i) => ({ skill_id: 11 + i, name: i ? `Invoice Skill ${i}` : "Invoice Skill", description: options.longDescriptions ? "Long resource description ".repeat(80) : "Invoice extraction", source: "local", config_schemas: [], config_values: {} })) };
    else if (pathname.includes("repository") || pathname === "/api/groups/list") result = { items: [], data: [], total: 0, pagination: { total: 0 } };
    else if (pathname === "/api/indices/health") result = { status: "healthy", elasticsearch: "connected" };
    else if (pathname === "/api/indices") result = { indices: Array.from({ length: resourceCount }, (_, i) => i ? `company-docs-${i}` : "company-docs"), count: resourceCount, indices_info: Array.from({ length: resourceCount }, (_, i) => ({ name: i ? `company-docs-${i}` : "company-docs", display_name: i ? `Company Docs ${i}` : "Company Docs", knowledge_id: String(21 + i), description: options.longDescriptions ? "Long resource description ".repeat(80) : undefined, embedding_model_id: 1 })) };
    else if (pathname === "/api/tag-libraries") result = [{ bucket_id: 1, status: "active", resource_types: ["agent", "skill", "knowledge_base"] }];
    else if (pathname === "/api/tag-libraries/1/definitions") result = [{ definition_id: 1, bucket_id: 1, definition_key: "domain", definition_name: "Business", selection_mode: "multi_select", status: "active", values: [{ value_id: 1, display_value: "Finance", normalized_value: "finance", status: "active" }] }];
    else if (pathname.endsWith("/filter")) result = { matched_resource_ids: body?.resource_ids ?? [] };
    else if (pathname === "/api/conversation/list") {
      const offset = Number(new URL(request.url()).searchParams.get("offset") ?? 0);
      const limit = Number(new URL(request.url()).searchParams.get("limit") ?? 30);
      result = { code: 0, data: { items: (options.histories ?? []).slice(offset, offset + limit), metadata: { total: options.histories?.length ?? 0 } } };
    }
    else if (pathname === "/api/conversation/workbench_pins" || pathname.endsWith("/workbench_pin")) {
      const scope = JSON.stringify([authorization.userId]);
      let ids = pinServer.scopes.get(scope) ?? [];
      if (request.method() === "PUT") {
        if (pinServer.rejectSave) {
          await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "Workbench conversation not found" }) });
          return;
        }
        const id = Number(pathname.split("/").at(-2));
        ids = body.pinned ? ids.includes(id) ? ids : [id, ...ids] : ids.filter(value => value !== id);
        pinServer.scopes.set(scope, ids);
      }
      result = { code: 0, data: { items: ids.flatMap(id => {
        const history = options.histories?.find(item => item.conversation_id === id);
        return history ? [{ ...history, pinned_at: new Date().toISOString() }] : [];
      }) } };
    }
    else if (pathname === "/api/conversation/rename") {
      const history = options.histories?.find(item => item.conversation_id === body.conversation_id);
      if (history) history.conversation_title = body.name;
      result = { code: 0, data: {} };
    }
    else if (/^\/api\/conversation\/\d+$/.test(pathname) && options.histories) {
      const history = options.histories.find(item => String(item.conversation_id) === pathname.split("/").at(-1));
      result = { code: 0, data: history ? [{ ...history, message: [], workbench_config: { schema_version: 4, mode: "generic_chat", agent_mounts: [], skill_mounts: [] } }] : [] };
    }
    else if (pathname.includes("conversation") || pathname.includes("tool")) result = { code: 0, data: [], conversations: [], tools: [] };
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(result) });
  });
  await page.goto(`${process.env.NEXENT_BASE_URL ?? "http://localhost:3031"}/zh/workbench`);
  return { writes, filters, authorization, pinServer };
}
