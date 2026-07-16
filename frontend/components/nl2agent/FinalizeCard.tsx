"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Alert, Button, message, Flex, Divider, Tag } from "antd";
import { CheckCircle2, ArrowRight, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useParams } from "next/navigation";

import {
  finalizeNl2Agent,
  getNl2AgentSessionState,
  type Nl2AgentFinalizePayload,
  type Nl2AgentSessionState,
} from "@/services/nl2agentService";

/** Unsaved descriptive, prompt, and runtime fields proposed for publication. */
export interface FinalizeCardData {
  agent_id: number;
  description?: string;
  business_description: string;

  duty_prompt: string;
  constraint_prompt?: string;
  few_shots_prompt?: string;

  greeting_message: string;
  example_questions?: string[];

  max_steps?: number;
  requested_output_tokens?: number;
  provide_run_summary?: boolean;
  verification_config?: FinalizeVerificationConfig;
  enable_context_manager?: boolean;
}

export interface FinalizeCardProps {
  data: FinalizeCardData;
}

export interface FinalReviewResource {
  id: number;
  kind: "tool" | "skill";
  name: string;
  origin: "local" | "online";
  source: string;
}

export const groupFinalReviewResources = (state: Nl2AgentSessionState) => {
  const resources: FinalReviewResource[] = [
    ...state.tools.map((tool) => ({
      id: tool.tool_id,
      kind: "tool" as const,
      name: tool.name,
      origin: tool.origin,
      source: tool.source,
    })),
    ...state.skills.map((skill) => ({
      id: skill.skill_id,
      kind: "skill" as const,
      name: skill.name,
      origin: skill.origin,
      source: skill.source,
    })),
  ];
  return {
    local: resources.filter((resource) => resource.origin === "local"),
    online: resources.filter((resource) => resource.origin === "online"),
  };
};

export const canPublishFinalReview = (
  state: Nl2AgentSessionState | null,
  proposalComplete: boolean,
  stateLoading: boolean,
  stateError: string | null
) =>
  Boolean(
    state?.identity_confirmed &&
    proposalComplete &&
    !state.invalid_references.length &&
    !stateLoading &&
    !stateError
  );

export type FinalizeVerificationConfig = NonNullable<
  Nl2AgentFinalizePayload["verification_config"]
> & { enabled: boolean };

export const getVerificationReviewFields = (
  config: FinalizeVerificationConfig
): Array<{ label: string; value: string | number }> => {
  if (!config.enabled) {
    return [{ label: "Verification", value: "Disabled" }];
  }
  const fields: Array<{ label: string; value: string | number }> = [
    { label: "Verification", value: "Enabled" },
  ];
  if (config.strictness) {
    fields.push({ label: "Strictness", value: config.strictness });
  }
  if (config.max_final_rounds !== undefined) {
    fields.push({
      label: "Max Verification Rounds",
      value: config.max_final_rounds,
    });
  }
  if (config.fail_policy) {
    fields.push({ label: "Failure Policy", value: config.fail_policy });
  }
  return fields;
};

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({
  title,
  children,
}) => (
  <div className="mb-3">
    <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
      {title}
    </div>
    {children}
  </div>
);

const FieldLine: React.FC<{
  label: string;
  value?: string | number | boolean | null;
}> = ({ label, value }) => {
  if (value === undefined || value === null || value === "") return null;
  return (
    <div className="flex gap-2 text-xs">
      <span className="text-gray-500 min-w-[120px]">{label}:</span>
      <span className="text-gray-800 break-all">
        {typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}
      </span>
    </div>
  );
};

const NameList: React.FC<{
  label: string;
  items: Array<{ key: string; name: string; typeLabel?: string }>;
  emptyText: string;
}> = ({ label, items, emptyText }) => (
  <div className="mb-2 text-xs">
    <div className="mb-1 text-gray-500">{label}</div>
    {items.length ? (
      <div className="space-y-1">
        {items.map((item) => (
          <div
            key={item.key}
            className="rounded border border-gray-200 bg-white px-2 py-1 text-gray-800 break-words"
          >
            {item.typeLabel ? (
              <span className="mr-1 text-gray-500">{item.typeLabel} ·</span>
            ) : null}
            {item.name}
          </div>
        ))}
      </div>
    ) : (
      <div className="text-gray-400">{emptyText}</div>
    )}
  </div>
);

