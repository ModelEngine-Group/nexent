"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  App,
  Button,
  Card,
  Dropdown,
  Empty,
  Flex,
  InputNumber,
  Popover,
  Segmented,
  Skeleton,
  Switch,
  Tag,
  Typography,
  type MenuProps,
} from "antd";
import {
  Edit3,
  MoreHorizontal,
  Plus,
  Plug,
  RefreshCw,
  Search,
  Settings2,
  Trash2,
} from "lucide-react";
import { useTranslation } from "react-i18next";

import { Can } from "@/components/permission/Can";
import { usePermission } from "@/hooks/permission/usePermission";
import {
  deleteProvider,
  listPlugins,
  listProviders,
  updateProvider,
  type PluginInfo,
  type ProviderConfig,
} from "@/services/providerService";
import { ProviderConfigDialog } from "./ProviderConfigDialog";
import { ProviderTestPanel } from "./ProviderTestPanel";

const { Text } = Typography;
type ProviderFilter = "all" | "enabled" | "attention";
type StatusKey =
  "normal" | "unauthorized" | "forbidden" | "timeout" | "error" | "disabled";

interface ProviderConfigCardProps {
  memoryEnabled: boolean;
  topK: number;
  savingTopK: boolean;
  onTopKChange: (value: number) => void;
  onTopKSave: () => Promise<void>;
}

function resolveProviderStatus(provider: ProviderConfig): {
  color: string;
  key: StatusKey;
} {
  if (provider.last_error_code === "unauthorized")
    return { color: "error", key: "unauthorized" };
  if (provider.last_error_code === "forbidden")
    return { color: "error", key: "forbidden" };
  if (provider.last_error_code === "timeout")
    return { color: "warning", key: "timeout" };
  if (provider.last_error_code) return { color: "warning", key: "error" };
  if (!provider.enabled) return { color: "default", key: "disabled" };
  return { color: "success", key: "normal" };
}

