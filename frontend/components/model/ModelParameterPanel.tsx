// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import type { ReactNode } from "react";
import {
  BrainCircuit,
  Layers,
  RotateCcw,
  SlidersHorizontal,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { StandardCard } from "@/components/common/StandardCard";
import { StandardButton } from "@/components/common/StandardButton";

/** Shared by single onboarding and the batch model configuration dialog. */
export function ModelParameterPanel({
  source,
  hasModel,
  pending,
  onReset,
  sampling,
  thinking,
  capacity,
}: {
  source?: string;
  hasModel: boolean;
  pending: boolean;
  onReset: () => void;
  sampling: ReactNode;
  thinking: ReactNode;
  capacity: ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <section
      aria-label={t("modelProfile.modelParameters")}
      className="min-w-0 space-y-3 bg-muted/30 p-6 lg:border-l"
    >
      <h3 className="text-sm font-semibold">
        {t("modelProfile.modelParameters")}
      </h3>
      {!hasModel ? (
        <div className="flex min-h-72 flex-col items-center justify-center gap-2 rounded-lg border border-dashed bg-background/50 p-6 text-center text-xs text-muted-foreground">
          <SlidersHorizontal className="mb-2 size-5" />
          <p className="font-medium text-foreground">
            {t("modelProfile.layout.emptyTitle")}
          </p>
          <p>{t("modelProfile.layout.emptyDescription")}</p>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-dashed bg-background px-3 py-2 text-xs">
            <span className="min-w-0 break-words text-muted-foreground">
              {t("modelProfile.layout.source")}{" "}
              <span className="font-medium text-foreground">
                {source ?? t("modelProfile.otherProfile")}
              </span>
            </span>
            <StandardButton
              className="!h-auto !border-0 !bg-transparent !p-0 !text-xs !shadow-none"
              icon={<RotateCcw size={12} />}
              disabled={pending}
              onClick={onReset}
            >
              {t("modelProfile.layout.reset")}
            </StandardButton>
          </div>
          <ParameterCard
            title={t("modelProfile.samplingGroup")}
            icon={<SlidersHorizontal size={16} />}
          >
            {sampling}
          </ParameterCard>
          <ParameterCard
            title={t("modelProfile.thinkingGroup")}
            icon={<BrainCircuit size={16} />}
          >
            {thinking}
          </ParameterCard>
          <ParameterCard
            title={t("modelProfile.capacityGroup")}
            icon={<Layers size={16} />}
          >
            {capacity}
          </ParameterCard>
        </>
      )}
    </section>
  );
}

function ParameterCard({
  title,
  icon,
  children,
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <StandardCard
      bordered
      role="region"
      aria-label={title}
      className="!mb-3 !bg-background shadow-sm [&_.ant-card-body]:!p-4"
    >
      <h4 className="mb-3 flex items-center gap-2 text-sm font-medium">
        <span className="text-primary">{icon}</span>
        {title}
      </h4>
      {children}
    </StandardCard>
  );
}
