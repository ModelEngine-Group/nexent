"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { theme, App } from "antd";
import {
  Modal,
  Button,
  Input,
  Select,
  Space,
  Popconfirm,
  Typography,
  Tag,
  Tooltip,
  Empty,
  Checkbox,
  Spin,
  Table,
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
  Sparkles,
  X,
} from "lucide-react";
import type { ColumnsType } from "antd/es/table";

import type {
  GuardrailConfig,
  GuardrailRule,
  GuardrailSeverity,
} from "@/types/agentConfig";
import type { ModelOption } from "@/types/modelConfig";
import { generateGuardrailRules } from "@/services/promptService";

const { Text, Paragraph } = Typography;

// Compile a guardrail regex, tolerating Python-style inline flags (?i)(?m)(?s)
// that JS RegExp rejects inline — strip them and pass as flags so the preview
// behaves the same way the backend (Python re) treats them.
function compileGuardrailRegex(pattern: string, baseFlags = ""): RegExp | null {
  let src = pattern;
  let flags = baseFlags;
  let m = src.match(/^\(\?([imsx]+)\)/);
  while (m) {
    const inline = m[1];
    if (inline.includes("i") && !flags.includes("i")) flags += "i";
    if (inline.includes("m") && !flags.includes("m")) flags += "m";
    if (inline.includes("s") && !flags.includes("s")) flags += "s";
    src = src.slice(m[0].length);
    m = src.match(/^\(\?([imsx]+)\)/);
  }
  try {
    return new RegExp(src, flags);
  } catch {
    return null;
  }
}

const SEVERITY_META: Record<
  GuardrailSeverity,
  { color: string; icon: ReactNode }
> = {
  block: { color: "error", icon: <ShieldOff /> },
  mask: { color: "warning", icon: <ShieldAlert /> },
  pass: { color: "success", icon: <ShieldCheck /> },
};

// SEVERITY_OPTIONS is built inside the component to access i18n t().
// See `useSeverityOptions` hook below.

// AI result types returned from backend
interface AiCandidate {
  pattern: string;
  desc: string;
}

interface AiRuleSuggestion {
  name: string;
  pattern: string;
  severity: GuardrailSeverity;
  desc: string;
}

type AiResult =
  | { type: "single"; candidates: AiCandidate[] }
  | { type: "multi"; rules: AiRuleSuggestion[] };

interface GuardrailConfigModalProps {
  open: boolean;
  config: GuardrailConfig;
  onChange: (config: GuardrailConfig) => void;
  onClose: () => void;
  llmModels: ModelOption[];
  defaultModelId?: number;
}

// Sub-component for multi-rule AI result rendering — keeps useState at top level.
function AiMultiResult({
  rules,
  onImport,
  onDiscard,
}: {
  rules: AiRuleSuggestion[];
  onImport: (selected: AiRuleSuggestion[]) => void;
  onDiscard: () => void;
}) {
  const { token } = theme.useToken();
  const { t } = useTranslation("common");
  const [checkedIndices, setCheckedIndices] = useState<Set<number>>(
    () => new Set(rules.map((_, i) => i))
  );

  const severityLabel = (sev: GuardrailSeverity) =>
    t(`agent.guardrail.severity.${sev}`) || sev;

  const toggle = (i: number, checked: boolean) => {
    setCheckedIndices((prev) => {
      const next = new Set(prev);
      if (checked) next.add(i);
      else next.delete(i);
      return next;
    });
  };

  return (
    <div>
      <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 8, fontWeight: 500 }}>
        {t("agent.guardrail.ai.multiHint") || "AI detected multiple rules. Select ones to import:"}
      </Text>
      <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 10 }}>
        {rules.map((rule, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              gap: 10,
              alignItems: "flex-start",
              padding: "10px 12px",
              border: `0.5px solid ${token.colorBorderSecondary}`,
              borderRadius: 8,
              background: token.colorBgContainer,
            }}
          >
            <Checkbox
              checked={checkedIndices.has(i)}
              onChange={(e) => toggle(i, e.target.checked)}
              style={{ marginTop: 4 }}
            />
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 3 }}>
                <Text style={{ fontSize: 12, fontWeight: 500 }}>{rule.name}</Text>
                <Tag color={SEVERITY_META[rule.severity].color} style={{ margin: 0 }}>
                  {severityLabel(rule.severity)}
                </Tag>
              </div>
              <code style={{ fontSize: 11, color: "#042C53", wordBreak: "break-all" }}>
                {rule.pattern}
              </code>
              {rule.desc && (
                <Text type="secondary" style={{ fontSize: 11, display: "block", marginTop: 2 }}>
                  {rule.desc}
                </Text>
              )}
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
        <Button size="small" onClick={onDiscard}>
          {t("agent.guardrail.ai.discard") || "Discard"}
        </Button>
        <Button
          size="small"
          type="primary"
          disabled={checkedIndices.size === 0}
          onClick={() => {
            const selected = rules.filter((_, i) => checkedIndices.has(i));
            onImport(selected);
          }}
        >
          {t("agent.guardrail.ai.import") || "Import"} ({checkedIndices.size})
        </Button>
      </div>
    </div>
  );
}

