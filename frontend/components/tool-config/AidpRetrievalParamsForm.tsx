// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
"use client";
import {
  Alert,
  Button,
  Checkbox,
  Collapse,
  InputNumber,
  Select,
  Switch,
  Tooltip,
} from "antd";
import { CircleHelp } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  aidpChannels,
  aidpDefaults,
  aidpErrors,
  aidpMethods,
  resolveAidpConfig,
} from "@/lib/aidpRetrievalConfig";

export function AidpRetrievalParamsForm({
  values,
  onChange,
  disabled = false,
}: {
  values: Record<string, unknown>;
  onChange: (patch: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  const { t } = useTranslation("common");
  const c = resolveAidpConfig(values),
    methods = aidpMethods(c.search_method);
  const selectedMethods = methods.filter((m) => aidpChannels.includes(m));
  const mixed =
    c.search_method === "hybrid_search" ||
    (typeof c.search_method === "string" && c.search_method.includes("|"));
  const errors = aidpErrors(values);
  if (mixed && selectedMethods.length < 2) errors.search_method = "combination";
  const label = (key: string) =>
    t(
      `aidpRetrieval.fields.${key === "hybrid_top_k" ? (methods.includes("vector_search") && methods.includes("full_text_search") ? "hybrid_top_k" : methods.includes("vector_search") ? "vector_top_k" : "full_text_top_k") : key}`
    );
  const row = (key: string, input: React.ReactNode) => (
    <div key={key} className="space-y-1">
      <div className="flex items-center gap-1 text-xs text-gray-600">
        {label(key)}
        <Tooltip
          title={
            <div className="space-y-2 text-left">
              <p>{t(`aidpRetrieval.help.${key}`)}</p>
              <p>{t("aidpRetrieval.help.defaults")}</p>
            </div>
          }
        >
          <button
            type="button"
            className="inline-flex cursor-help"
            aria-label={label(key)}
          >
            <CircleHelp size={13} />
          </button>
        </Tooltip>
      </div>
      {input}
      {errors[key] && (
        <div role="alert" className="text-xs text-red-600">
          {t(`aidpRetrieval.errors.${errors[key]}`)}
        </div>
      )}
    </div>
  );
  const number = (key: string, min: number, max: number, step = 1) =>
    row(
      key,
      <InputNumber
        aria-label={label(key)}
        className="!w-full"
        size="small"
        min={min}
        max={max}
        step={step}
        value={c[key] as number}
        disabled={disabled}
        status={errors[key] ? "error" : undefined}
        onChange={(v) => onChange({ [key]: v === null ? Number.NaN : v })}
      />
    );
  const toggle = (key: string, locked = false) =>
    row(
      key,
      <Switch
        size="small"
        aria-label={label(key)}
        checked={Boolean(c[key])}
        disabled={disabled || locked}
        onChange={(v) =>
          onChange(
            key === "reranking_enable" && !v
              ? { [key]: false, graph_reranking_enable: false }
              : { [key]: v }
          )
        }
      />
    );
  const candidate = (key: string) => (
    <div key={key}>
      {number(key, 1, 500)}
      <Checkbox
        disabled={disabled}
        checked={values[key] == null}
        onChange={(e) => onChange({ [key]: e.target.checked ? null : c[key] })}
      >
        {t("aidpRetrieval.follow")}
      </Checkbox>
    </div>
  );
  const vector = methods.includes("vector_search"),
    text = methods.includes("full_text_search"),
    graph = methods.includes("graph_search");
  return (
    <div className="space-y-3" data-testid="aidp-retrieval-form">
      {row(
        "search_method",
        <Select
          aria-label={label("search_method")}
          size="small"
          className="w-full"
          disabled={disabled}
          value={mixed ? "mixed" : methods[0]}
          options={[...aidpChannels, "mixed"].map((value) => ({
            value,
            label: t(`aidpRetrieval.methods.${value}`),
          }))}
          onChange={(v) => {
            onChange({ search_method: v === "mixed" ? "hybrid_search" : v });
          }}
        />
      )}
      {mixed && (
        <Collapse
          size="small"
          items={[
            {
              key: "combination",
              label: `${t("aidpRetrieval.combination")} · ${selectedMethods
                .map((m) => t(`aidpRetrieval.methods.${m}`))
                .join(" + ")}`,
              children: (
                <div className="space-y-2">
                  <Checkbox.Group
                    value={selectedMethods}
                    disabled={disabled}
                    options={aidpChannels.map((value) => ({
                      value,
                      label: t(`aidpRetrieval.methods.${value}`),
                    }))}
                    onChange={(v) => {
                      const chosen = aidpChannels.filter((m) => v.includes(m));
                      onChange({
                        search_method:
                          chosen.length === 3
                            ? "hybrid_search"
                            : chosen.length < 2
                              ? chosen.join("|") + "|"
                              : chosen.join("|"),
                      });
                    }}
                  />
                  {methods.length < 2 && (
                    <Alert
                      type="error"
                      title={t("aidpRetrieval.errors.combination")}
                    />
                  )}
                </div>
              ),
            },
          ]}
        />
      )}
      <div className="grid grid-cols-1 min-[400px]:grid-cols-2 gap-3">
        {number("top_k", 1, 100)}
        {number("score_threshold", 0, 1, 0.01)}
        {toggle("reranking_enable")}
        {row(
          "reranking_mode",
          <Select
            aria-label={label("reranking_mode")}
            size="small"
            className="w-full"
            value={c.reranking_mode as string}
            disabled={disabled || !c.reranking_enable}
            options={["performance", "high_accuracy", "jargon_coverage"].map(
              (value) => ({ value, label: t(`aidpRetrieval.modes.${value}`) })
            )}
            onChange={(v) => onChange({ reranking_mode: v })}
          />
        )}
      </div>
      <Collapse
        size="small"
        items={[
          {
            key: "details",
            label: t("aidpRetrieval.details"),
            children: (
              <div className="space-y-4">
                {vector && (
                  <section
                    aria-label={t("aidpRetrieval.methods.vector_search")}
                  >
                    <h3 className="mb-2 text-xs text-gray-500">
                      {t("aidpRetrieval.methods.vector_search")}
                    </h3>
                    <div className="grid grid-cols-1 min-[400px]:grid-cols-2 gap-3">
                      {candidate("vector_candidates")}
                      {number("vector_score_threshold", 0, 1, 0.01)}
                    </div>
                  </section>
                )}
                {text && (
                  <section
                    aria-label={t("aidpRetrieval.methods.full_text_search")}
                  >
                    <h3 className="mb-2 text-xs text-gray-500">
                      {t("aidpRetrieval.methods.full_text_search")}
                    </h3>
                    <div className="grid grid-cols-1 min-[400px]:grid-cols-2 gap-3">
                      {candidate("full_text_candidates")}
                      {number("full_text_score_threshold", 0, 1, 0.01)}
                    </div>
                  </section>
                )}
                {graph && (
                  <section aria-label={t("aidpRetrieval.methods.graph_search")}>
                    <h3 className="mb-2 text-xs text-gray-500">
                      {t("aidpRetrieval.methods.graph_search")}
                    </h3>
                    <div className="grid grid-cols-1 min-[400px]:grid-cols-2 gap-3">
                      {number("graph_top_k", 0, 100)}
                      {number("graph_score_threshold", 0, 1, 0.01)}
                      {toggle("graph_reranking_enable", !c.reranking_enable)}
                    </div>
                  </section>
                )}
                {(vector || text) &&
                  ((graph && !c.graph_reranking_enable) ||
                    Number(c.hybrid_top_k) > 0) &&
                  number("hybrid_top_k", 0, 100)}
              </div>
            ),
          },
          {
            key: "enhancement",
            label: t("aidpRetrieval.enhancement"),
            children: (
              <div className="grid grid-cols-1 min-[400px]:grid-cols-2 gap-3">
                {[
                  "rewrite_enable",
                  "query_expansion_enable",
                  "related_search_enable",
                  "multi_modal",
                ].map((key) => toggle(key))}
              </div>
            ),
          },
        ]}
      />
      {Object.keys(errors).length > 0 && (
        <Alert
          type="error"
          title={t("aidpRetrieval.invalid")}
          description={Object.keys(errors).map(label).join("、")}
        />
      )}
      <Button
        size="small"
        disabled={disabled}
        onClick={() => onChange({ ...aidpDefaults })}
      >
        {t("aidpRetrieval.reset")}
      </Button>
    </div>
  );
}
