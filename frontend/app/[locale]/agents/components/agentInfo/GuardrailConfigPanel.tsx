"use client";

import { useState, useMemo, useCallback } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { theme } from "antd";
import {
  Button,
  Input,
  Select,
  Table,
  Space,
  Popconfirm,
  Typography,
  Switch,
  Tag,
  Tooltip,
  Empty,
  Checkbox,
  Collapse,
} from "antd";
import {
  Plus,
  Copy,
  Trash2,
  ShieldCheck,
  ShieldOff,
  ShieldAlert,
  Info,
  AlertTriangle,
  FlaskConical,
  X,
  ChevronDown,
} from "lucide-react";
import type { ColumnsType } from "antd/es/table";

import type {
  GuardrailConfig,
  GuardrailRule,
  GuardrailSeverity,
} from "@/types/agentConfig";
import { DEFAULT_GUARDRAIL_RULES } from "@/types/agentConfig";

const { Text } = Typography;

// Severity visual config — color-coded tags for at-a-glance scanning
const SEVERITY_META: Record<
  GuardrailSeverity,
  { color: string; icon: ReactNode }
> = {
  block: { color: "error", icon: <ShieldOff /> },
  mask: { color: "warning", icon: <ShieldAlert /> },
  pass: { color: "success", icon: <ShieldCheck /> },
};

const SEVERITY_OPTIONS: { value: GuardrailSeverity; label: string }[] = [
  { value: "block", label: "Block" },
  { value: "mask", label: "Mask" },
  { value: "pass", label: "Pass" },
];

interface GuardrailConfigPanelProps {
  config: GuardrailConfig;
  onChange: (config: GuardrailConfig) => void;
}

