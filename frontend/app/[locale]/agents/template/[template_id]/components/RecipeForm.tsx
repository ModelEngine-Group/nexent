"use client";

import React, { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useModelList } from "@/hooks/model/useModelList";

export type RecipeVariableType = "string" | "number" | "select" | "radio" | "boolean" | "model";

export interface RecipeVariable {
  key: string;
  label: string;
  description?: string;
  type: RecipeVariableType;
  required: boolean;
  default?: any;
  options?: { label: string; value: string }[];
  group?: string;
}

interface RecipeFormProps {
  variables: RecipeVariable[];
  onSubmit?: (values: Record<string, any>) => void;
  submitLabel?: string;
}

/**
 * RecipeForm - Dynamic form for recipe variable configuration
 * Renders inputs based on variable type
 */
export function RecipeForm({ variables, onSubmit, submitLabel }: RecipeFormProps) {
  const { t } = useTranslation("common");
  const isZh = t("common.language") === "zh" || false;
  // Real tenant models for the "model" variable type.
  const { availableLlmModels } = useModelList();
  const modelOptions = useMemo(
    () =>
      (availableLlmModels || []).map((m) => ({
        label: m.displayName || m.name,
        value: m.displayName || m.name,
      })),
    [availableLlmModels]
  );
  const [values, setValues] = useState<Record<string, any>>(() => {
    const init: Record<string, any> = {};
    variables.forEach((v) => {
      init[v.key] = v.default ?? "";
    });
    return init;
  });

  // For "model" variables, default to the first available LLM when the
  // declared default is empty or not among the tenant's actual models.
  useEffect(() => {
    if (modelOptions.length === 0) return;
    setValues((prev) => {
      let changed = false;
      const next = { ...prev };
      variables.forEach((v) => {
        if (v.type !== "model") return;
        const current = next[v.key];
        const exists = modelOptions.some((o) => o.value === current);
        if (!exists) {
          next[v.key] = modelOptions[0].value;
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [modelOptions, variables]);

  const handleChange = (key: string, value: any) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit?.(values);
  };

  const renderField = (variable: RecipeVariable) => {
    const { key, label, description, type, required, options } = variable;

    const labelEl = (
      <label className="text-xs font-medium text-[#3C3489] dark:text-purple-300">
        {label}
        {required && (
          <span className="ml-2 inline-block px-1.5 py-0.5 rounded text-[9px] bg-[#EEEDFE] dark:bg-purple-900/30 text-[#534AB7] dark:text-purple-400">
            {isZh ? "必填" : "required"}
          </span>
        )}
      </label>
    );

    const descEl = description ? (
      <span className="text-[11px] text-slate-400 dark:text-slate-500">{description}</span>
    ) : null;

    let inputEl: React.ReactNode;

    switch (type) {
      case "model":
        // Dynamic enum sourced from the tenant's real LLM list (useModelList).
        inputEl = (
          <select
            value={values[key] || ""}
            onChange={(e) => handleChange(key, e.target.value)}
            className="w-full bg-[#FAFAFB] dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-md px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:border-[#534AB7] focus:ring-2 focus:ring-[#534AB7]/10"
          >
            {modelOptions.length === 0 ? (
              <option value="">
                {isZh ? "（租户暂无可用 LLM）" : "(no LLM configured)"}
              </option>
            ) : (
              modelOptions.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))
            )}
          </select>
        );
        break;
      case "select":
        inputEl = (
          <select
            value={values[key] || ""}
            onChange={(e) => handleChange(key, e.target.value)}
            className="w-full bg-[#FAFAFB] dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-md px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:border-[#534AB7] focus:ring-2 focus:ring-[#534AB7]/10"
          >
            <option value="">--</option>
            {options?.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        );
        break;
      case "number":
        inputEl = (
          <input
            type="number"
            value={values[key] ?? 0}
            onChange={(e) => handleChange(key, Number(e.target.value))}
            className="w-full bg-[#FAFAFB] dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-md px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:border-[#534AB7] focus:ring-2 focus:ring-[#534AB7]/10"
          />
        );
        break;
      case "radio":
        inputEl = (
          <div className="flex gap-4 py-2">
            {options?.map((opt) => (
              <label
                key={opt.value}
                className="flex items-center gap-1.5 text-sm text-slate-700 dark:text-slate-200"
              >
                <input
                  type="radio"
                  name={key}
                  value={opt.value}
                  checked={values[key] === opt.value}
                  onChange={(e) => handleChange(key, e.target.value)}
                  className="accent-[#534AB7]"
                />
                {opt.label}
              </label>
            ))}
          </div>
        );
        break;
      case "boolean":
        inputEl = (
          <label className="flex items-center gap-2 py-2 cursor-pointer">
            <input
              type="checkbox"
              checked={values[key] ?? false}
              onChange={(e) => handleChange(key, e.target.checked)}
              className="accent-[#534AB7] w-4 h-4"
            />
            <span className="text-sm text-slate-600 dark:text-slate-300">
              {values[key] ? (isZh ? "已启用" : "Enabled") : (isZh ? "未启用" : "Disabled")}
            </span>
          </label>
        );
        break;
      default:
        inputEl = (
          <input
            type="text"
            value={values[key] || ""}
            onChange={(e) => handleChange(key, e.target.value)}
            className="w-full bg-[#FAFAFB] dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-md px-3 py-2 text-sm text-slate-800 dark:text-slate-100 focus:outline-none focus:border-[#534AB7] focus:ring-2 focus:ring-[#534AB7]/10"
          />
        );
    }

    return (
      <div key={key} className="flex flex-col gap-1">
        {labelEl}
        {descEl}
        {inputEl}
      </div>
    );
  };

  if (variables.length === 0) {
    return (
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 text-center text-sm text-slate-400">
        {isZh ? "此模板无需配置变量" : "No variables to configure for this template"}
      </div>
    );
  }

  // Group variables by their `group` field (llm / mcp / other) so the form
  // renders as unified sections (LLM / MCP / 其他) instead of a flat grid.
  const GROUP_LABELS: Record<string, { zh: string; en: string }> = {
    llm: { zh: "LLM 配置", en: "LLM" },
    mcp: { zh: "MCP 配置", en: "MCP" },
    other: { zh: "其他配置", en: "Other" },
  };
  const groups: { key: string; label: string; items: RecipeVariable[] }[] = [];
  const groupMap = new Map<string, RecipeVariable[]>();
  const order: string[] = [];
  variables.forEach((v) => {
    const g = (v as any).group || "other";
    if (!groupMap.has(g)) {
      groupMap.set(g, []);
      order.push(g);
    }
    groupMap.get(g)!.push(v);
  });
  order.forEach((g) => {
    const meta = GROUP_LABELS[g] || { zh: g, en: g };
    groups.push({
      key: g,
      label: isZh ? meta.zh : meta.en,
      items: groupMap.get(g)!,
    });
  });

  return (
    <form onSubmit={handleSubmit} className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4 space-y-5">
      {groups.map((grp) => (
        <div key={grp.key}>
          <h3 className="text-xs font-semibold text-[#534AB7] dark:text-purple-300 mb-2 uppercase tracking-wide">
            {grp.label}
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {grp.items.map(renderField)}
          </div>
        </div>
      ))}
      {submitLabel && (
        <div className="mt-2 flex justify-end">
          <button
            type="submit"
            className="px-6 py-2.5 rounded-lg bg-[#534AB7] hover:bg-[#7F77DD] text-white text-sm font-medium transition-all duration-300"
          >
            {submitLabel}
          </button>
        </div>
      )}
    </form>
  );
}

export default RecipeForm;