export default function GuardrailConfigModal({
  open,
  config,
  onChange,
  onClose,
  llmModels,
  defaultModelId,
}: GuardrailConfigModalProps) {
  const { token } = theme.useToken();
  const { t } = useTranslation("common");
  const { message } = App.useApp();

  // --- Draft state: all edits target draft, only committed on save ---
  const [draft, setDraft] = useState<GuardrailConfig>(config);
  const [selectedKeys, setSelectedKeys] = useState<number[]>([]);
  const [testText, setTestText] = useState("");

  // --- AI generation state ---
  const [aiInput, setAiInput] = useState("");
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<AiResult | null>(null);
  const [aiModelId, setAiModelId] = useState<number | undefined>(defaultModelId);
  const [focusedPatternIndex, setFocusedPatternIndex] = useState<number | null>(null);

  // Sync draft when modal opens
  useEffect(() => {
    if (open) {
      setDraft(config);
      setAiInput("");
      setAiResult(null);
      setAiLoading(false);
      setSelectedKeys([]);
      setTestText("");
    }
  }, [open, config]);

  // Sync aiModelId with defaultModelId
  useEffect(() => {
    if (defaultModelId !== undefined && aiModelId === undefined) {
      setAiModelId(defaultModelId);
    }
  }, [defaultModelId, aiModelId]);

  // --- Derived state ---

  const duplicateNames = useMemo(() => {
    const counts = new Map<string, number>();
    draft.rules.forEach((r) => counts.set(r.name, (counts.get(r.name) || 0) + 1));
    const dupes = new Set<string>();
    counts.forEach((count, name) => {
      if (count > 1) dupes.add(name);
    });
    return dupes;
  }, [draft.rules]);

  const severityCounts = useMemo(() => {
    const counts: Record<GuardrailSeverity, number> = { block: 0, mask: 0, pass: 0 };
    draft.rules.forEach((r) => {
      counts[r.severity] = (counts[r.severity] || 0) + 1;
    });
    return counts;
  }, [draft.rules]);

  // Severity dropdown options — i18n aware
  const severityOptions = useMemo(
    () => [
      { value: "block" as const, label: t("agent.guardrail.severity.block") || "Block" },
      { value: "mask" as const, label: t("agent.guardrail.severity.mask") || "Mask" },
      { value: "pass" as const, label: t("agent.guardrail.severity.pass") || "Pass" },
    ],
    [t]
  );

  // Resolve a severity enum value to its localized label
  const severityLabel = useCallback(
    (sev: GuardrailSeverity) =>
      t(`agent.guardrail.severity.${sev}`) || sev,
    [t]
  );

  // --- Draft handlers (never call onChange directly) ---

  const updateDraft = useCallback((updater: (prev: GuardrailConfig) => GuardrailConfig) => {
    setDraft(updater);
  }, []);

  const handleToggle = useCallback((enabled: boolean) => {
    updateDraft((prev) => ({ ...prev, enabled }));
  }, [updateDraft]);

  const handleAddRule = useCallback(() => {
    const newRule: GuardrailRule = {
      name: `rule_${Date.now()}`,
      pattern: "",
      severity: "block",
      description: "",
    };
    updateDraft((prev) => ({ ...prev, rules: [...prev.rules, newRule] }));
  }, [updateDraft]);

  const handleDeleteRule = useCallback((index: number) => {
    updateDraft((prev) => ({
      ...prev,
      rules: prev.rules.filter((_, i) => i !== index),
    }));
    setSelectedKeys((prev) => prev.filter((k) => k !== index));
  }, [updateDraft]);

  const handleDuplicateRule = useCallback((index: number) => {
    updateDraft((prev) => {
      const original = prev.rules[index];
      const newRule: GuardrailRule = { ...original, name: `${original.name}_copy` };
      const newRules = [...prev.rules];
      newRules.splice(index + 1, 0, newRule);
      return { ...prev, rules: newRules };
    });
  }, [updateDraft]);

  const handleUpdateRule = useCallback(
    (index: number, field: keyof GuardrailRule, value: string) => {
      updateDraft((prev) => {
        const newRules = [...prev.rules];
        newRules[index] = { ...newRules[index], [field]: value };
        return { ...prev, rules: newRules };
      });
    },
    [updateDraft]
  );

  const handleBatchDelete = useCallback(() => {
    updateDraft((prev) => ({
      ...prev,
      rules: prev.rules.filter((_, i) => !selectedKeys.includes(i)),
    }));
    setSelectedKeys([]);
  }, [updateDraft, selectedKeys]);

  // --- Save: commit draft to parent ---
  const handleSave = useCallback(() => {
    onChange(draft);
    onClose();
  }, [draft, onChange, onClose]);

  // --- Regex validation ---

  const validatePattern = useCallback((pattern: string): string | null => {
    if (!pattern.trim()) return null;
    return compileGuardrailRegex(pattern)
      ? null
      : (t("agent.guardrail.invalidPattern") || "Invalid regex");
  }, [t]);

  // --- Regex test preview ---

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
    draft.rules.forEach((rule, idx) => {
      if (!rule.pattern.trim()) return;
      try {
        const re = compileGuardrailRegex(rule.pattern, "g");
        if (!re) return;
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
  }, [testText, draft.rules]);

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
        <Tooltip key={`match-${i}`} title={`${match.ruleName} → ${severityLabel(match.severity)}`}>
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
            border: `0.5px solid ${token.colorBorderSecondary}`,
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

  // --- AI generation ---

  const handleAiGenerate = useCallback(async () => {
    const desc = aiInput.trim();
    if (!desc) {
      message.warning(t("agent.guardrail.ai.descRequired") || "Please describe what you want to match");
      return;
    }
    if (aiModelId === undefined) {
      message.error(t("agent.guardrail.ai.modelRequired") || "Please select a model for AI generation");
      return;
    }

    setAiLoading(true);
    setAiResult(null);

    try {
      const data = await generateGuardrailRules({
        description: desc,
        model_id: aiModelId,
      });

      if (data?.type === "multi" && Array.isArray(data.rules)) {
        setAiResult({
          type: "multi",
          rules: data.rules.map((r) => ({
            name: r.name || `rule_${Date.now()}`,
            pattern: r.pattern || "",
            severity: ["block", "mask", "pass"].includes(r.severity as string)
              ? (r.severity as GuardrailSeverity)
              : "block",
            desc: r.desc || "",
          })),
        });
      } else if (data?.type === "single" && Array.isArray(data.candidates)) {
        setAiResult({
          type: "single",
          candidates: data.candidates.map((c) => ({
            pattern: c.pattern || "",
            desc: c.desc || "",
          })),
        });
      } else {
        message.error(t("agent.guardrail.ai.error") || "AI generation failed");
      }
    } catch (error: any) {
      message.error(error?.message || t("agent.guardrail.ai.error") || "AI generation failed");
    } finally {
      setAiLoading(false);
    }
  }, [aiInput, aiModelId, message, t]);

  const handleApplySingleCandidate = useCallback((pattern: string) => {
    // Fill into focused pattern row, or first empty row, or append new row
    updateDraft((prev) => {
      const newRules = [...prev.rules];
      let targetIndex = focusedPatternIndex;

      // If no focused row, find first empty pattern
      if (targetIndex === null || targetIndex === undefined) {
        targetIndex = newRules.findIndex((r) => !r.pattern.trim());
      }

      // If no empty row, append
      if (targetIndex === -1 || targetIndex === null) {
        newRules.push({
          name: `rule_${Date.now()}`,
          pattern,
          severity: "block",
          description: "",
        });
      } else if (targetIndex < newRules.length) {
        newRules[targetIndex] = { ...newRules[targetIndex], pattern };
      }

      return { ...prev, rules: newRules };
    });
    setAiInput("");
    setAiResult(null);
    setFocusedPatternIndex(null);
  }, [focusedPatternIndex, updateDraft]);

  const handleImportMultiRules = useCallback((selectedRules: AiRuleSuggestion[]) => {
    updateDraft((prev) => ({
      ...prev,
      rules: [
        ...prev.rules,
        ...selectedRules.map((r) => ({
          name: r.name,
          pattern: r.pattern,
          severity: r.severity,
          description: r.desc,
        })),
      ],
    }));
    setAiInput("");
    setAiResult(null);
  }, [updateDraft]);

  // --- Table columns ---

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
      width: 140,
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
              onFocus={() => setFocusedPatternIndex(index)}
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
          options={severityOptions}
          tagRender={(props) => {
            const meta = SEVERITY_META[props.value as GuardrailSeverity];
            return (
              <Tag color={meta?.color} icon={meta?.icon} style={{ margin: 0 }}>
                {severityLabel(props.value as GuardrailSeverity)}
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
      width: 180,
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
      width: 90,
      render: (_, _record, index) => (
        <Space size={6}>
          <Tooltip title={t("agent.guardrail.duplicate") || "Duplicate"}>
            <Button
              size="small"
              type="text"
              icon={<Copy size={14} />}
              onClick={() => handleDuplicateRule(index)}
            />
          </Tooltip>
          <Popconfirm
            title={t("agent.guardrail.confirmDelete") || "Delete this rule?"}
            onConfirm={() => handleDeleteRule(index)}
          >
            <Tooltip title={t("agent.guardrail.delete") || "Delete"}>
              <Button size="small" type="text" danger icon={<Trash2 size={14} />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  // --- AI result rendering ---

  const renderAiResult = () => {
    if (aiLoading) {
      return (
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 0" }}>
          <Spin size="small" />
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t("agent.guardrail.ai.analyzing") || "AI is analyzing your description..."}
          </Text>
        </div>
      );
    }

    if (!aiResult) return null;

    if (aiResult.type === "single") {
      return (
        <div>
          <Text type="secondary" style={{ fontSize: 11, display: "block", marginBottom: 8, fontWeight: 500 }}>
            {t("agent.guardrail.ai.singleHint") || "AI detected a single match. Choose a candidate:"}
          </Text>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {aiResult.candidates.map((cand, i) => (
              <div
                key={i}
                onClick={() => handleApplySingleCandidate(cand.pattern)}
                style={{
                  padding: "10px 12px",
                  border: `0.5px solid ${token.colorBorderSecondary}`,
                  borderRadius: 8,
                  background: token.colorBgContainer,
                  cursor: "pointer",
                  transition: "border-color 0.15s, box-shadow 0.15s",
                }}
                onMouseEnter={(e) => {
                  (e.currentTarget as HTMLDivElement).style.borderColor = token.colorPrimary;
                  (e.currentTarget as HTMLDivElement).style.boxShadow = "0 2px 8px rgba(24, 95, 165, 0.15)";
                }}
                onMouseLeave={(e) => {
                  (e.currentTarget as HTMLDivElement).style.borderColor = token.colorBorderSecondary;
                  (e.currentTarget as HTMLDivElement).style.boxShadow = "none";
                }}
              >
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {t("agent.guardrail.ai.candidate") || "Candidate"} {i + 1} · {cand.desc}
                </Text>
                <code style={{ display: "block", marginTop: 3, fontSize: 12, wordBreak: "break-all", color: "#042C53" }}>
                  {cand.pattern}
                </code>
              </div>
            ))}
          </div>
        </div>
      );
    }

    // Multi-rule result — delegated to sub-component to keep hooks valid
    return (
      <AiMultiResult
        rules={aiResult.rules}
        onImport={(selected) => handleImportMultiRules(selected)}
        onDiscard={() => {
          setAiInput("");
          setAiResult(null);
        }}
      />
    );
  };

  // --- AI zone rendering ---

  const modelOptions = llmModels.map((m) => ({
    value: m.id,
    label: m.displayName,
  }));

  const aiModeText =
    aiResult?.type === "single"
      ? (t("agent.guardrail.ai.singleMode") || "Single candidate")
      : aiResult?.type === "multi"
      ? (t("agent.guardrail.ai.multiMode") || "Multiple rules")
      : (t("agent.guardrail.ai.smartMode") || "Smart mode");

  const aiModeColor =
    aiResult?.type === "single"
      ? token.colorSuccess
      : aiResult?.type === "multi"
      ? token.colorWarning
      : token.colorSuccess;

  const aiModeBg =
    aiResult?.type === "single"
      ? token.colorSuccessBg
      : aiResult?.type === "multi"
      ? token.colorWarningBg
      : token.colorSuccessBg;

  // --- Severity summary ---

  const renderSeveritySummary = () => {
    if (draft.rules.length === 0) return null;
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

  // --- Batch bar ---

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

  return (
    <Modal
      title={
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span>{t("agent.guardrail.modalTitle") || "Guardrail Rules Configuration"}</span>
          {aiModelId !== undefined && (
            <Tag style={{ fontSize: 10, margin: 0 }}>
              {llmModels.find((m) => m.id === aiModelId)?.displayName || "—"}
            </Tag>
          )}
        </div>
      }
      open={open}
      onCancel={onClose}
      width={760}
      destroyOnHidden
      footer={
        <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center" }}>
          <Space>
            <Button onClick={onClose}>
              {t("agent.guardrail.cancel") || "Cancel"}
            </Button>
            <Button type="primary" onClick={handleSave}>
              {t("agent.guardrail.save") || "Save"}
            </Button>
          </Space>
        </div>
      }
    >
      {/* --- Toolbar: model selector + add rule --- */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          marginBottom: 18,
          paddingBottom: 10,
          borderBottom: `0.5px solid ${token.colorBorderSecondary}`,
        }}
      >
        <Select
          size="small"
          style={{ minWidth: 160 }}
          value={aiModelId}
          options={modelOptions}
          onChange={(v) => setAiModelId(v)}
          placeholder={t("agent.guardrail.ai.selectModel") || "Select model"}
        />
        <div style={{ flex: 1 }} />
        <Button size="small" icon={<Plus size={14} />} onClick={handleAddRule}>
          {t("agent.guardrail.addRule") || "Add Rule"}
        </Button>
      </div>

      {/* --- AI generation zone --- */}
      <div
        style={{
          marginBottom: 20,
          padding: 16,
          background: "#E6F1FB",
          border: `0.5px solid #B5D4F4`,
          borderRadius: 12,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <div
            style={{
              width: 20,
              height: 20,
              borderRadius: 5,
              background: "#185FA5",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#fff",
              fontSize: 10,
              fontWeight: 500,
            }}
          >
            <Sparkles size={12} />
          </div>
          <Text strong style={{ fontSize: 14, color: "#042C53" }}>
            {t("agent.guardrail.ai.title") || "Smart Generation"}
          </Text>
          <Tag
            style={{
              fontSize: 10,
              margin: 0,
              padding: "2px 8px",
              borderRadius: 10,
              background: aiModeBg,
              color: aiModeColor,
              border: "none",
            }}
          >
            {aiModeText}
          </Tag>
        </div>

        <Input.TextArea
          value={aiInput}
          onChange={(e) => setAiInput(e.target.value)}
          placeholder={t("agent.guardrail.ai.placeholder") || "Describe what you want to match or block. AI will determine single or multi."}
          autoSize={{ minRows: 2, maxRows: 4 }}
          style={{ fontSize: 13, borderRadius: 8, marginBottom: 12 }}
        />

        {/* Example chips + Generate button — same row to avoid extra line */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "nowrap", minHeight: 24 }}>
          <Text type="secondary" style={{ fontSize: 11, flexShrink: 0 }}>
            {t("agent.guardrail.ai.try") || "Try:"}
          </Text>
          {[
            { label: t("agent.guardrail.ai.exSensitive") || "Sensitive·phone", value: "掩码手机号、邮箱、身份证号等个人信息" },
            { label: t("agent.guardrail.ai.exDanger") || "Danger·rm-rf", value: "拦截 rm -rf 等危险删除命令" },
          ].map((ex, i) => (
            <span
              key={i}
              onClick={() => setAiInput(ex.value)}
              style={{
                fontSize: 11,
                padding: "2px 8px",
                border: `0.5px solid ${token.colorBorderSecondary}`,
                borderRadius: 10,
                cursor: "pointer",
                color: "#185FA5",
                background: token.colorBgContainer,
                transition: "all 0.15s",
                whiteSpace: "nowrap",
                flexShrink: 0,
              }}
              onMouseEnter={(e) => {
                (e.currentTarget as HTMLSpanElement).style.borderColor = "#185FA5";
                (e.currentTarget as HTMLSpanElement).style.background = "#E6F1FB";
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLSpanElement).style.borderColor = token.colorBorderSecondary;
                (e.currentTarget as HTMLSpanElement).style.background = token.colorBgContainer;
              }}
            >
              {ex.label}
            </span>
          ))}
          <div style={{ flex: 1 }} />
          <Button type="primary" size="small" icon={<Sparkles size={13} />} onClick={handleAiGenerate} loading={aiLoading}>
            {t("agent.guardrail.ai.generate") || "Generate"}
          </Button>
        </div>

        {/* AI result */}
        {renderAiResult()}
      </div>

      {/* --- Rule list --- */}
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4, marginBottom: 10 }}>
        <div style={{ width: 3, height: 12, background: "#185FA5", borderRadius: 2 }} />
        <Text strong style={{ fontSize: 12, color: token.colorTextSecondary }}>
          {t("agent.guardrail.ruleList") || "Rule List"}
        </Text>
      </div>

      {!draft.enabled ? null : draft.rules.length === 0 ? (
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
          </Space>
        </Empty>
      ) : (
        <>
          {renderSeveritySummary()}
          {renderBatchBar()}
          {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
          <Table<any>
            dataSource={draft.rules.map((rule, index) => ({ ...rule, key: index }))}
            columns={columns as ColumnsType<any>}
            pagination={false}
            size="small"
            scroll={{ x: 700 }}
            rowSelection={{
              selectedRowKeys: selectedKeys,
              onChange: (keys) => setSelectedKeys(keys as number[]),
              columnWidth: 32,
            }}
          />
          {/* --- Test preview --- */}
          <div style={{ marginTop: 16, paddingTop: 12, borderTop: `0.5px solid ${token.colorBorderSecondary}` }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
              <div style={{ width: 3, height: 12, background: "#185FA5", borderRadius: 2 }} />
              <Text strong style={{ fontSize: 12, color: token.colorTextSecondary }}>
                {t("agent.guardrail.testTitle") || "Regex Test Preview"}
              </Text>
            </div>
            <Input.TextArea
              value={testText}
              onChange={(e) => setTestText(e.target.value)}
              placeholder={t("agent.guardrail.testPlaceholder") || "e.g. My phone is 13812345678 and email is test@example.com"}
              autoSize={{ minRows: 2, maxRows: 4 }}
              style={{ fontSize: 13, marginBottom: 8 }}
            />
            {renderTestPreview()}
          </div>
        </>
      )}
    </Modal>
  );
}
