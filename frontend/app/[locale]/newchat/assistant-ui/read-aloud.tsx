// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useAuiState } from "@assistant-ui/react";
import { message } from "antd";
import { LoaderCircle, Square, Volume2 } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type PropsWithChildren,
} from "react";
import { useTranslation } from "react-i18next";
import { useConfig } from "@/hooks/useConfig";
import log from "@/lib/logger";
import { conversationService } from "@/services/conversationService";
import { TooltipIconButton } from "../ui/tooltip-icon-button";

type Playback = { messageId: string; phase: "generating" | "playing" };
type ReadAloudControls = {
  configured: boolean;
  playback: Playback | null;
  start: (messageId: string, text: string) => Promise<void>;
  stop: () => void;
};

const ReadAloudContext = createContext<ReadAloudControls | null>(null);

export function ReadAloudProvider({ children }: PropsWithChildren) {
  const { t } = useTranslation();
  const { modelConfig } = useConfig();
  const configured = Boolean(modelConfig?.tts?.modelName?.trim());
  const [playback, setPlayback] = useState<Playback | null>(null);
  const release = useRef<(() => void) | null>(null);

  useEffect(() => () => release.current?.(), []);

  const stop = useCallback(() => {
    release.current?.();
    release.current = null;
    setPlayback(null);
  }, []);

  useEffect(() => {
    if (!configured && release.current) stop();
  }, [configured, stop]);

  const start = async (messageId: string, text: string) => {
    stop();
    const controller = new AbortController();

    try {
      const audio = new AudioContext();
      release.current = () => {
        controller.abort();
        void audio.close().catch(() => undefined);
      };
      setPlayback({ messageId, phase: "generating" });

      // Resume while the click still grants browser audio playback permission.
      const [, speech] = await Promise.all([
        audio.resume(),
        conversationService.tts.synthesize(text, controller.signal),
      ]);
      const buffer = await audio.decodeAudioData(await speech.arrayBuffer());
      if (controller.signal.aborted) return;

      const source = audio.createBufferSource();
      source.buffer = buffer;
      source.connect(audio.destination);
      source.onended = () => {
        if (!controller.signal.aborted) stop();
      };
      source.start();
      setPlayback({ messageId, phase: "playing" });
    } catch (error) {
      if (controller.signal.aborted) return;
      stop();
      log.warn("Reply read-aloud failed", error);
      message.error(t("chat.thread.readAloudFailed"));
    }
  };

  return (
    <ReadAloudContext.Provider
      value={{
        configured,
        playback,
        start,
        stop,
      }}
    >
      {children}
    </ReadAloudContext.Provider>
  );
}

type ReplyPart = {
  type: string;
  text?: string;
  isWarning?: boolean;
  isError?: boolean;
  isSearchImage?: boolean;
  metadata?: { subagentId?: string | number };
};

export function ReadAloudButton() {
  const { t } = useTranslation();
  const controls = useContext(ReadAloudContext);
  const messageId = useAuiState((s) => s.message.id);
  const content = useAuiState((s) => s.message.content) as readonly ReplyPart[];
  if (!controls?.configured) return null;
  const active = controls.playback?.messageId === messageId;

  const text = content
    .filter(
      (part) =>
        part.type === "text" &&
        !part.isWarning &&
        !part.isError &&
        !part.isSearchImage &&
        part.metadata?.subagentId === undefined
    )
    .map((part) => part.text?.trim())
    .filter(Boolean)
    .join("\n\n");
  if (!text && !active) return null;

  return (
    <TooltipIconButton
      type="button"
      tooltip={t(
        active ? "chat.thread.stopReadAloud" : "chat.thread.readAloud"
      )}
      aria-pressed={active}
      onClick={() =>
        active ? controls.stop() : void controls.start(messageId, text)
      }
    >
      {active ? (
        controls.playback?.phase === "generating" ? (
          <LoaderCircle className="animate-spin" />
        ) : (
          <Square />
        )
      ) : (
        <Volume2 />
      )}
    </TooltipIconButton>
  );
}
