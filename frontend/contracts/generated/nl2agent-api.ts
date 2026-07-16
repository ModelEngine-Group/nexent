export interface paths {
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
}
export type webhooks = Record<string, never>;
export interface components {
  schemas: {
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
      /** Verification Config */
      verification_config?: {
        [key: string]: unknown;
      } | null;
    };
    /**
     * Nl2AgentIdentityRequest
     * @description Persist the user-confirmed display name for an NL2AGENT draft.
     */
    Nl2AgentIdentityRequest: {
      /** Display Name */
      display_name: string;
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
    /**
     * Nl2AgentMcpBindToolsRequest
     * @description Bind selected tools from an installed MCP to an NL2AGENT draft.
     */
    Nl2AgentMcpBindToolsRequest: {
      /** Tool Ids */
      tool_ids?: number[];
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
          "application/json": unknown;
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
