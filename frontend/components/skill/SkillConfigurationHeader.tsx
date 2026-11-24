// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Steps } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export default function SkillConfigurationHeader({
  groupStep,
  actions,
}: {
  groupStep?: boolean;
  actions: ReactNode;
}) {
  const { t } = useTranslation("common");

  return (
    <div className="flex flex-wrap items-center justify-end gap-3 p-4">
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
