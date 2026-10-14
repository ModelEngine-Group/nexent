"use client";
import { useRouter } from "next/navigation";

import { ResourceSelectionActions } from "@/features/workbench/components/ResourceSelectionActions";

import { SelectedResourceTags } from "@/features/workbench/components/SelectedResourceTags";

import {
  ResourceSelectionGrid,
  RESOURCE_SELECTION_AREA_CLASS,
} from "@/features/workbench/components/ResourceSelectionGrid";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Button,
  Empty,
  Input,
  Modal,
  Select,
  Spin,
  Switch,
  Tabs,
  message,
} from "antd";
import {
  fetchSkillRepositoryListings,
  installSkillFromRepository,
} from "@/services/skillRepositoryService";
import type { SkillRepositoryListingItem } from "@/types/skillRepository";
import { fetchSkillsList, type SkillListItem } from "@/services/skillService";
import type { WorkbenchSkillMount } from "../types";
import { ResourceCard } from "./ResourceCard";
import {
  ResourcePagination,
  RESOURCE_PAGE_SIZE,
  resourcePage,
} from "./ResourcePagination";
import { validateSkillConfig } from "../skillConfig";
import { RestoreDefaultsButton } from "./RestoreDefaultsButton";

function missingRequiredConfig(
  skill: SkillListItem,
  overrides: Record<string, unknown> = {}
): boolean {
  return (
    validateSkillConfig(skill.config_schemas || [], {
      ...skill.config_values,
      ...overrides,
    }).length > 0
  );
}

