export function makeDraft(permission = "EDIT") {
  return {
    agent_id: 42,
    name: "fixture_agent",
    display_name: "健康小助手",
    description: "A deterministic health question assistant.",
    author: "Fixture Author",
    permission,
    created_by: "fixture-user",
    model_ids: [7],
    model_names: ["Fixture Model"],
    tools: [
      {
        tool_id: 9001,
        name: "knowledge_base_search",
        origin_name: "knowledge_base_search",
        description: "Fixture knowledge-base retrieval",
        params: [
          {
            name: "index_names",
            type: "array",
            optional: true,
            default: ["fixture-kb"],
          },
        ],
      },
    ],
    skills: [],
    sub_agent_id_list: [],
    sub_agent_relations: [],
    external_sub_agent_id_list: [],
    group_ids: [],
    ingroup_permission: "READ_ONLY",
    greeting_message: "你好，我可以帮助你解答健康问题。",
    example_questions: [
      "如何保持健康？",
      "每天应该运动多久？",
      "怎样改善睡眠？",
    ],
    max_steps: 10,
    requested_output_tokens: 4096,
    is_main_agent: true,
    is_a2a: false,
    provide_run_summary: false,
    allow_chat_metadata: false,
    enable_protocol_repair_retry: false,
    is_available: true,
    unavailable_reasons: [],
    verification_config: {
      enabled: false,
      guardrail_config: { enabled: false, rules: [], default_action: "pass" },
    },
    duty_prompt: "Answer the question using the draft Agent configuration.",
    constraint_prompt: "",
    few_shots_prompt: "",
    current_version_no: null,
  };
}

/** Handle shared read-only editor fixtures; journey-specific writes stay in callers. */
export async function fulfillEditorReadFixture(route, endpoint) {
  const respond = async (requestRoute, body, status = 200) => {
    await requestRoute.fulfill({
      status,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
    return true;
  };
  if (endpoint === "/tenant_config/deployment_version")
    return respond(route, {
      deployment_version: "speed",
      app_version: "fixture",
      status: "success",
    });
  if (endpoint === "/user/current_user_info")
    return respond(route, {
      data: {
        user: {
          user_id: "fixture-user",
          tenant_id: "fixture-tenant",
          user_email: "fixture@nexent.test",
          user_role: "SPEED",
          auth_provider: "local",
          group_ids: [],
          permissions: [],
          accessibleRoutes: [
            "/agents",
            "/mcp-space",
            "/knowledges",
            "/newchat",
          ],
        },
      },
    });
  if (endpoint === "/groups/list")
    return respond(route, { data: [], total: 0, message: "ok" });
  if (endpoint === "/conversation/list")
    return respond(route, {
      code: 0,
      data: {
        items: [],
        metadata: { total: 0, today: 0, last_7_days: 0, older: 0 },
      },
    });
  if (endpoint === "/agent/42/knowledge-capabilities")
    return respond(route, {
      code: 0,
      data: {
        agent_id: 42,
        version_no: 1,
        sources: {
          local: {
            enabled: false,
            max_select: 0,
            requires_same_embedding_model: false,
            default_summary: "",
            default_knowledge_ids: [],
            default_range_values: [],
          },
          aidp: {
            enabled: false,
            max_select: 0,
            default_summary: "",
            default_knowledge_ids: [],
          },
        },
      },
    });
  if (endpoint === "/model/list" || endpoint === "/model/llm_list")
    return respond(route, {
      data: [
        {
          model_id: 8,
          model_name: "fixture_second",
          display_name: "Second Model",
          model_type: "llm",
          model_factory: "custom",
          connect_status: "available",
        },
        {
          model_id: 7,
          model_name: "fixture_model",
          display_name: "Fixture Model",
          model_type: "llm",
          model_factory: "custom",
          connect_status: "available",
          max_tokens: 8192,
          context_window_tokens: 8192,
          max_output_tokens: 4096,
        },
      ],
    });
  if (endpoint === "/model/catalog/inference_field_specs")
    return respond(route, { data: {} });
  if (
    endpoint === "/tool/list" ||
    endpoint === "/skills" ||
    endpoint === "/tag-libraries"
  )
    return respond(route, []);
  if (
    /^\/skills\/instances/.test(endpoint) ||
    endpoint === "/skills/instance/list"
  )
    return respond(route, []);
  if (endpoint === "/indices/health")
    return respond(route, { status: "healthy", elasticsearch: "connected" });
  if (endpoint === "/indices")
    return respond(route, {
      indices: ["fixture-kb"],
      count: 1,
      indices_info: [
        {
          name: "fixture-kb",
          display_name: "Fixture Knowledge Base",
          stats: {
            base_info: {
              doc_count: 1,
              chunk_count: 2,
              creation_date: "2026-09-14T00:00:00Z",
            },
          },
        },
      ],
    });
  if (endpoint.startsWith("/a2a/client/"))
    return respond(route, { status: "success", data: [] });
  return false;
}
