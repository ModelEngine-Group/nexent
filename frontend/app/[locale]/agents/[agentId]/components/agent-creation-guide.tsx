// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { Button } from "antd";
import { useTranslation } from "react-i18next";

import { StandardTour } from "@/components/common/StandardTour";
import {
  completeAgentCreationGuide,
  hasCompletedAgentCreationGuide,
} from "@/lib/agentCreationGuide";

const TARGETS = ["assistant", "core", "resources", "workflow"] as const;
const PLACEMENTS = ["right", "bottomLeft", "topLeft", "bottomRight"] as const;

interface AgentCreationGuideProps {
  preferenceKey: string;
  workspaceRef: RefObject<HTMLDivElement | null>;
}

export function AgentCreationGuide({
  preferenceKey,
  workspaceRef,
}: AgentCreationGuideProps) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState(0);
  // The local anchor is available before the parent's workspace ref is attached.
  const anchorRef = useRef<HTMLSpanElement>(null);
  const findTarget = useCallback(
    (name: (typeof TARGETS)[number]) =>
      (
        workspaceRef.current ?? anchorRef.current?.parentElement
      )?.querySelector<HTMLElement>(`[data-agent-guide="${name}"]`) ?? null,
    [workspaceRef]
  );

  const initializeGuide = useCallback(
    (anchor: HTMLSpanElement | null) => {
      anchorRef.current = anchor;
      if (
        !anchor ||
        hasCompletedAgentCreationGuide(preferenceKey) ||
        TARGETS.some((name) => !findTarget(name))
      ) {
        return;
      }
      setOpen(true);
    },
    [findTarget, preferenceKey]
  );

  const dismiss = useCallback(() => {
    completeAgentCreationGuide(preferenceKey);
    setOpen(false);
    window.requestAnimationFrame(() => {
      findTarget("assistant")
        ?.querySelector<HTMLTextAreaElement>("textarea")
        ?.focus({ preventScroll: true });
    });
  }, [findTarget, preferenceKey]);

  useEffect(() => {
    if (!open) return;
    const frame = window.requestAnimationFrame(() => {
      document
        .querySelector<HTMLButtonElement>(
          ".agent-creation-guide .ant-btn-primary"
        )
        ?.focus({ preventScroll: true });
    });
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        dismiss();
      }
    };
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.cancelAnimationFrame(frame);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [current, dismiss, open]);

  return (
    <>
      <span ref={initializeGuide} hidden />
      <StandardTour
        open={open}
        current={current}
        onChange={setCurrent}
        onClose={dismiss}
        rootClassName={`agent-creation-guide guide-step-${current + 1}`}
        actionsRender={(actions) =>
          current === 0 ? (
            <>
              <Button size="small" onClick={dismiss}>
                {t("agent.creationGuide.skip")}
              </Button>
              {actions}
            </>
          ) : (
            actions
          )
        }
        gap={{
          offset:
            current === 0
              ? [1, -9]
              : current === 3
                ? 0
                : current === 2
                  ? [17, 6.5]
                  : [17, 8],
          radius: 8,
        }}
        scrollIntoViewOptions={{ block: "nearest", inline: "nearest" }}
        steps={TARGETS.map((name, index) => ({
          title: t(`agent.creationGuide.${name}.title`),
          description: t(`agent.creationGuide.${name}.description`),
          target: () => findTarget(name) ?? workspaceRef.current!,
          placement: PLACEMENTS[index],
          className: index === 2 ? "guide-resources" : undefined,
          style: { width: index === 0 ? 292 : 300 },
          prevButtonProps: { children: t("agent.creationGuide.previous") },
          nextButtonProps: {
            children: t(
              index === 3
                ? "agent.creationGuide.finish"
                : "agent.creationGuide.next"
            ),
          },
        }))}
      />
    </>
  );
}
