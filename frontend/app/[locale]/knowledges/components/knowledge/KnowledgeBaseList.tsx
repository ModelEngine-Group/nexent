import React, { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";

import log from "@/lib/logger";

import { Button, Input, Select } from "antd";
import {
  SyncOutlined,
  PlusOutlined,
  SettingOutlined,
  SearchOutlined,
  FilterOutlined,
} from "@ant-design/icons";
import {
  PencilRuler,
  Eye,
  Glasses,
  Trash2,
  SquarePen,
  CircleOff,
} from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import { Can } from "@/components/permission/Can";
import { useAuthorizationContext } from "@/components/providers/AuthorizationProvider";
import { useGroupList } from "@/hooks/group/useGroupList";
import { KnowledgeBaseEditModal } from "./KnowledgeBaseEditModal";

import { KnowledgeBase } from "@/types/knowledgeBase";
import { KB_LAYOUT, KB_TAG_VARIANTS } from "@/const/knowledgeBaseLayout";

interface KnowledgeBaseListProps {
  knowledgeBases: KnowledgeBase[];
  activeKnowledgeBase: KnowledgeBase | null;
  currentEmbeddingModel: string | null;
  isLoading?: boolean;
  syncLoading?: boolean;
  onClick: (kb: KnowledgeBase) => void;
  onDelete: (id: string) => void;
  onSync: () => void;
  onCreateNew: () => void;
  onDataMateConfig?: () => void;
  showDataMateConfig?: boolean; // Control whether to show DataMate config button
  getModelDisplayName: (modelId: string) => string;
  containerHeight?: string; // Container total height, consistent with DocumentList
  onKnowledgeBaseChange?: () => void; // New: callback function when knowledge base switches
  // Optional controlled search / filter props (if parent wants to control filters)
  searchQuery?: string;
  onSearchChange?: (value: string) => void;
  sourceFilter?: string | string[];
  onSourceFilterChange?: (values: string[] | string) => void;
  modelFilter?: string | string[];
  onModelFilterChange?: (values: string[] | string) => void;
}

const KnowledgeBaseList: React.FC<KnowledgeBaseListProps> = ({
  knowledgeBases,
  activeKnowledgeBase,
  currentEmbeddingModel,
  isLoading = false,
  syncLoading = false,
  onClick,
  onDelete,
  onSync,
  onCreateNew,
  onDataMateConfig,
  showDataMateConfig = false,
  getModelDisplayName,
  containerHeight = "70vh", // Default container height consistent with DocumentList
  onKnowledgeBaseChange, // New: callback function when knowledge base switches
  searchQuery,
  onSearchChange,
  sourceFilter,
  onSourceFilterChange,
  modelFilter,
  onModelFilterChange,
}) => {
  const { t } = useTranslation();

  // Get user info for tenant ID
  const { user } = useAuthorizationContext();
  const tenantId = user?.tenantId || null;

  // Fetch groups for group name mapping
  const { data: groupData } = useGroupList(tenantId, 1, 100);
  const groups = groupData?.groups || [];

  // Create group name mapping from group_id to group_name
  const groupNameMap = useMemo(() => {
    const map = new Map<number, string>();
    groups.forEach((group) => {
      map.set(group.group_id, group.group_name);
    });
    return map;
  }, [groups]);

  // Get group names for knowledge base
  const getGroupNames = (groupIds?: number[]) => {
    if (!groupIds || groupIds.length === 0) return [];
    return groupIds
      .map((id) => groupNameMap.get(id))
      .filter((name): name is string => !!name);
  };

  // Get permission icon based on ingroup_permission type
  const getPermissionIcon = (permission: string) => {
    const iconProps = {
      size: 14,
      className: "text-gray-500",
    };

    switch (permission) {
      case "EDIT":
        return <PencilRuler {...iconProps} />;
      case "READ_ONLY":
        return <Eye {...iconProps} />;
      case "PRIVATE":
        return <Glasses {...iconProps} />;
      default:
        return <CircleOff {...iconProps} />;
    }
  };

  // Get permission tooltip key
  const getPermissionTooltipKey = (permission: string) => {
    return `knowledgeBase.ingroup.permission.${permission || "DEFAULT"}`;
  };

  // Search and filter states
  const [searchKeyword, setSearchKeyword] = useState("");
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);

  // Edit modal states
  const [editModalVisible, setEditModalVisible] = useState(false);
  const [editingKnowledge, setEditingKnowledge] =
    useState<KnowledgeBase | null>(null);

  // Open edit modal
  const openEditModal = (kb: KnowledgeBase) => {
    setEditingKnowledge(kb);
    setEditModalVisible(true);
  };

  // Close edit modal
  const closeEditModal = () => {
    setEditModalVisible(false);
    setEditingKnowledge(null);
  };

  // Effective (controlled or uncontrolled) values
  const effectiveSearchKeyword =
    typeof searchQuery !== "undefined" ? searchQuery : searchKeyword;
  const effectiveSelectedSources =
    typeof sourceFilter !== "undefined"
      ? Array.isArray(sourceFilter)
        ? sourceFilter
        : sourceFilter
          ? [sourceFilter]
          : []
      : selectedSources;
  const effectiveSelectedModels =
    typeof modelFilter !== "undefined"
      ? Array.isArray(modelFilter)
        ? modelFilter
        : modelFilter
          ? [modelFilter]
          : []
      : selectedModels;

  // Handlers that respect controlled props
  const handleSearchChange = (value: string) => {
    if (onSearchChange) onSearchChange(value);
    else setSearchKeyword(value);
  };

  const handleSourcesChange = (values: string[]) => {
    if (onSourceFilterChange) onSourceFilterChange(values);
    else setSelectedSources(values);
  };

  const handleModelsChange = (values: string[]) => {
    if (onModelFilterChange) onModelFilterChange(values);
    else setSelectedModels(values);
  };

  // Format date function, only keep date part
  const formatDate = (dateValue: any) => {
    try {
      const date =
        typeof dateValue === "number"
          ? new Date(dateValue)
          : new Date(dateValue);
      return isNaN(date.getTime())
        ? String(dateValue ?? "")
        : date.toISOString().split("T")[0]; // Only return YYYY-MM-DD part
    } catch (e) {
      return String(dateValue ?? ""); // If parsing fails, return original string
    }
  };

  // Helper to safely extract timestamp for sorting
  const getTimestamp = (value: any): number => {
    if (!value) return 0;
    if (typeof value === "number") return value;
    const t = Date.parse(value);
    return Number.isNaN(t) ? 0 : t;
  };

  // Sort knowledge bases by update time (fallback to creation time), latest first
  const sortedKnowledgeBases = [...knowledgeBases].sort((a, b) => {
    const aTime = getTimestamp(a.updatedAt ?? a.createdAt);
    const bTime = getTimestamp(b.updatedAt ?? b.createdAt);
    return bTime - aTime;
  });

  // Calculate available filter options
  const availableSources = useMemo(() => {
    const sources = new Set(knowledgeBases.map((kb) => kb.source));
    return Array.from(sources)
      .filter((source) => source)
      .sort();
  }, [knowledgeBases]);

  const availableModels = useMemo(() => {
    const models = new Set(knowledgeBases.map((kb) => kb.embeddingModel));
    return Array.from(models)
      .filter((model) => model && model !== "unknown")
      .sort();
  }, [knowledgeBases]);

  // Filter knowledge bases based on search and filters
  const filteredKnowledgeBases = useMemo(() => {
    log.log("Filtering knowledge bases:", {
      totalCount: knowledgeBases.length,
      searchKeyword: effectiveSearchKeyword,
      sourceFilter: effectiveSelectedSources,
      modelFilter: effectiveSelectedModels,
    });

    const result = sortedKnowledgeBases.filter((kb) => {
      // Keyword search: match name, description, or nickname
      const keyword = effectiveSearchKeyword || "";
      const kbName = kb.name || "";
      const kbDescription = kb.description || "";
      const kbNickname = kb.nickname || "";

      const matchesSearch =
        !keyword ||
        kbName.toLowerCase().includes(keyword.toLowerCase()) ||
        kbDescription.toLowerCase().includes(keyword.toLowerCase()) ||
        kbNickname.toLowerCase().includes(keyword.toLowerCase());

      // Source filter
      const matchesSource =
        effectiveSelectedSources.length === 0 ||
        effectiveSelectedSources.includes(kb.source);

      // Model filter
      const matchesModel =
        effectiveSelectedModels.length === 0 ||
        effectiveSelectedModels.includes(kb.embeddingModel);

      const matches = matchesSearch && matchesSource && matchesModel;

      if (!matches) {
        log.log("KB filtered out:", {
          name: kb.name,
          source: kb.source,
          embeddingModel: kb.embeddingModel,
          matchesSearch,
          matchesSource,
          matchesModel,
        });
      }

      return matches;
    });

    log.log("Filtered result:", result.length, "items");
    return result;
  }, [
    sortedKnowledgeBases,
    effectiveSearchKeyword,
    effectiveSelectedSources,
    effectiveSelectedModels,
  ]);

  return (
    <div className="w-full h-full bg-white border border-gray-200 rounded-md flex flex-col">
      {/* Fixed header area */}
      <div
        className={`${KB_LAYOUT.HEADER_PADDING} border-b border-gray-200 shrink-0`}
      >
        <div className="flex items-center justify-between">
          <div>
            <h3
              className={`${KB_LAYOUT.TITLE_MARGIN} ${KB_LAYOUT.TITLE_TEXT} text-gray-800`}
            >
              {t("knowledgeBase.list.title")}
            </h3>
          </div>
          <div className="flex items-center" style={{ gap: "6px" }}>
            <Button
              style={{
                padding: "4px 15px",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
                backgroundColor: "#1677ff",
                color: "white",
                border: "none",
              }}
              className="hover:!bg-blue-600"
              type="primary"
              onClick={onCreateNew}
              icon={<PlusOutlined />}
            >
              {t("knowledgeBase.button.create")}
            </Button>
            <Button
              style={{
                padding: "4px 15px",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "8px",
                backgroundColor: "#1677ff",
                color: "white",
                border: "none",
              }}
              className="hover:!bg-blue-600"
              type="primary"
              onClick={onSync}
            >
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  width: "14px",
                  height: "14px",
                }}
              >
                <SyncOutlined spin={syncLoading} style={{ color: "white" }} />
              </span>
              <span>{t("knowledgeBase.button.sync")}</span>
            </Button>
            {showDataMateConfig && (
              <Button
                style={{
                  padding: "4px 15px",
                  display: "inline-flex",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: "8px",
                  backgroundColor: "#1677ff",
                  color: "white",
                  border: "none",
                }}
                className="hover:!bg-blue-600"
                type="primary"
                onClick={onDataMateConfig}
                icon={<SettingOutlined />}
              >
                {t("knowledgeBase.button.dataMateConfig")}
              </Button>
            )}
          </div>
        </div>

        {/* Search and filter area */}
        <div className="mt-3 flex items-center gap-3">
          <Input
            placeholder={t("knowledgeBase.search.placeholder")}
            prefix={<SearchOutlined />}
            value={effectiveSearchKeyword}
            onChange={(e) => handleSearchChange(e.target.value)}
            style={{ width: 250 }}
            allowClear
          />

          {availableSources.length > 0 && (
            <Select
              mode="multiple"
              placeholder={t("knowledgeBase.filter.source.placeholder")}
              value={effectiveSelectedSources}
              onChange={handleSourcesChange}
              style={{ minWidth: 150 }}
              allowClear
              maxTagCount={2}
            >
              {availableSources.map((source) => (
                <Select.Option key={source} value={source}>
                  {t("knowledgeBase.source." + source, {
                    defaultValue: source,
                  })}
                </Select.Option>
              ))}
            </Select>
          )}

          {availableModels.length > 0 && (
            <Select
              mode="multiple"
              placeholder={t("knowledgeBase.filter.model.placeholder")}
              value={effectiveSelectedModels}
              onChange={handleModelsChange}
              style={{ minWidth: 180 }}
              allowClear
              maxTagCount={2}
            >
              {availableModels.map((model) => (
                <Select.Option key={model} value={model}>
                  {getModelDisplayName(model)}
                </Select.Option>
              ))}
            </Select>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden">
        {filteredKnowledgeBases.length > 0 ? (
          <div className="divide-y-0">
            {filteredKnowledgeBases.map((kb, index) => {
              const isActive = activeKnowledgeBase?.id === kb.id;

              return (
                <div
                  key={kb.id}
                  className={`${
                    KB_LAYOUT.ROW_PADDING
                  } px-2 hover:bg-gray-50 cursor-pointer transition-colors ${
                    index > 0 ? "border-t border-gray-200" : ""
                  }`}
                  style={{
                    borderLeftWidth: "4px",
                    borderLeftStyle: "solid",
                    borderLeftColor: isActive ? "#3b82f6" : "transparent",
                    backgroundColor: isActive
                      ? "rgb(226, 240, 253)"
                      : "inherit",
                  }}
                  onClick={() => {
                    onClick(kb);
                    if (onKnowledgeBaseChange) onKnowledgeBaseChange();
                  }}
                >
                  <div className="flex items-start">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center flex-1 min-w-0">
                          <p
                            className="text-base font-medium text-gray-800 truncate"
                            style={{
                              maxWidth: KB_LAYOUT.KB_NAME_MAX_WIDTH,
                              ...KB_LAYOUT.KB_NAME_OVERFLOW,
                            }}
                            title={kb.name}
                          >
                            {kb.name}
                          </p>
                          {/* Permission icon with tooltip */}
                          <Can permission="kb.groups:read">
                            <Tooltip
                              title={t(getPermissionTooltipKey(kb.ingroup_permission || ""))}
                              placement="top"
                            >
                              <div className="ml-3 flex-shrink-0 cursor-pointer">
                                <div className="flex items-center justify-center w-5 h-5 rounded-full bg-gray-200 hover:bg-gray-300 transition-all duration-200 hover:shadow-sm">
                                  {getPermissionIcon(kb.ingroup_permission || "")}
                                </div>
                              </div>
                            </Tooltip>
                          </Can>
                        </div>
                          <div className="flex items-center ml-2">
                          <Can permission="kb:update">
                            {/* Edit button - only show for Nexent (local) sources */}
                            {(!kb.source || kb.source === "nexent" || kb.source === "elasticsearch") && (
                              <Tooltip title={t("common.edit")}>
                                <Button
                                  type="text"
                                  icon={<SquarePen className="h-4 w-4" />}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    openEditModal(kb);
                                  }}
                                  size="small"
                                />
                              </Tooltip>
                            )}
                            </Can>
                          <Can permission="kb:delete">
                              {/* Delete button */}
                              <Tooltip title={t("common.delete")}>
                                <Button
                                  type="text"
                                  danger
                                  icon={<Trash2 className="h-4 w-4" />}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    onDelete(kb.id);
                                  }}
                                  size="small"
                                />
                              </Tooltip>
                            </Can>
                          </div>

                      </div>
                      <div
                        className={`flex flex-wrap items-center ${KB_LAYOUT.TAG_MARGIN} ${KB_LAYOUT.TAG_SPACING}`}
                      >
                        {/* Document count tag */}
                        <span
                          className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.light} mr-1`}
                        >
                          {t("knowledgeBase.tag.documents", {
                            count: kb.documentCount || 0,
                          })}
                        </span>

                        {/* Chunk count tag */}
                        <span
                          className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.light} mr-1`}
                        >
                          {t("knowledgeBase.tag.chunks", {
                            count: kb.chunkCount || 0,
                          })}
                        </span>

                        {/* Always show source tag regardless of document/chunk count */}
                        <span
                          className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.light} mr-1`}
                        >
                          {t("knowledgeBase.tag.source", {
                            source: kb.source,
                          })}
                        </span>

                        {/* Only show creation date, model tags when there are valid documents or chunks */}
                        {((kb.documentCount || 0) > 0 ||
                          (kb.chunkCount || 0) > 0) && (
                          <>
                            {/* Creation date tag - only show date */}
                            <span
                              className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_TAG_VARIANTS.light} mr-1`}
                            >
                              {t("knowledgeBase.tag.createdAt", {
                                date: formatDate(kb.createdAt),
                              })}
                            </span>

                            {/* Force line break */}
                            <div
                              className={`w-full ${KB_LAYOUT.TAG_BREAK_HEIGHT}`}
                            ></div>

                            {/* Model tag - only show when model is not "unknown" */}
                            {kb.embeddingModel !== "unknown" && (
                              <span
                                className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_LAYOUT.SECOND_ROW_TAG_MARGIN} ${KB_TAG_VARIANTS.model} mr-1`}
                              >
                                {t("knowledgeBase.tag.model", {
                                  model: getModelDisplayName(kb.embeddingModel),
                                })}
                              </span>
                            )}
                            {kb.embeddingModel !== "unknown" &&
                              kb.embeddingModel !== currentEmbeddingModel &&
                              kb.source !== "datamate" && (
                                <span
                                  className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_LAYOUT.SECOND_ROW_TAG_MARGIN} ${KB_TAG_VARIANTS.warning} mr-1`}
                                >
                                  {t("knowledgeBase.tag.modelMismatch")}
                                </span>
                              )}

                            {/* User group tags */}
                            <Can permission="group:read">
                              {getGroupNames(kb.group_ids).map((groupName, idx) => (
                                <span
                                  key={idx}
                                  className={`inline-flex items-center ${KB_LAYOUT.TAG_PADDING} ${KB_LAYOUT.TAG_ROUNDED} ${KB_LAYOUT.TAG_TEXT} ${KB_LAYOUT.SECOND_ROW_TAG_MARGIN} bg-blue-100 text-blue-800 border border-blue-200 mr-1`}
                                >
                                  {groupName}
                                </span>
                              ))}
                            </Can>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div
            className={`${KB_LAYOUT.EMPTY_STATE_PADDING} text-center text-gray-500`}
          >
            {searchKeyword ||
            selectedSources.length > 0 ||
            selectedModels.length > 0
              ? t("knowledgeBase.list.noResults")
              : t("knowledgeBase.list.empty")}
          </div>
        )}
      </div>

      {/* Edit Knowledge Base Modal */}
      <KnowledgeBaseEditModal
        open={editModalVisible}
        knowledgeBase={editingKnowledge}
        tenantId={tenantId}
        onCancel={closeEditModal}
        onSuccess={() => {}}
      />
    </div>
  );
};

export default KnowledgeBaseList;
