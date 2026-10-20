// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { AuiIf, ComposerPrimitive } from "@assistant-ui/react";
import { Mic, MicOff, Paperclip } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { ComposerAddAttachment } from "../ui/attachment";

export function ComposerAttachment() {
  const { t } = useTranslation();
  return (
    <ComposerAddAttachment
      tooltip={t("workbench.controls.uploadAttachment")}
      icon={<Paperclip className="size-5" />}
      className="size-8 text-muted-foreground"
    />
  );
}

export function ComposerDictation({ configured }: { configured: boolean }) {
  const { t } = useTranslation();
  return (
    <>
      <AuiIf condition={(state) => !state.composer.dictation}>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="inline-flex">
              <ComposerPrimitive.Dictate asChild>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  disabled={!configured}
                  className="size-8 text-muted-foreground"
                >
                  <Mic className="size-5" />
                </Button>
              </ComposerPrimitive.Dictate>
            </span>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            {configured
              ? t("chat.composer.voiceInput")
              : t("chat.composer.voiceInputDisabled")}
          </TooltipContent>
        </Tooltip>
      </AuiIf>
      <AuiIf condition={(state) => !!state.composer.dictation}>
        <Tooltip>
          <TooltipTrigger asChild>
            <ComposerPrimitive.StopDictation asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="size-8 text-destructive hover:text-destructive"
              >
                <MicOff className="size-4" />
              </Button>
            </ComposerPrimitive.StopDictation>
          </TooltipTrigger>
          <TooltipContent side="bottom">
            {t("chat.composer.stopVoiceInput")}
          </TooltipContent>
        </Tooltip>
      </AuiIf>
    </>
  );
}
