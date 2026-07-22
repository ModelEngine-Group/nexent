"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, Button } from "antd";
import { useAuiState } from "@assistant-ui/react";
import type { SyntaxHighlighterProps } from "@assistant-ui/react-markdown";

import { tryRenderNl2AgentCard } from "./index";
import { parseNl2AgentCard } from "./cardValidation";
import { useNl2AgentWorkflow } from "./Nl2AgentWorkflowContext";

export const resolveNl2AgentPersistedMessageId = (
  persistedMessageId: unknown,
  runtimeMessageId: unknown
): number | undefined => {
  for (const candidate of [persistedMessageId, runtimeMessageId]) {
    if (
      typeof candidate === "boolean" ||
      (typeof candidate === "string" && candidate.trim() === "")
    ) {
      continue;
    }
    const numericId = Number(candidate);
    if (Number.isInteger(numericId) && numericId > 0) return numericId;
  }
  return undefined;
};

export const Nl2AgentFenceRenderer = ({
  language,
  code,
}: SyntaxHighlighterProps) => {
  const workflow = useNl2AgentWorkflow();
  const { agentId, editable, reportRenderedCard } = workflow;
  const messageIdValue = useAuiState((s) => s.message.id);
  const persistedMessageIdValue = useAuiState(
    (s) => s.message.metadata.custom.persistedMessageId
  );
  const complete = useAuiState((s) => s.message.status?.type === "complete");
  const latest = useAuiState(
    (s) => s.thread.messages.at(-1)?.id === s.message.id
  );
  const messageId = resolveNl2AgentPersistedMessageId(
    persistedMessageIdValue,
    messageIdValue
  );
  const validation = useMemo(
    () => parseNl2AgentCard(language, code, agentId),
    [agentId, code, language]
  );
  const card = validation.cards[0];
  const interactive = complete && latest && editable;
  const registrationEnabled = interactive && messageId !== undefined;

  const onRegistered = useCallback(async () => {
    if (!card || messageId === undefined) return;
    await reportRenderedCard(messageId, card);
  }, [card, messageId, reportRenderedCard]);

  useEffect(() => {
    if (!registrationEnabled || !card || card.requiresRegistration) return;
    if (messageId === undefined) return;
    void reportRenderedCard(messageId, card).catch(() => undefined);
  }, [card, messageId, registrationEnabled, reportRenderedCard]);

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
    agentId,
    onRegistered,
    registrationEnabled
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
  const { active, busy, continueWithText, processCompletedMessage } = workflow;
  const [manualRetryText, setManualRetryText] = useState<string>();
  const messageIdValue = useAuiState((s) => s.message.id);
  const persistedMessageIdValue = useAuiState(
    (s) => s.message.metadata.custom.persistedMessageId
  );
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
    const messageId = resolveNl2AgentPersistedMessageId(
      persistedMessageIdValue,
      messageIdValue
    );
    if (!active || !complete || !latest || messageId === undefined) {
      return;
    }
    void processCompletedMessage(messageId, text)
      .then(setManualRetryText)
      .catch(() => undefined);
  }, [
    active,
    complete,
    latest,
    messageIdValue,
    persistedMessageIdValue,
    processCompletedMessage,
    text,
  ]);

  if (!manualRetryText) return null;
  return (
    <Alert
      className="mt-2"
      type="warning"
      showIcon
      title="The configuration card could not be rendered."
      action={
        <Button
          size="small"
          disabled={busy}
          onClick={() => {
            setManualRetryText(undefined);
            void continueWithText(manualRetryText);
          }}
        >
          Regenerate
        </Button>
      }
    />
  );
};
