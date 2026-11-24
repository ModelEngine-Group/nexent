// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { Steps } from "antd";
import { useTranslation } from "react-i18next";

export default function McpConfigurationSteps({
  current,
}: {
  current: number;
}) {
  const { t } = useTranslation("common");

  return (
    <Steps
      className="relative shrink-0 !justify-between before:absolute before:inset-x-10 before:top-3 before:h-px before:bg-primary"
      classNames={{
        item: "!flex-none",
        itemRail: "!hidden",
        itemWrapper: "relative z-10 !gap-2 bg-background",
        itemTitle: "!text-sm",
      }}
      current={current}
      size="small"
      titlePlacement="vertical"
      responsive={false}
      items={[
        { title: t("mcpTools.addModal.configureStep") },
        { title: t("mcpTools.addModal.groupsStep") },
      ]}
    />
  );
}