export function SkillPicker({
  open,
  selected,
  onCancel,
  onConfirm,
  loadDefaults,
}: {
  open: boolean;
  selected: WorkbenchSkillMount[];
  onCancel: () => void;
  loadDefaults?: () => Promise<WorkbenchSkillMount[]>;
  onConfirm: (
    mounts: WorkbenchSkillMount[],
    skills: SkillListItem[]
  ) => Promise<void> | void;
}) {
  const router = useRouter();
  const [skills, setSkills] = useState<SkillListItem[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const restoreOperationRef = useRef(0);
  const [tab, setTab] = useState("mine");
  const [repository, setRepository] = useState<SkillRepositoryListingItem[]>(
    []
  );
  const [repositoryPage, setRepositoryPage] = useState(1);
  const [repositoryTotal, setRepositoryTotal] = useState(0);
  const [minePage, setMinePage] = useState(1);
  const [installing, setInstalling] = useState<number | null>(null);
  const [conflict, setConflict] = useState<SkillRepositoryListingItem | null>(
    null
  );
  const [targetName, setTargetName] = useState("");
  const [configs, setConfigs] = useState<
    Record<number, Record<string, unknown>>
  >({});
  const [editingId, setEditingId] = useState<number | null>(null);
  const [configQueue, setConfigQueue] = useState<number[]>([]);
  const [draftConfigs, setDraftConfigs] = useState<
    Record<number, Record<string, unknown>>
  >({});
  const installOperationRef = useRef(0);
  useEffect(() => {
    setMinePage(1);
    setRepositoryPage(1);
  }, [open, search, tab]);

  useEffect(() => {
    if (!open) {
      restoreOperationRef.current += 1;
      setRestoring(false);
      setEditingId(null);
      setConfigQueue([]);
      installOperationRef.current += 1;
      setInstalling(null);
      setConflict(null);
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setListError(false);
    setSelectedIds(new Set(selected.map((mount) => mount.skill_id)));
    setConfigs(
      Object.fromEntries(
        selected.map((mount) => [mount.skill_id, { ...mount.config_values }])
      )
    );
    setLoading(true);
    void fetchSkillsList()
      .then((items) => {
        if (!cancelled) setSkills(items);
      })
      .catch((error) => {
        if (!cancelled) {
          setListError(true);
          message.error(
            error instanceof Error ? error.message : "Skill 加载失败"
          );
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, selected]);

  useEffect(() => {
    if (!open || tab !== "repository") return;
    let cancelled = false;
    setLoading(true);
    void fetchSkillRepositoryListings({
      search,
      page: repositoryPage,
      page_size: RESOURCE_PAGE_SIZE,
      status: "shared",
    })
      .then((result) => {
        if (!cancelled) {
          setRepository(result.items);
          setRepositoryTotal(result.pagination?.total ?? result.items.length);
        }
      })
      .catch((error) => {
        if (!cancelled) message.error(error.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, tab, search, repositoryPage]);

  const install = async (item: SkillRepositoryListingItem, name?: string) => {
    const operation = ++installOperationRef.current;
    setInstalling(item.skill_repository_id);
    try {
      const result = await installSkillFromRepository(
        item.skill_repository_id,
        name ? { target_name: name } : undefined
      );
      if (operation !== installOperationRef.current) return;
      if (!result.skill_id)
        throw new Error("安装响应缺少 Skill ID，请刷新后检查安装结果");
      const items = await fetchSkillsList();
      if (operation !== installOperationRef.current) return;
      setSkills(items);
      setSelectedIds(
        (current) => new Set([...current, Number(result.skill_id)])
      );
      setConflict(null);
      setTab("mine");
    } catch (error) {
      if (operation !== installOperationRef.current) return;
      if ((error as { status?: number }).status === 409) {
        setConflict(item);
        setTargetName(`${item.name}-copy`);
      } else message.error(error instanceof Error ? error.message : "安装失败");
    } finally {
      if (operation === installOperationRef.current) setInstalling(null);
    }
  };

  const filtered = useMemo(() => {
    const value = search.trim().toLowerCase();
    if (!value) return skills;
    return skills.filter((skill) =>
      [skill.name, skill.description]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(value))
    );
  }, [search, skills]);

  const allSelected =
    filtered.length > 0 &&
    filtered.every((skill) => selectedIds.has(Number(skill.skill_id)));
  const toggleAll = () => {
    const next = new Set(selectedIds);
    filtered.forEach((skill) => {
      const id = Number(skill.skill_id);
      if (allSelected) next.delete(id);
      else next.add(id);
    });
    if (next.size > 20) {
      message.warning("最多选择 20 个 Skills，请缩小搜索范围后重试");
      return;
    }
    if (!allSelected) {
      const queue = filtered
        .filter(
          (skill) =>
            !selectedIds.has(Number(skill.skill_id)) &&
            (skill.config_schemas || []).length > 0
        )
        .map((skill) => Number(skill.skill_id));
      queue.forEach((id) => next.delete(id));
      if (queue.length) {
        setDraftConfigs(
          Object.fromEntries(queue.map((id) => [id, { ...configs[id] }]))
        );
        setEditingId(queue[0]);
        setConfigQueue(queue.slice(1));
      }
    }
    setSelectedIds(next);
  };

  const submit = async () => {
    if (loading || saving || restoring || installing !== null || listError)
      return;
    if (selectedIds.size > 20) {
      message.warning("最多选择 20 个 Skills");
      return;
    }
    const selectedSkills = skills.filter((skill) =>
      selectedIds.has(Number(skill.skill_id))
    );
    if (selectedSkills.length !== selectedIds.size) {
      message.warning("部分已选 Skill 不可用，请重新选择");
      return;
    }
    if (
      selectedSkills.some((skill) =>
        missingRequiredConfig(skill, configs[Number(skill.skill_id)])
      )
    ) {
      message.warning("请先补全所选 Skill 的必填配置");
      return;
    }
    const mounts = selectedSkills.map((skill) => {
      const skillId = Number(skill.skill_id);
      return {
        skill_id: skillId,
        config_values: { ...configs[skillId] },
      };
    });
    setSaving(true);
    try {
      await onConfirm(mounts, selectedSkills);
    } catch (error) {
      message.error(
        error instanceof Error ? error.message : "资源配置保存失败"
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title="选择 Skills"
      open={open}
      onCancel={() => {
        installOperationRef.current += 1;
        setInstalling(null);
        setConflict(null);
        onCancel();
      }}
      onOk={() => void submit()}
      confirmLoading={saving}
      okButtonProps={{
        "aria-label": "确定",
        disabled: loading || restoring || listError || installing !== null,
      }}
      footer={(_, { OkBtn, CancelBtn }) => (
        <div className="flex items-center justify-between">
          <div>
            {loadDefaults && (
              <RestoreDefaultsButton
                loading={restoring}
                disabled={loading || saving || installing !== null || listError}
                onClick={async () => {
                  const operation = ++restoreOperationRef.current;
                  setRestoring(true);
                  try {
                    const defaults = await loadDefaults();
                    if (operation !== restoreOperationRef.current) return;
                    setSelectedIds(
                      new Set(defaults.map((mount) => mount.skill_id))
                    );
                    setConfigs(
                      Object.fromEntries(
                        defaults.map((mount) => [
                          mount.skill_id,
                          structuredClone(mount.config_values),
                        ])
                      )
                    );
                    setEditingId(null);
                    setConfigQueue([]);
                    setDraftConfigs({});
                    setSearch("");
                    setTab("mine");
                  } catch (error) {
                    if (operation === restoreOperationRef.current)
                      message.error(
                        error instanceof Error
                          ? error.message
                          : "恢复默认 Skills 失败"
                      );
                  } finally {
                    if (operation === restoreOperationRef.current)
                      setRestoring(false);
                  }
                }}
              >
                恢复默认
              </RestoreDefaultsButton>
            )}
          </div>
          <div className="flex gap-2">
            <CancelBtn />
            <OkBtn />
          </div>
        </div>
      )}
      okText="确定"
      cancelText="取消"
      width={920}
      centered
    >
      <Tabs
        activeKey={tab}
        onChange={(value) => {
          installOperationRef.current += 1;
          setInstalling(null);
          setConflict(null);
          setTab(value);
          setRepositoryPage(1);
        }}
        items={[
          { key: "mine", label: "我的" },
          { key: "repository", label: "仓库" },
        ]}
      />
      <Input.Search
        value={search}
        onChange={(event) => {
          setSearch(event.target.value);
          setRepositoryPage(1);
        }}
        placeholder="搜索 Skill 名称或描述"
        allowClear
      />
      {tab === "mine" && (
        <div className="mt-3 flex items-center justify-between gap-3 rounded bg-blue-50 px-4 py-3">
          <SelectedResourceTags
            items={skills
              .filter((skill) => selectedIds.has(Number(skill.skill_id)))
              .map((skill) => ({
                id: String(skill.skill_id),
                name: skill.name,
              }))}
            onRemove={(id) =>
              setSelectedIds((current) => {
                const next = new Set(current);
                next.delete(Number(id));
                return next;
              })
            }
          />
          <ResourceSelectionActions
            allSelected={allSelected}
            hasSelection={selectedIds.size > 0}
            disabled={loading || saving || listError || installing !== null}
            empty={filtered.length === 0}
            onToggleAll={toggleAll}
            onClear={() => setSelectedIds(new Set())}
          />
        </div>
      )}
      {tab === "repository" ? (
        <>
          <Spin spinning={loading}>
            <ResourceSelectionGrid className="mt-4 p-1">
              {repository.map((item) => (
                <ResourceCard
                  resourceType="skill"
                  key={item.skill_repository_id}
                  title={item.name}
                  description={item.description ?? undefined}
                  tags={item.tags}
                  disabled={installing !== null}
                  actions={
                    <Button
                      size="small"
                      disabled={installing !== null}
                      loading={installing === item.skill_repository_id}
                      onClick={() => void install(item)}
                    >
                      {installing === item.skill_repository_id
                        ? "安装中"
                        : "安装并选择"}
                    </Button>
                  }
                  onClick={() => void install(item)}
                />
              ))}
            </ResourceSelectionGrid>
          </Spin>
          <ResourcePagination
            current={repositoryPage}
            total={repositoryTotal}
            onChange={setRepositoryPage}
            disabled={loading || installing !== null}
          />
          <Modal
            title="Skill 名称已存在"
            open={!!conflict}
            onCancel={() => {
              installOperationRef.current += 1;
              setInstalling(null);
              setConflict(null);
            }}
            onOk={() => conflict && void install(conflict, targetName.trim())}
            okText="重命名安装"
            okButtonProps={{ disabled: !targetName.trim() }}
          >
            <Input
              value={targetName}
              onChange={(event) => setTargetName(event.target.value)}
              aria-label="新 Skill 名称"
            />
            {skills.some((skill) => skill.name === conflict?.name) && (
              <button
                onClick={() => {
                  const existing = skills.find(
                    (skill) => skill.name === conflict?.name
                  );
                  if (existing)
                    setSelectedIds(
                      (current) =>
                        new Set([...current, Number(existing.skill_id)])
                    );
                  setConflict(null);
                  setTab("mine");
                }}
              >
                使用已有 Skill
              </button>
            )}
          </Modal>
        </>
      ) : loading ? (
        <div
          className={`${RESOURCE_SELECTION_AREA_CLASS} mt-4 flex items-center justify-center`}
        >
          <Spin />
        </div>
      ) : filtered.length === 0 ? (
        <div
          className={`${RESOURCE_SELECTION_AREA_CLASS} mt-4 flex items-center justify-center`}
        >
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
        </div>
      ) : (
        <ResourceSelectionGrid className="mt-4 p-1">
          {skills
            .filter(
              (skill) =>
                resourcePage(filtered, minePage).includes(skill) ||
                Number(skill.skill_id) === editingId
            )
            .map((skill) => {
              const skillId = Number(skill.skill_id);
              const selectedNow = selectedIds.has(skillId);
              const invalid = missingRequiredConfig(skill, configs[skillId]);
              return (
                <div key={skillId} className="contents">
                  {resourcePage(filtered, minePage).includes(skill) && (
                    <ResourceCard
                      resourceType="skill"
                      key={skillId}
                      title={skill.name}
                      description={skill.description}
                      tags={skill.tags || []}
                      badges={[skill.source].filter(Boolean)}
                      selected={selectedNow}
                      actions={
                        <Button
                          size="small"
                          aria-label="编辑"
                          onClick={() =>
                            router.push(
                              `/skill-space?tab=mine&edit_skill_id=${skillId}`
                            )
                          }
                        >
                          编辑
                        </Button>
                      }
                      onClick={() => {
                        if (selectedNow) {
                          setSelectedIds((current) => {
                            const next = new Set(current);
                            next.delete(skillId);
                            return next;
                          });
                          return;
                        }
                        if ((skill.config_schemas || []).length > 0) {
                          setDraftConfigs({
                            [skillId]: { ...configs[skillId] },
                          });
                          setEditingId(skillId);
                        } else
                          setSelectedIds(
                            (current) => new Set([...current, skillId])
                          );
                      }}
                      footer={
                        invalid
                          ? "需要填写必填配置"
                          : selectedNow
                            ? "已选择"
                            : "选择"
                      }
                    />
                  )}
                  {editingId === skillId && (
                    <Modal
                      title={`配置 ${skill.name}`}
                      open
                      onCancel={() => {
                        setEditingId(null);
                        setConfigQueue([]);
                      }}
                      okText="保存配置"
                      cancelText="取消"
                      onOk={() => {
                        if (
                          missingRequiredConfig(skill, draftConfigs[skillId])
                        ) {
                          message.warning("请先补全所选 Skill 的必填配置");
                          return;
                        }
                        setConfigs((current) => ({
                          ...current,
                          [skillId]: { ...draftConfigs[skillId] },
                        }));
                        setSelectedIds(
                          (current) => new Set([...current, skillId])
                        );
                        setEditingId(configQueue[0] ?? null);
                        setConfigQueue((current) => current.slice(1));
                      }}
                    >
                      {(skill.config_schemas || []).map((item) => {
                        const schema = item as {
                          name?: string;
                          type?: string;
                          required?: boolean;
                          enum?: unknown[];
                        };
                        if (!schema.name) return null;
                        const name = schema.name;
                        const value =
                          draftConfigs[skillId]?.[name] ??
                          skill.config_values?.[name] ??
                          "";
                        return (
                          <label key={name} className="mt-2 block text-sm">
                            {name}
                            {schema.required ? " *" : ""}
                            {schema.type === "boolean" ? (
                              <Switch
                                aria-label={`${skill.name} ${name}`}
                                checked={value === true}
                                onChange={(checked) =>
                                  setDraftConfigs((current) => ({
                                    ...current,
                                    [skillId]: {
                                      ...current[skillId],
                                      [name]: checked,
                                    },
                                  }))
                                }
                              />
                            ) : Array.isArray(schema.enum) ? (
                              <Select
                                aria-label={`${skill.name} ${name}`}
                                value={value === "" ? undefined : value}
                                options={schema.enum.map((option) => ({
                                  value: option,
                                  label: String(option),
                                }))}
                                onChange={(selectedValue) =>
                                  setDraftConfigs((current) => ({
                                    ...current,
                                    [skillId]: {
                                      ...current[skillId],
                                      [name]: selectedValue,
                                    },
                                  }))
                                }
                              />
                            ) : (
                              <Input
                                aria-label={`${skill.name} ${name}`}
                                type={
                                  schema.type === "integer" ||
                                  schema.type === "number"
                                    ? "number"
                                    : "text"
                                }
                                value={
                                  typeof value === "object"
                                    ? JSON.stringify(value)
                                    : String(value)
                                }
                                onChange={(event) => {
                                  const raw = event.target.value;
                                  let parsed: unknown = raw;
                                  if (
                                    raw &&
                                    (schema.type === "integer" ||
                                      schema.type === "number")
                                  )
                                    parsed = Number(raw);
                                  if (schema.type === "boolean")
                                    parsed =
                                      raw === "true"
                                        ? true
                                        : raw === "false"
                                          ? false
                                          : raw;
                                  if (
                                    schema.type === "object" ||
                                    schema.type === "array"
                                  ) {
                                    try {
                                      parsed = JSON.parse(raw);
                                    } catch {
                                      parsed = raw;
                                    }
                                  }
                                  setDraftConfigs((current) => ({
                                    ...current,
                                    [skillId]: {
                                      ...current[skillId],
                                      [name]: parsed,
                                    },
                                  }));
                                }}
                              />
                            )}
                          </label>
                        );
                      })}
                    </Modal>
                  )}
                </div>
              );
            })}
        </ResourceSelectionGrid>
      )}
      {tab === "mine" && (
        <ResourcePagination
          current={minePage}
          total={filtered.length}
          onChange={setMinePage}
          disabled={loading || saving || editingId !== null}
        />
      )}
    </Modal>
  );
}
