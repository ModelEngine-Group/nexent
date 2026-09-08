"use client";

import { useEffect, useId, useRef, useState, type FC } from "react";
import { useAui } from "@assistant-ui/react";
import { AlertTriangle, PencilLine, PlusCircle, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import type {
  Nl2AgentCardAction,
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
  const [selectedRequirementId, setSelectedRequirementId] = useState<string | null>(null);
  const resumedRequestId = useRef<number | null>(null);
  const {
    registerCard,
    submitCard,
    isCardInteractive,
    requestSkillCreation,
    skillCreationRequest,
  } = useNl2AgentFlow();

  useEffect(() => {
    registerCard(cardKey, payload.subtype);
  }, [cardKey, payload.subtype, registerCard]);

  const isLocked = disabled || isSubmitted || !isCardInteractive(cardKey);

  const submit = (
    actionName: "skill_created" | "revise_requirements" | "abandon",
    requirementId = selectedRequirementId
  ) => {
    if (isLocked) return;
    setIsSubmitted(true);
    submitCard(cardKey);
    const action: Nl2AgentCardAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action: actionName,
      result: { requirement_id: requirementId },
    };
    aui.thread().append({
      role: "user",
      content: [
        { type: "text", text: t(`nl2agent.resourceGap.${actionName}`) },
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
      resumedRequestId.current === skillCreationRequest.requestId
    ) {
      return;
    }
    resumedRequestId.current = skillCreationRequest.requestId;
    submit("skill_created", skillCreationRequest.requirementId);
  }, [cardKey, payload.agent_id, skillCreationRequest]);

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
        <ul className="space-y-2 text-sm text-muted-foreground">
          {payload.requirements.map((requirement) => (
            <li key={requirement.requirement_id} className="flex items-center justify-between gap-3">
              <span>{requirement.query}</span>
              <div className="flex gap-1">
                <Button type="button" size="sm" disabled={isLocked} onClick={() => requestSkillCreation(payload.agent_id, cardKey, requirement.requirement_id)}><PlusCircle className="mr-1 size-4" />{t("nl2agent.resourceGap.createSkill", "Create Skill")}</Button>
                <Button type="button" size="sm" variant="outline" disabled={isLocked} onClick={() => submit("revise_requirements", requirement.requirement_id)}><PencilLine className="size-4" /></Button>
                <Button type="button" size="sm" variant="ghost" disabled={isLocked} onClick={() => submit("abandon", requirement.requirement_id)}><XCircle className="size-4" /></Button>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
};
