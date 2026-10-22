// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useTranslation } from "react-i18next";

import { useState } from "react";

import {
  ParamDialog,
  ParamField,
  ParamInput,
  ParamLabel,
  ParamSwitch,
} from "./ParamDialog";

export interface SkillConfigModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm?: (values: Record<string, string>) => void;
  skillName?: string;
}

export function SkillConfigModal({
  open,
  onClose,
  onConfirm,
  skillName = "search-web-tavily",
}: SkillConfigModalProps) {
  const { t } = useTranslation();
  const [apiKey, setApiKey] = useState("aqVLa_4z7T…");
  const [maxResults, setMaxResults] = useState("");
  const [imageFilter, setImageFilter] = useState(true);

  return (
    <ParamDialog
      variant="skill"
      open={open}
      title={t("ui.localization.resourceConfiguration", { name: skillName })}
      onClose={onClose}
      onConfirm={() =>
        onConfirm?.({ tavily_api_key: apiKey, max_results: maxResults })
      }
    >
      <ParamField label="tavily_api_key" required info>
        <ParamInput
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </ParamField>

      <ParamField label="max_results" info>
        <ParamInput
          placeholder={t("ui.localization.resultCount")}
          value={maxResults}
          onChange={(e) => setMaxResults(e.target.value)}
        />
      </ParamField>

      <div className="flex flex-col items-start gap-2">
        <ParamLabel label="Image filter" info />
        <ParamSwitch checked={imageFilter} onChange={setImageFilter} />
      </div>
    </ParamDialog>
  );
}
