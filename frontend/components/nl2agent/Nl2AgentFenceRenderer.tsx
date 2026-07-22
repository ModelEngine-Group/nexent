"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button } from "antd";
import { useAuiState } from "@assistant-ui/react";
import type { SyntaxHighlighterProps } from "@assistant-ui/react-markdown";

import { tryRenderNl2AgentCard } from "./index";
import {
  parseNl2AgentCard,
  validateNl2AgentCards,
  type Nl2AgentCardRegistrationReceipt,
  type ValidatedNl2AgentCard,
} from "./cardValidation";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";
import { reportNl2AgentCardDelivery } from "@/services/nl2agentService";

const deliveryKey = (messageId: number, card: ValidatedNl2AgentCard) =>
  `${messageId}:${card.cardType}:${card.cardKey ?? ""}`;

const reportRendered = async (
  messageId: number,
  card: ValidatedNl2AgentCard,
  workflow: ReturnType<typeof useNl2AgentWorkflow>
) => {
  const key = deliveryKey(messageId, card);
  if (!workflow.claimCardDelivery(key)) return;
  try {
    const result = await reportNl2AgentCardDelivery(card.agentId, {
      message_id: messageId,
      card_type: card.cardType,
      status: "rendered",
      card_key: card.cardKey,
    });
    workflow.completeCardDelivery(key);
    if (result.chat_injection_text) {
      await workflow.continueWithText(result.chat_injection_text);
    }
  } catch {
    workflow.failCardDelivery(key);
  }
};

export const Nl2AgentFenceRenderer = ({
  language,
  code,
}: SyntaxHighlighterProps) => {
  const workflow = useNl2AgentWorkflow();
  const messageIdValue = useAuiState((s) => s.message.id);
  const complete = useAuiState((s) => s.message.status?.type === "complete");
  const latest = useAuiState(
    (s) => s.thread.messages.at(-1)?.id === s.message.id
  );
  const messageId = Number(messageIdValue);
  const validation = useMemo(
    () => parseNl2AgentCard(language, code, workflow.agentId),
    [code, language, workflow.agentId]
  );
  const card = validation.cards[0];
  const interactive =
    complete && latest && workflow.editable && Number.isInteger(messageId);

  const onRegistered = useCallback(
    async (_receipt: Nl2AgentCardRegistrationReceipt) => {
      if (!card || !Number.isInteger(messageId)) return;
      await reportRendered(messageId, card, workflow);
    },
    [card, messageId, workflow]
  );

  useEffect(() => {
    if (!interactive || !card || card.requiresRegistration) return;
    void reportRendered(messageId, card, workflow);
  }, [card, interactive, messageId, workflow]);

  if (!complete) {
    return (
      <div className="my-2 rounded border border-dashed p-3 text-xs text-muted-foreground">
        Generating agent configuration card…
      </div>
    );
  }

  const rendered = tryRenderNl2AgentCard(
    language,
    code,
    workflow.agentId,
    onRegistered,
    interactive
  );
  if (!rendered) return null;
  return (
    <div
      className={interactive ? undefined : "pointer-events-none opacity-75"}
      aria-disabled={!interactive}
    >
      {rendered}
    </div>
  );
};

const languages = [
  "nl2agent-requirements-summary",
  "nl2agent-model-selection",
  "nl2agent-local-resources",
  "nl2agent-web-mcp",
  "nl2agent-web-mcps",
  "nl2agent-web-skill",
  "nl2agent-web-skills",
  "nl2agent-agent-identity",
  "nl2agent-finalize",
] as const;

type Nl2AgentFenceLanguage = (typeof languages)[number];

// @assistant-ui/react-markdown 0.14.x extracts fenced languages with `\w+`,
// which truncates every canonical `nl2agent-*` tag to `nl2agent`. Feed it a
// word-only alias and restore the canonical language before card validation.
const languageAliases = Object.fromEntries(
  languages.map((language) => [language, language.replaceAll("-", "")])
) as Record<Nl2AgentFenceLanguage, string>;

const languageByAlias = Object.fromEntries(
  Object.entries(languageAliases).map(([language, alias]) => [alias, language])
) as Record<string, Nl2AgentFenceLanguage>;

export const preprocessNl2AgentFences = (content: string): string =>
  content.replace(
    /^([ \t]*)(`{3,}|~{3,})(nl2agent-[\w-]+)([^\S\r\n]*)$/gm,
    (line, indentation, marker, language, trailing) => {
      const alias = languageAliases[language as Nl2AgentFenceLanguage];
      return alias ? `${indentation}${marker}${alias}${trailing}` : line;
    }
  );

const HiddenCodeHeader = () => null;

export const nl2AgentComponentsByLanguage = Object.fromEntries(
  Object.entries(languageByAlias).map(([alias, language]) => {
    const CanonicalNl2AgentFenceRenderer = (props: SyntaxHighlighterProps) => (
      <Nl2AgentFenceRenderer {...props} language={language} />
    );
    return [
      alias,
      {
        SyntaxHighlighter: CanonicalNl2AgentFenceRenderer,
        CodeHeader: HiddenCodeHeader,
      },
    ];
  })
);

export const Nl2AgentMessageLifecycle = () => {
  const workflow = useNl2AgentWorkflow();
  const [manualRetryText, setManualRetryText] = useState<string>();
  const messageIdValue = useAuiState((s) => s.message.id);
  const complete = useAuiState((s) => s.message.status?.type === "complete");
  const latest = useAuiState(
    (s) => s.thread.messages.at(-1)?.id === s.message.id
  );
  const text = useAuiState((s) =>
    s.message.content
      .filter((part) => part.type === "text")
      .map((part) => (part.type === "text" ? part.text : ""))
      .join("")
  );

  useEffect(() => {
    const messageId = Number(messageIdValue);
    if (
      !workflow.active ||
      !complete ||
      !latest ||
      !Number.isInteger(messageId)
    ) {
      return;
    }
    const validation = validateNl2AgentCards(text, workflow.agentId);
    const expected = workflow.sessionState?.expected_card_types ?? [];
    const failure =
      validation.failure ??
      (expected.length > 0 && validation.cards.length === 0
        ? { cardType: expected[0], reason: "missing_card" as const }
        : undefined);
    if (!failure) return;
    const key = `${messageId}:${failure.cardType}:${failure.cardKey ?? ""}:failed`;
    if (!workflow.claimCardDelivery(key)) return;
    void reportNl2AgentCardDelivery(workflow.agentId!, {
      message_id: messageId,
      card_type: failure.cardType,
      status: "failed",
      reason: failure.reason,
      card_key: failure.cardKey,
    })
      .then(async (result) => {
        workflow.completeCardDelivery(key);
        if (result.auto_retry_allowed && result.chat_injection_text) {
          await workflow.continueWithText(result.chat_injection_text);
        } else if (result.chat_injection_text) {
          setManualRetryText(result.chat_injection_text);
        }
      })
      .catch(() => workflow.failCardDelivery(key));
  }, [complete, latest, messageIdValue, text, workflow]);

  if (!manualRetryText) return null;
  return (
    <Alert
      className="mt-2"
      type="warning"
      showIcon
      message="The configuration card could not be rendered."
      action={
        <Button
          size="small"
          disabled={workflow.busy}
          onClick={() => {
            setManualRetryText(undefined);
            void workflow.continueWithText(manualRetryText);
          }}
        >
          Regenerate
        </Button>
      }
    />
  );
};
