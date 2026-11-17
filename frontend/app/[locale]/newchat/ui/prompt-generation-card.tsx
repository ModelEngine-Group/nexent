// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef, useState } from "react";
import { useAui, useAuiState } from "@assistant-ui/react";
import { Button, Input } from "antd";
import { FileText } from "lucide-react";
import { useTranslation } from "react-i18next";

import { useNl2AgentFlow } from "@/contexts/nl2AgentFlow";
import type {
  Nl2AgentCardAction,
  Nl2aPromptGenerationPayload,
} from "../adapter/remote-chat-model-adapter";
import { nl2AgentCardRunConfig } from "./nl2agent-card-run-config";

export function PromptGenerationCard({
  payload,
  disabled = false,
}: {
  payload: Nl2aPromptGenerationPayload;
  disabled?: boolean;
}) {
  const { t } = useTranslation("common");
  const aui = useAui();
  const running = useAuiState((state) => state.thread.isRunning);
  const { registerCard, submitCard, isCardInteractive } = useNl2AgentFlow();
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draftPrompt, setDraftPrompt] = useState(payload.proposed_prompt);
  const [localOutcome, setOutcome] = useState<typeof payload.status | null>(
    null
  );
  const outcome =
    payload.status === "pending"
      ? (localOutcome ?? payload.status)
      : payload.status;
  const [failed, setFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const inFlight = useRef(false);
  useEffect(() => {
    if (!disabled && outcome === "pending")
      registerCard(payload.card_id, payload.subtype, true);
  }, [disabled, outcome, payload.card_id, payload.subtype, registerCard]);
  const locked =
    disabled ||
    running ||
    submitting ||
    outcome !== "pending" ||
    !isCardInteractive(payload.card_id);

  const submit = (action: "apply" | "cancel") => {
    if (
      locked ||
      inFlight.current ||
      (action === "apply" && !draftPrompt.trim())
    )
      return;
    inFlight.current = true;
    setSubmitting(true);
    setFailed(false);
    const cardAction: Nl2AgentCardAction = {
      type: "nl2agent_card_action",
      subtype: payload.subtype,
      agent_id: payload.agent_id,
      action,
      result: {
        card_id: payload.card_id,
        prompt_revision: payload.prompt_revision,
        ...(action === "apply" ? { prompt: draftPrompt } : {}),
      },
    };
    try {
      aui.thread().append({
        role: "user",
        content: [
          { type: "text", text: t(`nl2agent.promptGeneration.${action}`) },
        ],
        metadata: { custom: { nl2agentCardAction: cardAction } },
        runConfig: nl2AgentCardRunConfig(
          aui.thread().composer().getState().runConfig,
          payload.agent_id,
          {
            onAccepted: () => {
              setOutcome(action === "apply" ? "applied" : "cancelled");
              setEditing(false);
              submitCard(payload.card_id);
              setSubmitting(false);
              inFlight.current = false;
            },
            onRejected: () => {
              registerCard(payload.card_id, payload.subtype, true);
              setFailed(true);
              setSubmitting(false);
              inFlight.current = false;
            },
          }
        ),
        startRun: true,
      });
    } catch {
      setFailed(true);
      setSubmitting(false);
      inFlight.current = false;
    }
  };

  return (
    <section
      data-testid="prompt-generation"
      className="my-4 min-w-0 overflow-hidden rounded-2xl border border-border bg-card text-foreground shadow-sm"
    >
      <header className="flex items-start gap-3 border-b bg-muted/25 px-4 py-3.5">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-primary">
          <FileText className="size-4" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">
            {t("nl2agent.promptGeneration.title")}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            {t("nl2agent.promptGeneration.description")}
          </p>
        </div>
      </header>
      <div className="min-w-0 px-4 py-3 text-xs">
        {editing && outcome === "pending" ? (
          <Input.TextArea
            aria-label={t("nl2agent.promptGeneration.editor")}
            value={draftPrompt}
            onChange={(event) => setDraftPrompt(event.target.value)}
            disabled={locked}
            autoSize={{ minRows: 8, maxRows: 24 }}
            className="!text-xs"
          />
        ) : (
          <pre
            className={`whitespace-pre-wrap break-words [overflow-wrap:anywhere] font-sans text-xs ${expanded ? "" : "max-h-48 overflow-hidden"}`}
          >
            {payload.status === "pending" && outcome !== "cancelled"
              ? draftPrompt
              : payload.proposed_prompt}
          </pre>
        )}
        <div className="flex flex-wrap items-center gap-3">
          {!editing && (
            <Button
              type="link"
              size="small"
              className="!px-0 !text-xs"
              aria-expanded={expanded}
              onClick={() => setExpanded(!expanded)}
            >
              {t(
                `nl2agent.promptGeneration.${expanded ? "collapse" : "expand"}`
              )}
            </Button>
          )}
          {outcome === "pending" && !disabled && (
            <>
              <Button
                type="link"
                size="small"
                className="!px-0 !text-xs"
                disabled={locked}
                onClick={() => setEditing(!editing)}
              >
                {t(`nl2agent.promptGeneration.${editing ? "preview" : "edit"}`)}
              </Button>
              {draftPrompt !== payload.proposed_prompt && (
                <Button
                  type="link"
                  size="small"
                  className="!px-0 !text-xs"
                  disabled={locked}
                  onClick={() => setDraftPrompt(payload.proposed_prompt)}
                >
                  {t("nl2agent.promptGeneration.reset")}
                </Button>
              )}
            </>
          )}
        </div>
        {failed && (
          <p role="alert" className="mt-2 text-destructive">
            {t("nl2agent.promptGeneration.failed")}
          </p>
        )}
      </div>
      <footer className="flex items-center justify-between gap-3 border-t px-4 py-3">
        {outcome === "pending" ? (
          <>
            <Button
              size="small"
              className="!h-7 !text-xs"
              disabled={locked}
              onClick={() => submit("cancel")}
            >
              {t("nl2agent.promptGeneration.cancel")}
            </Button>
            <Button
              type="primary"
              size="small"
              className="!h-7 !text-xs"
              disabled={locked || !draftPrompt.trim()}
              loading={submitting}
              onClick={() => submit("apply")}
            >
              {t("nl2agent.promptGeneration.apply")}
            </Button>
          </>
        ) : (
          <span role="status" className="text-xs text-muted-foreground">
            {t(`nl2agent.promptGeneration.${outcome}`)}
          </span>
        )}
      </footer>
    </section>
  );
}
