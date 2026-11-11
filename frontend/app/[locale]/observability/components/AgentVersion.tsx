// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { useTranslation } from "react-i18next";

interface AgentVersionProps {
  version?: number | null;
  name?: string | null;
}

export function AgentVersion({ version, name }: AgentVersionProps) {
  const { t } = useTranslation();
  const known =
    typeof version === "number" &&
    Number.isSafeInteger(version) &&
    version >= 0;
  const label = !known
    ? t("trajectory.unknownVersion")
    : version === 0
      ? t("trajectory.draftVersion")
      : `V${version}`;
  return <span title={known && name ? name : undefined}>{label}</span>;
}
