/**
 * NexusAgent — HttpAgent subclass for the Nexus backend API.
 *
 * Translates AG-UI's ``RunAgentInput`` (messages, forwardedProps, ...) into
 * the Nexus ``AgentRequest`` body format (query, history, conversation_id,
 * agent_id, etc.) that ``/api/agent/run`` expects.
 *
 * Usage::
 *
 *   const agent = new NexusAgent({
 *     url: API_ENDPOINTS.agent.run,
 *     headers: { ...authHeaders, "x-agui-format": "true" },
 *     onResponseHeaders: (headers) => {
 *       const convId = headers.get("conversation_id");
 *       if (convId) console.log("New conversation:", convId);
 *     },
 *   });
 */

import {
  HttpAgent,
  type RunAgentInput,
  type HttpAgentConfig,
} from "@ag-ui/client";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * Nexus-specific runtime config that the composer / page passes through
 * ``forwardedProps``.  This is the bridge between assistant-ui's generic
 * run() and the Nexus backend's AgentRequest fields.
 */
export interface NexusRunConfig {
  /** Server-side conversation id (numeric).  Undefined → let backend create one. */
  conversation_id?: number | string;
  /**
   * Assistant-ui's local thread id — used as the stable key for
   * serverConversationIdsRef mapping.  This is NOT the server-issued
   * conversation_id; it's the client-side thread identifier that stays
   * constant across the thread's lifetime.
   */
  threadKey?: string;
  /** Agent id to run. */
  agent_id?: number | string;
  /** Agent version override. */
  version_no?: number;
  /** Model id override (for agent-debug "Model" selector). */
  model_id?: number;
  /** Debug mode flag (agent-debug). */
  is_debug?: boolean;
  /** Enable planning mode. */
  enable_plan?: boolean;
  /** Knowledge scope override. */
  knowledge_scope?: unknown;
  /** Runtime metadata carried to the agent. */
  metadata?: Record<string, unknown>;
  /** Optimistic-lock version for metadata updates. */
  expected_metadata_version?: number;
  /** Runtime mode marker (nl2agent / nl2skill). */
  runtime_mode?: "nl2agent" | "nl2skill";
  /** NL2Skill draft snapshot. */
  draft_snapshot?: Record<string, unknown>;
  /** NL2Skill complexity hint. */
  complexity?: "simple" | "complicated";
  /** NL2Skill language. */
  language?: "zh" | "en";
  /** Optional file attachments in Nexus format. */
  minio_files?: Array<{
    object_name?: string;
    name: string;
    type: string;
    size: number;
    url?: string;
    presigned_url?: string;
    description?: string;
  }>;
}

/**
 * Combined forwardedProps shape — Nexus run config AND optional A2UI button
 * action from the generative-ui layer.
 */
export interface NexusForwardedProps extends NexusRunConfig {
  /** A2UI button action payload (from ``useAgUiSendA2uiAction``). */
  a2uiAction?: {
    userAction: string | Record<string, unknown>;
  };
}

