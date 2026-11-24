// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import { Activity, Puzzle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { UnavailableMonitoring } from "../shared/UnavailableMonitoring";

export function SkillMonitoring({ singleSkill }: { singleSkill: boolean }) {
  const { t } = useTranslation("common");
  return (
    <UnavailableMonitoring
      summaryLabel={t("ops.monitoring.skill.summary")}
      cards={[
        ...(!singleSkill
          ? [{ title: t("ops.monitoring.skill.current"), Icon: Puzzle }]
          : []),
        { title: t("ops.monitoring.skill.usage"), Icon: Activity },
      ]}
      trendTitle={t("ops.monitoring.skill.trend")}
      rankingTitle={singleSkill ? undefined : t("ops.monitoring.skill.top")}
      details={{
        title: t("ops.monitoring.skill.details"),
        nameLabel: t("common.name"),
        searchLabel: t("ops.monitoring.skill.search"),
        columns: [
          { title: t("common.source"), key: "source" },
          { title: t("ops.monitoring.skill.usageColumn"), key: "usage" },
          ...(!singleSkill
            ? [{ title: t("common.actions"), key: "actions" }]
            : []),
        ],
      }}
    />
  );
}