export default function GuardrailConfigPanel({
  config,
  onChange,
}: GuardrailConfigPanelProps) {
  // --- antd theme tokens for dark/light theme compatibility ---
  const { token } = theme.useToken();
  const { t } = useTranslation("common");
  const [restoreConfirmOpen, setRestoreConfirmOpen] = useState(false);
  const [selectedKeys, setSelectedKeys] = useState<number[]>([]);
  const [batchSeverityOpen, setBatchSeverityOpen] = useState(false);
  const [testText, setTestText] = useState("");
  const [testCollapsed, setTestCollapsed] = useState(true);

  // Derived state

  const duplicateNames = useMemo(() => {
    const counts = new Map<string, number>();
    config.rules.forEach((r) => counts.set(r.name, (counts.get(r.name) || 0) + 1));
    const dupes = new Set<string>();
    counts.forEach((count, name) => {
      if (count > 1) dupes.add(name);
    });
    return dupes;
  }, [config.rules]);

  const severityCounts = useMemo(() => {
    const counts: Record<GuardrailSeverity, number> = { block: 0, mask: 0, pass: 0 };
    config.rules.forEach((r) => {
      counts[r.severity] = (counts[r.severity] || 0) + 1;
    });
    return counts;
  }, [config.rules]);

  // Handlers

  const handleToggle = useCallback((enabled: boolean) => {
    onChange({ ...config, enabled });
  }, [config, onChange]);

  const handleAddRule = useCallback(() => {
    const newRule: GuardrailRule = {
      name: `rule_${Date.now()}`,
      pattern: "",
      severity: "block",
      description: "",
    };
    onChange({ ...config, rules: [...config.rules, newRule] });
  }, [config, onChange]);

  const handleDeleteRule = useCallback((index: number) => {
    const newRules = config.rules.filter((_, i) => i !== index);
    onChange({ ...config, rules: newRules });
    setSelectedKeys((prev) => prev.filter((k) => k !== index));
  }, [config, onChange]);

  const handleDuplicateRule = useCallback((index: number) => {
    const original = config.rules[index];
    const newRule: GuardrailRule = { ...original, name: `${original.name}_copy` };
    const newRules = [...config.rules];
    newRules.splice(index + 1, 0, newRule);
    onChange({ ...config, rules: newRules });
  }, [config, onChange]);

  const handleUpdateRule = useCallback(
    (index: number, field: keyof GuardrailRule, value: string) => {
      const newRules = [...config.rules];
      newRules[index] = { ...newRules[index], [field]: value };
      onChange({ ...config, rules: newRules });
    },
    [config, onChange]
  );

  const handleRestoreDefaults = useCallback(() => {
    onChange({ ...config, rules: [...DEFAULT_GUARDRAIL_RULES] });
    setRestoreConfirmOpen(false);
    setSelectedKeys([]);
  }, [config, onChange]);

  const handleBatchDelete = useCallback(() => {
    const newRules = config.rules.filter((_, i) => !selectedKeys.includes(i));
    onChange({ ...config, rules: newRules });
    setSelectedKeys([]);
  }, [config, onChange, selectedKeys]);

  const handleBatchSeverity = useCallback(
    (severity: GuardrailSeverity) => {
      const newRules = config.rules.map((rule, i) =>
        selectedKeys.includes(i) ? { ...rule, severity } : rule
      );
      onChange({ ...config, rules: newRules });
      setBatchSeverityOpen(false);
    },
    [config, onChange, selectedKeys]
  );

  // Regex validation

  const validatePattern = useCallback((pattern: string): string | null => {
    if (!pattern.trim()) return null;
    try {
      // eslint-disable-next-line no-new
      new RegExp(pattern);
      return null;
    } catch {
      return t("agent.guardrail.invalidPattern") || "Invalid regex";
    }
  }, [t]);

  // Regex test preview

  interface TestMatch {
    ruleIndex: number;
    ruleName: string;
    severity: GuardrailSeverity;
    matchText: string;
    matchStart: number;
    matchEnd: number;
  }

  const testMatches: TestMatch[] = useMemo(() => {
    if (!testText.trim()) return [];
    const matches: TestMatch[] = [];
    config.rules.forEach((rule, idx) => {
      if (!rule.pattern.trim()) return;
      try {
        const re = new RegExp(rule.pattern, "g");
        let m: RegExpExecArray | null;
        while ((m = re.exec(testText)) !== null) {
          matches.push({
            ruleIndex: idx,
            ruleName: rule.name,
            severity: rule.severity,
            matchText: m[0],
            matchStart: m.index,
            matchEnd: m.index + m[0].length,
          });
          if (m.index === re.lastIndex) re.lastIndex++;
        }
      } catch {
        // Invalid regex, skip
      }
    });
    return matches;
  }, [testText, config.rules]);

  const renderTestPreview = () => {
    if (!testText.trim()) return null;
    if (testMatches.length === 0) {
      return (
        <Text type="secondary" style={{ fontSize: 12 }}>
          {t("agent.guardrail.testNoMatch") || "No matches — input is safe under current rules."}
        </Text>
      );
    }

    const sorted = [...testMatches].sort((a, b) => a.matchStart - b.matchStart);
    const segments: ReactNode[] = [];
    let cursor = 0;

    sorted.forEach((match, i) => {
      if (match.matchStart > cursor) {
        segments.push(
          <span key={`plain-${i}`}>{testText.slice(cursor, match.matchStart)}</span>
        );
      }
      const severityColor =
        match.severity === "block" ? token.colorError :
        match.severity === "mask" ? token.colorWarning :
        token.colorSuccess;
      const severityBg =
        match.severity === "block" ? token.colorErrorBg :
        match.severity === "mask" ? token.colorWarningBg :
        token.colorSuccessBg;

      segments.push(
        <Tooltip key={`match-${i}`} title={`${match.ruleName} → ${match.severity}`}>
          <mark
            style={{
              backgroundColor: severityBg,
              color: severityColor,
              borderBottom: `2px solid ${severityColor}`,
              padding: "1px 2px",
              borderRadius: 2,
              cursor: "default",
            }}
          >
            {match.matchText}
          </mark>
        </Tooltip>
      );
      cursor = Math.max(cursor, match.matchEnd);
    });

    if (cursor < testText.length) {
      segments.push(<span key="trailing">{testText.slice(cursor)}</span>);
    }

    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div
          style={{
            padding: "8px 12px",
            background: token.colorFillQuaternary,
            border: `1px solid ${token.colorBorderSecondary}`,
            borderRadius: token.borderRadius,
            lineHeight: 1.8,
            wordBreak: "break-all",
            fontSize: 13,
          }}
        >
          {segments}
        </div>
        <Space size={4} wrap>
          {Object.entries(
            testMatches.reduce<Record<string, number>>((acc, m) => {
              acc[m.ruleName] = (acc[m.ruleName] || 0) + 1;
              return acc;
            }, {})
          ).map(([name, count]) => {
            const firstMatch = testMatches.find((m) => m.ruleName === name)!;
            const meta = SEVERITY_META[firstMatch.severity];
            return (
              <Tag key={name} color={meta?.color} style={{ margin: 0, fontSize: 11 }}>
                {name} ×{count}
              </Tag>
            );
          })}
        </Space>
      </div>
    );
  };

  // Table columns

  const columns: ColumnsType<GuardrailRule & { key: number }> = [
    {
      title: (
        <Tooltip title={t("agent.guardrail.tooltip.name") || "Unique identifier for this rule"}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4, flexShrink: 0, whiteSpace: "nowrap" }}>
            {t("agent.guardrail.column.name") || "Name"} <Info size={12} style={{ opacity: 0.4, flexShrink: 0 }} />
          </span>
        </Tooltip>
      ),
      dataIndex: "name",
      width: 150,
      render: (_, record, index) => {
        const isDuplicate = duplicateNames.has(record.name);
        return (
          <Tooltip
            open={isDuplicate ? undefined : false}
            title={isDuplicate ? (t("agent.guardrail.duplicateName") || "Duplicate name") : ""}
          >
            <Input
              value={record.name}
              size="small"
              status={isDuplicate ? "warning" : ""}
              suffix={isDuplicate ? <AlertTriangle size={12} style={{ color: token.colorWarning }} /> : undefined}
              onChange={(e) => handleUpdateRule(index, "name", e.target.value)}
            />
          </Tooltip>
        );
      },
    },
    {
      title: (
        <Tooltip title={t("agent.guardrail.tooltip.pattern") || "Python re syntax. First match wins."}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4, flexShrink: 0, whiteSpace: "nowrap" }}>
            {t("agent.guardrail.column.pattern") || "Pattern (regex)"} <Info size={12} style={{ opacity: 0.4, flexShrink: 0 }} />
          </span>
        </Tooltip>
      ),
      dataIndex: "pattern",
      render: (_, record, index) => {
        const error = validatePattern(record.pattern);
        return (
          <div>
            <Input
              value={record.pattern}
              size="small"
              status={error ? "error" : ""}
              placeholder={t("agent.guardrail.patternPlaceholder") || "e.g. \\d{17}[\\dXx]"}
              onChange={(e) => handleUpdateRule(index, "pattern", e.target.value)}
            />
            {error && (
              <Text type="danger" style={{ fontSize: 11 }}>
                {error}
              </Text>
            )}
          </div>
        );
      },
    },
    {
      title: (
        <Tooltip title={t("agent.guardrail.tooltip.severity") || "block=terminate/blocked, mask=redacted, pass=logged only"}>
          <span style={{ display: "inline-flex", alignItems: "center", gap: 4, flexShrink: 0, whiteSpace: "nowrap" }}>
            {t("agent.guardrail.column.severity") || "Severity"} <Info size={12} style={{ opacity: 0.4, flexShrink: 0 }} />
          </span>
        </Tooltip>
      ),
      dataIndex: "severity",
      width: 110,
      render: (_, record, index) => (
        <Select
          value={record.severity}
          size="small"
          style={{ width: "100%" }}
          options={SEVERITY_OPTIONS}
          tagRender={(props) => {
            const meta = SEVERITY_META[props.value as GuardrailSeverity];
            return (
              <Tag color={meta?.color} icon={meta?.icon} style={{ margin: 0 }}>
                {props.label}
              </Tag>
            );
          }}
          onChange={(value) =>
            handleUpdateRule(index, "severity", value as GuardrailSeverity)
          }
        />
      ),
    },
    {
      title: t("agent.guardrail.column.description") || "Description",
      dataIndex: "description",
      width: 200,
      render: (_, record, index) => (
        <Input
          value={record.description || ""}
          size="small"
          onChange={(e) => handleUpdateRule(index, "description", e.target.value)}
        />
      ),
    },
    {
      title: "",
      width: 100,
      render: (_, _record, index) => (
        <Space size={8}>
          <Tooltip title={t("agent.guardrail.duplicate") || "Duplicate"}>
            <Button
              size="small"
              type="text"
              icon={<Copy size={16} />}
              onClick={() => handleDuplicateRule(index)}
            />
          </Tooltip>
          <Popconfirm
            title={t("agent.guardrail.confirmDelete") || "Delete this rule?"}
            onConfirm={() => handleDeleteRule(index)}
          >
            <Tooltip title={t("agent.guardrail.delete") || "Delete"}>
              <Button size="small" type="text" danger icon={<Trash2 size={16} />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // Severity summary bar — placed above table, not in title row

  const renderSeveritySummary = () => {
    if (config.rules.length === 0) return null;
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "4px 0",
          marginBottom: 8,
        }}
      >
        <Text type="secondary" style={{ fontSize: 11 }}>
          {t("agent.guardrail.severitySummary") || "Distribution:"}
        </Text>
        {severityCounts.block > 0 && (
          <Tag color="error" style={{ margin: 0, fontSize: 11 }}>
            {t("agent.guardrail.severity.block") || "Block"} {severityCounts.block}
          </Tag>
        )}
        {severityCounts.mask > 0 && (
          <Tag color="warning" style={{ margin: 0, fontSize: 11 }}>
            {t("agent.guardrail.severity.mask") || "Mask"} {severityCounts.mask}
          </Tag>
        )}
        {severityCounts.pass > 0 && (
          <Tag color="success" style={{ margin: 0, fontSize: 11 }}>
            {t("agent.guardrail.severity.pass") || "Pass"} {severityCounts.pass}
          </Tag>
        )}
      </div>
    );
  };

  // Batch operation bar

  const renderBatchBar = () => {
    if (selectedKeys.length === 0) return null;
    return (
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          padding: "6px 12px",
          background: token.colorInfoBg,
          borderRadius: token.borderRadius,
          marginBottom: 8,
        }}
      >
        <Text strong style={{ fontSize: 12 }}>
          {t("agent.guardrail.batch.selected") || "Selected"} {selectedKeys.length}
        </Text>
        <Select
          size="small"
          style={{ width: 120 }}
          placeholder={t("agent.guardrail.batch.setSeverity") || "Set severity"}
          open={batchSeverityOpen}
          onDropdownVisibleChange={setBatchSeverityOpen}
          options={SEVERITY_OPTIONS}
          onChange={(v) => handleBatchSeverity(v as GuardrailSeverity)}
          tagRender={(props) => {
            const meta = SEVERITY_META[props.value as GuardrailSeverity];
            return (
              <Tag color={meta?.color} style={{ margin: 0 }}>
                {props.label}
              </Tag>
            );
          }}
        />
        <Popconfirm
          title={t("agent.guardrail.batch.confirmDelete") || `Delete ${selectedKeys.length} selected rules?`}
          onConfirm={handleBatchDelete}
        >
          <Button size="small" danger icon={<Trash2 size={12} />}>
            {t("agent.guardrail.batch.delete") || "Delete"}
          </Button>
        </Popconfirm>
        <Button
          size="small"
          type="text"
          icon={<X size={12} />}
          onClick={() => setSelectedKeys([])}
        >
          {t("agent.guardrail.batch.clear") || "Cancel"}
        </Button>
      </div>
    );
  };

  // Render — no Card wrapper (parent Form.Item already provides the shell)

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
      {/* --- Header row: switch + title + count + actions --- */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 12,
          padding: "8px 0",
        }}
      >
        <Space>
          <Switch
            checked={config.enabled}
            onChange={handleToggle}
            size="small"
          />
          <Text strong>
            {t("agent.guardrail.title") || "Guardrail Rules"}
          </Text>
          {config.enabled && config.rules.length > 0 && (
            <Tag color="blue" style={{ marginInlineStart: 4 }}>
              {config.rules.length} {t("agent.guardrail.rulesCount") || "rules"}
            </Tag>
          )}
        </Space>
        {config.enabled && (
          <Space>
            <Button
              size="small"
              icon={<Plus size={14} />}
              onClick={handleAddRule}
            >
              {t("agent.guardrail.addRule") || "Add Rule"}
            </Button>
            <Popconfirm
              title={t("agent.guardrail.confirmRestore") || "This will replace all current rules with defaults. Continue?"}
              open={restoreConfirmOpen}
              onConfirm={handleRestoreDefaults}
              onCancel={() => setRestoreConfirmOpen(false)}
              onOpenChange={setRestoreConfirmOpen}
              okText={t("agent.guardrail.confirm") || "OK"}
              cancelText={t("agent.guardrail.cancel") || "Cancel"}
            >
              <Button size="small">
                {t("agent.guardrail.restoreDefaults") || "Restore Defaults"}
              </Button>
            </Popconfirm>
          </Space>
        )}
      </div>

      {/* --- Body: collapsed when disabled --- */}
      {!config.enabled ? null : config.rules.length === 0 ? (
        <Empty
          image={<ShieldCheck style={{ fontSize: 40, color: token.colorTextDisabled }} />}
          description={
            <span>
              {t("agent.guardrail.empty") || "No rules configured. Click 'Add Rule' or 'Restore Defaults'."}
            </span>
          }
        >
          <Space>
            <Button size="small" icon={<Plus size={14} />} onClick={handleAddRule}>
              {t("agent.guardrail.addRule") || "Add Rule"}
            </Button>
            <Button size="small" onClick={handleRestoreDefaults}>
              {t("agent.guardrail.restoreDefaults") || "Restore Defaults"}
            </Button>
          </Space>
        </Empty>
      ) : (
        <>
          {renderSeveritySummary()}
          {renderBatchBar()}
          <Table
            dataSource={config.rules.map((rule, index) => ({ ...rule, key: index }))}
            columns={columns}
            pagination={false}
            size="small"
            scroll={{ x: 700 }}
            rowSelection={{
              selectedRowKeys: selectedKeys,
              onChange: (keys) => setSelectedKeys(keys as number[]),
              columnWidth: 32,
            }}
          />
          {/* --- Collapsible regex test preview --- */}
          <div style={{ marginTop: 8 }}>
            <Collapse
              ghost
              activeKey={testCollapsed ? [] : ["test"]}
              onChange={() => setTestCollapsed((v) => !v)}
              items={[
                {
                  key: "test",
                  label: (
                    <Space size={6}>
                      <FlaskConical size={14} style={{ opacity: 0.5 }} />
                      <Text strong style={{ fontSize: 13 }}>
                        {t("agent.guardrail.testTitle") || "Regex Test Preview"}
                      </Text>
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        {t("agent.guardrail.testHint") || "Paste sample text to see which rules match"}
                      </Text>
                    </Space>
                  ),
                  children: (
                    <>
                      <Input.TextArea
                        value={testText}
                        onChange={(e) => setTestText(e.target.value)}
                        placeholder={t("agent.guardrail.testPlaceholder") || "e.g. My phone is 13812345678 and email is test@example.com"}
                        autoSize={{ minRows: 2, maxRows: 4 }}
                        style={{ fontSize: 13 }}
                      />
                      <div style={{ marginTop: 8 }}>
                        {renderTestPreview()}
                      </div>
                    </>
                  ),
                },
              ]}
            />
          </div>
        </>
      )}
    </div>
  );
}