interface NexusAgentConfig extends HttpAgentConfig {
  /**
   * Callback to extract response headers (e.g. ``conversation_id``) back
   * to the UI.  ``threadKey`` is the assistant-ui thread id (or runKey)
   * captured from the incoming forwardedProps at request time, so the caller
   * can map the server-issued conversation_id to the correct thread.
   */
  onResponseHeaders?: (headers: Headers, threadKey?: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Extract the last user message's text content from an AG-UI message array.
 * Returns empty string if no user message is found.
 */
function extractLastUserQuery(messages: RunAgentInput["messages"]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    if (msg.role === "user") {
      const content = msg.content;
      if (typeof content === "string") return content;
      if (Array.isArray(content)) {
        return content
          .map((part) => {
            if (part.type === "text") return part.text;
            if (part.type === "image") return "[image]";
            if (part.type === "audio") return "[audio]";
            if (part.type === "video") return "[video]";
            if (part.type === "document") return "[document]";
            if (part.type === "binary") return "[binary]";
            return "";
          })
          .join("\n");
      }
      return "";
    }
  }
  return "";
}

/**
 * Convert AG-UI messages → Nexus history format
 * (``{role: "user"|"assistant", content: string}``).
 *
 * We only include user and assistant messages because Nexus backend expects
 * that shape.  System/developer messages live in the agent config, not the
 * conversation history.
 */
function buildNexusHistory(
  messages: RunAgentInput["messages"]
): Array<{ role: string; content: string }> {
  return messages
    .filter((m) => m.role === "user" || m.role === "assistant")
    .map((m) => {
      const role = m.role;
      let content = "";
      if (m.role === "user") {
        if (typeof m.content === "string") content = m.content;
        else if (Array.isArray(m.content)) {
          content = m.content
            .map((part) => {
              if (part.type === "text") return part.text;
              return "";
            })
            .join("\n");
        }
      } else if (m.role === "assistant") {
        content = (m.content ?? "") as string;
        // If the assistant message has toolCalls, include them as context
        if (m.toolCalls && m.toolCalls.length > 0) {
          const toolSummary = m.toolCalls
            .map((tc) => `[tool: ${tc.function.name}]`)
            .join(", ");
          content = content ? `${content}\n${toolSummary}` : toolSummary;
        }
      }
      return { role, content };
    })
    .filter((h) => h.content.trim().length > 0);
}

// ---------------------------------------------------------------------------
// NexusAgent
// ---------------------------------------------------------------------------

export class NexusAgent extends HttpAgent {
  private readonly _onResponseHeaders?: (
    headers: Headers,
    threadKey?: string
  ) => void;

  /** Base URL set in constructor — used to restore URL after nl2 variants. */
  private readonly _baseUrl: string;

  /**
   * Stored Nexus run config (agent_id, conversation_id, etc.).
   *
   * Set by the React component via ``agent.setRunConfig(...)`` whenever the
   * composer's ``runConfig.custom`` changes.  Merged into ``forwardedProps``
   * at request-construction time so the backend receives Nexus-specific
   * parameters alongside the AG-UI protocol envelope.
   */
  private _runConfig: NexusRunConfig = {};

  /**
   * Thread key captured from the incoming forwardedProps at request time
   * (in requestInit).  Used by the fetch wrapper's onResponseHeaders callback
   * to tell the caller which assistant-ui thread this response belongs to.
   * Without this, NexusAgent cannot know the thread identity because AG-UI's
   * HttpAgent transport is stateless.
   */
  private _pendingThreadKey?: string;

  constructor(config: NexusAgentConfig) {
    // super() must come before any 'this' access in derived class constructors.
    super(config);
    const self = this;

    // Override fetch to capture response headers and tee SSE for debug logging.
    // HttpAgent stores fetch as a public instance property, so we can replace it
    // after super() and it will be used by the inherited run() method.
    const origFetch = (config.fetch ?? fetch) as typeof fetch;
    this.fetch = (async (url: string, init: RequestInit): Promise<Response> => {
      const threadKey = self._pendingThreadKey;
      const resp = await origFetch(url, init);
      console.log("[NexusAgent.fetch] status:", resp.status, "content-type:", resp.headers.get("content-type"));

      if (
        resp.ok &&
        resp.headers.get("content-type")?.includes("text/event-stream") &&
        resp.body
      ) {
        // Tee the SSE stream so we can log events without consuming the real body.
        const [loggedBody, originalBody] = resp.body.tee();
        self._onResponseHeaders?.(resp.headers, threadKey);
        self._pendingThreadKey = undefined;

        const reader = loggedBody.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        const MAX_LOG_LINES = 500;  // Increased from 20 so we can see ACTIVITY_SNAPSHOT / RUN_FINISHED
        let lineCount = 0;
        (async () => {
          try {
            while (lineCount < MAX_LOG_LINES) {
              const { done, value } = await reader.read();
              if (done) break;
              buffer += decoder.decode(value, { stream: true });
              const lines = buffer.split("\n");
              buffer = lines.pop() || "";
              for (const line of lines) {
                if (line.startsWith("data:")) {
                  const payload = line.substring(5);
                  // Highlight critical events so they stand out in DevTools
                  if (payload.includes('"ACTIVITY_SNAPSHOT"') || payload.includes('"RUN_FINISHED"') || payload.includes('"RUN_ERROR"')) {
                    console.warn("═══ [NexusAgent KEY EVENT] ═══", JSON.parse(payload));
                  } else {
                    console.log("[NexusAgent SSE]", payload.substring(0, 300));
                  }
                  lineCount++;
                } else if (line.trim()) {
                  console.log("[NexusAgent SSE raw]", line.substring(0, 200));
                  lineCount++;
                }
              }
            }
            if (lineCount >= MAX_LOG_LINES) {
              console.log(`[NexusAgent SSE] log truncated at ${MAX_LOG_LINES} lines`);
            }
          } catch (e) {
            console.error("[NexusAgent SSE log error]", e);
          }
        })();

        return new Response(originalBody, resp);
      }

      self._onResponseHeaders?.(resp.headers, threadKey);
      self._pendingThreadKey = undefined;
      return resp;
    }) as typeof fetch;

    this._onResponseHeaders = config.onResponseHeaders;
    this._baseUrl = config.url;
  }

