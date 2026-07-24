"use client";

import React, { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Alert,
  Checkbox,
  Button,
  Input,
  InputNumber,
  Select,
  Switch,
  message as AntMessage,
} from "antd";
import { CheckCircle2, Loader2 } from "lucide-react";
import type { LocalToolParameterSchema } from "@/services/nl2agentService";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";
import { useNl2AgentCardLifecycle } from "./useNl2AgentCardLifecycle";

export interface LocalResourceItem {
  tool_id?: number;
  skill_id?: number;
  name: string;
  description?: string;
  source?: string;
  score?: number;
  reason?: string;
  kind: "tool" | "skill";
}

export interface LocalResourcesCardProps {
  /** The draft agent_id being built by the NL2AGENT session. */
  agentId: number;
  recommendationBatchId: string;
  workflowRevision?: number;
  tools: LocalResourceItem[];
  skills: LocalResourceItem[];
}

const MASKED_SECRET_VALUE = "••••••••";

/**
 * Renders recommended local tools and skills with per-item checkboxes and a
 * single "Apply All" button that bulk-binds the selected resources to the
 * draft agent.
 *
 * Rendered from a validated local-resources card in the persisted structured
 * NL2AGENT message envelope.
 */
export const LocalResourcesCard: React.FC<LocalResourcesCardProps> = ({
  agentId,
  recommendationBatchId,
  workflowRevision,
  tools,
  skills,
}) => {
  const workflow = useNl2AgentWorkflow();
  const lifecycle = useNl2AgentCardLifecycle(
    `local:${agentId}:${recommendationBatchId}`,
    workflowRevision
  );
  const { execute, pending } = lifecycle;
  const { t } = useTranslation("common");
  const [selected, setSelected] = useState<Set<string>>(() => {
    const s = new Set<string>();
    tools.forEach((x) => x.tool_id != null && s.add(`t:${x.tool_id}`));
    skills.forEach((x) => x.skill_id != null && s.add(`s:${x.skill_id}`));
    return s;
  });
  const [applied, setApplied] = useState(false);
  const [skipped, setSkipped] = useState(false);
  const [applying, setApplying] = useState(false);
  const [toolParameterSchemas, setToolParameterSchemas] = useState<
    Record<string, LocalToolParameterSchema[]>
  >({});
  const [toolConfigValues, setToolConfigValues] = useState<
    Record<number, Record<string, unknown>>
  >({});
  useEffect(() => {
    const state = workflow.sessionState;
    if (state?.agent_id !== agentId) return;
    const batch =
      state.resource_review.recommendations?.[recommendationBatchId];
    if (!batch || batch.resource_type !== "local") return;

    setApplying(batch.status === "applying");
    setToolParameterSchemas(
      state.local_tool_parameter_schemas?.[recommendationBatchId] ?? {}
    );
    if (batch.status === "applied") {
      const appliedToolIds = batch.applied_tool_ids ?? [];
      const appliedSkillIds = batch.applied_skill_ids ?? [];
      setSelected(
        new Set([
          ...appliedToolIds.map((toolId) => `t:${toolId}`),
          ...appliedSkillIds.map((skillId) => `s:${skillId}`),
        ])
      );
      const summariesById = new Map(
        state.tools.map((tool) => [tool.tool_id, tool])
      );
      setToolConfigValues(
        Object.fromEntries(
          appliedToolIds.map((toolId) => {
            const configuration =
              summariesById.get(toolId)?.configuration ?? {};
            return [
              toolId,
              Object.fromEntries(
                Object.entries(configuration).flatMap(([name, field]) => {
                  if (!field.configured) return [];
                  return [
                    [name, field.secret ? MASKED_SECRET_VALUE : field.value],
                  ];
                })
              ),
            ];
          })
        )
      );
      setApplied(true);
      setSkipped(false);
    } else if (batch.status === "skipped") {
      setSelected(new Set());
      setApplied(false);
      setSkipped(true);
    } else {
      setApplied(false);
      setSkipped(false);
    }
  }, [agentId, recommendationBatchId, workflow.sessionState]);

  const toggle = (key: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const selectedToolIds = useMemo(
    () =>
      tools
        .filter((x) => x.tool_id != null && selected.has(`t:${x.tool_id}`))
        .map((x) => x.tool_id!) as number[],
    [selected, tools]
  );
  const selectedSkillIds = useMemo(
    () =>
      skills
        .filter((x) => x.skill_id != null && selected.has(`s:${x.skill_id}`))
        .map((x) => x.skill_id!) as number[],
    [selected, skills]
  );

  const handleApplyAll = async () => {
    if (selectedToolIds.length === 0 && selectedSkillIds.length === 0) {
      AntMessage.warning(
        t(
          "nl2agent.localResources.selectAtLeastOne",
          "Please select at least one resource."
        )
      );
      return;
    }
    const missingField = tools
      .filter(
        (tool) => tool.tool_id != null && selected.has(`t:${tool.tool_id}`)
      )
      .flatMap((tool) =>
        (toolParameterSchemas[String(tool.tool_id)] ?? []).flatMap((field) => {
          const value =
            toolConfigValues[tool.tool_id!]?.[field.name] ?? field.default;
          const required = field.required === true || field.optional === false;
          return required && (value == null || value === "")
            ? [`${tool.name}: ${field.name}`]
            : [];
        })
      )[0];
    if (missingField) {
      AntMessage.warning(
        t("nl2agent.localResources.missingConfiguration", {
          defaultValue: "Please configure {{field}}.",
          field: missingField,
        })
      );
      return;
    }
    try {
      await execute(
        {
          action: "apply_local_resources",
          display_text: t("nl2agent.action.applyLocalResources", {
            defaultValue:
              "Local resources applied: {{toolCount}} tool(s), {{skillCount}} skill(s)",
            toolCount: selectedToolIds.length,
            skillCount: selectedSkillIds.length,
          }),
          payload: {
            recommendation_batch_id: recommendationBatchId,
            tool_ids: selectedToolIds,
            skill_ids: selectedSkillIds,
            tool_config_values: Object.fromEntries(
              selectedToolIds.flatMap((toolId) =>
                toolConfigValues[toolId]
                  ? [[String(toolId), toolConfigValues[toolId]]]
                  : []
              )
            ),
          },
        },
        {
          onSuccess: () => {
            AntMessage.success(
              t("nl2agent.localResources.applied", {
                defaultValue:
                  "Applied {{toolCount}} tool(s) and {{skillCount}} skill(s).",
                toolCount: selectedToolIds.length,
                skillCount: selectedSkillIds.length,
              })
            );
            setSelected(
              new Set([
                ...selectedToolIds.map((toolId) => `t:${toolId}`),
                ...selectedSkillIds.map((skillId) => `s:${skillId}`),
              ])
            );
            setApplied(true);
          },
        }
      );
    } catch (error) {
      AntMessage.error(
        error instanceof Error ? error.message : "Failed to apply resources."
      );
    }
  };

  const handleSkip = async () => {
    try {
      await execute(
        {
          action: "skip_local_resources",
          display_text: t(
            "nl2agent.action.skipLocalResources",
            "Local resources skipped"
          ),
          payload: { recommendation_batch_id: recommendationBatchId },
        },
        {
          onSuccess: () => {
            setSkipped(true);
            AntMessage.success(
              t(
                "nl2agent.localResources.skipped",
                "Continuing without these local resources."
              )
            );
          },
        }
      );
    } catch (error) {
      AntMessage.error(
        error instanceof Error ? error.message : "Failed to skip resources."
      );
    }
  };

  const renderRow = (item: LocalResourceItem) => {
    const key =
      item.kind === "tool" ? `t:${item.tool_id}` : `s:${item.skill_id}`;
    const toolId = item.tool_id;
    const configurableFields =
      item.kind === "tool" && toolId != null
        ? (toolParameterSchemas[String(toolId)] ?? [])
        : [];
    return (
      <React.Fragment key={key}>
        <label className="flex items-start gap-2 py-1.5 px-2 rounded hover:bg-gray-50 cursor-pointer">
          <Checkbox
            checked={selected.has(key)}
            onChange={() => toggle(key)}
            disabled={applied || applying}
            className="mt-1"
          />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-sm">{item.name}</span>
              {item.source && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">
                  {item.source}
                </span>
              )}
              {typeof item.score === "number" && (
                <span className="text-[10px] text-gray-500">
                  score: {item.score}
                </span>
              )}
            </div>
            {item.description && (
              <div className="text-xs text-gray-600 mt-0.5 line-clamp-2">
                {item.description}
              </div>
            )}
            {item.reason && (
              <div className="text-xs text-gray-400 mt-0.5 italic">
                {item.reason}
              </div>
            )}
          </div>
        </label>
        {toolId != null &&
          selected.has(key) &&
          configurableFields.length > 0 && (
            <div className="mx-2 mb-2 space-y-2 rounded border border-gray-100 bg-gray-50 p-2">
              {configurableFields.map((field) => {
                const value =
                  toolConfigValues[toolId]?.[field.name] ?? field.default;
                const setValue = (nextValue: unknown) =>
                  setToolConfigValues((previous) => ({
                    ...previous,
                    [toolId]: {
                      ...previous[toolId],
                      [field.name]: nextValue,
                    },
                  }));
                const label = `${field.name}${
                  field.required === true || field.optional === false
                    ? " *"
                    : ""
                }`;
                const secret =
                  field.isSecret === true ||
                  field.is_secret === true ||
                  /password|authorization|api[_-]?key|secret|token/i.test(
                    field.name
                  );
                return (
                  <div key={field.name}>
                    <div className="mb-1 text-xs text-gray-600">{label}</div>
                    {Array.isArray(field.choices) &&
                    field.choices.length > 0 ? (
                      <Select
                        aria-label={label}
                        size="small"
                        className="w-full"
                        value={value}
                        options={field.choices.map((choice) => ({
                          value: choice as string | number,
                          label: String(choice),
                        }))}
                        onChange={setValue}
                        disabled={applied || applying}
                      />
                    ) : field.type === "boolean" ? (
                      <Switch
                        aria-label={label}
                        size="small"
                        checked={Boolean(value)}
                        onChange={setValue}
                        disabled={applied || applying}
                      />
                    ) : field.type === "integer" || field.type === "number" ? (
                      <InputNumber
                        aria-label={label}
                        size="small"
                        className="w-full"
                        value={typeof value === "number" ? value : undefined}
                        precision={field.type === "integer" ? 0 : undefined}
                        onChange={setValue}
                        disabled={applied || applying}
                      />
                    ) : field.type === "array" || field.type === "object" ? (
                      <Input.TextArea
                        aria-label={label}
                        size="small"
                        value={
                          typeof value === "string"
                            ? value
                            : value == null
                              ? ""
                              : JSON.stringify(value)
                        }
                        placeholder={field.description ?? undefined}
                        onChange={(event) => {
                          const raw = event.target.value;
                          try {
                            setValue(JSON.parse(raw));
                          } catch {
                            setValue(raw);
                          }
                        }}
                        disabled={applied || applying}
                      />
                    ) : (
                      <Input
                        aria-label={label}
                        size="small"
                        type={secret ? "password" : "text"}
                        value={typeof value === "string" ? value : ""}
                        placeholder={field.description ?? undefined}
                        onChange={(event) => setValue(event.target.value)}
                        disabled={applied}
                      />
                    )}
                  </div>
                );
              })}
            </div>
          )}
      </React.Fragment>
    );
  };

  return (
    <div className="my-3 border border-gray-200 rounded-lg overflow-hidden">
      <div className="px-3 py-2 bg-gray-50 border-b border-gray-200 flex items-center justify-between">
        <span className="font-medium text-sm">
          {t("nl2agent.localResources.title", "Recommended Local Resources")}
        </span>
        <span className="text-xs text-gray-500">
          {tools.length + skills.length} {t("nl2agent.items", "items")}
        </span>
      </div>
      <div className="max-h-80 overflow-y-auto p-1">
        {tools.length > 0 && (
          <div className="mb-2">
            <div className="text-[11px] uppercase tracking-wide text-gray-400 px-2 py-1">
              {t("nl2agent.localResources.tools", "Tools")}
            </div>
            {tools.map(renderRow)}
          </div>
        )}
        {skills.length > 0 && (
          <div>
            <div className="text-[11px] uppercase tracking-wide text-gray-400 px-2 py-1">
              {t("nl2agent.localResources.skills", "Skills")}
            </div>
            {skills.map(renderRow)}
          </div>
        )}
        {tools.length === 0 && skills.length === 0 && (
          <div className="text-sm text-gray-400 p-3">
            {t("nl2agent.localResources.empty", "No local resources found.")}
          </div>
        )}
      </div>
      {workflow.active && workflow.sessionStateError && (
        <Alert
          className="m-3"
          type="error"
          title="Failed to restore saved resource selection."
          action={
            <Button onClick={() => void workflow.refreshSessionState()}>
              Retry
            </Button>
          }
        />
      )}
      <div className="px-3 py-2 border-t border-gray-200 bg-white flex gap-2">
        <Button
          type="primary"
          size="small"
          onClick={handleApplyAll}
          loading={pending}
          disabled={
            !recommendationBatchId ||
            pending ||
            applying ||
            workflow.sessionStateLoading ||
            Boolean(workflow.sessionStateError) ||
            applied ||
            skipped ||
            (selectedToolIds.length === 0 && selectedSkillIds.length === 0)
          }
        >
          {applied ? (
            <>
              <CheckCircle2 className="h-3.5 w-3.5 mr-1" />
              {t("nl2agent.localResources.appliedShort", "Applied")}
            </>
          ) : pending || applying ? (
            <>
              <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
              {t("nl2agent.localResources.applying", "Applying...")}
            </>
          ) : (
            t("nl2agent.localResources.applyAll", "Apply All")
          )}
        </Button>
        <Button
          size="small"
          onClick={handleSkip}
          loading={pending}
          disabled={
            !recommendationBatchId ||
            pending ||
            applying ||
            workflow.sessionStateLoading ||
            Boolean(workflow.sessionStateError) ||
            applied ||
            skipped
          }
        >
          {skipped
            ? t("nl2agent.localResources.skippedShort", "Skipped")
            : t(
                "nl2agent.localResources.continueWithout",
                "Continue Without Resources"
              )}
        </Button>
      </div>
    </div>
  );
};
