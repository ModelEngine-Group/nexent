// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Steps } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import SkillTypeIcon from "./SkillTypeIcon";

export default function SkillConfigurationHeader({
  name,
  tags,
  subtitle,
  groupStep,
  actions,
}: {
  name: string;
  tags?: string[];
  subtitle?: string;
  groupStep?: boolean;
  actions: ReactNode;
}) {
  const { t } = useTranslation("common");

  return (
    <div className="flex flex-wrap items-center gap-3 p-4">
      <SkillTypeIcon name={name} tags={tags} />
      <div className="min-w-0 flex-1">
        <h2 className="truncate text-base font-medium">
          {name || t("skillChat.untitled")}
        </h2>
        {subtitle && (
          <p className="text-body-1 text-muted-foreground">{subtitle}</p>
        )}
      </div>
      {groupStep !== undefined && (
        <Steps
          current={groupStep ? 1 : 0}
          size="small"
          responsive={false}
          className="!w-full !max-w-[360px]"
          items={[
            { title: t("skillCreation.parameters") },
            { title: t("skillCreation.groups") },
          ]}
        />
      )}
      {actions}
    </div>
  );
}