  /**
   * Switch the backend endpoint URL.  Used for nl2agent / nl2skill variants
   * that hit different API endpoints than the standard agent.run.
   */
  setEndpointUrl(url: string): void {
    (this as unknown as { url: string }).url = url;
  }

  /** Restore the base (default agent.run) URL. */
  restoreBaseUrl(): void {
    (this as unknown as { url: string }).url = this._baseUrl;
  }

  /**
   * Update the stored Nexus run config.  Called from the React component
   * whenever agent_id / conversation_id / chat mode / etc. changes.
   *
   * Also auto-switches the endpoint URL for nl2agent / nl2skill runtime
   * modes so the component doesn't have to manage URLs itself.
   */
  setRunConfig(config: NexusRunConfig): void {
    this._runConfig = config;
    // Auto-switch endpoint URL based on runtime_mode
    const runtimeMode = config.runtime_mode;
    const urlMap: Record<string, string> = (NexusAgent as any)._urlMap;
    if (runtimeMode && urlMap && urlMap[runtimeMode]) {
      this.setEndpointUrl(urlMap[runtimeMode]);
    } else {
      this.restoreBaseUrl();
    }
  }

  /**
   * Static endpoint URL registry.  Components register their custom URLs
   * at module load time so NexusAgent can auto-switch based on runtime_mode.
   */
  static _urlMap: Record<string, string> = {};

  /** Register a runtime_mode → endpoint URL mapping. */
  static registerEndpoint(runtimeMode: string, url: string): void {
    (NexusAgent as any)._urlMap[runtimeMode] = url;
  }

