"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  App,
  Checkbox,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Switch,
} from "antd";

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
  onSaved: () => void;
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
      .catch(() => message.error("Failed to load plugins"))
      .finally(() => setPluginsLoading(false));
  }, [open, message]);

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

  const handleSave = async () => {
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
        await updateProvider(editing.provider_config_id, {
          provider_name: values.provider_name,
          enabled: values.enabled,
          timeout_seconds: values.timeout_seconds,
          params,
        });
        message.success("Provider updated");
      } else {
        await createProvider({
          provider_name: values.provider_name,
          connection_type: "plugin",
          enabled: values.enabled,
          timeout_seconds: values.timeout_seconds,
          params,
        });
        message.success("Provider created");
      }
      onSaved();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "errorFields" in err) {
        return;
      }
      message.error(isEditing ? "Failed to update provider" : "Failed to create provider");
    } finally {
      setSaving(false);
    }
  };

  const renderDynamicField = (field: ConfigSchemaField) => {
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
                ? [{ required: true, message: `${field.label} is required` }]
                : []
            }
          >
            <Input.Password
              placeholder={isSecretEditing ? SECRET_MASK : `Enter ${field.label}`}
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
                ? [{ required: true, message: `${field.label} is required` }]
                : []),
              {
                type: "number",
                message: `${field.label} must be a valid number`,
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
              field.required
                ? [{ required: true, message: `${field.label} is required` }]
                : []
            }
          >
            <Select
              placeholder={`Select ${field.label}`}
              options={field.options ?? []}
            />
          </Form.Item>
        );

      default:
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
              field.required
                ? [{ required: true, message: `${field.label} is required` }]
                : []
            }
          >
            <Input placeholder={`Enter ${field.label}`} />
          </Form.Item>
        );
    }
  };

  return (
    <Modal
      open={open}
      centered
      title={isEditing ? "Edit Provider" : "Add Provider"}
      okText={isEditing ? "Save Changes" : "Create"}
      cancelText="Cancel"
      confirmLoading={saving}
      onOk={handleSave}
      onCancel={onClose}
      destroyOnHidden
      width={560}
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        style={{ paddingTop: 12 }}
        initialValues={{ enabled: false, timeout_seconds: 30, params: {} }}
      >
        <Form.Item
          name="provider_name"
          label="Provider Name"
          rules={[
            { required: true, message: "Provider name is required" },
            { whitespace: true, message: "Provider name cannot be empty" },
          ]}
        >
          <Input placeholder="Enter provider name" />
        </Form.Item>

        <Form.Item
          name="plugin_name"
          label="Plugin"
          rules={[{ required: true, message: "Plugin is required" }]}
        >
          <Select
            placeholder="Select a plugin"
            loading={pluginsLoading}
            disabled={isEditing}
            onChange={handlePluginChange}
            options={plugins.map((p) => ({
              value: p.name,
              label: `${p.name} (v${p.version})`,
            }))}
          />
        </Form.Item>

        <Form.Item name="enabled" label="Enabled" valuePropName="checked">
          <Switch />
        </Form.Item>

        <Form.Item
          name="timeout_seconds"
          label="Timeout (seconds)"
          rules={[
            { required: true, message: "Timeout is required" },
            {
              type: "number",
              min: 1,
              max: 300,
              message: "Timeout must be between 1 and 300 seconds",
            },
          ]}
        >
          <InputNumber style={{ width: "100%" }} min={1} max={300} />
        </Form.Item>

        {schemaFields.length > 0 && (
          <div style={{ borderTop: "1px solid #f0f0f0", paddingTop: 16, marginTop: 8 }}>
            {schemaFields.map(renderDynamicField)}
          </div>
        )}
      </Form>
    </Modal>
  );
}
