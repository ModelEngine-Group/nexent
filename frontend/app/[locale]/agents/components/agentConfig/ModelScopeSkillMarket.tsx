"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Button,
  Col,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Skeleton,
  Tag,
  message,
} from "antd";
import {
  ChevronLeft,
  ChevronRight,
  Clock3,
  Download,
  Search,
  Tag as TagIcon,
  UserRound,
} from "lucide-react";

import log from "@/lib/logger";
import { shouldShowModelScopeUpdate } from "@/lib/modelscopeSkillUpdate";
import { ApiError } from "@/services/api";
import {
  fetchModelScopeSkillDetail,
  fetchModelScopeSkills,
  installModelScopeSkill,
  parseInstalledMarketSkill,
  updateModelScopeSkill,
} from "@/services/modelscopeSkillService";
import type {
  InstalledMarketSkill,
  ModelScopeMarketListResponse,
  ModelScopeMarketSkill,
  ModelScopeSkillInstallPayload,
} from "@/types/skill";

const PAGE_SIZE = 12;
const MODELSCOPE_MAX_RESULT_WINDOW = 2_400;
const MAX_BROWSE_PAGES = Math.floor(MODELSCOPE_MAX_RESULT_WINDOW / PAGE_SIZE);

type PaginationItem = number | "start-ellipsis" | "end-ellipsis";

const CATEGORY_COLORS = [
  { background: "#eff6ff", color: "#2563eb" },
  { background: "#fdf2f8", color: "#db2777" },
  { background: "#f0fdf4", color: "#16a34a" },
  { background: "#fff7ed", color: "#ea580c" },
  { background: "#ecfeff", color: "#0891b2" },
  { background: "#f7fee7", color: "#65a30d" },
  { background: "#faf5ff", color: "#9333ea" },
  { background: "#fffbeb", color: "#d97706" },
  { background: "#fff1f2", color: "#e11d48" },
  { background: "#eef2ff", color: "#4f46e5" },
];

interface ModelScopeSkillMarketProps {
  groupSelectOptions: Array<{ label: string; value: number }>;
  defaultGroupIds: number[];
  onInstalled: () => void | Promise<void>;
  onOpenInstalledSkill: (skill: InstalledMarketSkill) => void;
}

function getAuthor(skill: ModelScopeMarketSkill) {
  return String(skill.skill_id).split("/")[0]?.replace(/^@/, "") || "ModelScope";
}

function formatCategoryLabel(category: string | undefined) {
  return category?.replaceAll("-", " ").trim() || "";
}

function getCategoryStyle(category: string) {
  const index = Array.from(category).reduce(
    (sum, character) => sum + character.charCodeAt(0),
    0
  );
  return CATEGORY_COLORS[index % CATEGORY_COLORS.length];
}

function mergeMarketSkillDetail(
  marketSkill: ModelScopeMarketSkill,
  localRecord: InstalledMarketSkill | Record<string, never>
): ModelScopeMarketSkill {
  if (Object.keys(localRecord).length === 0) {
    return marketSkill;
  }
  const localName =
    "name" in localRecord && typeof localRecord.name === "string"
      ? localRecord.name.trim()
      : "";
  const localDescription =
    "description" in localRecord && typeof localRecord.description === "string"
      ? localRecord.description
      : undefined;
  return {
    ...marketSkill,
    name: localName || marketSkill.name,
    description:
      localDescription === undefined
        ? marketSkill.description
        : localDescription,
  };
}

function formatDownloads(downloads: number): string {
  const count = Number.isFinite(downloads) ? downloads : 0;
  if (count < 1000) {
    return String(Math.trunc(count));
  }
  return `${(count / 1000).toFixed(1)}k`;
}

function shouldShowUpdateButton(
  marketSkill: ModelScopeMarketSkill | null,
  localSkill: InstalledMarketSkill | null
): boolean {
  if (!marketSkill || !localSkill) return false;
  if (localSkill.upstream_last_modified !== undefined) {
    return shouldShowModelScopeUpdate(
      localSkill.version_update_time,
      localSkill.upstream_last_modified
    );
  }
  return shouldShowModelScopeUpdate(
    localSkill.version_update_time,
    marketSkill.last_modified
  );
}

