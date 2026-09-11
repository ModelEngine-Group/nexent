"use client";

import { useEffect, useId, useRef, useState, type FC } from "react";
import { useAui } from "@assistant-ui/react";
import {
  AlertTriangle,
  CheckCircle2,
  PencilLine,
  PlusCircle,
  RotateCcw,
  Trash2,
  Wrench,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import {
  abandonResourceGapRequirement,
  buildResourceGapResolutionResult,
  canSubmitResourceGapResolution,
  cancelResourceGapRequirementEdit,
  createResourceGapRequirementStates,
  getResourceGapRequirementActions,
  markResourceGapSkillCreated,
  markResourceGapToolConfigured,
  restoreResourceGapRequirement,
  saveResourceGapRequirementEdit,
  startResourceGapRequirementEdit,
} from "@/lib/nl2agent-resource-gap";
import type {
  Nl2AgentResourceGapResolutionAction,
  Nl2aResourceGapResolutionPayload,
} from "../adapter/remote-chat-model-adapter";

export const ResourceGapResolutionCard: FC<{
  payload: Nl2aResourceGapResolutionPayload;
  disabled?: boolean;
}> = ({ payload, disabled = false }) => {
  const { t } = useTranslation("common");
  const aui = useAui();
  const reactId = useId();
  const cardKey = `resource_gap_resolution:${payload.agent_id}:${reactId}`;
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [states, setStates] = useState(() =>
    createResourceGapRequirementStates(payload.requirements)
  );
  const [editingValues, setEditingValues] = useState<Record<string, string>>(
    {}
  );
  const completedRequestIds = useRef<Set<number>>(new Set());
  const completedMcpRequestIds = useRef<Set<number>>(new Set());
  const {
    registerCard,
    submitCard,
    isCardInteractive,
    requestSkillCreation,
    skillCreationRequest,
    requestMcpConfiguration,
    mcpConfigurationRequest,
    requestConfigFocus,
  } = useNl2AgentFlow();

  useEffect(() => {
    registerCard(cardKey, payload.subtype);
  }, [cardKey, payload.subtype, registerCard]);

  const isLocked = disabled || isSubmitted || !isCardInteractive(cardKey);

  const submit = () => {
    if (isLocked || !canSubmitResourceGapResolution(states)) return;
    setIsSubmitted(true);
    submitCard(cardKey);
    const action: Nl2AgentResourceGapResolutionAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action: "resolve_requirements",
      result: buildResourceGapResolutionResult(payload.requirements, states),
    };
    aui.thread().append({
      role: "user",
      content: [
        {
          type: "text",
          text: t(
            "nl2agent.resourceGap.resolve_requirements",
            "Confirm requirement changes"
          ),
        },
      ],
      metadata: { custom: { nl2agentCardAction: action } },
      startRun: true,
    });
  };

  useEffect(() => {
    if (
      !skillCreationRequest?.completed ||
      skillCreationRequest.agentId !== payload.agent_id ||
      skillCreationRequest.cardKey !== cardKey ||
      completedRequestIds.current.has(skillCreationRequest.requestId)
    ) {
      return;
    }
    completedRequestIds.current.add(skillCreationRequest.requestId);
    setStates((current) =>
      markResourceGapSkillCreated(current, skillCreationRequest.requirementId)
    );
  }, [cardKey, payload.agent_id, skillCreationRequest]);

  useEffect(() => {
    if (
      !mcpConfigurationRequest?.completed ||
      mcpConfigurationRequest.agentId !== payload.agent_id ||
      mcpConfigurationRequest.cardKey !== cardKey ||
      completedMcpRequestIds.current.has(mcpConfigurationRequest.requestId)
    ) {
      return;
    }
    completedMcpRequestIds.current.add(mcpConfigurationRequest.requestId);
    setStates((current) =>
      markResourceGapToolConfigured(
        current,
        mcpConfigurationRequest.requirementId
      )
    );
  }, [cardKey, mcpConfigurationRequest, payload.agent_id]);

  const isSkillCreationPending =
    skillCreationRequest?.agentId === payload.agent_id &&
    skillCreationRequest.cardKey === cardKey &&
    !skillCreationRequest.completed;
  const isMcpConfigurationPending =
    mcpConfigurationRequest?.agentId === payload.agent_id &&
    mcpConfigurationRequest.cardKey === cardKey &&
    !mcpConfigurationRequest.completed;

  return (
    <section className="my-4 overflow-hidden rounded-lg border border-amber-200 bg-amber-50/30 shadow-sm">
      <div className="flex items-center gap-3 border-b border-amber-200 bg-amber-50 px-4 py-3">
        <AlertTriangle className="size-5 text-amber-700" />
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            {t("nl2agent.resourceGap.title", "Resources needed")}
          </h3>
          <p className="text-xs text-muted-foreground">
            {t(
              "nl2agent.resourceGap.description",
              "No available resource covers this need."
            )}
          </p>
        </div>
      </div>
      <div className="space-y-3 p-4">
        <ul className="space-y-2 text-sm">
          {payload.requirements.map((requirement) =>
            (() => {
              const state = states[requirement.requirement_id];
              const isAbandoned = state.status === "abandoned";
              const isEditing = state.status === "editing";
              const isSkillCreated = state.status === "skill_created";
              const isToolConfigured = state.status === "tool_configured";
              const availableActions = getResourceGapRequirementActions(
                state.status
              );
              return (
                <li
                  key={requirement.requirement_id}
                  className={`rounded-md border p-3 ${
                    isAbandoned
                      ? "border-muted bg-muted/50 text-muted-foreground"
                      : "border-border"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      {isEditing ? (
                        <div className="flex flex-wrap items-center gap-2">
                          <Input
                            aria-label={t(
                              "nl2agent.resourceGap.editInputLabel",
                              "Requirement"
                            )}
                            autoFocus
                            className="min-w-56 flex-1"
                            value={
                              editingValues[requirement.requirement_id] ??
                              state.query
                            }
                            onChange={(event) =>
                              setEditingValues((current) => ({
                                ...current,
                                [requirement.requirement_id]:
                                  event.target.value,
                              }))
                            }
                          />
                          <Button
                            type="button"
                            size="sm"
                            disabled={
                              !editingValues[requirement.requirement_id]?.trim()
                            }
                            onClick={() => {
                              setStates((current) =>
                                saveResourceGapRequirementEdit(
                                  current,
                                  requirement.requirement_id,
                                  editingValues[requirement.requirement_id] ??
                                    state.query
                                )
                              );
                              setEditingValues((current) => {
                                const next = { ...current };
                                delete next[requirement.requirement_id];
                                return next;
                              });
                            }}
                          >
                            {t("nl2agent.resourceGap.save", "Save")}
                          </Button>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setStates((current) =>
                                cancelResourceGapRequirementEdit(
                                  current,
                                  requirement.requirement_id
                                )
                              );
                              setEditingValues((current) => {
                                const next = { ...current };
                                delete next[requirement.requirement_id];
                                return next;
                              });
                            }}
                          >
                            {t("nl2agent.resourceGap.cancel", "Cancel")}
                          </Button>
                        </div>
                      ) : (
                        <p className={isAbandoned ? "line-through" : undefined}>
                          {state.query}
                        </p>
                      )}
                      {state.status === "revised" && (
                        <p className="mt-1 text-xs text-blue-600">
                          {t("nl2agent.resourceGap.revised", "Modified")}
                        </p>
                      )}
                      {isAbandoned && (
                        <p className="mt-1 text-xs">
                          {t(
                            "nl2agent.resourceGap.removed",
                            "Removed from requirements"
                          )}
                        </p>
                      )}
                      {isSkillCreated && (
                        <p className="mt-1 flex items-center gap-1 text-xs text-emerald-700">
                          <CheckCircle2 className="size-3.5" />
                          {t(
                            "nl2agent.resourceGap.skillCreated",
                            "Skill created"
                          )}
                        </p>
                      )}
                      {isToolConfigured && (
                        <p className="mt-1 flex items-center gap-1 text-xs text-emerald-700">
                          <CheckCircle2 className="size-3.5" />
                          {t(
                            "nl2agent.resourceGap.toolConfigured",
                            "Tool configured"
                          )}
                        </p>
                      )}
                    </div>
                    {!isEditing && (
                      <div className="flex shrink-0 gap-1">
                        {availableActions.requirement.includes("restore") ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={isLocked}
                            onClick={() =>
                              setStates((current) =>
                                restoreResourceGapRequirement(
                                  current,
                                  requirement.requirement_id
                                )
                              )
                            }
                          >
                            <RotateCcw className="mr-1 size-4" />
                            {t("nl2agent.resourceGap.restore", "Undo")}
                          </Button>
                        ) : availableActions.requirement.length > 0 ? (
                          <>
                            <Button
                              type="button"
                              size="icon"
                              variant="outline"
                              className="size-8"
                              disabled={isLocked}
                              title={t(
                                "nl2agent.resourceGap.revise",
                                "Revise requirement"
                              )}
                              onClick={() => {
                                setStates((current) =>
                                  startResourceGapRequirementEdit(
                                    current,
                                    requirement.requirement_id
                                  )
                                );
                                setEditingValues((current) => ({
                                  ...current,
                                  [requirement.requirement_id]: state.query,
                                }));
                              }}
                            >
                              <PencilLine className="size-4" />
                              <span className="sr-only">
                                {t(
                                  "nl2agent.resourceGap.revise",
                                  "Revise requirement"
                                )}
                              </span>
                            </Button>
                            <Button
                              type="button"
                              size="icon"
                              variant="ghost"
                              className="size-8"
                              disabled={isLocked}
                              title={t(
                                "nl2agent.resourceGap.delete",
                                "Delete requirement"
                              )}
                              onClick={() =>
                                setStates((current) =>
                                  abandonResourceGapRequirement(
                                    current,
                                    requirement.requirement_id
                                  )
                                )
                              }
                            >
                              <Trash2 className="size-4" />
                              <span className="sr-only">
                                {t(
                                  "nl2agent.resourceGap.delete",
                                  "Delete requirement"
                                )}
                              </span>
                            </Button>
                          </>
                        ) : null}
                      </div>
                    )}
                  </div>
                  {availableActions.solutions.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-2 border-t pt-3">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={
                          isLocked ||
                          isSkillCreationPending ||
                          isMcpConfigurationPending
                        }
                        onClick={() => {
                          requestConfigFocus(payload.agent_id, {
                            section: "tools_skills",
                            capabilityTab: "skills",
                          });
                          requestSkillCreation(
                            payload.agent_id,
                            cardKey,
                            requirement.requirement_id
                          );
                        }}
                      >
                        <PlusCircle className="mr-1 size-4" />
                        {t("nl2agent.resourceGap.createSkill", "Create Skill")}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={
                          isLocked ||
                          isSkillCreationPending ||
                          isMcpConfigurationPending
                        }
                        onClick={() => {
                          requestConfigFocus(payload.agent_id, {
                            section: "tools_skills",
                            capabilityTab: "tools",
                          });
                          requestMcpConfiguration(
                            payload.agent_id,
                            cardKey,
                            requirement.requirement_id
                          );
                        }}
                      >
                        <Wrench className="mr-1 size-4" />
                        {t(
                          "nl2agent.resourceGap.configureTool",
                          "Configure tool"
                        )}
                      </Button>
                    </div>
                  )}
                </li>
              );
            })()
          )}
        </ul>
        <div className="flex justify-end border-t pt-3">
          <Button
            type="button"
            disabled={isLocked || !canSubmitResourceGapResolution(states)}
            onClick={submit}
          >
            <CheckCircle2 className="mr-1 size-4" />
            {t("nl2agent.resourceGap.confirm", "Confirm and continue")}
          </Button>
        </div>
      </div>
    </section>
  );
};
