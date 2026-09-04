"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Button,
  Checkbox,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  Typography,
} from "antd";
import { useTranslation } from "react-i18next";

import {
  createProvider,
  listPlugins,
  updateProvider,
  type ConfigSchemaField,
  type PluginInfo,
  type ProviderConfig,
} from "@/services/providerService";

interface ProviderConfigDialogProps {
  open: boolean;
  editing: ProviderConfig | null;
  onClose: () => void;
  onSaved: (provider: ProviderConfig, shouldTest: boolean) => void;
}

const SECRET_MASK = "••••••••";

interface FormValues {
  provider_name: string;
  plugin_name: string;
  enabled: boolean;
  timeout_seconds: number;
  params: Record<string, string>;
}

export function ProviderConfigDialog({
  open,
  editing,
  onClose,
  onSaved,
}: ProviderConfigDialogProps) {
  const { message } = App.useApp();
  const { t } = useTranslation("common");
  const [form] = Form.useForm<FormValues>();
  const [saving, setSaving] = useState(false);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [pluginsLoading, setPluginsLoading] = useState(false);
  const [selectedPlugin, setSelectedPlugin] = useState<PluginInfo | null>(null);
  const [changedSecrets, setChangedSecrets] = useState<Set<string>>(new Set());

  const isEditing = editing !== null;

  useEffect(() => {
    if (!open) return;

    setPluginsLoading(true);
    listPlugins()
      .then((data) => setPlugins(data))
      .catch(() => message.error(t("memory.external.form.pluginsLoadFailed")))
      .finally(() => setPluginsLoading(false));
  }, [open, message, t]);

  useEffect(() => {
    if (!open) {
      form.resetFields();
      setSelectedPlugin(null);
      setChangedSecrets(new Set());
      return;
    }

    if (editing) {
      const pluginName = editing.params?.["plugin.name"] ?? "";
      const matchedPlugin = plugins.find((p) => p.name === pluginName) ?? null;
      setSelectedPlugin(matchedPlugin);

      const paramValues: Record<string, string> = {};
      if (matchedPlugin) {
        for (const field of matchedPlugin.config_schema) {
          const storedValue =
            editing.params?.[`plugin.${field.key}`] ??
            editing.params?.[field.key];
          if (field.type === "secret") {
            paramValues[field.key] = storedValue ? SECRET_MASK : "";
          } else {
            paramValues[field.key] = storedValue ?? "";
          }
        }
      } else {
        for (const [key, value] of Object.entries(editing.params ?? {})) {
          if (key !== "plugin.name") {
            paramValues[key] = value;
          }
        }
      }

      form.setFieldsValue({
        provider_name: editing.provider_name,
        plugin_name: pluginName,
        enabled: editing.enabled,
        timeout_seconds: editing.timeout_seconds,
        params: paramValues,
      });
    } else {
      form.resetFields();
      form.setFieldsValue({
        enabled: false,
        timeout_seconds: 30,
        params: {},
      });
      setSelectedPlugin(null);
    }
    setChangedSecrets(new Set());
  }, [open, editing, plugins, form]);

  const handlePluginChange = useCallback(
    (pluginName: string) => {
      const plugin = plugins.find((p) => p.name === pluginName) ?? null;
      setSelectedPlugin(plugin);

      const paramValues: Record<string, string> = {};
      if (plugin) {
        for (const field of plugin.config_schema) {
          if (field.default !== undefined) {
            paramValues[field.key] = String(field.default);
          } else {
            paramValues[field.key] = "";
          }
        }
      }
      form.setFieldsValue({ params: paramValues });
    },
    [plugins, form]
  );

  const handleSecretChange = useCallback((key: string) => {
    setChangedSecrets((prev) => new Set(prev).add(key));
  }, []);

  const schemaFields = useMemo(
    () => selectedPlugin?.config_schema ?? [],
    [selectedPlugin]
  );

  const handleSave = async (shouldTest = false) => {
    try {
      const values = await form.validateFields();
      setSaving(true);

      const params: Record<string, string> = {};
      params["plugin.name"] = values.plugin_name;

      for (const field of schemaFields) {
        const rawValue = values.params?.[field.key];
        const storageKey = `plugin.${field.key}`;
        if (field.type === "secret" && isEditing) {
          if (rawValue === SECRET_MASK && !changedSecrets.has(field.key)) {
            continue;
          }
          if (rawValue !== undefined && rawValue !== "") {
            params[storageKey] = rawValue;
          }
        } else if (field.type === "boolean") {
          params[storageKey] = rawValue ? "true" : "false";
        } else if (rawValue !== undefined && rawValue !== "") {
          params[storageKey] = String(rawValue);
        }
      }

      if (isEditing) {
        const provider = await updateProvider(editing.provider_config_id, {
          provider_name: values.provider_name,
          enabled: values.enabled,
          timeout_seconds: values.timeout_seconds,
          params,
        });
        message.success(t("memory.external.form.updated"));
        onSaved(provider, shouldTest);
      } else {
        const provider = await createProvider({
          provider_name: values.provider_name,
          connection_type: "plugin",
          enabled: values.enabled,
          timeout_seconds: values.timeout_seconds,
          params,
        });
        message.success(t("memory.external.form.created"));
        onSaved(provider, shouldTest);
      }
    } catch (err: unknown) {
      if (err && typeof err === "object" && "errorFields" in err) {
        return;
      }
      message.error(
        isEditing
          ? t("memory.external.form.updateFailed")
          : t("memory.external.form.createFailed")
      );
    } finally {
      setSaving(false);
    }
  };

  const renderDynamicField = (field: ConfigSchemaField) => {
    const fieldLabel = field.required ? (
      <>
        {field.label} <span style={{ color: "#ff4d4f" }}>*</span>
      </>
    ) : (
      field.label
    );
    const requiredRules = field.required
      ? [
          {
            required: true,
            message: t("memory.external.form.fieldRequired", {
              label: field.label,
            }),
          },
        ]
      : [];

    const isSecretEditing =
      field.type === "secret" && isEditing && !changedSecrets.has(field.key);

    switch (field.type) {
      case "secret":
        return (
          <Form.Item
            key={field.key}
            name={["params", field.key]}
            label={
              field.required ? (
                <>
                  {field.label} <span style={{ color: "#ff4d4f" }}>*</span>
                </>
              ) : (
                field.label
              )
            }
            rules={
              field.required && !isSecretEditing
                ? [
                    {
                      required: true,
                      message: t("memory.external.form.fieldRequired", {
                        label: field.label,
                      }),
                    },
                  ]
                : []
            }
          >
            <Input.Password
              placeholder={
                isSecretEditing
                  ? SECRET_MASK
                  : t("memory.external.form.fieldPlaceholder", {
                      label: field.label,
                    })
              }
              onChange={() => handleSecretChange(field.key)}
            />
          </Form.Item>
        );

      case "number":
        return (
          <Form.Item
            key={field.key}
            name={["params", field.key]}
            label={
              field.required ? (
                <>
                  {field.label} <span style={{ color: "#ff4d4f" }}>*</span>
                </>
              ) : (
                field.label
              )
            }
            rules={[
              ...(field.required
                ? [
                    {
                      required: true,
                      message: t("memory.external.form.fieldRequired", {
                        label: field.label,
                      }),
                    },
                  ]
                : []),
              {
                type: "number",
                message: t("memory.external.form.fieldNumber", {
                  label: field.label,
                }),
                transform: (value: string) =>
                  value === "" || value === undefined
                    ? undefined
                    : Number(value),
              },
            ]}
          >
            <InputNumber style={{ width: "100%" }} />
          </Form.Item>
        );

      case "boolean":
        return (
          <Form.Item
            key={field.key}
            name={["params", field.key]}
            label={field.label}
            valuePropName="checked"
            getValueFromEvent={(checked: boolean) =>
              checked ? "true" : "false"
            }
            getValueProps={(value: string) => ({
              checked: value === "true",
            })}
          >
            <Checkbox />
          </Form.Item>
        );

      case "select":
        return (
          <Form.Item
            key={field.key}
            name={["params", field.key]}
            label={fieldLabel}
            rules={requiredRules}
          >
            <Select
              placeholder={t("memory.external.form.fieldSelect", {
                label: field.label,
              })}
              options={field.options ?? []}
            />
          </Form.Item>
        );

      default:
        return (
          <Form.Item
            key={field.key}
            name={["params", field.key]}
            label={fieldLabel}
            rules={requiredRules}
          >
            <Input
              placeholder={t("memory.external.form.fieldPlaceholder", {
                label: field.label,
              })}
            />
          </Form.Item>
        );
    }
  };

  return (
    <Drawer
      open={open}
      title={
        isEditing
          ? t("memory.external.form.editTitle")
          : t("memory.external.form.addTitle")
      }
      onClose={onClose}
      destroyOnHidden
      width={680}
      extra={
        <Button onClick={onClose}>{t("memory.external.actions.cancel")}</Button>
      }
      footer={
        <div className="external-provider-drawer-footer">
          <Button onClick={onClose}>
            {t("memory.external.actions.cancel")}
          </Button>
          <Button loading={saving} onClick={() => void handleSave(true)}>
            {t("memory.external.form.saveAndTest")}
          </Button>
          <Button
            type="primary"
            loading={saving}
            onClick={() => void handleSave(false)}
          >
            {t("memory.external.actions.save")}
          </Button>
        </div>
      }
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        style={{ paddingTop: 12 }}
        initialValues={{ enabled: false, timeout_seconds: 30, params: {} }}
      >
        <Divider titlePlacement="start">
          {t("memory.external.form.providerSection")}
        </Divider>
        <Form.Item
          name="provider_name"
          label={t("memory.external.form.providerName")}
          rules={[
            {
              required: true,
              message: t("memory.external.form.providerNameRequired"),
            },
            {
              whitespace: true,
              message: t("memory.external.form.providerNameRequired"),
            },
          ]}
        >
          <Input
            placeholder={t("memory.external.form.providerNamePlaceholder")}
          />
        </Form.Item>

        <Form.Item
          name="plugin_name"
          label={t("memory.external.form.plugin")}
          rules={[
            {
              required: true,
              message: t("memory.external.form.pluginRequired"),
            },
          ]}
        >
          <Select
            placeholder={t("memory.external.form.pluginPlaceholder")}
            loading={pluginsLoading}
            disabled={isEditing}
            onChange={handlePluginChange}
            options={plugins.map((p) => ({
              value: p.name,
              label: `${p.name} (v${p.version})`,
            }))}
          />
        </Form.Item>

        <Divider titlePlacement="start">
          {t("memory.external.form.connectionSection")}
        </Divider>
        <Form.Item
          name="timeout_seconds"
          label={t("memory.external.form.timeout")}
          rules={[
            {
              required: true,
              message: t("memory.external.form.timeoutRequired"),
            },
            {
              type: "number",
              min: 1,
              max: 300,
              message: t("memory.external.form.timeoutRange"),
            },
          ]}
        >
          <InputNumber style={{ width: "100%" }} min={1} max={300} />
        </Form.Item>

        {schemaFields.map(renderDynamicField)}
        <Divider titlePlacement="start">
          {t("memory.external.form.activationSection")}
        </Divider>
        <Form.Item
          name="enabled"
          label={t("memory.external.form.enabled")}
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>
        <Typography.Text type="secondary">
          {t("memory.external.form.masterSwitchHint")}
        </Typography.Text>
      </Form>
    </Drawer>
  );
}
