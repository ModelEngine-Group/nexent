"use client";

import { useAui, useAuiState } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import { Lightbulb } from "lucide-react";

import { Composer } from "./composer";

interface AgentConfigurationWelcomeProps {
  disabled: boolean;
  dictationConfigured: boolean;
}

export function AgentConfigurationWelcome({
  disabled,
  dictationConfigured,
}: AgentConfigurationWelcomeProps) {
  const { t } = useTranslation("common");
  const aui = useAui();
  const isRunning = useAuiState((state) => state.thread.isRunning);

  return (
    <div
      data-testid="agent-configuration-welcome"
      className="relative flex h-full min-h-[700px] w-full flex-col items-center overflow-y-hidden px-4 text-[#191919]"
    >
      <div className="flex min-h-0 w-full flex-1 items-center justify-center pb-[120px]">
        <div className="w-full max-w-[512px]">
          <div
            data-testid="agent-configuration-greeting"
            className="flex min-h-[100px] flex-col items-center gap-4 pb-6 text-center"
          >
            <h2 className="text-[28px] font-bold leading-9 tracking-[0px]">
              {t("nl2agent.configuration.title")}
            </h2>
            <p className="text-base font-normal leading-6 tracking-[0px]">
              {t("nl2agent.configuration.description")}
            </p>
          </div>
          <Composer
            models={[]}
            chatMode="execution"
            onChatModeChange={() => undefined}
            showModelSelector={false}
            isDictationConfigured={dictationConfigured}
            disabled={disabled}
            configurationLayout
          />
        </div>
      </div>
      <div
        data-testid="agent-configuration-suggestions"
        className="absolute top-[calc(100%-282px)] flex min-h-[312px] w-[calc(100%-32px)] max-w-[512px] flex-col gap-4 px-4 py-4"
      >
        <h3 className="text-base font-normal leading-6">
          {t("nl2agent.configuration.helpTitle")}
        </h3>
        {[1, 2, 3, 4].map((index) => {
          const prompt = t(`nl2agent.configuration.help${index}`);
          return (
            <button
              key={index}
              type="button"
              disabled={disabled || isRunning}
              className="flex min-h-10 cursor-pointer items-start gap-2 text-left text-sm font-normal leading-[22px] disabled:cursor-not-allowed disabled:opacity-50"
              onClick={() => aui.thread.composer().setText(prompt)}
            >
              <Lightbulb className="mt-[3px] size-4 shrink-0" />
              <span>{prompt}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
