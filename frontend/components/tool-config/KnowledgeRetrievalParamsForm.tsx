"use client";
import { Input, InputNumber, Select, Switch, Tooltip } from "antd";
import { Info } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { ToolParam } from "@/types/agentConfig";
function getLocalizedParamDescription(
  param: ToolParam,
  language: string
): string | undefined {
  if (language.toLowerCase().startsWith("zh")) {
    return param.description_zh || param.description;
  }
  return param.description || param.description_zh;
}

function renderParamInput(
  t: (key: string) => string,
  param: ToolParam,
  value: unknown,
  onChange: (value: unknown) => void
) {
  if (param.type === "boolean") {
    return <Switch checked={Boolean(value)} onChange={onChange} />;
  }

  if (param.type === "number") {
    return (
      <InputNumber
        className="w-full"
        value={typeof value === "number" ? value : undefined}
        onChange={onChange}
        placeholder={
          param.default || t("agent.knowledge.inputNumberPlaceholder")
        }
      />
    );
  }

  if (param.name === "search_method") {
    return (
      <Select
        className="w-full"
        value={typeof value === "string" ? value : undefined}
        onChange={onChange}
        options={[
          {
            label: "hybrid_search",
            value: "hybrid_search",
          },
          {
            label: "vector_search",
            value: "vector_search",
          },
          {
            label: "full_text_search",
            value: "full_text_search",
          },
        ]}
      />
    );
  }

  if (param.name === "reranking_mode" || param.name === "rerank_mode") {
    return (
      <Select
        className="w-full"
        value={typeof value === "string" ? value : undefined}
        onChange={onChange}
        options={[
          {
            label: "performance",
            value: "performance",
          },
          {
            label: "high_accuracy",
            value: "high_accuracy",
          },
        ]}
      />
    );
  }

  if (param.name === "search_mode") {
    return (
      <Select
        className="w-full"
        value={typeof value === "string" ? value : undefined}
        onChange={onChange}
        options={[
          { label: t("agent.knowledge.searchMode.hybrid"), value: "hybrid" },
          {
            label: t("agent.knowledge.searchMode.accurate"),
            value: "accurate",
          },
          {
            label: t("agent.knowledge.searchMode.semantic"),
            value: "semantic",
          },
        ]}
      />
    );
  }

  return (
    <Input
      value={typeof value === "string" ? value : ""}
      onChange={(event) => onChange(event.target.value)}
      placeholder={param.default || t("agent.knowledge.paramPlaceholder")}
    />
  );
}

export function KnowledgeRetrievalParamsForm({
  params,
  values,
  onChange,
}: {
  params: ToolParam[];
  values: Record<string, unknown>;
  onChange: (name: string, value: unknown) => void;
}) {
  const { t, i18n } = useTranslation("common");
  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      {params.map((param) => {
        const description = getLocalizedParamDescription(param, i18n.language);
        return (
          <label key={param.name} className="space-y-1.5">
            <span className="flex items-center gap-1 text-xs font-medium text-gray-600">
              {param.name}
              {description && (
                <Tooltip title={description}>
                  <Info
                    size={13}
                    className="cursor-help text-gray-400"
                    aria-label={description}
                  />
                </Tooltip>
              )}
            </span>
            {renderParamInput(t, param, values[param.name], (value) =>
              onChange(param.name, value)
            )}
          </label>
        );
      })}
    </div>
  );
}