  /**
   * Override the HTTP request builder to produce a Nexus AgentRequest body.
   *
   * The default HttpAgent implementation serialises ``RunAgentInput`` directly
   * as JSON — that would not work because Nexus has a completely different
   * schema (query string, numeric conversation_id, minio_files, ...).
   */
  protected requestInit(input: RunAgentInput): RequestInit {
    console.log('[NexusAgent.requestInit] CALLED', {
      threadId: input.threadId,
      runId: input.runId,
      messageCount: input.messages?.length,
      hasForwardedProps: !!input.forwardedProps,
    });
    const body = this._buildAgentRequestBody(input);
    console.log('[NexusAgent.requestInit] body keys:', Object.keys(body));

    return {
      method: "POST",
      headers: {
        ...this.headers,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    };
  }

  // ------------------------------------------------------------------
  // Body construction
  // ------------------------------------------------------------------

  private _buildAgentRequestBody(input: RunAgentInput): Record<string, unknown> {
    const query = extractLastUserQuery(input.messages);
    const history = buildNexusHistory(input.messages);

    // ---- Merge priority: stored runConfig < forwardedProps.runConfig.custom < forwardedProps.a2uiAction ---
    // AG-UI runtime's buildRunInput() nests runConfig.custom under forwardedProps.runConfig,
    // and a2uiAction under forwardedProps.a2uiAction. We need to extract both.
    const fp = (input.forwardedProps ?? {}) as Record<string, unknown>;
    const runConfigCustom =
      (fp.runConfig as Record<string, unknown> | undefined) ?? {};
    const a2uiAction = fp.a2uiAction as
      | { userAction: string | Record<string, unknown> }
      | undefined;

    // Also read NexusRunConfig fields directly from forwardedProps (in case
    // someone passes them at top level via NexusAgent.setRunConfig merge).
    const topLevel = fp as Partial<NexusRunConfig>;

    // Build the effective run config with proper priority ordering:
    //   1. _runConfig (lowest — defaults from setRunConfig)
    //   2. top-level forwardedProps fields (compat)
    //   3. forwardedProps.runConfig.custom (highest — runtime composer.setRunConfig)
    const merged: Record<string, unknown> = {
      ...this._runConfig,
      ...topLevel,
      ...runConfigCustom,
    };

    // Capture the thread key BEFORE destructuring — it's needed by the
    // fetch wrapper to map the response headers back to the correct thread.
    const threadKey = (merged.threadKey as string | undefined) ??
      (merged.localThreadId as string | undefined) ??
      runConfigCustom.threadKey as string | undefined;
    if (threadKey) {
      this._pendingThreadKey = threadKey;
    }

    const {
      conversation_id,
      threadId, // assistant-ui uses "threadId" not "conversation_id"
      agent_id,
      agentId, // assistant-ui uses "agentId" not "agent_id"
      agentVersionNo,
      version_no,
      model_id,
      is_debug,
      enable_plan,
      enablePlan,
      knowledge_scope,
      knowledgeScope,
      metadata,
      runtimeMetadata,
      expected_metadata_version,
      runtimeMetadataVersion,
      runtime_mode,
      draft_snapshot,
      complexity,
      language,
      minio_files,
    } = merged;

    // Resolve fields with both Nexus and assistant-ui naming conventions
    const resolvedConversationId =
      conversation_id ?? threadId;
    const resolvedAgentId = agent_id ?? agentId;
    const resolvedVersionNo = version_no ?? agentVersionNo;
    const resolvedEnablePlan = enable_plan ?? enablePlan;
    const resolvedKnowledgeScope = knowledge_scope ?? knowledgeScope;
    const resolvedMetadata = metadata ?? runtimeMetadata;
    const resolvedMetadataVersion =
      expected_metadata_version ?? runtimeMetadataVersion;

    const body: Record<string, unknown> = {
      query,
      history,
      conversation_id:
        resolvedConversationId !== undefined && resolvedConversationId !== null
          ? String(resolvedConversationId)
          : null,
      minio_files: minio_files ?? null,
      is_debug: is_debug ?? false,
      enable_plan: resolvedEnablePlan ?? false,
      // --- forwardedProps round-trip ---
      forwarded_props: a2uiAction ? { a2uiAction } : undefined,
    };

    if (resolvedAgentId !== undefined && resolvedAgentId !== null)
      body.agent_id = resolvedAgentId;
    if (model_id !== undefined && model_id !== null) body.model_id = model_id;
    if (resolvedVersionNo !== undefined && resolvedVersionNo !== null)
      body.version_no = resolvedVersionNo;
    if (resolvedKnowledgeScope !== undefined)
      body.knowledge_scope = resolvedKnowledgeScope;
    if (resolvedMetadata !== undefined) body.metadata = resolvedMetadata;
    if (resolvedMetadataVersion !== undefined)
      body.expected_metadata_version = resolvedMetadataVersion;

    // NL2 variants
    if (runtime_mode === "nl2skill") {
      body.draft_snapshot = draft_snapshot;
      body.complexity = complexity ?? "complicated";
      body.language = language;
    }

    return body;
  }
}