/**
 * Renders the proposal together with authoritative persisted draft state.
 * The user reviews the spec and clicks "Review & Publish" to finalize.
 *
 * Rendered from a ```nl2agent-finalize fenced JSON block emitted by NL2AGENT.
 */
export const FinalizeCard: React.FC<FinalizeCardProps> = ({ data }) => {
  const { t } = useTranslation("common");
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params?.locale || "en";
  const [loading, setLoading] = useState(false);
  const [sessionState, setSessionState] = useState<Nl2AgentSessionState | null>(
    null
  );
  const [stateLoading, setStateLoading] = useState(true);
  const [stateError, setStateError] = useState<string | null>(null);

  const agentId = data.agent_id;

  const loadState = useCallback(async () => {
    setStateLoading(true);
    setStateError(null);
    try {
      setSessionState(await getNl2AgentSessionState(agentId));
    } catch (error: any) {
      setSessionState(null);
      setStateError(error?.message || "Failed to load persisted agent state.");
    } finally {
      setStateLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void loadState();
  }, [loadState]);

  const proposalComplete = Boolean(
    data.business_description?.trim() &&
    data.duty_prompt?.trim() &&
    data.greeting_message?.trim()
  );
  const canPublish = canPublishFinalReview(
    sessionState,
    proposalComplete,
    stateLoading,
    stateError
  );

  const handlePublish = async () => {
    setLoading(true);
    try {
      await finalizeNl2Agent(agentId, {
        description: data.description,
        business_description: data.business_description,
        duty_prompt: data.duty_prompt,
        constraint_prompt: data.constraint_prompt,
        few_shots_prompt: data.few_shots_prompt,
        greeting_message: data.greeting_message,
        example_questions: data.example_questions ?? [],
        max_steps: data.max_steps,
        requested_output_tokens: data.requested_output_tokens,
        provide_run_summary: data.provide_run_summary,
        verification_config: data.verification_config,
        enable_context_manager: data.enable_context_manager,
      });
      message.success(
        t("nl2agent.finalize.published", "Agent published successfully!")
      );
      router.push(`/${locale}/agents?agent_id=${agentId}`);
    } catch (error: any) {
      message.error(
        error?.message ||
          t(
            "nl2agent.finalize.error",
            "Failed to publish agent. Please try again."
          )
      );
    } finally {
      setLoading(false);
    }
  };

  if (stateLoading) {
    return (
      <div className="my-3 rounded-lg border border-gray-200 bg-white p-6 text-center text-sm text-gray-500">
        <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
        Loading persisted agent state...
      </div>
    );
  }

  if (stateError || !sessionState) {
    return (
      <div className="my-3 rounded-lg border border-red-200 bg-red-50 p-4">
        <Alert
          type="error"
          showIcon
          message="Persisted agent state could not be loaded"
          description={stateError || "No persisted state was returned."}
          action={
            <Button size="small" onClick={() => void loadState()}>
              Retry
            </Button>
          }
        />
      </div>
    );
  }

  const resourceGroups = groupFinalReviewResources(sessionState);
  const primaryModels = sessionState.models.filter(
    (model) => model.role === "primary" && model.display_name
  );
  const fallbackModels = sessionState.models.filter(
    (model) => model.role === "fallback" && model.display_name
  );
  const invalidReferenceText = sessionState.invalid_references
    .map(
      (reference) =>
        `${reference.reference_type} #${reference.reference_id} (${reference.reason})`
    )
    .join(", ");

  return (
    <div className="my-3 border border-emerald-200 rounded-lg p-4 bg-emerald-50/50 max-h-[480px] overflow-y-auto">
      <div className="flex items-start gap-3">
        <CheckCircle2 className="h-5 w-5 text-emerald-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="font-medium text-emerald-800 text-sm mb-1">
            {t("nl2agent.finalize.title", "Your agent is ready")}
          </div>

          {!sessionState.identity_confirmed ? (
            <Alert
              type="warning"
              showIcon
              message="Agent identity has not been saved"
              description="Return to the identity card and save the display name before publishing."
              className="mb-3"
            />
          ) : sessionState.invalid_references.length ? (
            <Alert
              type="error"
              showIcon
              message={t(
                "nl2agent.finalize.invalidReferences",
                "Selected models or resources are no longer valid"
              )}
              description={t("nl2agent.finalize.invalidReferencesDescription", {
                defaultValue:
                  "Reconfigure the draft before publishing. Invalid references: {{references}}",
                references: invalidReferenceText,
              })}
              className="mb-3"
            />
          ) : !proposalComplete ? (
            <Alert
              type="warning"
              showIcon
              message="The generated proposal is incomplete"
              description="Business description, duty prompt, and greeting message are required."
              className="mb-3"
            />
          ) : null}
          <div className="text-xs text-emerald-700 mb-3">
            {t("nl2agent.finalize.description", {
              defaultValue:
                "Review the generated agent spec below. Click Publish to finalize.",
            })}
          </div>

          {/* Identity */}
          <Section title={t("nl2agent.finalize.identity", "Identity")}>
            <FieldLine
              label="Agent Display Name"
              value={sessionState.display_name}
            />
            <FieldLine
              label="Internal Variable Name"
              value={sessionState?.internal_name}
            />
            <FieldLine label="Description" value={data.description} />
          </Section>

          <Divider className="my-2" />

          {/* Models */}
          {sessionState.models.length > 0 ? (
            <>
              <Section title={t("nl2agent.finalize.models", "LLM Models")}>
                <NameList
                  label={t("nl2agent.finalize.primaryModel", "Primary Model")}
                  items={primaryModels.map((model) => ({
                    key: `model-${model.model_id}`,
                    name: model.display_name || "",
                  }))}
                  emptyText={t("nl2agent.finalize.none", "None")}
                />
                <NameList
                  label={t(
                    "nl2agent.finalize.fallbackModels",
                    "Fallback Models"
                  )}
                  items={fallbackModels.map((model) => ({
                    key: `model-${model.model_id}`,
                    name: model.display_name || "",
                  }))}
                  emptyText={t("nl2agent.finalize.none", "None")}
                />
              </Section>
              <Divider className="my-2" />
            </>
          ) : null}

          {/* Task */}
          {data.business_description ? (
            <>
              <Section title={t("nl2agent.finalize.task", "Task")}>
                <div className="text-xs text-gray-700 bg-white rounded border border-gray-200 p-2 whitespace-pre-wrap">
                  {data.business_description}
                </div>
              </Section>
              <Divider className="my-2" />
            </>
          ) : null}

          {/* Prompts */}
          {data.duty_prompt ||
          data.constraint_prompt ||
          data.few_shots_prompt ? (
            <>
              <Section title={t("nl2agent.finalize.prompts", "Prompts")}>
                {data.duty_prompt ? (
                  <div className="mb-2">
                    <div className="text-[11px] text-gray-500 mb-0.5">
                      {t("nl2agent.finalize.duty", "Duty")}
                    </div>
                    <div className="text-xs text-gray-700 bg-white rounded border border-gray-200 p-2 whitespace-pre-wrap">
                      {data.duty_prompt}
                    </div>
                  </div>
                ) : null}
                {data.constraint_prompt ? (
                  <div className="mb-2">
                    <div className="text-[11px] text-gray-500 mb-0.5">
                      {t("nl2agent.finalize.constraints", "Constraints")}
                    </div>
                    <div className="text-xs text-gray-700 bg-white rounded border border-gray-200 p-2 whitespace-pre-wrap">
                      {data.constraint_prompt}
                    </div>
                  </div>
                ) : null}
                {data.few_shots_prompt ? (
                  <div className="mb-2">
                    <div className="text-[11px] text-gray-500 mb-0.5">
                      {t("nl2agent.finalize.fewshots", "Few-Shot Examples")}
                    </div>
                    <div className="text-xs text-gray-700 bg-white rounded border border-gray-200 p-2 whitespace-pre-wrap">
                      {data.few_shots_prompt}
                    </div>
                  </div>
                ) : null}
              </Section>
              <Divider className="my-2" />
            </>
          ) : null}

          {/* UI */}
          {data.greeting_message ||
          (data.example_questions?.length ?? 0) > 0 ? (
            <>
              <Section title={t("nl2agent.finalize.ui", "Greeting & Starters")}>
                <FieldLine label="Greeting" value={data.greeting_message} />
                {data.example_questions?.length ? (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {data.example_questions.map((q, i) => (
                      <Tag key={i} className="text-xs">
                        {q}
                      </Tag>
                    ))}
                  </div>
                ) : null}
              </Section>
              <Divider className="my-2" />
            </>
          ) : null}

          {/* Resources */}
          {sessionState.tools.length > 0 || sessionState.skills.length > 0 ? (
            <>
              <Section
                title={t("nl2agent.finalize.resources", "Selected Resources")}
              >
                <NameList
                  label={t(
                    "nl2agent.finalize.localResources",
                    "Local Resources"
                  )}
                  items={resourceGroups.local.map((resource) => ({
                    key: `${resource.kind}-${resource.id}`,
                    name: resource.name,
                    typeLabel: t(
                      resource.kind === "tool"
                        ? "nl2agent.finalize.tool"
                        : "nl2agent.finalize.skill",
                      resource.kind === "tool" ? "Tool" : "Skill"
                    ),
                  }))}
                  emptyText={t("nl2agent.finalize.none", "None")}
                />
                <NameList
                  label={t(
                    "nl2agent.finalize.onlineResources",
                    "Online Resources"
                  )}
                  items={resourceGroups.online.map((resource) => ({
                    key: `${resource.kind}-${resource.id}`,
                    name: resource.name,
                    typeLabel: t(
                      resource.kind === "tool"
                        ? "nl2agent.finalize.mcpTool"
                        : "nl2agent.finalize.officialSkill",
                      resource.kind === "tool" ? "MCP Tool" : "Official Skill"
                    ),
                  }))}
                  emptyText={t("nl2agent.finalize.none", "None")}
                />
              </Section>
              <Divider className="my-2" />
            </>
          ) : null}

          {/* Runtime */}
          {data.max_steps ||
          data.requested_output_tokens ||
          data.provide_run_summary !== undefined ||
          data.verification_config !== undefined ||
          data.enable_context_manager !== undefined ? (
            <>
              <Section
                title={t("nl2agent.finalize.runtime", "Runtime Options")}
              >
                <FieldLine label="Max Steps" value={data.max_steps} />
                <FieldLine
                  label="Output Tokens"
                  value={data.requested_output_tokens}
                />
                <FieldLine
                  label="Run Summary"
                  value={
                    data.provide_run_summary !== undefined
                      ? data.provide_run_summary
                        ? "Enabled"
                        : "Disabled"
                      : undefined
                  }
                />
                {data.verification_config
                  ? getVerificationReviewFields(data.verification_config).map(
                      (field) => (
                        <FieldLine
                          key={field.label}
                          label={field.label}
                          value={field.value}
                        />
                      )
                    )
                  : null}
                <FieldLine
                  label="Context Manager"
                  value={
                    data.enable_context_manager !== undefined
                      ? data.enable_context_manager
                        ? "Enabled"
                        : "Disabled"
                      : undefined
                  }
                />
              </Section>
            </>
          ) : null}

          {/* Action */}
          <Flex justify="flex-end" align="center" gap={8} className="mt-3">
            <span className="text-[11px] text-gray-400">
              agent_id: {agentId}
            </span>
            <Button
              size="small"
              type="primary"
              onClick={handlePublish}
              loading={loading}
              disabled={!canPublish}
              icon={
                loading ? (
                  <Loader2 className="h-3.5 w-3.5" />
                ) : (
                  <ArrowRight className="h-3.5 w-3.5" />
                )
              }
            >
              {t("nl2agent.finalize.publish", "Review & Publish")}
            </Button>
          </Flex>
        </div>
      </div>
    </div>
  );
};
