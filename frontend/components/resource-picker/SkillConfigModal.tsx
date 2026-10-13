"use client";

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
  const [apiKey, setApiKey] = useState("aqVLa_4z7T…");
  const [maxResults, setMaxResults] = useState("");
  const [imageFilter, setImageFilter] = useState(true);

  return (
    <ParamDialog
      open={open}
      title={`${skillName} 配置`}
      onClose={onClose}
      onConfirm={() => onConfirm?.({ tavily_api_key: apiKey, max_results: maxResults })}
    >
      <ParamField label="tavily_api_key" required info>
        <ParamInput value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
      </ParamField>

      <ParamField label="max_results" info>
        <ParamInput
          placeholder="查询数量"
          value={maxResults}
          onChange={(e) => setMaxResults(e.target.value)}
        />
      </ParamField>

      <div className="flex items-center gap-3">
        <ParamLabel label="Image filter" info />
        <ParamSwitch checked={imageFilter} onChange={setImageFilter} />
      </div>
    </ParamDialog>
  );
}