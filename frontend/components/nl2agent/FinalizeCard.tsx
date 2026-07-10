"use client";

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button, message, Flex, Divider, Tag } from "antd";
import { CheckCircle2, ArrowRight, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useParams } from "next/navigation";

import { finalizeNl2Agent } from "@/services/nl2agentService";

/** Full agent spec produced by the nl2agent_finalize_proposal skill. */
export interface FinalizeCardData {
  agent_id: number;
  name?: string;
  display_name?: string;
  description?: string;

  business_logic_model_id?: number;
  model_ids?: number[];

  business_description?: string;
  prompt_template_id?: number;
  prompt_template_name?: string;

  duty_prompt?: string;
  constraint_prompt?: string;
  few_shots_prompt?: string;

  greeting_message?: string;
  example_questions?: string[];

  max_steps?: number;
  requested_output_tokens?: number;
  provide_run_summary?: boolean;
  verification_config?: { enabled: boolean; mode?: string };
  enable_context_manager?: boolean;

  selected_tools?: number[];
  selected_skills?: number[];
  sub_agent_ids?: number[];

  tool_configs?: Record<string, Record<string, unknown>>;
  skill_configs?: Record<string, Record<string, unknown>>;

  author?: string;
}

export interface FinalizeCardProps {
  data: FinalizeCardData;
}

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

const FieldLine: React.FC<{ label: string; value?: string | number | boolean }> = ({
  label,
  value,
}) => {
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

/**
 * Renders the full agent spec produced by the nl2agent_finalize_proposal skill.
 * The user reviews the spec and clicks "Review & Publish" to finalize.
 *
 * Rendered from a ```nl2agent-finalize fenced JSON block emitted by the skill.
 */
export const FinalizeCard: React.FC<FinalizeCardProps> = ({ data }) => {
  const { t } = useTranslation("common");
  const router = useRouter();
  const params = useParams<{ locale: string }>();
  const locale = params?.locale || "en";
  const [loading, setLoading] = useState(false);

  const agentId = data.agent_id;

  const handlePublish = async () => {
    setLoading(true);
    try {
      await finalizeNl2Agent(agentId, {
        name: data.name,
        display_name: data.display_name,
        description: data.description,
        business_logic_model_id: data.business_logic_model_id,
        model_ids: data.model_ids ?? [],
        business_description: data.business_description,
        prompt_template_id: data.prompt_template_id,
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
        tool_ids: data.selected_tools ?? [],
        skill_ids: data.selected_skills ?? [],
        sub_agent_ids: data.sub_agent_ids ?? [],
        tool_configs: data.tool_configs ?? {},
        skill_configs: data.skill_configs ?? {},
      });
      message.success(
        t("nl2agent.finalize.published", "Agent published successfully!")
      );
      router.push(`/${locale}/agents?agent_id=${agentId}`);
    } catch {
      message.error(
        t("nl2agent.finalize.error", "Failed to publish agent. Please try again.")
      );
    } finally {
      setLoading(false);
    }
  };

  const displayName = data.display_name || data.name || `Agent #${agentId}`;

  return (
    <div className="my-3 border border-emerald-200 rounded-lg p-4 bg-emerald-50/50 max-h-[480px] overflow-y-auto">
      <div className="flex items-start gap-3">
        <CheckCircle2 className="h-5 w-5 text-emerald-600 flex-shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="font-medium text-emerald-800 text-sm mb-1">
            {t("nl2agent.finalize.title", "Your agent is ready")}
          </div>
          <div className="text-xs text-emerald-700 mb-3">
            {t("nl2agent.finalize.description", {
              defaultValue:
                "Review the generated agent spec below. Click Publish to finalize.",
            })}
          </div>

          {/* Identity */}
          <Section title={t("nl2agent.finalize.identity", "Identity")}>
            <FieldLine label="Name" value={data.name} />
            <FieldLine label="Display Name" value={data.display_name} />
            <FieldLine label="Description" value={data.description} />
          </Section>

          <Divider className="my-2" />

          {/* Models */}
          {data.business_logic_model_id || (data.model_ids?.length ?? 0) > 0 ? (
            <>
              <Section title={t("nl2agent.finalize.models", "LLM Models")}>
                <FieldLine
                  label="Logic Model ID"
                  value={data.business_logic_model_id}
                />
                <FieldLine
                  label="Runtime Model IDs"
                  value={
                    data.model_ids?.length
                      ? data.model_ids.join(", ")
                      : undefined
                  }
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
          {(data.duty_prompt || data.constraint_prompt || data.few_shots_prompt) ? (
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
          {data.greeting_message || (data.example_questions?.length ?? 0) > 0 ? (
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
          {(data.selected_tools?.length ?? 0) > 0 ||
          (data.selected_skills?.length ?? 0) > 0 ? (
            <>
              <Section title={t("nl2agent.finalize.resources", "Selected Resources")}>
                <FieldLine
                  label="Tools"
                  value={
                    data.selected_tools?.length
                      ? data.selected_tools.join(", ")
                      : "None"
                  }
                />
                <FieldLine
                  label="Skills"
                  value={
                    data.selected_skills?.length
                      ? data.selected_skills.join(", ")
                      : "None"
                  }
                />
                <FieldLine
                  label="Sub-Agents"
                  value={
                    data.sub_agent_ids?.length
                      ? data.sub_agent_ids.join(", ")
                      : "None"
                  }
                />
              </Section>
              <Divider className="my-2" />
            </>
          ) : null}

          {/* Runtime */}
          {data.max_steps ||
          data.requested_output_tokens ||
          data.provide_run_summary !== undefined ||
          data.enable_context_manager !== undefined ? (
            <>
              <Section title={t("nl2agent.finalize.runtime", "Runtime Options")}>
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
