// Copyright (c) Huawei Technologies Co., Ltd. 2026. All rights reserved.

"use client";

import { ComposerPrimitive, useAui } from "@assistant-ui/react";
import { useTranslation } from "react-i18next";
import { StandardButton } from "@/components/common/StandardButton";

export function UserMessageEditComposer() {
  const { t } = useTranslation();
  const aui = useAui();

  return (
    <ComposerPrimitive.Root
      aria-label={t("chat.thread.edit")}
      className="mx-auto flex w-full max-w-(--thread-max-width) flex-col gap-3 rounded-2xl border-0 bg-[#f3f3f3] p-4 dark:bg-muted"
      onKeyDown={(event) => {
        if (event.key === "Escape" && !event.nativeEvent.isComposing) {
          event.preventDefault();
          aui.composer().cancel();
        }
      }}
    >
      <ComposerPrimitive.Input
        autoFocus
        aria-label={t("chat.thread.edit")}
        rows={2}
        submitMode="ctrlEnter"
        className="min-h-16 max-h-80 w-full resize-none border-0 bg-transparent text-sm leading-6 text-foreground outline-none focus:ring-0 focus-visible:outline-none focus-visible:ring-0"
      />
      <div className="flex items-center justify-end gap-2">
        <ComposerPrimitive.Cancel asChild>
          <StandardButton
            htmlType="button"
            className="!rounded-full !bg-background"
          >
            {t("common.cancel")}
          </StandardButton>
        </ComposerPrimitive.Cancel>
        <ComposerPrimitive.Send asChild>
          <StandardButton
            htmlType="button"
            variant="primary"
            className="!rounded-full !bg-foreground !text-background"
          >
            {t("chat.composer.send")}
          </StandardButton>
        </ComposerPrimitive.Send>
      </div>
    </ComposerPrimitive.Root>
  );
}
