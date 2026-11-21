// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Input, Radio, Select, Switch, Tooltip } from "antd";
import { PlusOutlined } from "@ant-design/icons";
import { Info, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import aidpKnowledgeService from "@/ext_components/aidp/shared/services/aidpKnowledgeService";
import type { AidpDocumentItem } from "@/ext_components/aidp/shared/types/management";
import type {
  AidpFileNameCondition,
  AidpMetadataFilter,
  AidpMetadataFilterMatch,
  AidpMetadataFilterOperator,
} from "@/types/knowledgeScope";

const OPERATOR_OPTIONS: Array<{
  value: AidpMetadataFilterOperator;
  labelKey: string;
  defaultLabel: string;
}> = [
  {
    value: "contains",
    labelKey: "chat.knowledgeScope.filterOperatorContains",
    defaultLabel: "包含",
  },
  {
    value: "is",
    labelKey: "chat.knowledgeScope.filterOperatorIs",
    defaultLabel: "等于",
  },
  {
    value: "starts_with",
    labelKey: "chat.knowledgeScope.filterOperatorStartsWith",
    defaultLabel: "开头是",
  },
  {
    value: "ends_with",
    labelKey: "chat.knowledgeScope.filterOperatorEndsWith",
    defaultLabel: "结尾是",
  },
];

/** One KB the file-name search may query. */
export interface FileSearchTarget {
  id: string;
  name: string;
}

interface FileSearchResult {
  name: string;
  knowledgeBases: string[];
}

interface AdvancedMetadataFilterProps {
  value: AidpMetadataFilter;
  targets: FileSearchTarget[];
  disabled?: boolean;
  onChange: (value: AidpMetadataFilter) => void;
}

const MAX_CONDITIONS = 20;
const SEARCH_PAGE_SIZE = 20;
const SEARCH_CONCURRENCY = 3;
const SEARCH_TIMEOUT_MS = 8000;
const SEARCH_DISPLAY_LIMIT = 50;

function searchableFileName(item: AidpDocumentItem): string {
  const name = String(item.original_file_name || item.file_name || "").trim();
  return name || String(item.file_uuid || "").trim();
}

function FileConditionRow({
  condition,
  targets,
  disabled,
  canRemove,
  onChange,
  onRemove,
}: {
  condition: AidpFileNameCondition;
  targets: FileSearchTarget[];
  disabled: boolean;
  canRemove: boolean;
  onChange: (condition: AidpFileNameCondition) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const [results, setResults] = useState<FileSearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const generationRef = useRef(0);
  const controllersRef = useRef<Set<AbortController>>(new Set());

  const abortSearches = () => {
    generationRef.current += 1;
    controllersRef.current.forEach((controller) => controller.abort());
    controllersRef.current.clear();
    setSearching(false);
  };

  useEffect(() => () => abortSearches(), []);

  const updateCondition = (next: AidpFileNameCondition) => {
    setResults(null);
    onChange(next);
  };

  const runSearch = () => {
    const keyword = condition.value.trim();
    if (!keyword || disabled) return;
    abortSearches();
    const generation = generationRef.current;
    setResults([]);
    if (targets.length === 0) {
      setSearching(false);
      return;
    }
    setSearching(true);

    const aggregated = new Map<string, FileSearchResult>();
    const queue = [...targets];
    const worker = async () => {
      while (queue.length > 0) {
        if (generation !== generationRef.current) return;
        const target = queue.shift();
        if (!target) return;
        const controller = new AbortController();
        controllersRef.current.add(controller);
        const timeout = window.setTimeout(
          () => controller.abort(),
          SEARCH_TIMEOUT_MS
        );
        try {
          const response = await aidpKnowledgeService.listIngestedFiles(
            target.id,
            1,
            SEARCH_PAGE_SIZE,
            keyword,
            controller.signal
          );
          if (
            controller.signal.aborted ||
            generation !== generationRef.current
          ) {
            return;
          }
          response.value.forEach((item) => {
            const name = searchableFileName(item);
            if (!name) return;
            const existing = aggregated.get(name);
            if (existing) {
              if (!existing.knowledgeBases.includes(target.name)) {
                existing.knowledgeBases.push(target.name);
              }
              return;
            }
            aggregated.set(name, { name, knowledgeBases: [target.name] });
          });
          setResults(
            Array.from(aggregated.values()).sort((left, right) =>
              left.name.localeCompare(right.name)
            )
          );
        } catch {
          // A failed KB stays silent; other KBs still contribute results.
        } finally {
          window.clearTimeout(timeout);
          controllersRef.current.delete(controller);
        }
      }
    };

    const workers = Array.from(
      { length: Math.min(SEARCH_CONCURRENCY, targets.length) },
      () => worker()
    );
    void Promise.all(workers).then(() => {
      if (generation !== generationRef.current) return;
      setSearching(false);
      setResults(
        Array.from(aggregated.values()).sort((left, right) =>
          left.name.localeCompare(right.name)
        )
      );
    });
  };

  const pickResult = (name: string) => {
    setResults(null);
    onChange({ operator: condition.operator, value: name });
  };

  const visibleResults = results ? results.slice(0, SEARCH_DISPLAY_LIMIT) : [];

  return (
    <div className="flex items-start gap-2">
      <Select
        className="w-24 shrink-0"
        value={condition.operator}
        disabled={disabled}
        options={OPERATOR_OPTIONS.map((option) => ({
          value: option.value,
          label: t(option.labelKey, option.defaultLabel),
        }))}
        onChange={(nextOperator) =>
          updateCondition({ operator: nextOperator, value: condition.value })
        }
      />
      <div className="min-w-0 flex-1">
        <Input
          value={condition.value}
          disabled={disabled}
          allowClear
          maxLength={256}
          placeholder={t(
            "chat.knowledgeScope.filterFileNamePlaceholder",
            "请输入文件名关键词，回车搜索"
          )}
          onChange={(event) =>
            updateCondition({
              operator: condition.operator,
              value: event.target.value,
            })
          }
          onPressEnter={(event) => {
            event.preventDefault();
            runSearch();
          }}
          suffix={
            <Search
              className="size-3.5 cursor-pointer text-muted-foreground"
              aria-label={t(
                "chat.knowledgeScope.filterSearchAction",
                "搜索文件"
              )}
              onClick={runSearch}
            />
          }
        />
        {searching ? (
          <div className="mt-2 text-xs text-muted-foreground">
            {t("chat.knowledgeScope.filterSearching", "搜索中…")}
          </div>
        ) : results !== null ? (
          <div className="mt-2 max-h-60 overflow-y-auto rounded-md border border-border">
            {targets.length === 0 ? (
              <div className="px-3 py-2 text-xs text-muted-foreground">
                {t(
                  "chat.knowledgeScope.filterSearchNoTargets",
                  "请先选择知识库"
                )}
              </div>
            ) : visibleResults.length === 0 ? (
              <div className="px-3 py-2 text-xs text-muted-foreground">
                {t("chat.knowledgeScope.filterSearchEmpty", "没有匹配的文件")}
              </div>
            ) : (
              <>
                {visibleResults.map((result) => (
                  <button
                    key={result.name}
                    type="button"
                    disabled={disabled}
                    className="flex w-full items-center justify-between gap-3 border-b border-border px-3 py-2 text-left last:border-0 hover:bg-accent disabled:cursor-not-allowed"
                    onClick={() => pickResult(result.name)}
                  >
                    <span className="min-w-0 truncate text-[13px]">
                      {result.name}
                    </span>
                    <span className="max-w-[45%] shrink-0 truncate text-[11px] text-muted-foreground">
                      {result.knowledgeBases.length > 1
                        ? t(
                            "chat.knowledgeScope.filterSearchSameName",
                            "同名于 {{count}} 个库",
                            { count: result.knowledgeBases.length }
                          )
                        : result.knowledgeBases[0]}
                    </span>
                  </button>
                ))}
                {results.length > SEARCH_DISPLAY_LIMIT ? (
                  <div className="px-3 py-2 text-[11px] text-muted-foreground">
                    {t(
                      "chat.knowledgeScope.filterSearchTruncated",
                      "仅显示前 {{count}} 条",
                      { count: SEARCH_DISPLAY_LIMIT }
                    )}
                  </div>
                ) : null}
              </>
            )}
          </div>
        ) : null}
      </div>
      {canRemove ? (
        <Button
          type="text"
          size="small"
          className="mt-0.5 shrink-0 text-muted-foreground"
          icon={<X size={14} />}
          aria-label={t(
            "chat.knowledgeScope.filterRemoveCondition",
            "删除条件"
          )}
          disabled={disabled}
          onClick={onRemove}
        />
      ) : null}
    </div>
  );
}

export function AdvancedMetadataFilter({
  value,
  targets,
  disabled = false,
  onChange,
}: AdvancedMetadataFilterProps) {
  const { t } = useTranslation();
  const enabled = Boolean(value.enabled);
  const match: AidpMetadataFilterMatch = value.match === "any" ? "any" : "all";
  const conditions =
    value.conditions.length > 0
      ? value.conditions
      : [{ operator: "contains" as AidpMetadataFilterOperator, value: "" }];

  const commit = (
    nextMatch: AidpMetadataFilterMatch,
    nextConditions: AidpFileNameCondition[]
  ) => {
    onChange({ enabled: true, match: nextMatch, conditions: nextConditions });
  };

  const updateCondition = (index: number, condition: AidpFileNameCondition) => {
    commit(
      match,
      conditions.map((item, itemIndex) =>
        itemIndex === index ? condition : item
      )
    );
  };

  const removeCondition = (index: number) => {
    commit(
      match,
      conditions.filter((_, itemIndex) => itemIndex !== index)
    );
  };

  const addCondition = () => {
    if (conditions.length >= MAX_CONDITIONS) return;
    commit(match, [...conditions, { operator: "contains", value: "" }]);
  };

  return (
    <div className="border-t border-border px-1 pb-1 pt-3">
      <div className="flex items-center gap-2">
        <span className="text-[14px] font-medium">
          {t("chat.knowledgeScope.advancedFilter", "高级筛选")}
        </span>
        <Tooltip
          title={t(
            "chat.knowledgeScope.advancedFilterHint",
            "按文件元数据限制进入检索的 chunk"
          )}
        >
          <Info
            className="size-3.5 text-muted-foreground"
            aria-label={t(
              "chat.knowledgeScope.advancedFilterHint",
              "按文件元数据限制进入检索的 chunk"
            )}
          />
        </Tooltip>
        <Switch
          size="small"
          checked={enabled}
          disabled={disabled}
          onChange={(checked) =>
            onChange({
              enabled: checked,
              match,
              conditions: checked ? conditions : value.conditions,
            })
          }
        />
        {!enabled ? (
          <span className="ml-auto text-xs text-muted-foreground">
            {t(
              "chat.knowledgeScope.advancedFilterOffHint",
              "开启开关进行高级筛选设置"
            )}
          </span>
        ) : null}
      </div>
      {enabled ? (
        <div className="mt-2 space-y-2">
          <p className="text-xs text-muted-foreground">
            {t(
              "chat.knowledgeScope.advancedFilterOnHint",
              "设定高级筛选后，满足筛选规则的 chunk 才会被检索"
            )}
          </p>
          <div className="space-y-2">
            {conditions.map((condition, index) => (
              <FileConditionRow
                key={`condition-${index}`}
                condition={condition}
                targets={targets}
                disabled={disabled}
                canRemove={conditions.length > 1}
                onChange={(next) => updateCondition(index, next)}
                onRemove={() => removeCondition(index)}
              />
            ))}
          </div>
          <Button
            type="link"
            style={{
              alignSelf: "flex-start",
              height: 24,
              padding: 0,
              fontSize: 13,
            }}
            icon={<PlusOutlined />}
            disabled={disabled || conditions.length >= MAX_CONDITIONS}
            onClick={addCondition}
          >
            {t("chat.knowledgeScope.filterAddCondition", "添加文件")} (
            {conditions.length}/{MAX_CONDITIONS})
          </Button>
          <div className="flex items-center gap-3 pt-1">
            <span className="text-[13px]">
              {t("chat.knowledgeScope.filterMatchLabel", "条件组合方式")}
            </span>
            <Radio.Group
              value={match}
              disabled={disabled}
              onChange={(event) =>
                commit(
                  event.target.value as AidpMetadataFilterMatch,
                  conditions
                )
              }
              className="flex flex-wrap gap-4 text-sm leading-[22px] text-[#191919]"
            >
              <Radio value="all">
                {t("chat.knowledgeScope.filterMatchAll", "满足全部")}
              </Radio>
              <Radio value="any">
                {t("chat.knowledgeScope.filterMatchAny", "满足其一")}
              </Radio>
            </Radio.Group>
          </div>
        </div>
      ) : null}
    </div>
  );
}
