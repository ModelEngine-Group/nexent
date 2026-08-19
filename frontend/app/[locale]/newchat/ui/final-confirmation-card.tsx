"use client";

import { useEffect, useId, useMemo, useState, type FC } from "react";
import { useAui } from "@assistant-ui/react";
import { useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, Pencil, RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import { searchAgentInfo } from "@/services/agentConfigService";
import { useAgentStore } from "@/stores/agentStore";
import type {
  Nl2AgentCardAction,
  Nl2aFinalConfirmationPayload,
  Nl2aPromptField,
} from "../adapter/remote-chat-model-adapter";

const PROMPT_FIELDS: Nl2aPromptField[] = [
  "duty_prompt",
  "constraint_prompt",
  "few_shots_prompt",
  "greeting_message",
  "example_questions",
];

const MODIFICATION_TARGETS = [
  "basic_info",
  "requirements",
  "bound_resources",
  ...PROMPT_FIELDS,
] as const;

export const FinalConfirmationCard: FC<{
  payload: Nl2aFinalConfirmationPayload;
  disabled?: boolean;
}> = ({ payload, disabled = false }) => {
  const { t } = useTranslation("common");
  const aui = useAui();
  const queryClient = useQueryClient();
  const reactId = useId();
  const cardKey = `final_confirmation:${payload.agent_id}:${reactId}`;
  const { registerCard, submitCard, markFinalConfirmed, isCardInteractive } =
    useNl2AgentFlow();
  const replaceServerSnapshot = useAgentStore(
    (state) => state.replaceServerSnapshot
  );
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [isModifying, setIsModifying] = useState(false);
  const [selectedTargets, setSelectedTargets] = useState<Set<string>>(
    new Set()
  );
  const [feedback, setFeedback] = useState("");
  const [isSynchronizing, setIsSynchronizing] = useState(true);
  const [syncFailed, setSyncFailed] = useState(false);
  const [syncAttempt, setSyncAttempt] = useState(0);

  useEffect(() => {
    registerCard(cardKey, payload.subtype);
  }, [cardKey, payload.subtype, registerCard]);

  useEffect(() => {
    let active = true;
    const synchronize = async () => {
      setIsSynchronizing(true);
      setSyncFailed(false);
      try {
        const result = await searchAgentInfo(payload.agent_id, undefined, 0);
        if (!result.success || !result.data) throw new Error(result.message);
        if (!replaceServerSnapshot(payload.agent_id, result.data)) {
          throw new Error("Agent context changed");
        }
        await Promise.all([
          queryClient.invalidateQueries({ queryKey: ["agents"] }),
          queryClient.invalidateQueries({
            queryKey: ["agentInfo", payload.agent_id],
          }),
        ]);
      } catch {
        if (active) setSyncFailed(true);
      } finally {
        if (active) setIsSynchronizing(false);
      }
    };
    void synchronize();
    return () => {
      active = false;
    };
  }, [payload.agent_id, queryClient, replaceServerSnapshot, syncAttempt]);

  const isLocked = disabled || isSubmitted || !isCardInteractive(cardKey);
  const canSubmitModification =
    selectedTargets.size > 0 && feedback.trim().length > 0;
  const promptEntries = useMemo(
    () =>
      PROMPT_FIELDS.map((field) => {
        const value = payload.prompts[field];
        return {
          field,
          content: Array.isArray(value) ? value.join("\n") : value,
        };
      }),
    [payload.prompts]
  );

  const toggleTarget = (target: string) => {
    if (isLocked) return;
    setSelectedTargets((current) => {
      const next = new Set(current);
      if (next.has(target)) next.delete(target);
      else next.add(target);
      return next;
    });
  };

  const confirm = () => {
    if (isLocked || isSynchronizing || syncFailed) return;
    setIsSubmitted(true);
    submitCard(cardKey);
    markFinalConfirmed(payload.agent_id);
  };

  const submitModification = () => {
    if (isLocked || !canSubmitModification) return;
    setIsSubmitted(true);
    submitCard(cardKey);
    const action: Nl2AgentCardAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action: "modify",
      result: {
        target_fields: Array.from(selectedTargets),
        feedback: feedback.trim(),
      },
    };
    aui.thread().append({
      role: "user",
      content: [
        {
          type: "text",
          text: t(
            "nl2agent.finalConfirmation.modificationSummary",
            "Requested changes to the Agent"
          ),
        },
      ],
      metadata: { custom: { nl2agentCardAction: action } },
      startRun: true,
    });
  };

  return (
    <section
      data-slot="aui-final-confirmation"
      className="my-4 overflow-hidden rounded-lg border bg-card shadow-sm"
    >
      <div className="flex items-center gap-3 border-b bg-muted/30 px-4 py-3">
        <div className="flex size-9 shrink-0 items-center justify-center rounded-md bg-emerald-50">
          <CheckCircle2 className="size-4 text-emerald-600" />
        </div>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold text-foreground">
            {t("nl2agent.finalConfirmation.title", "Final confirmation")}
          </h3>
          <p className="text-xs text-muted-foreground">
            {t(
              "nl2agent.finalConfirmation.description",
              "Review the saved Agent configuration."
            )}
          </p>
        </div>
      </div>

      <div className="space-y-5 p-4 text-sm">
        <section>
          <h4 className="mb-2 font-medium">
            {t(
              "nl2agent.finalConfirmation.basicInfo",
              "Description information"
            )}
          </h4>
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs text-muted-foreground">
                {t("nl2agent.finalConfirmation.name", "Name")}
              </dt>
              <dd className="break-words">{payload.agent.display_name}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">
                {t("nl2agent.finalConfirmation.identifier", "Identifier")}
              </dt>
              <dd className="break-words font-mono text-xs">
                {payload.agent.name}
              </dd>
            </div>
          </dl>
          <p className="mt-2 whitespace-pre-wrap text-muted-foreground">
            {payload.agent.description}
          </p>
          <p className="mt-2 whitespace-pre-wrap text-xs text-muted-foreground">
            <span className="font-medium text-foreground">
              {t("nl2agent.finalConfirmation.businessDescription", "Workflow")}
              :{" "}
            </span>
            {payload.agent.business_description}
          </p>
        </section>

        <section>
          <h4 className="mb-2 font-medium">
            {t("nl2agent.finalConfirmation.requirements", "Requirements")}
          </h4>
          <ul className="space-y-1 text-muted-foreground">
            {payload.requirements.map((requirement) => (
              <li key={requirement.requirement_id} className="break-words">
                {requirement.query}
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h4 className="mb-2 font-medium">
            {t("nl2agent.finalConfirmation.resources", "Bound resources")}
          </h4>
          {payload.resources.length ? (
            <ul className="space-y-2">
              {payload.resources.map((resource) => (
                <li
                  key={`${resource.resource_type}:${resource.resource_id}`}
                  className="flex min-w-0 items-start gap-2"
                >
                  <Check className="mt-0.5 size-4 shrink-0 text-emerald-600" />
                  <span className="min-w-0 break-words">
                    <span className="font-medium">{resource.name}</span>
                    {resource.description ? (
                      <span className="block text-xs text-muted-foreground">
                        {resource.description}
                      </span>
                    ) : null}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-muted-foreground">
              {t(
                "nl2agent.finalConfirmation.noResources",
                "No bound resources"
              )}
            </p>
          )}
        </section>

        <section>
          <h4 className="mb-2 font-medium">
            {t("nl2agent.finalConfirmation.prompts", "Prompt fields")}
          </h4>
          <div className="divide-y border-y">
            {promptEntries.map(({ field, content }) => (
              <details key={field} className="py-2">
                <summary className="cursor-pointer text-xs font-medium">
                  {t(`nl2agent.finalConfirmation.field.${field}`, field)}
                </summary>
                <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words font-sans text-xs text-muted-foreground">
                  {content || t("nl2agent.finalConfirmation.empty", "Empty")}
                </pre>
              </details>
            ))}
          </div>
        </section>

        {payload.abandoned_requirements.length ? (
          <section>
            <h4 className="mb-2 font-medium text-amber-700">
              {t(
                "nl2agent.finalConfirmation.abandoned",
                "Abandoned requirements"
              )}
            </h4>
            <ul className="space-y-1 text-muted-foreground">
              {payload.abandoned_requirements.map((requirement) => (
                <li key={requirement.requirement_id}>{requirement.query}</li>
              ))}
            </ul>
          </section>
        ) : null}

        {isModifying && !isSubmitted ? (
          <section className="space-y-3 border-t pt-4">
            <fieldset disabled={isLocked}>
              <legend className="mb-2 text-sm font-medium">
                {t(
                  "nl2agent.finalConfirmation.modifyScope",
                  "Modification scope"
                )}
              </legend>
              <div className="grid gap-2 sm:grid-cols-2">
                {MODIFICATION_TARGETS.map((target) => (
                  <label
                    key={target}
                    className="flex items-center gap-2 text-xs"
                  >
                    <input
                      type="checkbox"
                      checked={selectedTargets.has(target)}
                      onChange={() => toggleTarget(target)}
                      className="size-4 accent-primary"
                    />
                    {t(`nl2agent.finalConfirmation.target.${target}`, target)}
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="block text-sm font-medium">
              {t(
                "nl2agent.finalConfirmation.feedback",
                "Modification instructions"
              )}
              <textarea
                value={feedback}
                onChange={(event) => setFeedback(event.target.value)}
                rows={3}
                disabled={isLocked}
                className="mt-2 w-full resize-y rounded-md border bg-background px-3 py-2 text-sm outline-none focus:border-primary disabled:cursor-not-allowed"
              />
            </label>
          </section>
        ) : null}

        {syncFailed ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs text-destructive" role="alert">
              {t(
                "nl2agent.finalConfirmation.syncFailed",
                "The Agent was saved, but the editor could not be refreshed."
              )}
            </p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => setSyncAttempt((attempt) => attempt + 1)}
            >
              <RefreshCw />
              {t("common.retry", "Retry")}
            </Button>
          </div>
        ) : null}
      </div>

      <div className="flex flex-wrap justify-end gap-2 border-t bg-muted/20 px-4 py-3">
        {isModifying && !isSubmitted ? (
          <>
            <Button
              type="button"
              variant="outline"
              disabled={isLocked}
              onClick={() => setIsModifying(false)}
            >
              {t("common.cancel", "Cancel")}
            </Button>
            <Button
              type="button"
              disabled={isLocked || !canSubmitModification}
              onClick={submitModification}
            >
              <Pencil />
              {t(
                "nl2agent.finalConfirmation.submitModification",
                "Submit changes"
              )}
            </Button>
          </>
        ) : (
          <>
            <Button
              type="button"
              variant="outline"
              disabled={isLocked || isSynchronizing || syncFailed}
              onClick={() => setIsModifying(true)}
            >
              <Pencil />
              {t("nl2agent.finalConfirmation.modify", "Needs changes")}
            </Button>
            <Button
              type="button"
              disabled={isLocked || isSynchronizing || syncFailed}
              onClick={confirm}
            >
              {isSynchronizing ? (
                <RefreshCw className="animate-spin" />
              ) : (
                <Check />
              )}
              {isSubmitted
                ? t("nl2agent.finalConfirmation.confirmed", "Confirmed")
                : t("nl2agent.finalConfirmation.confirm", "Confirm")}
            </Button>
          </>
        )}
      </div>
    </section>
  );
};
