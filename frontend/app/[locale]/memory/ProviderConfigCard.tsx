"use client";

import React, { useCallback, useEffect, useState } from "react";
import {
  App,
  Badge,
  Button,
  Card,
  Empty,
  Flex,
  Spin,
  Switch,
  Typography,
} from "antd";
import { Edit3, Plus, Search, Trash2, Upload, Plug } from "lucide-react";

import { Can } from "@/components/permission/Can";
import {
  deleteProvider,
  listProviders,
  testSearch,
  testIngest,
  updateProvider,
  type ProviderConfig,
} from "@/services/providerService";
import { ProviderConfigDialog } from "./ProviderConfigDialog";

const { Text } = Typography;

type ProviderStatus = {
  status: "success" | "error" | "warning" | "default";
  text: string;
};

function resolveProviderStatus(provider: ProviderConfig): ProviderStatus {
  if (!provider.enabled) {
    return { status: "default", text: "disabled" };
  }
  if (provider.last_error_code === null) {
    return { status: "success", text: "normal" };
  }
  if (
    provider.last_error_code === "unauthorized" ||
    provider.last_error_code === "forbidden"
  ) {
    return { status: "error", text: provider.last_error_code };
  }
  return { status: "warning", text: provider.last_error_code };
}

export function ProviderConfigCard() {
  const { message, modal } = App.useApp();

  const [loading, setLoading] = useState(true);
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ProviderConfig | null>(null);
  const [togglingIds, setTogglingIds] = useState<Set<number>>(new Set());
  const [testingIds, setTestingIds] = useState<Set<number>>(new Set());

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listProviders();
      setProviders(data);
    } catch {
      message.error("Failed to load providers");
    } finally {
      setLoading(false);
    }
  }, [message]);

  useEffect(() => {
    let active = true;
    listProviders()
      .then((data) => {
        if (active) setProviders(data);
      })
      .catch(() => {
        if (active) message.error("Failed to load providers");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [message]);

  const handleToggleEnabled = async (
    provider: ProviderConfig,
    enabled: boolean
  ) => {
    setTogglingIds((prev) => new Set(prev).add(provider.provider_config_id));
    try {
      const updated = await updateProvider(provider.provider_config_id, {
        enabled,
      });
      setProviders((prev) =>
        prev.map((p) =>
          p.provider_config_id === provider.provider_config_id ? updated : p
        )
      );
    } catch {
      message.error("Failed to update provider");
    } finally {
      setTogglingIds((prev) => {
        const next = new Set(prev);
        next.delete(provider.provider_config_id);
        return next;
      });
    }
  };

  const handleDelete = (provider: ProviderConfig) => {
    modal.confirm({
      centered: true,
      title: "Delete this provider?",
      content: `Provider "${provider.provider_name}" will be permanently removed.`,
      okText: "Delete",
      cancelText: "Cancel",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteProvider(provider.provider_config_id);
          setProviders((prev) =>
            prev.filter(
              (p) => p.provider_config_id !== provider.provider_config_id
            )
          );
          message.success("Provider deleted");
        } catch {
          message.error("Failed to delete provider");
        }
      },
    });
  };

  const handleTestSearch = async (provider: ProviderConfig) => {
    setTestingIds((prev) => new Set(prev).add(provider.provider_config_id));
    try {
      await testSearch(provider.provider_config_id, "test query", 3);
      message.success("Test search succeeded");
    } catch {
      message.error("Test search failed");
    } finally {
      setTestingIds((prev) => {
        const next = new Set(prev);
        next.delete(provider.provider_config_id);
        return next;
      });
    }
  };

  const handleTestIngest = async (provider: ProviderConfig) => {
    setTestingIds((prev) => new Set(prev).add(provider.provider_config_id));
    try {
      await testIngest(provider.provider_config_id, [
        {
          event_id: "__test__",
          event_type: "test",
          unit_type: "test",
          unit_content: "test ingest payload",
          unit_index: 0,
          metadata: {},
        },
      ]);
      message.success("Test ingest succeeded");
    } catch {
      message.error("Test ingest failed");
    } finally {
      setTestingIds((prev) => {
        const next = new Set(prev);
        next.delete(provider.provider_config_id);
        return next;
      });
    }
  };

  const openCreate = () => {
    setEditing(null);
    setDialogOpen(true);
  };

  const openEdit = (provider: ProviderConfig) => {
    setEditing(provider);
    setDialogOpen(true);
  };

  const handleDialogSaved = () => {
    setDialogOpen(false);
    void refresh();
  };

  const pluginNameFromParams = (provider: ProviderConfig): string =>
    provider.params?.["plugin.name"] ?? "—";

  if (loading) {
    return (
      <Card className="memory-config-card">
        <Flex justify="center" style={{ padding: 48 }}>
          <Spin />
        </Flex>
      </Card>
    );
  }

  return (
    <>
      <Card className="memory-config-card">
        <Flex
          align="center"
          justify="space-between"
          style={{ marginBottom: 16 }}
        >
          <Flex align="center" gap={12}>
            <Plug size={20} />
            <div>
              <Text strong>External Memory Providers</Text>
              <Text type="secondary" className="memory-setting-description">
                Configure plugin-based external memory providers
              </Text>
            </div>
          </Flex>
          <Can permission="mem.provider:create">
            <Button type="primary" icon={<Plus size={17} />} onClick={openCreate}>
              Add Provider
            </Button>
          </Can>
        </Flex>

        {providers.length === 0 ? (
          <Empty
            description="No providers configured"
            image={Empty.PRESENTED_IMAGE_SIMPLE}
          />
        ) : (
          <Flex vertical gap={12}>
            {providers.map((provider) => {
              const badge = resolveProviderStatus(provider);
              const isToggling = togglingIds.has(provider.provider_config_id);
              const isTesting = testingIds.has(provider.provider_config_id);

              return (
                <div
                  key={provider.provider_config_id}
                  className="provider-row"
                >
                  <Flex
                    align="center"
                    justify="space-between"
                    gap={12}
                    wrap="wrap"
                  >
                    <Flex align="center" gap={12} style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ minWidth: 0 }}>
                        <Text strong ellipsis>
                          {provider.provider_name}
                        </Text>
                        <br />
                        <Text type="secondary" style={{ fontSize: 12 }}>
                          {pluginNameFromParams(provider)}
                        </Text>
                      </div>
                      <Badge
                        status={badge.status}
                        text={
                          <span style={{ fontSize: 12 }}>{badge.text}</span>
                        }
                      />
                    </Flex>

                    <Flex align="center" gap={8}>
                      <Switch
                        size="small"
                        checked={provider.enabled}
                        loading={isToggling}
                        onChange={(checked) =>
                          handleToggleEnabled(provider, checked)
                        }
                      />
                      <Button
                        size="small"
                        icon={<Search size={14} />}
                        loading={isTesting}
                        onClick={() => handleTestSearch(provider)}
                      >
                        Search
                      </Button>
                      <Button
                        size="small"
                        icon={<Upload size={14} />}
                        loading={isTesting}
                        onClick={() => handleTestIngest(provider)}
                      >
                        Ingest
                      </Button>
                      <Can permission="mem.provider:update">
                        <Button
                          size="small"
                          icon={<Edit3 size={14} />}
                          onClick={() => openEdit(provider)}
                        />
                      </Can>
                      <Can permission="mem.provider:delete">
                        <Button
                          size="small"
                          danger
                          icon={<Trash2 size={14} />}
                          onClick={() => handleDelete(provider)}
                        />
                      </Can>
                    </Flex>
                  </Flex>
                </div>
              );
            })}
          </Flex>
        )}
      </Card>

      <ProviderConfigDialog
        open={dialogOpen}
        editing={editing}
        onClose={() => setDialogOpen(false)}
        onSaved={handleDialogSaved}
      />
    </>
  );
}