export function ProviderConfigCard({
  memoryEnabled,
  topK,
  savingTopK,
  onTopKChange,
  onTopKSave,
}: ProviderConfigCardProps) {
  const { message, modal } = App.useApp();
  const { t } = useTranslation("common");
  const { can } = usePermission();
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [filter, setFilter] = useState<ProviderFilter>("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ProviderConfig | null>(null);
  const [testProvider, setTestProvider] = useState<ProviderConfig | null>(null);
  const [testOpen, setTestOpen] = useState(false);
  const [togglingIds, setTogglingIds] = useState<Set<number>>(new Set());

  const refresh = useCallback(async () => {
    setLoading(true);
    setLoadError(false);
    try {
      const [providerData, pluginData] = await Promise.all([
        listProviders(),
        listPlugins(),
      ]);
      setProviders(providerData);
      setPlugins(pluginData);
    } catch {
      setLoadError(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const filteredProviders = useMemo(
    () =>
      providers.filter((provider) => {
        if (filter === "enabled") return provider.enabled;
        if (filter === "attention") {
          const status = resolveProviderStatus(provider).key;
          return status !== "normal" && status !== "disabled";
        }
        return true;
      }),
    [filter, providers]
  );

  const pluginByName = useMemo(
    () => new Map(plugins.map((plugin) => [plugin.name, plugin])),
    [plugins]
  );

  const handleToggleEnabled = async (
    provider: ProviderConfig,
    enabled: boolean
  ) => {
    setTogglingIds((current) =>
      new Set(current).add(provider.provider_config_id)
    );
    try {
      const updated = await updateProvider(provider.provider_config_id, {
        enabled,
      });
      setProviders((current) =>
        current.map((item) =>
          item.provider_config_id === provider.provider_config_id
            ? updated
            : item
        )
      );
    } catch {
      message.error(t("memory.external.providers.updateFailed"));
    } finally {
      setTogglingIds((current) => {
        const next = new Set(current);
        next.delete(provider.provider_config_id);
        return next;
      });
    }
  };

  const handleDelete = (provider: ProviderConfig) => {
    modal.confirm({
      centered: true,
      title: t("memory.external.providers.deleteTitle"),
      content: t("memory.external.providers.deleteDescription", {
        name: provider.provider_name,
      }),
      okText: t("memory.external.actions.delete"),
      cancelText: t("memory.external.actions.cancel"),
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteProvider(provider.provider_config_id);
          setProviders((current) =>
            current.filter(
              (item) => item.provider_config_id !== provider.provider_config_id
            )
          );
          message.success(t("memory.external.providers.deleted"));
        } catch {
          message.error(t("memory.external.providers.deleteFailed"));
        }
      },
    });
  };

  const openTest = (provider: ProviderConfig) => {
    setTestProvider(provider);
    setTestOpen(true);
  };
  const menuFor = (provider: ProviderConfig): MenuProps["items"] => {
    const items: MenuProps["items"] = [];
    if (can("mem.provider:update")) {
      items.push(
        {
          key: "test",
          icon: <Search size={15} />,
          label: t("memory.external.actions.test"),
          onClick: () => openTest(provider),
        },
        {
          key: "edit",
          icon: <Edit3 size={15} />,
          label: t("memory.external.actions.edit"),
          onClick: () => {
            setEditing(provider);
            setDialogOpen(true);
          },
        }
      );
    }
    if (can("mem.provider:delete")) {
      items.push(
        { type: "divider" },
        {
          key: "delete",
          danger: true,
          icon: <Trash2 size={15} />,
          label: t("memory.external.actions.delete"),
          onClick: () => handleDelete(provider),
        }
      );
    }
    return items;
  };

  return (
    <>
      <Card className="memory-config-card external-memory-card">
        <Flex vertical gap={20}>
          <Flex align="flex-start" justify="space-between" gap={16} wrap="wrap">
            <Flex align="center" gap={12}>
              <Plug size={20} aria-hidden="true" />
              <div>
                <Text strong>{t("memory.external.title")}</Text>
                <Text type="secondary" className="memory-setting-description">
                  {t("memory.external.description")}
                </Text>
              </div>
            </Flex>
            <Flex gap={8} wrap="wrap">
              <Popover
                placement="bottomRight"
                trigger="click"
                title={t("memory.external.advanced.title")}
                content={
                  <div className="external-memory-advanced-popover">
                    <Text type="secondary">
                      {t("memory.external.topK.description")}
                    </Text>
                    <div className="external-memory-advanced-field">
                      <Text strong>{t("memory.external.topK.label")}</Text>
                      <InputNumber
                        min={1}
                        max={100}
                        value={topK}
                        disabled={savingTopK}
                        aria-label={t("memory.external.topK.label")}
                        onChange={(value) =>
                          value !== null && onTopKChange(value)
                        }
                        onBlur={() => void onTopKSave()}
                      />
                    </div>
                  </div>
                }
              >
                <Button icon={<Settings2 size={17} />}>
                  {t("memory.external.advanced.title")}
                </Button>
              </Popover>
              <Can permission="mem.provider:create">
                <Button
                  type="primary"
                  icon={<Plus size={17} />}
                  disabled={!loading && plugins.length === 0}
                  onClick={() => {
                    setEditing(null);
                    setDialogOpen(true);
                  }}
                >
                  {t("memory.external.actions.add")}
                </Button>
              </Can>
            </Flex>
          </Flex>

          {!memoryEnabled && (
            <Alert
              type="info"
              showIcon
              message={t("memory.external.masterSwitchOff")}
            />
          )}

          <Flex align="center" justify="space-between" gap={12} wrap="wrap">
            <Text strong>
              {t("memory.external.providers.title", {
                count: providers.length,
              })}
            </Text>
            <Segmented<ProviderFilter>
              size="small"
              value={filter}
              onChange={setFilter}
              options={[
                { value: "all", label: t("memory.external.filters.all") },
                {
                  value: "enabled",
                  label: t("memory.external.filters.enabled"),
                },
                {
                  value: "attention",
                  label: t("memory.external.filters.attention"),
                },
              ]}
            />
          </Flex>

          {loading ? (
            <Skeleton active paragraph={{ rows: 3 }} />
          ) : loadError ? (
            <Alert
              type="error"
              showIcon
              message={t("memory.external.loadFailed")}
              action={
                <Button
                  size="small"
                  icon={<RefreshCw size={14} />}
                  onClick={() => void refresh()}
                >
                  {t("memory.external.actions.retry")}
                </Button>
              }
            />
          ) : plugins.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("memory.external.noPlugins")}
            />
          ) : providers.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("memory.external.empty")}
            >
              <Can permission="mem.provider:create">
                <Button
                  type="primary"
                  icon={<Plus size={16} />}
                  onClick={() => {
                    setEditing(null);
                    setDialogOpen(true);
                  }}
                >
                  {t("memory.external.actions.add")}
                </Button>
              </Can>
            </Empty>
          ) : filteredProviders.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description={t("memory.external.noFilterResults")}
            />
          ) : (
            <div className="external-provider-list">
              {filteredProviders.map((provider) => {
                const status = resolveProviderStatus(provider);
                const pluginName = provider.params?.["plugin.name"] ?? "";
                const plugin = pluginByName.get(pluginName);
                const actions = menuFor(provider);
                return (
                  <div
                    className="external-provider-row"
                    key={provider.provider_config_id}
                  >
                    <div className="external-provider-main">
                      <Flex align="center" gap={8} wrap="wrap">
                        <Text strong>{provider.provider_name}</Text>
                        <Tag color={status.color}>
                          {t(`memory.external.status.${status.key}`)}
                        </Tag>
                      </Flex>
                      <Flex
                        gap={8}
                        wrap="wrap"
                        className="external-provider-meta"
                      >
                        <Text type="secondary">
                          {pluginName || "—"}
                          {plugin ? ` · v${plugin.version}` : ""}
                        </Text>
                        {plugin?.implements.map((capability) => (
                          <Tag key={capability}>
                            {t(`memory.external.capability.${capability}`, {
                              defaultValue: capability,
                            })}
                          </Tag>
                        ))}
                      </Flex>
                      {status.key !== "normal" && status.key !== "disabled" && (
                        <Text
                          type="danger"
                          className="external-provider-guidance"
                        >
                          {t(`memory.external.statusHelp.${status.key}`)}
                        </Text>
                      )}
                    </div>
                    <Flex
                      align="center"
                      gap={8}
                      className="external-provider-actions"
                    >
                      <Can
                        permission="mem.provider:update"
                        fallback={
                          <Switch
                            size="small"
                            checked={provider.enabled}
                            disabled
                            aria-label={t("memory.external.actions.enable")}
                          />
                        }
                      >
                        <Switch
                          size="small"
                          checked={provider.enabled}
                          loading={togglingIds.has(provider.provider_config_id)}
                          aria-label={t("memory.external.actions.enable")}
                          onChange={(checked) =>
                            void handleToggleEnabled(provider, checked)
                          }
                        />
                      </Can>
                      {actions && actions.length > 0 && (
                        <Dropdown menu={{ items: actions }} trigger={["click"]}>
                          <Button
                            type="text"
                            aria-label={t("memory.external.actions.more")}
                            icon={<MoreHorizontal size={18} />}
                          />
                        </Dropdown>
                      )}
                    </Flex>
                  </div>
                );
              })}
            </div>
          )}
        </Flex>
      </Card>

      <ProviderConfigDialog
        open={dialogOpen}
        editing={editing}
        onClose={() => setDialogOpen(false)}
        onSaved={(provider, shouldTest) => {
          setDialogOpen(false);
          void refresh();
          if (shouldTest) openTest(provider);
        }}
      />
      <ProviderTestPanel
        open={testOpen}
        provider={testProvider}
        onClose={() => setTestOpen(false)}
        onTested={() => void refresh()}
      />
    </>
  );
}