function getPaginationItems(
  currentPage: number,
  totalPages: number
): PaginationItem[] {
  if (totalPages <= 7) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }
  if (currentPage <= 4) {
    return [1, 2, 3, 4, 5, "end-ellipsis", totalPages];
  }
  if (currentPage >= totalPages - 3) {
    return [
      1,
      "start-ellipsis",
      totalPages - 4,
      totalPages - 3,
      totalPages - 2,
      totalPages - 1,
      totalPages,
    ];
  }
  return [
    1,
    "start-ellipsis",
    currentPage - 1,
    currentPage,
    currentPage + 1,
    "end-ellipsis",
    totalPages,
  ];
}

export default function ModelScopeSkillMarket({
  groupSelectOptions,
  defaultGroupIds,
  onInstalled,
  onOpenInstalledSkill,
}: ModelScopeSkillMarketProps) {
  const { t, i18n } = useTranslation("common");
  const [installForm] = Form.useForm<ModelScopeSkillInstallPayload>();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [retryToken, setRetryToken] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [data, setData] = useState<ModelScopeMarketListResponse | null>(null);
  const [detail, setDetail] = useState<ModelScopeMarketSkill | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [installedSkill, setInstalledSkill] =
    useState<InstalledMarketSkill | null>(null);
  const detailRequestId = useRef(0);
  const [installingSkill, setInstallingSkill] =
    useState<ModelScopeMarketSkill | null>(null);
  const [installing, setInstalling] = useState(false);
  const [updating, setUpdating] = useState(false);
  const showUpdateButton = shouldShowUpdateButton(detail, installedSkill);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(false);
    fetchModelScopeSkills({ search, pageNumber: page, pageSize: PAGE_SIZE })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((requestError) => {
        log.error("Failed to load ModelScope Skills", requestError);
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [page, retryToken, search]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setPage(1);
      setSearch(searchInput.trim());
    }, 400);
    return () => window.clearTimeout(timer);
  }, [searchInput]);

  const submitSearch = () => {
    setPage(1);
    setSearch(searchInput.trim());
  };

  const openDetail = async (skill: ModelScopeMarketSkill) => {
    const requestId = ++detailRequestId.current;
    setDetail(skill);
    setInstalledSkill(null);
    setDetailLoading(true);
    try {
      const result = await fetchModelScopeSkillDetail(skill.skill_id);
      if (requestId === detailRequestId.current) {
        setDetail(mergeMarketSkillDetail(skill, result));
        setInstalledSkill(parseInstalledMarketSkill(result));
      }
    } catch (requestError) {
      if (requestId === detailRequestId.current) {
        log.error("Failed to load ModelScope Skill detail", requestError);
        message.error(t("skillManagement.market.detailFailed"));
      }
    } finally {
      if (requestId === detailRequestId.current) {
        setDetailLoading(false);
      }
    }
  };

  const closeDetail = () => {
    detailRequestId.current += 1;
    setDetail(null);
    setInstalledSkill(null);
    setDetailLoading(false);
  };

  const openInstall = (skill: ModelScopeMarketSkill) => {
    setInstallingSkill(skill);
    installForm.setFieldsValue({
      unique_id: skill.skill_id,
      name: skill.name,
      description: skill.description,
      tags: skill.tags ?? [],
      group_ids: defaultGroupIds,
      ingroup_permission: "READ_ONLY",
    });
  };

  const closeInstall = () => {
    setInstallingSkill(null);
    installForm.resetFields();
  };

  const submitInstall = async () => {
    if (!installingSkill) return;
    try {
      const values = await installForm.validateFields();
      setInstalling(true);
      await installModelScopeSkill({
        ...values,
        unique_id: installingSkill.skill_id,
      });
      message.success(t("skillManagement.market.installSuccess"));
      closeInstall();
      await onInstalled();
    } catch (requestError) {
      if (
        requestError &&
        typeof requestError === "object" &&
        "errorFields" in requestError
      ) {
        return;
      }
      if (
        requestError instanceof ApiError &&
        Number(requestError.code) === 409
      ) {
        installForm.setFields([
          { name: "name", errors: [t("skillManagement.message.nameExists")] },
        ]);
      } else {
        log.error("Failed to install ModelScope Skill", requestError);
        message.error(t("skillManagement.market.installFailed"));
      }
    } finally {
      setInstalling(false);
    }
  };

  const submitUpdate = async () => {
    if (!installedSkill || !detail) return;
    try {
      setUpdating(true);
      const result = await updateModelScopeSkill({
        skill_id: installedSkill.skill_id,
        unique_id: detail.skill_id,
      });
      const parsed = parseInstalledMarketSkill(result);
      if (parsed) {
        setInstalledSkill(parsed);
      }
      message.success(t("skillManagement.market.updateSuccess"));
      await onInstalled();
    } catch (requestError) {
      log.error("Failed to update ModelScope Skill", requestError);
      message.error(t("skillManagement.market.updateFailed"));
    } finally {
      setUpdating(false);
    }
  };

  const renderSkillCard = (skill: ModelScopeMarketSkill) => {
    const categoryLabel = formatCategoryLabel(skill.category);
    const visibleTags = (skill.tags ?? []).slice(0, 3);

    return (
      <button
        type="button"
        className="flex h-full min-h-[198px] w-full min-w-0 flex-1 flex-col overflow-hidden rounded-xl border border-slate-200 bg-white px-4 py-4 text-left transition hover:border-blue-300 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:border-slate-700 dark:bg-slate-900"
        onClick={() => void openDetail(skill)}
      >
        <div className="flex w-full min-w-0 items-start justify-between gap-3">
          <h3 className="min-w-0 flex-1 truncate text-base font-semibold text-slate-900 dark:text-slate-100">
            {skill.name}
          </h3>
          {categoryLabel ? (
            <span
              className="max-w-[50%] shrink-0 truncate rounded-full px-2.5 py-1 text-xs font-medium capitalize"
              style={getCategoryStyle(categoryLabel)}
              title={categoryLabel}
            >
              {categoryLabel}
            </span>
          ) : null}
        </div>
        <p className="mt-3 line-clamp-2 min-h-11 text-sm leading-6 text-slate-500 dark:text-slate-400">
          {skill.description || t("skillPool.noDescription")}
        </p>
        <div className="mt-3 flex min-h-7 flex-wrap gap-2">
          {visibleTags.map((tag) => (
            <Tag
              key={tag}
              variant="filled"
              className="m-0 bg-slate-100 text-slate-500"
            >
              <span className="inline-flex items-center gap-1">
                <TagIcon size={11} />
                {tag}
              </span>
            </Tag>
          ))}
        </div>
        <div className="mt-auto flex w-full items-center gap-5 border-t border-slate-100 pt-3 text-xs text-slate-400 dark:border-slate-800">
          <span className="inline-flex min-w-0 items-center gap-1.5 truncate">
            <UserRound size={13} />
            {getAuthor(skill)}
          </span>
          <span className="inline-flex shrink-0 items-center gap-1.5">
            <Download size={13} />
            {formatDownloads(skill.downloads)}
          </span>
        </div>
      </button>
    );
  };

  const detailCategory = formatCategoryLabel(detail?.category);
  const providerTotalPages = data ? Math.ceil(data.total_count / PAGE_SIZE) : 0;
  const accessibleTotalPages = Math.min(providerTotalPages, MAX_BROWSE_PAGES);
  const paginationItems = getPaginationItems(page, accessibleTotalPages);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden bg-white dark:bg-slate-950">
      <div className="shrink-0 border-b border-slate-200 pb-4 dark:border-slate-700">
        <Input
          allowClear
          size="large"
          value={searchInput}
          prefix={<Search size={17} className="text-slate-400" />}
          placeholder={t("skillManagement.market.searchPlaceholder")}
          onChange={(event) => setSearchInput(event.target.value)}
          onPressEnter={submitSearch}
          onClear={() => {
            setSearchInput("");
            setPage(1);
            setSearch("");
          }}
        />
      </div>

      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto py-4 pr-1">
        {loading ? (
          <Row gutter={[16, 16]}>
            {Array.from({ length: 9 }).map((_, index) => (
              <Col xs={24} md={12} xl={8} key={index} className="flex">
                <div className="h-[198px] w-full rounded-xl border border-slate-200 p-4 dark:border-slate-700">
                  <Skeleton active />
                </div>
              </Col>
            ))}
          </Row>
        ) : error ? (
          <div className="flex h-full items-center justify-center">
            <Empty description={t("skillManagement.market.unavailable")}>
              <Button onClick={() => setRetryToken((value) => value + 1)}>
                {t("skillManagement.market.retry")}
              </Button>
            </Empty>
          </div>
        ) : !data?.items.length ? (
          <div className="flex h-full items-center justify-center">
            <Empty description={t("skillManagement.market.empty")} />
          </div>
        ) : (
          <Row gutter={[16, 16]}>
            {data.items.map((skill) => (
              <Col xs={24} md={12} xl={8} key={skill.skill_id} className="flex">
                {renderSkillCard(skill)}
              </Col>
            ))}
          </Row>
        )}
      </div>

      {data && accessibleTotalPages > 1 ? (
        <div className="flex shrink-0 items-center justify-end gap-4 border-t border-slate-200 pt-4 dark:border-slate-700">
          <div className="flex items-center gap-2">
            <Button
              aria-label={t("skillManagement.market.previousPage")}
              icon={<ChevronLeft size={16} />}
              disabled={page === 1 || loading}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
            />
            {paginationItems.map((item) =>
              typeof item === "number" ? (
                <Button
                  key={item}
                  type={item === page ? "primary" : "default"}
                  aria-current={item === page ? "page" : undefined}
                  disabled={loading}
                  className="min-w-10"
                  onClick={() => setPage(item)}
                >
                  {item}
                </Button>
              ) : (
                <span
                  key={item}
                  className="inline-flex min-w-6 justify-center text-slate-400"
                >
                  …
                </span>
              )
            )}
            <Button
              aria-label={t("skillManagement.market.nextPage")}
              icon={<ChevronRight size={16} />}
              disabled={
                page >= accessibleTotalPages || !data.has_next || loading
              }
              onClick={() => setPage((value) => value + 1)}
            />
          </div>
        </div>
      ) : null}

      <Modal
        open={Boolean(detail)}
        width={720}
        title={
          detail ? (
            <div className="flex items-center gap-4 pr-10">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-xl bg-blue-50 text-xl font-medium text-blue-600">
                {detail.name.trim().charAt(0).toUpperCase() || "S"}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-lg font-semibold">
                    {detail.name}
                  </span>
                  {detailCategory ? (
                    <span
                      className="max-w-[50%] shrink-0 truncate rounded-full px-2.5 py-1 text-xs font-medium capitalize"
                      style={getCategoryStyle(detailCategory)}
                      title={detailCategory}
                    >
                      {detailCategory}
                    </span>
                  ) : null}
                </div>
                <div className="mt-1 text-sm font-normal text-slate-400">
                  {t("skillManagement.market.fromModelScope")}
                </div>
              </div>
            </div>
          ) : null
        }
        onCancel={closeDetail}
        footer={
          detail
            ? [
                <Button key="close" onClick={closeDetail}>
                  {t("common.close")}
                </Button>,
                installedSkill ? (
                  <Button
                    key="open"
                    type="primary"
                    loading={detailLoading}
                    onClick={() => {
                      onOpenInstalledSkill(installedSkill);
                    }}
                  >
                    {t("skillManagement.market.open")}
                  </Button>
                ) : (
                  <Button
                    key="install"
                    type="primary"
                    loading={detailLoading}
                    onClick={() => {
                      openInstall(detail);
                      closeDetail();
                    }}
                  >
                    {t("skillManagement.market.install")}
                  </Button>
                ),
              ]
            : null
        }
      >
        <Skeleton loading={detailLoading} active>
          {detail ? (
            <div className="pt-4">
              <div className="grid grid-cols-3 gap-5 border-b border-slate-100 pb-6 dark:border-slate-800">
                <div>
                  <div className="flex items-center gap-1.5 text-sm text-slate-400">
                    <UserRound size={16} />
                    {t("agent.author")}
                  </div>
                  <div className="mt-2 font-medium text-slate-800 dark:text-slate-100">
                    {getAuthor(detail)}
                  </div>
                </div>
                <div>
                  <div className="flex items-center gap-1.5 text-sm text-slate-400">
                    <Download size={16} />
                    {t("skillManagement.market.downloads")}
                  </div>
                  <div className="mt-2 font-medium text-slate-800 dark:text-slate-100">
                    {formatDownloads(detail.downloads)}
                  </div>
                </div>
                <div>
                  <div className="flex items-center gap-1.5 text-sm text-slate-400">
                    <Clock3 size={16} />
                    {t("skillManagement.market.lastModified")}
                  </div>
                  <div className="mt-2 flex items-center gap-2 font-medium text-slate-800 dark:text-slate-100">
                    <span>
                      {detail.last_modified
                        ? new Date(detail.last_modified).toLocaleDateString(
                            i18n.language
                          )
                        : "-"}
                    </span>
                    {showUpdateButton ? (
                      <Button
                        size="small"
                        type="primary"
                        loading={updating}
                        onClick={() => void submitUpdate()}
                      >
                        {t("skillManagement.market.update")}
                      </Button>
                    ) : null}
                  </div>
                </div>
              </div>
              <div className="pt-5">
                <h4 className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">
                  {t("skillManagement.market.introduction")}
                </h4>
                <p className="text-sm leading-7 text-slate-700 dark:text-slate-300">
                  {detail.description || t("skillPool.noDescription")}
                </p>
              </div>
              <div className="pt-5">
                <h4 className="mb-2 text-sm font-medium text-slate-600 dark:text-slate-300">
                  {t("skillManagement.form.tags")}
                </h4>
                <div className="flex flex-wrap gap-2">
                  {(detail.tags ?? []).map((tag) => (
                    <Tag
                      key={tag}
                      variant="filled"
                      className="m-0 bg-slate-100 text-slate-500"
                    >
                      <span className="inline-flex items-center gap-1">
                        <TagIcon size={11} />
                        {tag}
                      </span>
                    </Tag>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </Skeleton>
      </Modal>

      <Modal
        open={Boolean(installingSkill)}
        width={760}
        title={
          <div>
            <div className="text-lg font-semibold">
              {t("skillManagement.market.installTitle")}
            </div>
            {installingSkill ? (
              <div className="mt-1 text-sm font-normal text-slate-400">
                {t("skillManagement.market.installSource", {
                  name: installingSkill.name,
                })}
              </div>
            ) : null}
          </div>
        }
        okText={t("skillManagement.market.confirmInstall")}
        cancelText={t("common.cancel")}
        confirmLoading={installing}
        onOk={() => void submitInstall()}
        onCancel={closeInstall}
        forceRender
      >
        <Form
          form={installForm}
          layout="vertical"
          preserve={false}
          className="pt-4"
        >
          <Form.Item name="unique_id" hidden>
            <Input />
          </Form.Item>
          <Form.Item
            name="name"
            label={t("skillManagement.form.name")}
            rules={[
              {
                required: true,
                whitespace: true,
                message: t("skillManagement.form.nameRequired"),
              },
            ]}
          >
            <Input size="large" maxLength={100} />
          </Form.Item>
          <Form.Item
            name="description"
            label={t("skillManagement.form.description")}
            rules={[
              {
                required: true,
                whitespace: true,
                message: t("skillManagement.form.descriptionRequired"),
              },
            ]}
          >
            <Input.TextArea rows={4} maxLength={1000} />
          </Form.Item>
          <Form.Item name="tags" label={t("skillManagement.form.tags")}>
            <Select
              mode="tags"
              maxCount={20}
              size="large"
              placeholder={t("skillManagement.form.tagsPlaceholder")}
            />
          </Form.Item>
          <Row gutter={24}>
            <Col span={12}>
              <Form.Item
                name="group_ids"
                label={t("skillManagement.market.visibleGroups")}
                rules={[
                  {
                    required: true,
                    type: "array",
                    min: 1,
                    message: t("tenantResources.groups.required"),
                  },
                ]}
              >
                <Select
                  mode="multiple"
                  allowClear
                  size="large"
                  options={groupSelectOptions}
                  placeholder={t("agent.userGroup.empty")}
                />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name="ingroup_permission"
                label={t("tenantResources.knowledgeBase.permission")}
              >
                <Select
                  size="large"
                  options={["EDIT", "READ_ONLY", "PRIVATE"].map((value) => ({
                    value,
                    label: t(
                      `tenantResources.knowledgeBase.permission.${value}`
                    ),
                  }))}
                />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}
