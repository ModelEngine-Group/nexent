export interface paths {
  "/nl2agent/session/by-agent/{draft_agent_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Resolve Session By Agent Api
     * @description Resolve an optional owned session for the Agent configuration page.
     */
    get: operations["resolve_session_by_agent_api_nl2agent_session_by_agent__draft_agent_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/by-conversation/{conversation_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Resolve Session Api
     * @description Resolve an optional owned session after browser state is lost.
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
     * @description Create one draft, builder Conversation, and durable workflow session.
     */
    post: operations["start_session_api_nl2agent_session_start_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{draft_agent_id}/abandon": {
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
     * @description Explicitly end one owned draft session.
     */
    post: operations["abandon_session_api_nl2agent_session__draft_agent_id__abandon_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{draft_agent_id}/actions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Dispatch Action Api
     * @description Apply one strict, idempotent business action to an active session.
     */
    post: operations["dispatch_action_api_nl2agent_session__draft_agent_id__actions_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{draft_agent_id}/resume": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /**
     * Resume Session Api
     * @description Resume a final-review session in targeted editing mode.
     */
    post: operations["resume_session_api_nl2agent_session__draft_agent_id__resume_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{draft_agent_id}/state": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Session State Api
     * @description Return the authoritative read-only workflow projection.
     */
    get: operations["get_session_state_api_nl2agent_session__draft_agent_id__state_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/nl2agent/session/{draft_agent_id}/web-skill/configuration": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Get Web Skill Configuration Api
     * @description Return trusted, redacted configuration metadata for one Skill.
     */
    get: operations["get_web_skill_configuration_api_nl2agent_session__draft_agent_id__web_skill_configuration_get"];
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
    /** HTTPValidationError */
    HTTPValidationError: {
      /** Detail */
      detail?: components["schemas"]["ValidationError"][];
    };
    /** Nl2AgentActionResponse */
    Nl2AgentActionResponse: {
      /**
       * Action
       * @enum {string}
       */
      action:
        | "confirm_requirements"
        | "save_model_selection"
        | "apply_local_resources"
        | "skip_local_resources"
        | "install_mcp"
        | "bind_mcp_tools"
        | "skip_mcp_tools"
        | "install_web_skill"
        | "complete_online_configuration"
        | "save_identity"
        | "finalize";
      /**
       * Action Id
       * Format: uuid
       */
      action_id: string;
      /** Result */
      result?: {
        [key: string]: unknown;
      };
      /**
       * Status
       * @enum {string}
       */
      status: "applied" | "pending" | "replayed";
      /** Workflow Revision */
      workflow_revision: number;
    };
    /** Nl2AgentAgentIdentityCard */
    Nl2AgentAgentIdentityCard: {
      /**
       * Card Key
       * @constant
       */
      card_key: "agent_identity";
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      card_type: "agent_identity";
      payload: components["schemas"]["Nl2AgentAgentIdentityCardPayload"];
    };
    /** Nl2AgentAgentIdentityCardPayload */
    Nl2AgentAgentIdentityCardPayload: {
      /**
       * Agent Id
       * @default null
       */
      agent_id?: number;
      /** Display Name */
      display_name: string;
    };
    /**
     * Nl2AgentApplyLocalResourcesActionPayload
     * @description Select resources only from one server-recorded recommendation batch.
     */
    Nl2AgentApplyLocalResourcesActionPayload: {
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
    /** Nl2AgentApplyLocalResourcesActionRequest */
    Nl2AgentApplyLocalResourcesActionRequest: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      action: "apply_local_resources";
      /**
       * Action Id
       * Format: uuid
       */
      action_id: string;
      /** Display Text */
      display_text: string;
      /** Expected Revision */
      expected_revision: number;
      payload: components["schemas"]["Nl2AgentApplyLocalResourcesActionPayload"];
    };
    /** Nl2AgentBindMcpToolsActionPayload */
    Nl2AgentBindMcpToolsActionPayload: {
      /** Recommendation Id */
      recommendation_id: string;
      /** Tool Ids */
      tool_ids?: number[];
    };
    /** Nl2AgentBindMcpToolsActionRequest */
    Nl2AgentBindMcpToolsActionRequest: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      action: "bind_mcp_tools";
      /**
       * Action Id
       * Format: uuid
       */
      action_id: string;
      /** Display Text */
      display_text: string;
      /** Expected Revision */
      expected_revision: number;
      payload: components["schemas"]["Nl2AgentBindMcpToolsActionPayload"];
    };
    /**
     * Nl2AgentCardEnvelope
     * @description Persisted cards and their authoritative Session revision.
     */
    Nl2AgentCardEnvelope: {
      /** Cards */
      cards: (
        | components["schemas"]["Nl2AgentRequirementsSummaryCard"]
        | components["schemas"]["Nl2AgentModelSelectionCard"]
        | components["schemas"]["Nl2AgentLocalResourcesCard"]
        | components["schemas"]["Nl2AgentWebMcpCard"]
        | components["schemas"]["Nl2AgentWebSkillCard"]
        | components["schemas"]["Nl2AgentAgentIdentityCard"]
        | components["schemas"]["Nl2AgentFinalReviewCard"]
      )[];
      /** Draft Agent Id */
      draft_agent_id: number;
      /**
       * Schema Version
       * @constant
       */
      schema_version: 1;
      /** Workflow Revision */
      workflow_revision: number;
    };
    /** Nl2AgentCompleteOnlineConfigurationActionRequest */
    Nl2AgentCompleteOnlineConfigurationActionRequest: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      action: "complete_online_configuration";
      /**
       * Action Id
       * Format: uuid
       */
      action_id: string;
      /** Display Text */
      display_text: string;
      /** Expected Revision */
      expected_revision: number;
      payload?: components["schemas"]["Nl2AgentEmptyActionPayload"];
    };
    /** Nl2AgentConfirmRequirementsActionPayload */
    Nl2AgentConfirmRequirementsActionPayload: {
      summary: components["schemas"]["Nl2AgentRequirementsSummaryPayload"];
    };
    /** Nl2AgentConfirmRequirementsActionRequest */
    Nl2AgentConfirmRequirementsActionRequest: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      action: "confirm_requirements";
      /**
       * Action Id
       * Format: uuid
       */
      action_id: string;
      /** Display Text */
      display_text: string;
      /** Expected Revision */
      expected_revision: number;
      payload: components["schemas"]["Nl2AgentConfirmRequirementsActionPayload"];
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
     * Nl2AgentEmptyActionPayload
     * @description An action with no client-controlled domain identifiers.
     */
    Nl2AgentEmptyActionPayload: Record<string, never>;
    /** Nl2AgentFinalReviewCard */
    Nl2AgentFinalReviewCard: {
      /**
       * Card Key
       * @constant
       */
      card_key: "final_review";
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      card_type: "final_review";
      payload: components["schemas"]["Nl2AgentFinalReviewCardPayload"];
    };
    /** Nl2AgentFinalReviewCardPayload */
    Nl2AgentFinalReviewCardPayload: {
      /**
       * Agent Id
       * @default null
       */
      agent_id?: number;
      /** Business Description */
      business_description: string;
      /**
       * Constraint Prompt
       * @default null
       */
      constraint_prompt?: string;
      /**
       * Description
       * @default null
       */
      description?: string;
      /** Duty Prompt */
      duty_prompt: string;
      /**
       * Enable Context Manager
       * @default null
       */
      enable_context_manager?: boolean;
      /**
       * Example Questions
       * @default null
       */
      example_questions?: string[];
      /**
       * Few Shots Prompt
       * @default null
       */
      few_shots_prompt?: string;
      /** Greeting Message */
      greeting_message: string;
      /**
       * Max Steps
       * @default null
       */
      max_steps?: number;
      /**
       * Provide Run Summary
       * @default null
       */
      provide_run_summary?: boolean;
      /**
       * Requested Output Tokens
       * @default null
       */
      requested_output_tokens?: number;
      /** @default null */
      verification_config?: components["schemas"]["Nl2AgentVerificationConfig"];
    };
    /**
     * Nl2AgentFinalizeActionPayload
     * @description Unsaved descriptive, prompt, and runtime fields for draft publication.
     */
    Nl2AgentFinalizeActionPayload: {
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
    /** Nl2AgentFinalizeActionRequest */
    Nl2AgentFinalizeActionRequest: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      action: "finalize";
      /**
       * Action Id
       * Format: uuid
       */
      action_id: string;
      /** Display Text */
      display_text: string;
      /** Expected Revision */
      expected_revision: number;
      payload: components["schemas"]["Nl2AgentFinalizeActionPayload"];
    };
    /**
     * Nl2AgentInstallMcpActionPayload
     * @description Install one MCP recommendation without accepting a client URL.
     */
    Nl2AgentInstallMcpActionPayload: {
      /** Config Values */
      config_values?: {
        [key: string]: unknown;
      };
      /**
       * Option Id
       * @default remote
       */
      option_id?: string;
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
      /** Recommendation Id */
      recommendation_id: string;
    };
    /** Nl2AgentInstallMcpActionRequest */
    Nl2AgentInstallMcpActionRequest: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      action: "install_mcp";
      /**
       * Action Id
       * Format: uuid
       */
      action_id: string;
      /** Display Text */
      display_text: string;
      /** Expected Revision */
      expected_revision: number;
      payload: components["schemas"]["Nl2AgentInstallMcpActionPayload"];
    };
    /**
     * Nl2AgentInstallWebSkillActionPayload
     * @description Install one Skill from a server-recorded recommendation batch.
     */
    Nl2AgentInstallWebSkillActionPayload: {
      /** Config Values */
      config_values?: {
        [key: string]: unknown;
      };
      /** Item Key */
      item_key: string;
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
    };
    /** Nl2AgentInstallWebSkillActionRequest */
    Nl2AgentInstallWebSkillActionRequest: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      action: "install_web_skill";
      /**
       * Action Id
       * Format: uuid
       */
      action_id: string;
      /** Display Text */
      display_text: string;
      /** Expected Revision */
      expected_revision: number;
      payload: components["schemas"]["Nl2AgentInstallWebSkillActionPayload"];
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
    /** Nl2AgentLocalResourcesCard */
    Nl2AgentLocalResourcesCard: {
      /** Card Key */
      card_key: string;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      card_type: "local_resources";
      payload: components["schemas"]["Nl2AgentLocalResourcesCardPayload"];
    };
    /** Nl2AgentLocalResourcesCardPayload */
    Nl2AgentLocalResourcesCardPayload: {
      /**
       * Agent Id
       * @default null
       */
      agent_id?: number;
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
      /** Skills */
      skills: components["schemas"]["Nl2AgentLocalSkillCardItem"][];
      /** Tools */
      tools: components["schemas"]["Nl2AgentLocalToolCardItem"][];
    };
    /** Nl2AgentLocalSkillCardItem */
    Nl2AgentLocalSkillCardItem: {
      /**
       * Description
       * @default null
       */
      description?: string;
      /** Name */
      name: string;
      /**
       * Reason
       * @default null
       */
      reason?: string;
      /**
       * Score
       * @default null
       */
      score?: number;
      /** Skill Id */
      skill_id: number;
      /**
       * Tags
       * @default null
       */
      tags?: string[];
    };
    /** Nl2AgentLocalToolCardItem */
    Nl2AgentLocalToolCardItem: {
      /**
       * Category
       * @default null
       */
      category?: string;
      /**
       * Description
       * @default null
       */
      description?: string;
      /**
       * Labels
       * @default null
       */
      labels?: string[];
      /** Name */
      name: string;
      /**
       * Reason
       * @default null
       */
      reason?: string;
      /**
       * Score
       * @default null
       */
      score?: number;
      /**
       * Source
       * @default null
       */
      source?: string;
      /** Tool Id */
      tool_id: number;
      /**
       * Usage
       * @default null
       */
      usage?: string;
    };
    /** Nl2AgentMcpField */
    Nl2AgentMcpField: {
      /**
       * Argument Name
       * @default null
       */
      argument_name?: string | null;
      /**
       * Argument Type
       * @default null
       * @enum {string}
       */
      argument_type?: "named" | "positional";
      /**
       * Category
       * @default null
       */
      category?: string;
      /**
       * Choices
       * @default null
       */
      choices?: string[];
      /**
       * Default
       * @default null
       */
      default?: string | number | boolean | null;
      /**
       * Description
       * @default null
       */
      description?: string;
      /** Key */
      key: string;
      /**
       * Label
       * @default null
       */
      label?: string;
      /** Name */
      name: string;
      /**
       * Placeholder
       * @default null
       */
      placeholder?: string;
      /**
       * Repeated
       * @default null
       */
      repeated?: boolean;
      /** Required */
      required: boolean;
      /** Secret */
      secret: boolean;
      /**
       * Type
       * @enum {string}
       */
      type: "text" | "number" | "url" | "json";
    };
    /** Nl2AgentMcpInstallOption */
    Nl2AgentMcpInstallOption: {
      /**
       * Description
       * @default null
       */
      description?: string;
      /** Fields */
      fields: components["schemas"]["Nl2AgentMcpField"][];
      /** Label */
      label: string;
      /** Option Id */
      option_id: string;
      /**
       * Package Identifier
       * @default null
       */
      package_identifier?: string | null;
      /**
       * Registry Type
       * @default null
       */
      registry_type?: string | null;
      /** Requires Configuration */
      requires_configuration: boolean;
      /**
       * Runtime Hint
       * @default null
       */
      runtime_hint?: string | null;
      /**
       * Server Url Template
       * @default null
       */
      server_url_template?: string | null;
      /**
       * Status
       * @enum {string}
       */
      status: "ready" | "configuration_required" | "unsupported";
      /** Supported */
      supported: boolean;
      /**
       * Transport
       * @default null
       */
      transport?: string | null;
      /**
       * Type
       * @enum {string}
       */
      type: "remote" | "container" | "unsupported";
      /**
       * Unsupported Reason
       * @default null
       */
      unsupported_reason?: string;
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
    /** Nl2AgentModelSelectionCard */
    Nl2AgentModelSelectionCard: {
      /**
       * Card Key
       * @constant
       */
      card_key: "model_selection";
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      card_type: "model_selection";
      payload: components["schemas"]["Nl2AgentModelSelectionCardPayload"];
    };
    /** Nl2AgentModelSelectionCardPayload */
    Nl2AgentModelSelectionCardPayload: {
      /**
       * Agent Id
       * @default null
       */
      agent_id?: number;
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
    /** Nl2AgentRequirementsSummaryCard */
    Nl2AgentRequirementsSummaryCard: {
      /**
       * Card Key
       * @constant
       */
      card_key: "requirements_summary";
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      card_type: "requirements_summary";
      payload: components["schemas"]["Nl2AgentRequirementsSummaryCardPayload"];
    };
    /** Nl2AgentRequirementsSummaryCardPayload */
    Nl2AgentRequirementsSummaryCardPayload: {
      /**
       * Agent Id
       * @default null
       */
      agent_id?: number;
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
    /**
     * Nl2AgentRequirementsSummaryPayload
     * @description The five-field requirements summary visible in a confirmation card.
     */
    Nl2AgentRequirementsSummaryPayload: {
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
    /** Nl2AgentSaveIdentityActionPayload */
    Nl2AgentSaveIdentityActionPayload: {
      /** Display Name */
      display_name: string;
    };
    /** Nl2AgentSaveIdentityActionRequest */
    Nl2AgentSaveIdentityActionRequest: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      action: "save_identity";
      /**
       * Action Id
       * Format: uuid
       */
      action_id: string;
      /** Display Text */
      display_text: string;
      /** Expected Revision */
      expected_revision: number;
      payload: components["schemas"]["Nl2AgentSaveIdentityActionPayload"];
    };
    /** Nl2AgentSaveModelSelectionActionPayload */
    Nl2AgentSaveModelSelectionActionPayload: {
      /** Fallback Model Ids */
      fallback_model_ids?: number[];
      /** Primary Model Id */
      primary_model_id: number;
    };
    /** Nl2AgentSaveModelSelectionActionRequest */
    Nl2AgentSaveModelSelectionActionRequest: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      action: "save_model_selection";
      /**
       * Action Id
       * Format: uuid
       */
      action_id: string;
      /** Display Text */
      display_text: string;
      /** Expected Revision */
      expected_revision: number;
      payload: components["schemas"]["Nl2AgentSaveModelSelectionActionPayload"];
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
        | "revision_routing"
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
      /** Local Tool Parameter Schemas */
      local_tool_parameter_schemas?: {
        [key: string]: {
          [key: string]: components["schemas"]["Nl2AgentToolParameterSchema"][];
        };
      };
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
      schema_version: 3;
      /**
       * Session Status
       * @enum {string}
       */
      session_status: "active" | "completed";
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
      /** Nl2Agent Agent Id */
      nl2agent_agent_id: number;
      /**
       * Status
       * @enum {string}
       */
      status: "active" | "completed" | "abandoned";
      /** Update Time */
      update_time?: string | null;
    };
    /** Nl2AgentSkillParameterSchema */
    Nl2AgentSkillParameterSchema: {
      /** Choices */
      choices?: unknown[] | null;
      /** Default */
      default?: unknown | null;
      /** Depends On */
      depends_on?: string | null;
      /** Description En */
      description_en?: string | null;
      /** Description Zh */
      description_zh?: string | null;
      /** Issecret */
      isSecret?: boolean | null;
      /** Is Secret */
      is_secret?: boolean | null;
      /** Name */
      name: string;
      /** Optional */
      optional?: boolean | null;
      /**
       * Required
       * @default false
       */
      required?: boolean;
      /** Type */
      type?: string | null;
      /** Value */
      value?: unknown | null;
    } & {
      [key: string]: unknown;
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
    };
    /**
     * Nl2AgentSkipLocalResourcesActionPayload
     * @description Skip one server-recorded local recommendation batch.
     */
    Nl2AgentSkipLocalResourcesActionPayload: {
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
    };
    /** Nl2AgentSkipLocalResourcesActionRequest */
    Nl2AgentSkipLocalResourcesActionRequest: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      action: "skip_local_resources";
      /**
       * Action Id
       * Format: uuid
       */
      action_id: string;
      /** Display Text */
      display_text: string;
      /** Expected Revision */
      expected_revision: number;
      payload: components["schemas"]["Nl2AgentSkipLocalResourcesActionPayload"];
    };
    /** Nl2AgentSkipMcpToolsActionPayload */
    Nl2AgentSkipMcpToolsActionPayload: {
      /** Recommendation Id */
      recommendation_id: string;
    };
    /** Nl2AgentSkipMcpToolsActionRequest */
    Nl2AgentSkipMcpToolsActionRequest: {
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      action: "skip_mcp_tools";
      /**
       * Action Id
       * Format: uuid
       */
      action_id: string;
      /** Display Text */
      display_text: string;
      /** Expected Revision */
      expected_revision: number;
      payload: components["schemas"]["Nl2AgentSkipMcpToolsActionPayload"];
    };
    /** Nl2AgentToolConfigurationField */
    Nl2AgentToolConfigurationField: {
      /**
       * Configured
       * @default false
       */
      configured?: boolean;
      /**
       * Secret
       * @default false
       */
      secret?: boolean;
      /** Value */
      value?: unknown | null;
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
      /** Configuration */
      configuration?: {
        [key: string]: components["schemas"]["Nl2AgentToolConfigurationField"];
      };
      /** Name */
      name: string;
      /**
       * Origin
       * @enum {string}
       */
      origin: "local" | "online";
      /** Parameter Schema */
      parameter_schema?: components["schemas"]["Nl2AgentToolParameterSchema"][];
      /** Source */
      source: string;
      /** Tool Id */
      tool_id: number;
    };
    /** Nl2AgentVerificationConfig */
    Nl2AgentVerificationConfig: {
      /**
       * Critical Events
       * @default null
       */
      critical_events?: (
        | "tool_precheck"
        | "tool_result"
        | "retrieval"
        | "code_execution"
        | "handoff"
        | "final_answer"
      )[];
      /** Enabled */
      enabled: boolean;
      /**
       * Fail Policy
       * @default null
       * @enum {string}
       */
      fail_policy?: "repair_then_controlled_summary" | "warn";
      /**
       * Final Verification Enabled
       * @default null
       */
      final_verification_enabled?: boolean;
      /**
       * Llm Verification Enabled
       * @default null
       */
      llm_verification_enabled?: boolean;
      /**
       * Max Final Rounds
       * @default null
       */
      max_final_rounds?: number;
      /**
       * Pass Score
       * @default null
       */
      pass_score?: number;
      /**
       * Step Verification Enabled
       * @default null
       */
      step_verification_enabled?: boolean;
      /**
       * Strictness
       * @default null
       * @enum {string}
       */
      strictness?: "lenient" | "balanced" | "strict";
    };
    /** Nl2AgentWebMcpCard */
    Nl2AgentWebMcpCard: {
      /** Card Key */
      card_key: string;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      card_type: "web_mcp";
      /** Payload */
      payload:
        | components["schemas"]["Nl2AgentWebMcpListCardPayload"]
        | components["schemas"]["Nl2AgentWebMcpSingleCardPayload"];
    };
    /** Nl2AgentWebMcpCardItem */
    Nl2AgentWebMcpCardItem: {
      /**
       * Agent Id
       * @default null
       */
      agent_id?: number;
      /**
       * Description
       * @default null
       */
      description?: string;
      /** Install Options */
      install_options: components["schemas"]["Nl2AgentMcpInstallOption"][];
      /** Name */
      name: string;
      /**
       * Reason
       * @default null
       */
      reason?: string;
      /**
       * Recommendation Batch Id
       * @default null
       */
      recommendation_batch_id?: string;
      /** Recommendation Id */
      recommendation_id: string;
      /**
       * Score
       * @default null
       */
      score?: number;
      /**
       * Source
       * @default null
       * @enum {string}
       */
      source?: "registry" | "community";
      /**
       * Tags
       * @default null
       */
      tags?: string[];
      /**
       * Transport
       * @default null
       */
      transport?: string | null;
    };
    /** Nl2AgentWebMcpListCardPayload */
    Nl2AgentWebMcpListCardPayload: {
      /**
       * Agent Id
       * @default null
       */
      agent_id?: number;
      /** Items */
      items: components["schemas"]["Nl2AgentWebMcpCardItem"][];
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
    };
    /** Nl2AgentWebMcpSingleCardPayload */
    Nl2AgentWebMcpSingleCardPayload: {
      /**
       * Agent Id
       * @default null
       */
      agent_id?: number;
      /**
       * Description
       * @default null
       */
      description?: string;
      /** Install Options */
      install_options: components["schemas"]["Nl2AgentMcpInstallOption"][];
      /** Name */
      name: string;
      /**
       * Reason
       * @default null
       */
      reason?: string;
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
      /** Recommendation Id */
      recommendation_id: string;
      /**
       * Score
       * @default null
       */
      score?: number;
      /**
       * Source
       * @default null
       * @enum {string}
       */
      source?: "registry" | "community";
      /**
       * Tags
       * @default null
       */
      tags?: string[];
      /**
       * Transport
       * @default null
       */
      transport?: string | null;
    };
    /** Nl2AgentWebSkillCard */
    Nl2AgentWebSkillCard: {
      /** Card Key */
      card_key: string;
      /**
       * @description discriminator enum property added by openapi-typescript
       * @enum {string}
       */
      card_type: "web_skill";
      /** Payload */
      payload:
        | components["schemas"]["Nl2AgentWebSkillListCardPayload"]
        | components["schemas"]["Nl2AgentWebSkillSingleCardPayload"];
    };
    /** Nl2AgentWebSkillCardItem */
    Nl2AgentWebSkillCardItem: {
      /**
       * Agent Id
       * @default null
       */
      agent_id?: number;
      /**
       * Description
       * @default null
       */
      description?: string;
      /**
       * Name
       * @default null
       */
      name?: string;
      /**
       * Reason
       * @default null
       */
      reason?: string;
      /**
       * Recommendation Batch Id
       * @default null
       */
      recommendation_batch_id?: string;
      /**
       * Score
       * @default null
       */
      score?: number;
      /**
       * Skill Id
       * @default null
       */
      skill_id?: number;
      /**
       * Skill Name
       * @default null
       */
      skill_name?: string;
      /**
       * Source
       * @default null
       */
      source?: string;
      /**
       * Status
       * @default null
       */
      status?: string;
      /**
       * Tags
       * @default null
       */
      tags?: string[];
    } & ((unknown | unknown) & (unknown | unknown));
    /** Nl2AgentWebSkillConfigurationResponse */
    Nl2AgentWebSkillConfigurationResponse: {
      /** Config Schemas */
      config_schemas?: components["schemas"]["Nl2AgentSkillParameterSchema"][];
      /** Config Values */
      config_values?: {
        [key: string]: unknown;
      };
      /** Skill Id */
      skill_id?: number | null;
      /** Skill Name */
      skill_name: string;
    };
    /** Nl2AgentWebSkillListCardPayload */
    Nl2AgentWebSkillListCardPayload: {
      /**
       * Agent Id
       * @default null
       */
      agent_id?: number;
      /** Items */
      items: components["schemas"]["Nl2AgentWebSkillCardItem"][];
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
    };
    /** Nl2AgentWebSkillSingleCardPayload */
    Nl2AgentWebSkillSingleCardPayload: {
      /**
       * Agent Id
       * @default null
       */
      agent_id?: number;
      /**
       * Description
       * @default null
       */
      description?: string;
      /**
       * Name
       * @default null
       */
      name?: string;
      /**
       * Reason
       * @default null
       */
      reason?: string;
      /** Recommendation Batch Id */
      recommendation_batch_id: string;
      /**
       * Score
       * @default null
       */
      score?: number;
      /**
       * Skill Id
       * @default null
       */
      skill_id?: number;
      /**
       * Skill Name
       * @default null
       */
      skill_name?: string;
      /**
       * Source
       * @default null
       */
      source?: string;
      /**
       * Status
       * @default null
       */
      status?: string;
      /**
       * Tags
       * @default null
       */
      tags?: string[];
    } & ((unknown | unknown) & (unknown | unknown));
    /** Nl2AgentWorkflowStateResponse */
    Nl2AgentWorkflowStateResponse: {
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
      /** Recommendations */
      recommendations?: {
        [key: string]: components["schemas"]["RecommendationBatch"];
      };
      requirements_review: components["schemas"]["Nl2AgentRequirementsReviewResponse"];
      /**
       * Revision
       * @default 0
       */
      revision?: number;
      /**
       * Revision Mode
       * @default false
       */
      revision_mode?: boolean;
      /**
       * Schema Version
       * @default 3
       * @constant
       */
      schema_version?: 3;
    };
    /**
     * RecommendationBatch
     * @description One immutable search proof and its presentation/application lifecycle.
     */
    RecommendationBatch: {
      /** Applied Skill Ids */
      applied_skill_ids?: number[];
      /** Applied Tool Ids */
      applied_tool_ids?: number[];
      /**
       * Catalog Hash
       * @default
       */
      catalog_hash?: string;
      /**
       * Catalog Version
       * @default
       */
      catalog_version?: string;
      /** Item Keys */
      item_keys?: string[];
      /** Operation Id */
      operation_id?: string | null;
      /**
       * Resource Type
       * @enum {string}
       */
      resource_type: "local" | "mcp" | "skill";
      /** Skill Ids */
      skill_ids?: number[];
      /**
       * Status
       * @enum {string}
       */
      status:
        | "searched"
        | "presented"
        | "applying"
        | "applied"
        | "skipped"
        | "completed";
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
  resolve_session_by_agent_api_nl2agent_session_by_agent__draft_agent_id__get: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        draft_agent_id: number;
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
          "application/json":
            components["schemas"]["Nl2AgentSessionSummaryResponse"] | null;
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
          "application/json":
            components["schemas"]["Nl2AgentSessionSummaryResponse"] | null;
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
  abandon_session_api_nl2agent_session__draft_agent_id__abandon_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        draft_agent_id: number;
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
  dispatch_action_api_nl2agent_session__draft_agent_id__actions_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        draft_agent_id: number;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json":
          | components["schemas"]["Nl2AgentConfirmRequirementsActionRequest"]
          | components["schemas"]["Nl2AgentSaveModelSelectionActionRequest"]
          | components["schemas"]["Nl2AgentApplyLocalResourcesActionRequest"]
          | components["schemas"]["Nl2AgentSkipLocalResourcesActionRequest"]
          | components["schemas"]["Nl2AgentInstallMcpActionRequest"]
          | components["schemas"]["Nl2AgentBindMcpToolsActionRequest"]
          | components["schemas"]["Nl2AgentSkipMcpToolsActionRequest"]
          | components["schemas"]["Nl2AgentInstallWebSkillActionRequest"]
          | components["schemas"]["Nl2AgentCompleteOnlineConfigurationActionRequest"]
          | components["schemas"]["Nl2AgentSaveIdentityActionRequest"]
          | components["schemas"]["Nl2AgentFinalizeActionRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Nl2AgentActionResponse"];
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
  resume_session_api_nl2agent_session__draft_agent_id__resume_post: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        draft_agent_id: number;
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
  get_session_state_api_nl2agent_session__draft_agent_id__state_get: {
    parameters: {
      query?: never;
      header?: {
        authorization?: string | null;
      };
      path: {
        draft_agent_id: number;
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
  get_web_skill_configuration_api_nl2agent_session__draft_agent_id__web_skill_configuration_get: {
    parameters: {
      query?: {
        skill_id?: number | null;
        skill_name?: string | null;
      };
      header?: {
        authorization?: string | null;
      };
      path: {
        draft_agent_id: number;
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
          "application/json": components["schemas"]["Nl2AgentWebSkillConfigurationResponse"];
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
