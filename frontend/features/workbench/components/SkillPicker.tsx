// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";
import { useTranslation } from "react-i18next";
import { WorkbenchResourceDrawer } from "./WorkbenchResourceDrawer";
import { ResourceTagFilter } from "./ResourceTagFilter";
import { useResourceTags } from "../hooks/useResourceTags";

import { ResourceSelectionActions } from "@/features/workbench/components/ResourceSelectionActions";

import { SelectedResourceTags } from "@/features/workbench/components/SelectedResourceTags";

import { ResourceSelectionGrid } from "@/features/workbench/components/ResourceSelectionGrid";

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
import { ResourceSelectionRow } from "./ResourceSelectionRow";
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
  disabled = false,
}: {
  open: boolean;
  disabled?: boolean;
  selected: WorkbenchSkillMount[];
  onCancel: () => void;
  loadDefaults?: () => Promise<WorkbenchSkillMount[]>;
  onConfirm: (
    mounts: WorkbenchSkillMount[],
    skills: SkillListItem[]
  ) => Promise<void> | void;
}) {
  const { t } = useTranslation();
  const [skills, setSkills] = useState<SkillListItem[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(
    () => new Set(selected.map((mount) => mount.skill_id))
  );
  const [search, setSearch] = useState("");
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
  >(() =>
    Object.fromEntries(
      selected.map((mount) => [mount.skill_id, { ...mount.config_values }])
    )
  );
  const [editingId, setEditingId] = useState<number | null>(null);
  const [configQueue, setConfigQueue] = useState<number[]>([]);
  const [draftConfigs, setDraftConfigs] = useState<
    Record<number, Record<string, unknown>>
  >({});
  const installOperationRef = useRef(0);
  const mineTags = useResourceTags(
    open,
    "skill",
    skills.map((skill) => String(skill.skill_id)),
    tab !== "mine"
  );
  const repositoryTags = useResourceTags(open, "skill", [], true);
  const tags = tab === "mine" ? mineTags : repositoryTags;
  const mineRequest = useMemo(() => ({ open, selected }), [open, selected]);
  const repositoryRequest = useMemo(
    () => ({
      open,
      tab,
      search,
      page: repositoryPage,
      predicates: repositoryTags.predicates,
    }),
    [open, tab, search, repositoryPage, repositoryTags.predicates]
  );
  const [settledMineRequest, setSettledMineRequest] = useState<
    typeof mineRequest | null
  >(null);
  const [settledRepositoryRequest, setSettledRepositoryRequest] = useState<
    typeof repositoryRequest | null
  >(null);
  const loading =
    open &&
    (settledMineRequest !== mineRequest ||
      (tab === "repository" && settledRepositoryRequest !== repositoryRequest));
  const [previousInputs, setPreviousInputs] = useState({
    open,
    search,
    tab,
    selected,
  });
  // Guard input-driven resets so children never render stale picker state.
  if (
    previousInputs.open !== open ||
    previousInputs.search !== search ||
    previousInputs.tab !== tab ||
    previousInputs.selected !== selected
  ) {
    setPreviousInputs({ open, search, tab, selected });
    if (
      previousInputs.open !== open ||
      previousInputs.search !== search ||
      previousInputs.tab !== tab
    ) {
      setMinePage(1);
      setRepositoryPage(1);
    }
    if (!open && previousInputs.open !== open) {
      setRestoring(false);
      setEditingId(null);
      setConfigQueue([]);
      setInstalling(null);
      setConflict(null);
    }
    if (
      open &&
      (previousInputs.open !== open || previousInputs.selected !== selected)
    ) {
      setListError(false);
      setSelectedIds(new Set(selected.map((mount) => mount.skill_id)));
      setConfigs(
        Object.fromEntries(
          selected.map((mount) => [mount.skill_id, { ...mount.config_values }])
        )
      );
    }
  }
  useEffect(() => {
    if (!open) {
      restoreOperationRef.current += 1;
      installOperationRef.current += 1;
    }
  }, [open]);
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void fetchSkillsList()
      .then((items) => {
        if (!cancelled) setSkills(items);
      })
      .catch((error) => {
        if (!cancelled) {
          setListError(true);
          message.error(
            error instanceof Error
              ? error.message
              : t("workbench.controls.skillLoadFailed")
          );
        }
      })
      .finally(() => {
        if (!cancelled) setSettledMineRequest(mineRequest);
      });
    return () => {
      cancelled = true;
    };
  }, [open, mineRequest, t]);

  useEffect(() => {
    if (!open || tab !== "repository") return;
    let cancelled = false;
    void fetchSkillRepositoryListings({
      search: repositoryRequest.search,
      page: repositoryRequest.page,
      page_size: RESOURCE_PAGE_SIZE,
      status: "shared",
      tag_predicates: repositoryRequest.predicates,
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
        if (!cancelled) setSettledRepositoryRequest(repositoryRequest);
      });
    return () => {
      cancelled = true;
    };
  }, [open, tab, repositoryRequest]);

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
        throw new Error(t("workbench.controls.skillInstallMissingId"));
      const items = await fetchSkillsList();
      if (operation !== installOperationRef.current) return;
      setSkills(items);
      if (selectedIds.size >= 20) {
        message.warning(t("workbench.skills.limit", { count: 20 }));
        setTab("mine");
        return;
      }
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
      } else
        message.error(
          error instanceof Error
            ? error.message
            : t("workbench.controls.installFailed")
        );
    } finally {
      if (operation === installOperationRef.current) setInstalling(null);
    }
  };

  const filtered = useMemo(() => {
    const value = search.trim().toLowerCase();
    const candidates = skills.filter(
      (skill) =>
        !mineTags.visibleIds || mineTags.visibleIds.has(String(skill.skill_id))
    );
    if (!value) return candidates;
    return candidates.filter((skill) =>
      [skill.name, skill.description]
        .filter(Boolean)
        .some((field) => String(field).toLowerCase().includes(value))
    );
  }, [search, skills, mineTags.visibleIds]);

  const allSelected =
    resourcePage(filtered, minePage).length > 0 &&
    resourcePage(filtered, minePage).every((skill) =>
      selectedIds.has(Number(skill.skill_id))
    );
  const toggleAll = () => {
    const next = new Set(selectedIds);
    resourcePage(filtered, minePage).forEach((skill) => {
      const id = Number(skill.skill_id);
      if (allSelected) next.delete(id);
      else next.add(id);
    });
    if (next.size > 20) {
      message.warning(t("workbench.controls.skillLimitSearch"));
      return;
    }
    if (!allSelected) {
      const queue = resourcePage(filtered, minePage)
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
    if (
      disabled ||
      loading ||
      saving ||
      restoring ||
      installing !== null ||
      listError
    )
      return;
    if (selectedIds.size > 20) {
      message.warning(t("workbench.controls.skillLimit"));
      return;
    }
    const selectedSkills = skills.filter((skill) =>
      selectedIds.has(Number(skill.skill_id))
    );
    if (selectedSkills.length !== selectedIds.size) {
      message.warning(t("workbench.controls.skillsUnavailable"));
      return;
    }
    if (
      selectedSkills.some((skill) =>
        missingRequiredConfig(skill, configs[Number(skill.skill_id)])
      )
    ) {
      message.warning(t("workbench.controls.completeSkillConfig"));
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
        error instanceof Error
          ? error.message
          : t("workbench.controls.saveConfigFailed")
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <WorkbenchResourceDrawer
      listContent={
        <>
          {" "}
          {tab === "repository" ? (
            <>
              <Spin
                spinning={loading}
                className="h-full [&>.ant-spin-container]:min-h-full"
              >
                <ResourceSelectionGrid
                  layout="list"
                  aria-label={t("workbench.controls.skills", "技能")}
                  fillAvailable
                  className="p-1"
                >
                  {repository.map((item) => (
                    <ResourceSelectionRow
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
                            ? t("workbench.controls.installing")
                            : t("workbench.controls.installAndSelect")}
                        </Button>
                      }
                      onClick={() => void install(item)}
                    />
                  ))}
                </ResourceSelectionGrid>
              </Spin>
              <Modal
                title={t("workbench.controls.skillNameExists")}
                open={!!conflict}
                onCancel={() => {
                  installOperationRef.current += 1;
                  setInstalling(null);
                  setConflict(null);
                }}
                onOk={() =>
                  conflict && void install(conflict, targetName.trim())
                }
                okText={t("workbench.controls.renameInstall")}
                okButtonProps={{ disabled: !targetName.trim() }}
              >
                <Input
                  value={targetName}
                  onChange={(event) => setTargetName(event.target.value)}
                  aria-label={t("workbench.controls.newSkillName")}
                />
                {skills.some((skill) => skill.name === conflict?.name) && (
                  <button
                    onClick={() => {
                      const existing = skills.find(
                        (skill) => skill.name === conflict?.name
                      );
                      if (
                        existing &&
                        !selectedIds.has(Number(existing.skill_id)) &&
                        selectedIds.size >= 20
                      ) {
                        message.warning(
                          t("workbench.skills.limit", { count: 20 })
                        );
                        return;
                      }
                      if (existing)
                        setSelectedIds(
                          (current) =>
                            new Set([...current, Number(existing.skill_id)])
                        );
                      setConflict(null);
                      setTab("mine");
                    }}
                  >
                    {t("workbench.controls.useExistingSkill")}
                  </button>
                )}
              </Modal>
            </>
          ) : loading ? (
            <div className={`min-h-full flex items-center justify-center`}>
              <Spin />
            </div>
          ) : filtered.length === 0 ? (
            <div className={`min-h-full flex items-center justify-center`}>
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
            </div>
          ) : (
            <ResourceSelectionGrid
              layout="list"
              aria-label={t("workbench.controls.skills", "技能")}
              fillAvailable
              className="p-1"
            >
              {skills
                .filter(
                  (skill) =>
                    resourcePage(filtered, minePage).includes(skill) ||
                    Number(skill.skill_id) === editingId
                )
                .map((skill) => {
                  const skillId = Number(skill.skill_id);
                  const selectedNow = selectedIds.has(skillId);
                  const invalid = missingRequiredConfig(
                    skill,
                    configs[skillId]
                  );
                  return (
                    <div key={skillId} className="contents">
                      {resourcePage(filtered, minePage).includes(skill) && (
                        <ResourceSelectionRow
                          key={skillId}
                          title={skill.name}
                          description={skill.description}
                          tags={skill.tags || []}
                          selected={selectedNow}
                          onClick={() => {
                            if (selectedNow) {
                              setSelectedIds((current) => {
                                const next = new Set(current);
                                next.delete(skillId);
                                return next;
                              });
                              return;
                            }
                            if (selectedIds.size >= 20) {
                              message.warning(
                                t("workbench.skills.limit", { count: 20 })
                              );
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
                          disabledReason={
                            invalid
                              ? t("workbench.controls.requiredConfig")
                              : undefined
                          }
                        />
                      )}
                      {editingId === skillId && (
                        <Modal
                          title={t("workbench.controls.configureSkill", {
                            name: skill.name,
                          })}
                          open
                          onCancel={() => {
                            setEditingId(null);
                            setConfigQueue([]);
                          }}
                          okText={t("workbench.controls.saveConfig")}
                          cancelText={t("common.cancel")}
                          onOk={() => {
                            if (
                              missingRequiredConfig(
                                skill,
                                draftConfigs[skillId]
                              )
                            ) {
                              message.warning(
                                t("workbench.controls.completeSkillConfig")
                              );
                              return;
                            }
                            if (
                              !selectedIds.has(skillId) &&
                              selectedIds.size >= 20
                            ) {
                              message.warning(
                                t("workbench.skills.limit", { count: 20 })
                              );
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
        </>
      }
      pagination={
        <ResourcePagination
          current={tab === "repository" ? repositoryPage : minePage}
          total={tab === "repository" ? repositoryTotal : filtered.length}
          onChange={tab === "repository" ? setRepositoryPage : setMinePage}
          disabled={
            loading || saving || installing !== null || editingId !== null
          }
        />
      }
      title={t("chat.composer.skills", "Skills")}
      open={open}
      saving={saving}
      disabled={disabled}
      confirmDisabled={
        loading ||
        restoring ||
        listError ||
        installing !== null ||
        (!!tags.predicates.length && tags.loading)
      }
      onCancel={() => {
        installOperationRef.current += 1;
        setInstalling(null);
        setConflict(null);
        onCancel();
      }}
      onConfirm={() => void submit()}
      footerLeading={
        loadDefaults ? (
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
                      : t("workbench.controls.restoreSkillsFailed")
                  );
              } finally {
                if (operation === restoreOperationRef.current)
                  setRestoring(false);
              }
            }}
          >
            {t("workbench.controls.restoreDefaults")}
          </RestoreDefaultsButton>
        ) : undefined
      }
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
          { key: "mine", label: t("workbench.controls.mine") },
          { key: "repository", label: t("workbench.controls.repository") },
        ]}
      />
      <ResourceTagFilter
        filter={tags}
        onChange={() => {
          setMinePage(1);
          setRepositoryPage(1);
        }}
        search={
          <Input.Search
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setRepositoryPage(1);
            }}
            placeholder={t("workbench.controls.searchSkills")}
            allowClear
          />
        }
      />
      <p className="mt-2 text-xs text-muted-foreground">
        {t("workbench.controls.installedNotice")}
      </p>
      {
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
            toggleAllDisabled={tab !== "mine"}
            pageOnly
            allSelected={allSelected}
            hasSelection={selectedIds.size > 0}
            disabled={loading || saving || listError || installing !== null}
            empty={filtered.length === 0}
            onToggleAll={toggleAll}
            onClear={() => setSelectedIds(new Set())}
          />
        </div>
      }
    </WorkbenchResourceDrawer>
  );
}
