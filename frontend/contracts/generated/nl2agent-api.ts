export interface paths {
  "/nl2agent/session/by-conversation/{conversation_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Resolve Session Api
     * @description Resolve an active owned draft after local browser state is lost.
     */
    get: operations["resolve_session_api_nl2agent_session_by_conversation__conversation_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/start": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Start Session Api
     * @description Start a new NL2AGENT session: creates a draft agent and a conversation.
     *
     *     Returns ``{"agent_id": int, "conversation_id": int, "draft_name": str}``.
     *     The frontend then opens the chat page with the NL2AGENT default agent_id
     *     and this conversation_id.
     */
    post: operations["start_session_api_nl2agent_session_start_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/abandon": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Abandon Session Api
     * @description Explicitly end one owned draft session without deleting it immediately.
     */
    post: operations["abandon_session_api_nl2agent_session__agent_id__abandon_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/apply-local-resources": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Apply Local Resources Api
     * @description Bulk-bind local tools and skills to the draft agent.
     */
    post: operations["apply_local_resources_api_nl2agent_session__agent_id__apply_local_resources_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/card-delivery": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Report Card Delivery Api */
    post: operations["report_card_delivery_api_nl2agent_session__agent_id__card_delivery_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/finalize": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Finalize Agent Api
     * @description Finalize the draft agent by generating its full prompt set.
     */
    post: operations["finalize_agent_api_nl2agent_session__agent_id__finalize_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/identity": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    /** Save Agent Identity Api */
    put: operations["save_agent_identity_api_nl2agent_session__agent_id__identity_put"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/install-web-skill": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Install Web Skill Api
     * @description Install a single official/web skill and bind it to the draft agent.
     */
    post: operations["install_web_skill_api_nl2agent_session__agent_id__install_web_skill_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/local-resources/register": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Register Local Resources Api */
    post: operations["register_local_resources_api_nl2agent_session__agent_id__local_resources_register_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/local-resources/skip": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Skip Local Resources Api */
    post: operations["skip_local_resources_api_nl2agent_session__agent_id__local_resources_skip_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/mcp/install": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Install Recommended Mcp Api */
    post: operations["install_recommended_mcp_api_nl2agent_session__agent_id__mcp_install_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/mcp/{mcp_id}/bind-tools": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Bind Mcp Tools Api */
    post: operations["bind_mcp_tools_api_nl2agent_session__agent_id__mcp__mcp_id__bind_tools_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/mcp/{mcp_id}/skip-tools": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Skip Mcp Tools Api */
    post: operations["skip_mcp_tools_api_nl2agent_session__agent_id__mcp__mcp_id__skip_tools_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/models": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    /** Select Models Api */
    put: operations["select_models_api_nl2agent_session__agent_id__models_put"];
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/online-configuration/complete": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Complete Online Configuration Api */
    post: operations["complete_online_configuration_api_nl2agent_session__agent_id__online_configuration_complete_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/online-recommendations/register": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Register Online Recommendations Api */
    post: operations["register_online_recommendations_api_nl2agent_session__agent_id__online_recommendations_register_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/requirements/confirm": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Confirm Requirements Api */
    post: operations["confirm_requirements_api_nl2agent_session__agent_id__requirements_confirm_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/requirements/register": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Register Requirements Api */
    post: operations["register_requirements_api_nl2agent_session__agent_id__requirements_register_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{agent_id}/state": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Get Session State Api */
    get: operations["get_session_state_api_nl2agent_session__agent_id__state_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/sessions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * List Sessions Api
     * @description List the current user's active NL2AGENT sessions.
     */
    get: operations["list_sessions_api_nl2agent_sessions_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}
export type webhooks = Record<string, never>;
export interface components {
  schemas: {
    /**
     * AgentVerificationConfig
     * @description Configuration for layered ReAct self-verification.
     */
    AgentVerificationConfig: {
      /**
       * Critical Events
       * @description Critical ReAct events that should be verified
       */
      critical_events?: (
        | "tool_precheck"
        | "tool_result"
        | "retrieval"
        | "code_execution"
        | "handoff"
        | "final_answer"
      )[];
      /**
       * Enabled
       * @description Whether self-verification is enabled
       * @default true
       */
      enabled?: boolean;
      /**
       * Fail Policy
       * @description Policy when final verification still fails after repair attempts
       * @default repair_then_controlled_summary
       * @enum {string}
       */
      fail_policy?: "repair_then_controlled_summary" | "warn";
      /**
       * Final Verification Enabled
       * @description Whether to verify final answer candidates before returning them
       * @default true
       */
      final_verification_enabled?: boolean;
      /**
       * Llm Verification Enabled
       * @description Whether to use the LLM as a final-answer verifier after deterministic checks
       * @default true
       */
      llm_verification_enabled?: boolean;
      /**
       * Max Final Rounds
       * @description Maximum number of final-answer verification attempts
       * @default 2
       */
      max_final_rounds?: number;
      /**
       * Pass Score
       * @description Minimum verifier score for final answers
       * @default 0.75
       */
      pass_score?: number;
      /**
       * Step Verification Enabled
       * @description Whether to verify critical ReAct step events
       * @default true
       */
      step_verification_enabled?: boolean;
      /**
       * Strictness
       * @description Verification strictness profile
       * @default balanced
       * @enum {string}
       */
      strictness?: "lenient" | "balanced" | "strict";
    };
    /** CardDelivery */
    CardDelivery: {
      /** Card Key */
      card_key?: string | null;
      /**
       * Card Type
       * @enum {string}
       */
      card_type:
        | "requirements_summary"
        | "model_selection"
        | "local_resources"
        | "web_mcp"
        | "web_skill"
        | "agent_identity"
        | "final_review";
      /** Message Id */
      message_id: number;
      /** Reason */
      reason?: string | null;
      /**
       * Retry Count
       * @default 0
       */
      retry_count?: number;
      /**
       * Status
       * @enum {string}
       */
      status: "rendered" | "failed";
    };
    /** HTTPValidationError */
    HTTPValidationError: {
      /** Detail */
      detail?: components["schemas"]["ValidationError"][];
    };
    /**
     * Nl2AgentApplyLocalResourcesRequest
     * @description Request body for bulk-binding local tools and skills to a draft agent.
     */
    Nl2AgentApplyLocalResourcesRequest: {
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
      /** Skill Ids */
      skill_ids?: number[];
      /** Tool Config Values */
      tool_config_values?: {
        [key: string]: {
          [key: string]: unknown;
        };
      };
      /** Tool Ids */
      tool_ids?: number[];
    };
    /** Nl2AgentApplyLocalResourcesResponse */
    Nl2AgentApplyLocalResourcesResponse: {
      /** Bound Skill Count */
      bound_skill_count: number;
      /** Bound Tool Count */
      bound_tool_count: number;
      /** Chat Injection Text */
      chat_injection_text: string;
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
      /** Skill Ids */
      skill_ids: number[];
      /**
       * Status
       * @constant
       */
      status: "applied";
      /** Tool Ids */
      tool_ids: number[];
    };
    /**
     * Nl2AgentCardDeliveryRequest
     * @description Report final-message rendering success or failure for one NL2AGENT card.
     */
    Nl2AgentCardDeliveryRequest: {
      /** Card Key */
      card_key?: string | null;
      /**
       * Card Type
       * @enum {string}
       */
      card_type:
        | "requirements_summary"
        | "model_selection"
        | "local_resources"
        | "web_mcp"
        | "web_skill"
        | "agent_identity"
        | "final_review";
      /** Message Id */
      message_id: number;
      /** Reason */
      reason?:
        | (
            | "truncated_fence"
            | "invalid_json"
            | "invalid_schema"
            | "missing_card"
          )
        | null;
      /**
       * Status
       * @enum {string}
       */
      status: "rendered" | "failed";
    };
    /** Nl2AgentCardDeliveryResponse */
    Nl2AgentCardDeliveryResponse: {
      /** Agent Id */
      agent_id: number;
      /** Auto Retry Allowed */
      auto_retry_allowed: boolean;
      /** Card Key */
      card_key?: string | null;
      /**
       * Card Type
       * @enum {string}
       */
      card_type:
        | "requirements_summary"
        | "model_selection"
        | "local_resources"
        | "web_mcp"
        | "web_skill"
        | "agent_identity"
        | "final_review";
      /** Chat Injection Text */
      chat_injection_text?: string | null;
      /** Message Id */
      message_id: number;
      /** Reason */
      reason?: string | null;
      /**
       * Retry Count
       * @default 0
       */
      retry_count?: number;
      /**
       * Status
       * @enum {string}
       */
      status: "rendered" | "failed";
    };
    /** Nl2AgentDiscoveredTool */
    Nl2AgentDiscoveredTool: {
      /** Description */
      description?: string | null;
      /** Name */
      name: string;
      /** Tool Id */
      tool_id: number;
    };
    /**
     * Nl2AgentFinalizeRequest
     * @description Unsaved descriptive, prompt, and runtime fields for draft publication.
     */
    Nl2AgentFinalizeRequest: {
      /** Business Description */
      business_description: string;
      /** Constraint Prompt */
      constraint_prompt?: string | null;
      /** Description */
      description?: string | null;
      /** Duty Prompt */
      duty_prompt: string;
      /**
       * Enable Context Manager
       * @default true
       */
      enable_context_manager?: boolean;
      /** Example Questions */
      example_questions?: string[];
      /** Few Shots Prompt */
      few_shots_prompt?: string | null;
      /** Greeting Message */
      greeting_message: string;
      /** Max Steps */
      max_steps?: number | null;
      /**
       * Provide Run Summary
       * @default false
       */
      provide_run_summary?: boolean;
      /** Requested Output Tokens */
      requested_output_tokens?: number | null;
      verification_config?:
        components["schemas"]["AgentVerificationConfig"] | null;
    };
    /** Nl2AgentFinalizeResponse */
    Nl2AgentFinalizeResponse: {
      /** Agent Id */
      agent_id: number;
      /** Display Name */
      display_name: string;
      /** Name */
      name: string;
      /** Skill Ids */
      skill_ids: number[];
      /**
       * Status
       * @constant
       */
      status: "draft_ready";
      /** Tool Ids */
      tool_ids: number[];
    };
    /**
     * Nl2AgentIdentityRequest
     * @description Persist the user-confirmed display name for an NL2AGENT draft.
     */
    Nl2AgentIdentityRequest: {
      /** Display Name */
      display_name: string;
    };
    /** Nl2AgentIdentityResponse */
    Nl2AgentIdentityResponse: {
      /** Agent Id */
      agent_id: number;
      /** Chat Injection Text */
      chat_injection_text?: string | null;
      /** Display Name */
      display_name: string;
      /** Identity Confirmed */
      identity_confirmed: boolean;
      /** Internal Name */
      internal_name: string;
    };
    /**
     * Nl2AgentInstallWebSkillRequest
     * @description Request body for installing a single official/web skill into the tenant.
     */
    Nl2AgentInstallWebSkillRequest: {
      /** Skill Id */
      skill_id?: number | null;
      /** Skill Name */
      skill_name?: string | null;
    };
    /** Nl2AgentInvalidReference */
    Nl2AgentInvalidReference: {
      /**
       * Reason
       * @enum {string}
       */
      reason:
        | "not_found"
        | "not_llm"
        | "unavailable"
        | "name_missing"
        | "primary_not_in_runtime_models";
      /** Reference Id */
      reference_id: number;
      /**
       * Reference Type
       * @enum {string}
       */
      reference_type: "model" | "tool" | "skill";
    };
    /** Nl2AgentLocalRecommendationResponse */
    Nl2AgentLocalRecommendationResponse: {
      /** Applied Skill Ids */
      applied_skill_ids: number[];
      /** Applied Tool Ids */
      applied_tool_ids: number[];
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
      /** Skill Ids */
      skill_ids: number[];
      /**
       * Status
       * @constant
       */
      status: "recommendations_ready";
      /** Tool Ids */
      tool_ids: number[];
      /** Tool Parameter Schemas */
      tool_parameter_schemas: {
        [key: string]: components["schemas"]["Nl2AgentToolParameterSchema"][];
      };
    };
    /** Nl2AgentLocalSkipResponse */
    Nl2AgentLocalSkipResponse: {
      /** Applied Skill Ids */
      applied_skill_ids: number[];
      /** Applied Tool Ids */
      applied_tool_ids: number[];
      /** Chat Injection Text */
      chat_injection_text: string;
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
      /** Skill Ids */
      skill_ids: number[];
      /**
       * Status
       * @constant
       */
      status: "skipped";
      /** Tool Ids */
      tool_ids: number[];
    };
    /**
     * Nl2AgentMcpBindToolsRequest
     * @description Bind selected tools from an installed MCP to an NL2AGENT draft.
     */
    Nl2AgentMcpBindToolsRequest: {
      /** Tool Ids */
      tool_ids?: number[];
    };
    /** Nl2AgentMcpBindToolsResponse */
    Nl2AgentMcpBindToolsResponse: {
      /** Agent Id */
      agent_id: number;
      /** Bound Tool Ids */
      bound_tool_ids: number[];
      /** Mcp Id */
      mcp_id: number;
    };
    /**
     * Nl2AgentMcpInstallRequest
     * @description Install a recommended MCP using user-confirmed configuration.
     */
    Nl2AgentMcpInstallRequest: {
      /** Config Values */
      config_values?: {
        [key: string]: unknown;
      };
      /**
       * Option Id
       * @default remote
       */
      option_id?: string;
      /** Recommendation Id */
      recommendation_id: string;
    };
    /** Nl2AgentMcpInstallResponse */
    Nl2AgentMcpInstallResponse: {
      /** Agent Id */
      agent_id: number;
      /** Mcp Id */
      mcp_id: number;
      /**
       * Status
       * @constant
       */
      status: "connected";
      /** Tools */
      tools: components["schemas"]["Nl2AgentDiscoveredTool"][];
    };
    /** Nl2AgentMcpSkipToolsResponse */
    Nl2AgentMcpSkipToolsResponse: {
      /** Agent Id */
      agent_id: number;
      /** Mcp Id */
      mcp_id: number;
      /**
       * Status
       * @constant
       */
      status: "binding_skipped";
    };
    /** Nl2AgentMcpWorkflowResponse */
    Nl2AgentMcpWorkflowResponse: {
      /** Bound Tool Ids */
      bound_tool_ids?: number[];
      /** Discovered Tool Ids */
      discovered_tool_ids?: number[];
      /** Discovered Tools */
      discovered_tools?: components["schemas"]["Nl2AgentDiscoveredTool"][];
      /** Error */
      error?: string | null;
      /** Installation Key */
      installation_key?: string | null;
      /** Mcp Id */
      mcp_id?: number | null;
      /** Option Id */
      option_id?: string | null;
      /** Recommendation Id */
      recommendation_id: string;
      /** Status */
      status?:
        | (
            | "configuration_required"
            | "installing"
            | "connected"
            | "tools_bound"
            | "binding_skipped"
            | "failed"
          )
        | null;
    };
    /**
     * Nl2AgentModelSelectionRequest
     * @description Persist the ordered LLM selection for an NL2AGENT draft.
     */
    Nl2AgentModelSelectionRequest: {
      /** Fallback Model Ids */
      fallback_model_ids?: number[];
      /** Primary Model Id */
      primary_model_id: number;
    };
    /** Nl2AgentModelSelectionResponse */
    Nl2AgentModelSelectionResponse: {
      /** Agent Id */
      agent_id: number;
      /** Chat Injection Text */
      chat_injection_text?: string | null;
      /** Fallback Model Ids */
      fallback_model_ids: number[];
      /** Models */
      models: components["schemas"]["Nl2AgentModelSummary"][];
      /** Primary Model Id */
      primary_model_id: number;
    };
    /** Nl2AgentModelSummary */
    Nl2AgentModelSummary: {
      /** Display Name */
      display_name: string;
      /** Model Id */
      model_id: number;
    };
    /** Nl2AgentOnlineConfigurationResponse */
    Nl2AgentOnlineConfigurationResponse: {
      /** Agent Id */
      agent_id: number;
      /** Chat Injection Text */
      chat_injection_text?: string | null;
      /** Completed Batch Ids */
      completed_batch_ids: string[];
      /** Online Configuration Confirmed */
      online_configuration_confirmed: boolean;
    };
    /**
     * Nl2AgentOnlineRecommendationBatchRequest
     * @description Register a rendered MCP or web-Skill recommendation batch.
     */
    Nl2AgentOnlineRecommendationBatchRequest: {
      /** Item Keys */
      item_keys?: string[];
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
      /**
       * Resource Type
       * @enum {string}
       */
      resource_type: "mcp" | "skill";
    };
    /** Nl2AgentOnlineRecommendationResponse */
    Nl2AgentOnlineRecommendationResponse: {
      /** Item Keys */
      item_keys: string[];
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
      /**
       * Resource Type
       * @enum {string}
       */
      resource_type: "mcp" | "skill";
      /**
       * Status
       * @constant
       */
      status: "recommendations_ready";
    };
    /** Nl2AgentPersistedModel */
    Nl2AgentPersistedModel: {
      /** Display Name */
      display_name?: string | null;
      /** Model Id */
      model_id: number;
      /**
       * Role
       * @enum {string}
       */
      role: "primary" | "fallback";
      /** Valid */
      valid: boolean;
    };
    /**
     * Nl2AgentRecommendationBatchRequest
     * @description Register a local-resource recommendation card rendered by the client.
     */
    Nl2AgentRecommendationBatchRequest: {
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
      /** Skill Ids */
      skill_ids?: number[];
      /** Tool Ids */
      tool_ids?: number[];
    };
    /**
     * Nl2AgentRecommendationSkipRequest
     * @description Explicitly skip one rendered local-resource recommendation batch.
     */
    Nl2AgentRecommendationSkipRequest: {
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
    };
    /**
     * Nl2AgentRequirementsConfirmRequest
     * @description Confirm the currently registered NL2AGENT requirements summary.
     */
    Nl2AgentRequirementsConfirmRequest: {
      /** Fingerprint */
      fingerprint: string;
    };
    /** Nl2AgentRequirementsConfirmationResponse */
    Nl2AgentRequirementsConfirmationResponse: {
      /** Agent Id */
      agent_id: number;
      /** Chat Injection Text */
      chat_injection_text?: string | null;
      /** Fingerprint */
      fingerprint: string;
      /**
       * Status
       * @constant
       */
      status: "confirmed";
    };
    /** Nl2AgentRequirementsData */
    Nl2AgentRequirementsData: {
      /** Audience Or Scenario */
      audience_or_scenario: string;
      /** Expected Output */
      expected_output: string;
      /** Goal */
      goal: string;
      /** Key Constraints */
      key_constraints: string;
      /** Primary Input */
      primary_input: string;
    };
    /** Nl2AgentRequirementsRegistrationResponse */
    Nl2AgentRequirementsRegistrationResponse: {
      /** Agent Id */
      agent_id: number;
      /** Fingerprint */
      fingerprint: string;
      /** Is Current */
      is_current: boolean;
      /**
       * Status
       * @enum {string}
       */
      status: "collecting" | "awaiting_confirmation" | "confirmed";
      summary: components["schemas"]["Nl2AgentRequirementsData"];
    };
    /** Nl2AgentRequirementsReviewResponse */
    Nl2AgentRequirementsReviewResponse: {
      /**
       * Fingerprint
       * @default
       */
      fingerprint?: string;
      /**
       * Status
       * @default collecting
       * @enum {string}
       */
      status?: "collecting" | "awaiting_confirmation" | "confirmed";
      summary?: components["schemas"]["Nl2AgentRequirementsData"] | null;
    };
    /**
     * Nl2AgentRequirementsSummaryRequest
     * @description Register the read-only requirements summary rendered by NL2AGENT.
     */
    Nl2AgentRequirementsSummaryRequest: {
      /** Audience Or Scenario */
      audience_or_scenario: string;
      /** Expected Output */
      expected_output: string;
      /** Goal */
      goal: string;
      /** Key Constraints */
      key_constraints: string;
      /** Primary Input */
      primary_input: string;
    };
    /** Nl2AgentSessionListResponse */
    Nl2AgentSessionListResponse: {
      /** Sessions */
      sessions: components["schemas"]["Nl2AgentSessionSummaryResponse"][];
    };
    /** Nl2AgentSessionStartResponse */
    Nl2AgentSessionStartResponse: {
      /** Conversation Id */
      conversation_id: number;
      /** Draft Agent Id */
      draft_agent_id: number;
      /** Draft Name */
      draft_name: string;
      /** Nl2Agent Agent Id */
      nl2agent_agent_id: number;
    };
    /** Nl2AgentSessionStateResponse */
    Nl2AgentSessionStateResponse: {
      /** Agent Id */
      agent_id: number;
      /** Allowed Actions */
      allowed_actions: string[];
      /** Business Logic Model Id */
      business_logic_model_id?: number | null;
      /**
       * Current Stage
       * @enum {string}
       */
      current_stage:
        | "requirements_collecting"
        | "requirements_confirmation"
        | "model_selection"
        | "local_resource_search"
        | "local_resource_review"
        | "online_resource_search"
        | "online_resource_review"
        | "agent_identity"
        | "final_review";
      /** Display Name */
      display_name?: string | null;
      /** Expected Card Types */
      expected_card_types: (
        | "requirements_summary"
        | "model_selection"
        | "local_resources"
        | "web_mcp"
        | "web_skill"
        | "agent_identity"
        | "final_review"
      )[];
      /** Identity Confirmed */
      identity_confirmed: boolean;
      /** Internal Name */
      internal_name: string;
      /** Invalid References */
      invalid_references: components["schemas"]["Nl2AgentInvalidReference"][];
      /** Model Ids */
      model_ids: number[];
      /** Models */
      models: components["schemas"]["Nl2AgentPersistedModel"][];
      resource_review: components["schemas"]["Nl2AgentWorkflowStateResponse"];
      /** Revision */
      revision: number;
      /**
       * Schema Version
       * @constant
       */
      schema_version: 2;
      /** Skills */
      skills: components["schemas"]["Nl2AgentSkillSummary"][];
      /** Tools */
      tools: components["schemas"]["Nl2AgentToolSummary"][];
    };
    /** Nl2AgentSessionSummaryResponse */
    Nl2AgentSessionSummaryResponse: {
      /** Conversation Id */
      conversation_id: number;
      /** Create Time */
      create_time?: string | null;
      /** Draft Agent Id */
      draft_agent_id: number;
      /**
       * Status
       * @enum {string}
       */
      status: "active" | "completed" | "abandoned";
      /** Update Time */
      update_time?: string | null;
    };
    /** Nl2AgentSkillSummary */
    Nl2AgentSkillSummary: {
      /** Name */
      name: string;
      /**
       * Origin
       * @enum {string}
       */
      origin: "local" | "online";
      /** Skill Id */
      skill_id: number;
      /** Source */
      source: string;
    } & {
      [key: string]: unknown;
    };
    /** Nl2AgentToolParameterSchema */
    Nl2AgentToolParameterSchema: {
      /** Choices */
      choices?: unknown[] | null;
      /** Default */
      default?: unknown | null;
      /** Description */
      description?: string | null;
      /** Issecret */
      isSecret?: boolean | null;
      /** Is Secret */
      is_secret?: boolean | null;
      /** Name */
      name: string;
      /** Optional */
      optional?: boolean | null;
      /** Required */
      required?: boolean | null;
      /** Type */
      type?: string | null;
    } & {
      [key: string]: unknown;
    };
    /** Nl2AgentToolSummary */
    Nl2AgentToolSummary: {
      /** Name */
      name: string;
      /**
       * Origin
       * @enum {string}
       */
      origin: "local" | "online";
      /** Source */
      source: string;
      /** Tool Id */
      tool_id: number;
    } & {
      [key: string]: unknown;
    };
    /** Nl2AgentWebSkillInstallResponse */
    Nl2AgentWebSkillInstallResponse: {
      /** Bound */
      bound: boolean;
      /** Installed */
      installed: boolean;
      /** Installed Ids */
      installed_ids: number[];
      /** Installed Names */
      installed_names?: string[] | null;
      /** Skill Id */
      skill_id: number;
      /** Skill Name */
      skill_name?: string | null;
    };
    /** Nl2AgentWorkflowStateResponse */
    Nl2AgentWorkflowStateResponse: {
      /** Card Delivery */
      card_delivery?: {
        [key: string]: components["schemas"]["CardDelivery"];
      };
      /** Conversation Id */
      conversation_id: number;
      /**
       * Identity Confirmed
       * @default false
       */
      identity_confirmed?: boolean;
      /** Mcp Workflows */
      mcp_workflows: {
        [key: string]: components["schemas"]["Nl2AgentMcpWorkflowResponse"];
      };
      /**
       * Model Selection Confirmed
       * @default false
       */
      model_selection_confirmed?: boolean;
      /**
       * Online Configuration Confirmed
       * @default false
       */
      online_configuration_confirmed?: boolean;
      /** Online Recommendation Batches */
      online_recommendation_batches?: {
        [key: string]: components["schemas"]["OnlineRecommendationBatch"];
      };
      /** Recommendation Batches */
      recommendation_batches?: {
        [key: string]: components["schemas"]["RecommendationBatch"];
      };
      requirements_review: components["schemas"]["Nl2AgentRequirementsReviewResponse"];
      /**
       * Revision
       * @default 0
       */
      revision?: number;
      /**
       * Schema Version
       * @default 2
       * @constant
       */
      schema_version?: 2;
      /** Trusted Search Batches */
      trusted_search_batches?: {
        [key: string]: components["schemas"]["TrustedSearchBatch"];
      };
    };
    /** OnlineRecommendationBatch */
    OnlineRecommendationBatch: {
      /** Item Keys */
      item_keys?: string[];
      /**
       * Resource Type
       * @enum {string}
       */
      resource_type: "mcp" | "skill";
      /**
       * Status
       * @enum {string}
       */
      status: "recommendations_ready" | "completed";
    };
    /** RecommendationBatch */
    RecommendationBatch: {
      /** Applied Skill Ids */
      applied_skill_ids?: number[];
      /** Applied Tool Ids */
      applied_tool_ids?: number[];
      /** Operation Id */
      operation_id?: string | null;
      /** Skill Ids */
      skill_ids?: number[];
      /**
       * Status
       * @enum {string}
       */
      status: "recommendations_ready" | "applying" | "applied" | "skipped";
      /** Tool Ids */
      tool_ids?: number[];
    } & {
      [key: string]: unknown;
    };
    /**
     * TrustedSearchBatch
     * @description Backend-recorded proof that an SDK search produced one result batch.
     */
    TrustedSearchBatch: {
      /** Item Keys */
      item_keys?: string[];
      /**
       * Resource Type
       * @enum {string}
       */
      resource_type: "local" | "mcp" | "skill";
      /** Skill Ids */
      skill_ids?: number[];
      /** Tool Ids */
      tool_ids?: number[];
    };
    /** ValidationError */
    ValidationError: {
      /** Context */
      ctx?: Record<string, never>;
      /** Input */
      input?: unknown;
      /** Location */
      loc: (string | number)[];
      /** Message */
      msg: string;
      /** Error Type */
      type: string;
    };
  };
  responses: never;
  parameters: never;
  requestBodies: never;
  headers: never;
  pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
  resolve_session_api_nl2agent_session_by_conversation__conversation_id__get: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        conversation_id: number;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentSessionSummaryResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  start_session_api_nl2agent_session_start_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentSessionStartResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  abandon_session_api_nl2agent_session__agent_id__abandon_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentSessionSummaryResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  apply_local_resources_api_nl2agent_session__agent_id__apply_local_resources_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentApplyLocalResourcesRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentApplyLocalResourcesResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  report_card_delivery_api_nl2agent_session__agent_id__card_delivery_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentCardDeliveryRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentCardDeliveryResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  finalize_agent_api_nl2agent_session__agent_id__finalize_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentFinalizeRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentFinalizeResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  save_agent_identity_api_nl2agent_session__agent_id__identity_put: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentIdentityRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentIdentityResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  install_web_skill_api_nl2agent_session__agent_id__install_web_skill_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentInstallWebSkillRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentWebSkillInstallResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  register_local_resources_api_nl2agent_session__agent_id__local_resources_register_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentRecommendationBatchRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentLocalRecommendationResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  skip_local_resources_api_nl2agent_session__agent_id__local_resources_skip_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentRecommendationSkipRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentLocalSkipResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  install_recommended_mcp_api_nl2agent_session__agent_id__mcp_install_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentMcpInstallRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentMcpInstallResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  bind_mcp_tools_api_nl2agent_session__agent_id__mcp__mcp_id__bind_tools_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
        mcp_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentMcpBindToolsRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentMcpBindToolsResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  skip_mcp_tools_api_nl2agent_session__agent_id__mcp__mcp_id__skip_tools_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
        mcp_id: number;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentMcpSkipToolsResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  select_models_api_nl2agent_session__agent_id__models_put: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentModelSelectionRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentModelSelectionResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  complete_online_configuration_api_nl2agent_session__agent_id__online_configuration_complete_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentOnlineConfigurationResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  register_online_recommendations_api_nl2agent_session__agent_id__online_recommendations_register_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentOnlineRecommendationBatchRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentOnlineRecommendationResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  confirm_requirements_api_nl2agent_session__agent_id__requirements_confirm_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentRequirementsConfirmRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentRequirementsConfirmationResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  register_requirements_api_nl2agent_session__agent_id__requirements_register_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Nl2AgentRequirementsSummaryRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentRequirementsRegistrationResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  get_session_state_api_nl2agent_session__agent_id__state_get: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        agent_id: number;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentSessionStateResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  list_sessions_api_nl2agent_sessions_get: {
    parameters: {
      query?: {
        limit?: number;
      };
      header?: {
        authorization?: string | null;
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentSessionListResponse"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
}
