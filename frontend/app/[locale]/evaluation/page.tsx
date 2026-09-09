"use client";
import { useState, useEffect, useRef, useCallback, type Key } from "react";
import {
  Tabs,
  Typography,
  Card,
  Table,
  Button,
  Tag,
  Flex,
  Select,
  Drawer,
  Modal,
  App,
  Input,
  InputNumber,
  Space,
  Popconfirm,
  Spin,
  Progress,
  Radio,
  Tooltip,
} from "antd";
import { useTranslation } from "react-i18next";
import { useRouter, useSearchParams } from "next/navigation";
import {
  Plus,
  Upload,
  Zap,
  Download,
  Pencil,
  Trash2,
  RotateCw,
  List,
  LayoutGrid,
  Eye,
  GitBranch,
  CheckCircle,
} from "lucide-react";
import { API_ENDPOINTS } from "@/services/api";
import { getAuthHeaders } from "@/lib/auth";
import { useModelList } from "@/hooks/model/useModelList";
import { getI18nErrorMessage } from "@/const/errorMessageI18n";
import AnnotationLabels from "./components/AnnotationLabels";
const { Text, Title } = Typography;

function useList(url: string) {
  /**
   * Tiny reusable list fetcher — used for agent/evaluator/evaluation-set
   * dropdowns in the Runs list tab.
   *
   * Refresh semantics: mutating `key` (via `refresh()`) bumps a counter in
   * the useEffect dependency list and triggers a re-fetch.  Callers MUST
   * treat the returned list as immutable because `setData` replaces it
   * every fetch.
   *
   * Logging policy: console.* calls live outside loops (one line per
   * fetch, not per item) so the browser console stays usable on slow
   * connections.
   */
  const [data, setData] = useState<any[]>([]);
  const [key, setKey] = useState(0);
  const refresh = () => setKey((k) => k + 1);
  useEffect(() => {
    // Skip fetch for empty-ish URLs that accidental callers sometimes pass.
    if (!url) return;
    fetch(url, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => {
        // Accept raw arrays, or {data: [...]}, or {items: [...]} — each
        // API in Nexent has its own envelope, and callers of useList
        // should not need to know which one.
        const arr = Array.isArray(d) ? d : d.data || d.items || [];
        setData(arr);
      })
      .catch((e) => console.error("useList error", url, e));
  }, [url, key]);
  return [data, refresh] as const;
}

function RunsTab() {
  const { t, i18n } = useTranslation("common");
  const { message } = App.useApp();
  const currentLang = (i18n.language || "zh").startsWith("zh") ? "zh" : "en";
  const [agents] = useList("/api/agent/published_list");

  // ── Top-level list state ──────────────────────────────────────────────
  // `filterAgent` is the selected agent dropdown (drives which runs appear
  // in the main Table).  Initialised either from the `?agent_id=` URL query
  // param (so users can deep-link from the agent detail page) or from the
  // first agent returned by the published list.
  const [filterAgent, setFilterAgent] = useState<number | null>(null);
  const [runs, setRuns] = useState<any[]>([]);
  const { availableLlmModels } = useModelList();
  const [evalSets, setEvalSets] = useState<any[]>([]);
  const [evaluators, setEvaluators] = useState<any[]>([]);

  // ── Drawer (create-evaluation form) state ─────────────────────────────
  // Short variable names intentionally match the drawer inputs one-to-one:
  //   sA  = selected agent_id
  //   sS  = selected evaluation_set_id (only meaningful in with_set mode)
  //   sM  = selected judge model_id
  //   sE  = array of selected evaluator ids
  //   sAVer = selected agent version number
  // `agentVersions` is a fetched list — populated when the user picks an
  // agent, used to drive the version dropdown.  `mappings` carries the
  // (agent_output_column → evaluator_input_column) field map.
  const [drawer, setDrawer] = useState(false);
  const [sA, setA] = useState<number | null>(null);
  const [sS, setS] = useState<number | null>(null);
  const [sM, setM] = useState<number | null>(null);
  const [sE, setSE] = useState<number[]>([]);
  const [sAVer, setAVer] = useState<number | null>(null);
  const [agentVersions, setAgentVersions] = useState<any[]>([]);
  const [mappings, setMappings] = useState<
    Record<string, Record<string, string>>
  >({});
  // `errors.{a,s,m}` drive the per-field red "error" highlight on the
  // create form — each flag is flipped to `true` on submit when the field
  // is empty, cleared when the user touches the field.
  const [errors, setErrors] = useState<{
    a?: boolean;
    s?: boolean;
    m?: boolean;
  }>({});
  // `evalMode` controls which form fields are visible: with_set shows the
  // evaluation-set picker, no_set shows the query-count stepper + agent
  // version picker.
  const [evalMode, setEvalMode] = useState<"with_set" | "no_set">("no_set");
  const [queryCount, setQueryCount] = useState(10);
  const [creating, setCreating] = useState(false);

  // ── Trial-run (in-drawer "Try it out") state ───────────────────────────
  // The trial run fetches live output from the real agent + evaluators so
  // the user can sanity-check the configuration before queueing a full run.
  // `trialRunning` also blocks the drawer close button.
  const [trialQuery, setTrialQuery] = useState("");
  const [trialRunning, setTrialRunning] = useState(false);
  const [trialResult, setTrialResult] = useState<any>(null);
  const router = useRouter();
  const searchParams = useSearchParams();

  const refreshEvaluators = () => {
    fetch(API_ENDPOINTS.evaluators.list, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => setEvaluators(d.data || []));
  };
  const refreshEvalSets = () => {
    fetch("/api/evaluation-sets", { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => setEvalSets(d.data || d.items || []));
  };
  useEffect(() => {
    // Populate form dropdowns once; refreshEvaluators/refreshEvalSets are
    // ALSO called inside the drawer-open onClick so stale data never
    // blocks the user.
    refreshEvaluators();
    refreshEvalSets();
  }, []);

  // ── Init `filterAgent` from URL or default ────────────────────────────
  // Runs exactly once after agents list loads (so deep-linking works even
  // on page refresh, before the agent SELECT is interactive).  The guard
  // `!filterAgent` prevents overwriting user selection when `agents` gets
  // re-fetched later.
  useEffect(() => {
    if (agents.length > 0) {
      const urlAgentId = searchParams?.get("agent_id");
      if (
        urlAgentId &&
        agents.some((a: any) => String(a.agent_id) === urlAgentId)
      ) {
        setFilterAgent(Number(urlAgentId));
      } else if (!filterAgent) {
        setFilterAgent(agents[0].agent_id);
      }
    }
  }, [agents, searchParams]);

  const fetchRuns = useCallback(() => {
    if (!filterAgent) return;
    // limit=0 requests the full set for this agent (the backend treats it
    // as "no pagination window") — the page is already narrowed to one
    // agent, so a hard limit would silently hide older runs.
    fetch(`/api/agent-evaluations?agent_id=${filterAgent}&limit=0`, {
      headers: getAuthHeaders(),
    })
      .then((r) => r.json())
      .then((d) => setRuns(d.data || d.items || []));
  }, [filterAgent]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // ── Polling ───────────────────────────────────────────────────────────
  // While ANY row in the visible runs list has status PENDING / RUNNING we
  // start a 2-second interval.  Polling stops cleanly when all rows are
  // terminal states (COMPLETED / FAILED) so the idle page does not
  // contribute to backend load.  `pollRef` lives on a ref so unmount can
  // clear it even if the cleanup of a stale effect fires after a later one.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    const hasRunning = runs.some(
      (r) => r.status === "PENDING" || r.status === "RUNNING"
    );
    if (hasRunning && !pollRef.current) {
      pollRef.current = setInterval(fetchRuns, 2000);
    } else if (!hasRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [runs, fetchRuns]);

  // Shared create-run POST used by both eval modes (no_set / with_set).
  const submitEvaluation = async (payload: any) => {
    const r = await fetch(API_ENDPOINTS.agentEvaluations.create, {
      method: "POST",
      headers: {
        ...getAuthHeaders(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (r.ok) {
      setRuns((prev) => [d.data || d, ...prev]);
      setDrawer(false);
      setFilterAgent(sA);
    } else {
      message.error(d?.detail || t("agentEvaluation.createFailed"));
    }
  };

  // Parse scores JSON (may be a single number, or {"evaluator_name": score, ...})
  const cols = [
    { title: "ID", dataIndex: "agent_evaluation_id", width: 50 },
    {
      title: t("agentEvaluation.colHeader.agent"),
      key: "a",
      width: 120,
      ellipsis: true,
      render: (_: any, r: any) => {
        if (r.agent_name) return r.agent_name;
        const a = agents.find((x: any) => x.agent_id === r.agent_id);
        return a?.display_name || a?.name || `#${r.agent_id}`;
      },
    },
    {
      title: t("agentEvaluation.colHeader.version"),
      dataIndex: "agent_version_no",
      width: 55,
      render: (v: any) => (v != null ? `v${v}` : "-"),
    },
    {
      title: t("agentEvaluation.evalSetLabel"),
      dataIndex: "evaluation_set_name",
      width: 140,
      ellipsis: true,
      render: (_v: string, r: any) => {
        const isNoSet =
          r?.evaluator_config?.no_set_mode === true ||
          (r?.evaluation_set_name || "").startsWith("运行时评测") ||
          (r?.evaluation_set_name || "").startsWith("[No-Set]");
        return (
          <Space size={4}>
            {isNoSet ? (
              <Tag color="orange" className="text-xs">
                {t("agentEvaluation.noSetTag")}
              </Tag>
            ) : (
              _v || "-"
            )}
          </Space>
        );
      },
      filters: [
        ...new Set(runs.map((r) => r.evaluation_set_name).filter(Boolean)),
      ].map((n) => {
        const isNS = n.startsWith("[No-Set]") || n.startsWith("运行时评测");
        return { text: isNS ? t("agentEvaluation.noSetTag") : n, value: n };
      }),
      onFilter: (value: any, record: any) =>
        record.evaluation_set_name === value,
      filterSearch: true,
    },
    {
      title: t("agentEvaluation.colHeader.score"),
      dataIndex: "score_overall",
      width: 70,
      render: (v: any) => (v != null ? Number(v).toFixed(2) : "-"),
      sorter: (a: any, b: any) =>
        (a.score_overall ?? -1) - (b.score_overall ?? -1),
    },
    {
      title: t("agentEvaluation.colHeader.status"),
      dataIndex: "status",
      width: 70,
      render: (s: string) => {
        const st: Record<string, { color: string; label: string }> = {
          COMPLETED: {
            color: "green",
            label: t("agentEvaluation.status.completed"),
          },
          RUNNING: {
            color: "blue",
            label: t("agentEvaluation.status.running"),
          },
          PENDING: {
            color: "default",
            label: t("agentEvaluation.status.pending"),
          },
          FAILED: { color: "red", label: t("agentEvaluation.status.failed") },
        };
        const v = st[s] || { color: "default", label: s };
        return <Tag color={v.color}>{v.label}</Tag>;
      },
      filters: [
        { text: t("agentEvaluation.status.pending"), value: "PENDING" },
        { text: t("agentEvaluation.status.running"), value: "RUNNING" },
        { text: t("agentEvaluation.status.completed"), value: "COMPLETED" },
        { text: t("agentEvaluation.status.failed"), value: "FAILED" },
      ],
      onFilter: (value: any, record: any) => record.status === value,
    },
    {
      title: t("agentEvaluation.colHeader.actions"),
      width: 80,
      render: (_: any, r: any) => (
        <Space size={0}>
          <Tooltip title={t("agentEvaluation.detail")}>
            <Button
              type="link"
              size="small"
              icon={<Eye className="size-3.5" />}
              onClick={() =>
                router.push(`/evaluation/${r.agent_evaluation_id}`)
              }
            />
          </Tooltip>
          <Popconfirm
            title={t("agentEvaluation.deleteConfirm")}
            onConfirm={async () => {
              await fetch(
                API_ENDPOINTS.agentEvaluations.delete(r.agent_evaluation_id),
                { method: "DELETE", headers: getAuthHeaders() }
              );
              setRuns((prev) =>
                prev.filter(
                  (x) => x.agent_evaluation_id !== r.agent_evaluation_id
                )
              );
            }}
          >
            <Tooltip title={t("agentEvaluation.delete")}>
              <Button
                type="link"
                size="small"
                danger
                icon={<Trash2 className="size-3.5" />}
              />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
        <Space>
          <span className="font-medium leading-8">
            {t("agentEvaluation.sectionTitle")}
          </span>
          <Select
            allowClear
            showSearch
            placeholder="Agent"
            value={filterAgent}
            onChange={setFilterAgent}
            style={{ width: 240 }}
            options={agents.map((a: any) => ({
              label: a.display_name || a.name || `#${a.agent_id}`,
              value: a.agent_id,
            }))}
            filterOption={(input, option) =>
              String(option?.label || "")
                .toLowerCase()
                .includes(input.toLowerCase())
            }
          />
          <Button icon={<RotateCw className="size-4" />} onClick={fetchRuns} />
        </Space>
        <Button
          type="primary"
          icon={<Plus className="size-4" />}
          onClick={() => {
            setA(null);
            setS(null);
            setM(null);
            setSE([]);
            setAVer(null);
            setAgentVersions([]);
            setMappings({});
            setErrors({});
            setEvalMode("no_set");
            refreshEvaluators();
            refreshEvalSets();
            setDrawer(true);
          }}
        >
          {t("agentEvaluation.createEval")}
        </Button>
      </Flex>
      <Table
        columns={cols}
        dataSource={runs}
        rowKey="agent_evaluation_id"
        size="small"
        pagination={{ pageSize: 10 }}
      />
      <Drawer
        title={t("agentEvaluation.createEval")}
        open={drawer}
        onClose={() => {
          if (!trialRunning) setDrawer(false);
        }}
        size="large"
        maskClosable={!trialRunning}
        closable={!trialRunning}
      >
        <Spin
          spinning={trialRunning}
          description={t("agentEvaluation.trialRunning")}
        >
          <Flex vertical gap={16}>
            {/* Mode switch — default: no_set, larger + left-aligned */}
            <Radio.Group
              value={evalMode}
              onChange={(e) => {
                setEvalMode(e.target.value);
                setSE([]);
                setS(null);
                setMappings({});
              }}
              size="middle"
              buttonStyle="solid"
              style={{ width: "100%" }}
            >
              <Radio.Button
                value="no_set"
                style={{ width: "50%", textAlign: "center" }}
              >
                {t("agentEvaluation.modeNoSet")}
              </Radio.Button>
              <Radio.Button
                value="with_set"
                style={{ width: "50%", textAlign: "center" }}
              >
                {t("agentEvaluation.modeWithSet")}
              </Radio.Button>
            </Radio.Group>
            {/* Step 1: Agent + Version */}
            <Card size="small" title={t("agentEvaluation.stepAgent")}>
              <Flex vertical gap={8}>
                <Flex vertical gap={4}>
                  <Text className="text-xs">
                    {t("agentEvaluation.agentLabel")}{" "}
                    <Text type="danger">*</Text>
                  </Text>
                  <Select
                    showSearch
                    status={errors.a ? "error" : undefined}
                    value={sA}
                    onChange={(v) => {
                      setA(v);
                      setAVer(null);
                      setAgentVersions([]);
                      setErrors((e) => ({ ...e, a: false }));
                      fetch(`/api/agent/${v}/versions`, {
                        headers: getAuthHeaders(),
                      })
                        .then((r) => r.json())
                        .then((d) => {
                          const vs = d.items || d.data || [];
                          setAgentVersions(vs);
                          if (vs.length > 0) setAVer(vs[0].version_no);
                        });
                    }}
                    options={agents.map((a: any) => ({
                      label: a.display_name || a.name || `#${a.agent_id}`,
                      value: a.agent_id,
                    }))}
                  />
                  {errors.a && (
                    <Text type="danger" className="text-xs">
                      {t("agentEvaluation.selectAgent")}
                    </Text>
                  )}
                </Flex>
                <Flex vertical gap={4}>
                  <Text className="text-xs">
                    {t("agentEvaluation.agentVersionLabel")}{" "}
                    <Text type="danger">*</Text>
                  </Text>
                  <Select
                    value={sAVer}
                    onChange={(v) => setAVer(v)}
                    loading={agentVersions.length === 0 && !!sA}
                    options={agentVersions.map((v: any) => ({
                      label: `v${v.version_no}${v.version_name ? ` (${v.version_name})` : ""}`,
                      value: v.version_no,
                    }))}
                  />
                </Flex>
              </Flex>
            </Card>
            {/* Step 2: 评测集 + Judge模型 */}
            <Card size="small" title={t("agentEvaluation.stepEvalConfig")}>
              <Flex vertical gap={8}>
                {evalMode === "with_set" && (
                  <Flex vertical gap={4}>
                    <Text className="text-xs">
                      {t("agentEvaluation.evalSetLabel")}{" "}
                      <Text type="danger">*</Text>
                    </Text>
                    <Select
                      status={errors.s ? "error" : undefined}
                      value={sS}
                      onChange={(v) => {
                        setS(v);
                        setErrors((e) => ({ ...e, s: false }));
                      }}
                      options={evalSets.map((s: any) => ({
                        label: `${s.name} (${s.case_count || "?"})`,
                        value: s.evaluation_set_id,
                      }))}
                    />
                    {errors.s && (
                      <Text type="danger" className="text-xs">
                        {t("agentEvaluation.selectEvalSet")}
                      </Text>
                    )}
                  </Flex>
                )}
                <Flex vertical gap={4}>
                  <Text className="text-xs">
                    {t("agentEvaluation.judgeModelLabel")}{" "}
                    <Text type="danger">*</Text>
                  </Text>
                  <Select
                    status={errors.m ? "error" : undefined}
                    value={sM}
                    onChange={(v) => {
                      setM(v);
                      setErrors((e) => ({ ...e, m: false }));
                    }}
                    loading={availableLlmModels.length === 0}
                    options={availableLlmModels.map((m) => ({
                      label: m.displayName || m.name,
                      value: m.id,
                    }))}
                  />
                  {errors.m && (
                    <Text type="danger" className="text-xs">
                      {t("agentEvaluation.selectJudgeModel")}
                    </Text>
                  )}
                </Flex>
              </Flex>
            </Card>
            {/* Step 3: 评估器 */}
            <Card
              size="small"
              title={
                evalMode === "no_set"
                  ? `${t("agentEvaluation.evaluatorCount")} (${sE.length}/5)`
                  : `${t("agentEvaluation.stepEvaluators")} (${sE.length}/5)`
              }
            >
              <Flex vertical gap={8}>
                <Select
                  mode="multiple"
                  maxCount={5}
                  value={sE}
                  onChange={(vs) => {
                    setSE(vs);
                    const newM: any = {};
                    vs.forEach((id: number) => {
                      const ev = evaluators.find(
                        (e: any) => e.evaluator_id === id
                      );
                      const fields = ev?.input_fields || [];
                      const auto: any = {};
                      fields.forEach((f: any) => {
                        if (f.name === "query")
                          auto[f.name] = "case.inputs.query";
                        else if (f.name === "expected")
                          auto[f.name] = "case.label.answer";
                        else if (f.name === "actual")
                          auto[f.name] = "agent_output";
                      });
                      newM[id] = auto;
                    });
                    setMappings(newM);
                  }}
                  options={evaluators
                    .filter((e: any) => e.status === "PUBLISHED")
                    .map((e: any) => ({
                      label:
                        currentLang === "en"
                          ? e.name_en || e.name
                          : e.name || e.name_en,
                      value: e.evaluator_id,
                      desc:
                        currentLang === "en"
                          ? e.description_en || e.description || ""
                          : e.description || e.description_en || "",
                    }))}
                  optionRender={(opt: any) => (
                    <Flex vertical gap={2}>
                      <Text strong>{opt.label}</Text>
                      {opt.data.desc && (
                        <Text
                          type="secondary"
                          className="text-xs"
                          style={{ lineHeight: 1.2 }}
                        >
                          {opt.data.desc}
                        </Text>
                      )}
                    </Flex>
                  )}
                  placeholder={t("agentEvaluation.evaluatorPlaceholder")}
                />
              </Flex>
            </Card>
            {/* Step 3b: no_set mode — AI generates test queries from agent config */}
            {evalMode === "no_set" && (
              <Card size="small" title={t("agentEvaluation.stepAiGenQueries")}>
                <Flex vertical gap={8}>
                  <Text className="text-xs" type="secondary">
                    {t("agentEvaluation.aiGenDesc")}
                  </Text>
                  <Flex gap={8} align="center">
                    <Text className="text-xs">
                      {t("agentEvaluation.genCount")}
                    </Text>
                    <InputNumber
                      size="small"
                      min={1}
                      max={50}
                      value={queryCount}
                      onChange={(v) => setQueryCount(v || 10)}
                      style={{ width: 80 }}
                    />
                    <Text className="text-xs" type="secondary">
                      {t("agentEvaluation.genCountRange")}
                    </Text>
                  </Flex>
                </Flex>
              </Card>
            )}
            <Flex gap={8}>
              {evalMode === "with_set" && (
                <Button
                  onClick={async () => {
                    let q = trialQuery;
                    if (!q && sS) {
                      const r = await fetch(
                        `/api/evaluation-sets/${sS}/cases?limit=1`,
                        { headers: getAuthHeaders() }
                      );
                      const d = await r.json();
                      const cs = d.data || d.items || [];
                      q = cs[0]?.inputs?.query || "";
                      setTrialQuery(q);
                    }
                    if (!q.trim() || !sA || !sM) return;
                    if (sE.length === 0) {
                      message.warning(t("agentEvaluation.queryCountRequired"));
                      return;
                    }
                    setTrialRunning(true);
                    setTrialResult(null);
                    try {
                      const b: any = {
                        agent_id: sA,
                        agent_version_no: sAVer,
                        query: q.trim(),
                        judge_model_id: sM,
                      };
                      if (sE.length > 0) {
                        b.evaluator_ids = sE;
                        b.field_mappings = mappings;
                      }
                      const r = await fetch(
                        "/api/agent-evaluations/trial-run",
                        {
                          method: "POST",
                          headers: {
                            ...getAuthHeaders(),
                            "Content-Type": "application/json",
                          },
                          body: JSON.stringify(b),
                        }
                      );
                      const d = await r.json();
                      setTrialResult(d.data || d);
                    } catch {
                    } finally {
                      setTrialRunning(false);
                    }
                  }}
                  loading={trialRunning}
                  icon={<Zap className="size-4" />}
                >
                  {t("agentEvaluation.trialRun")}
                </Button>
              )}
              <Button
                type="primary"
                loading={creating}
                onClick={async () => {
                  const errs: any = {};
                  if (!sA) errs.a = true;
                  if (!sM) errs.m = true;
                  if (evalMode === "with_set") {
                    if (!sS) errs.s = true;
                  }
                  if (sE.length === 0) {
                    message.warning(t("agentEvaluation.queryCountRequired"));
                    return;
                  }
                  if (Object.keys(errs).length > 0) {
                    setErrors(errs);
                    return;
                  }
                  setCreating(true);
                  try {
                    if (evalMode === "no_set") {
                      const b: any = {
                        agent_id: sA,
                        agent_version_no: sAVer,
                        judge_model_id: sM,
                        evaluator_ids: sE,
                        query_count: queryCount,
                      };
                      await submitEvaluation(b);
                    } else {
                      const b: any = {
                        agent_id: sA,
                        agent_version_no: sAVer,
                        evaluation_set_id: sS,
                        judge_model_id: sM,
                      };
                      if (sE.length > 0) {
                        b.evaluator_ids = sE;
                        b.field_mappings = mappings;
                      }
                      await submitEvaluation(b);
                    }
                  } finally {
                    setCreating(false);
                  }
                }}
                block
              >
                {t("agentEvaluation.startEval")}
              </Button>
            </Flex>
          </Flex>
        </Spin>
      </Drawer>
      <Modal
        title={t("agentEvaluation.trialResult")}
        open={!!trialResult}
        onCancel={() => setTrialResult(null)}
        footer={null}
        width={600}
      >
        {trialResult && (
          <Flex vertical gap={12}>
            <Flex vertical gap={4}>
              <Text className="text-xs" type="secondary">
                {t("agentEvaluation.testQuestion")}
              </Text>
              <Text>{trialResult.query}</Text>
            </Flex>
            <Flex vertical gap={4}>
              <Text className="text-xs" type="secondary">
                {t("agentEvaluation.agentOutput")}
              </Text>
              <Text>{trialResult.answer || "-"}</Text>
            </Flex>
            {trialResult.scores && (
              <Flex vertical gap={4}>
                <Text className="text-xs" type="secondary">
                  {t("agentEvaluation.evalResult")}
                </Text>
                {(() => {
                  const sel = sE
                    .map((id: number) =>
                      evaluators.find((e: any) => e.evaluator_id === id)
                    )
                    .filter(Boolean);
                  const thByName: Record<string, number> = Object.fromEntries(
                    sel.map((e: any) => [
                      e.name,
                      Number(e.pass_threshold ?? 0.5),
                    ])
                  );
                  return Object.entries(
                    trialResult.scores as Record<string, number>
                  ).map(([k, v]) => {
                    const th = thByName[k] ?? 0.5;
                    return (
                      <Flex key={k} gap={8} align="center">
                        <Tag color={Number(v) >= th ? "green" : "red"}>
                          {Number(v).toFixed(2)}
                        </Tag>
                        <Text>{k}</Text>
                      </Flex>
                    );
                  });
                })()}
              </Flex>
            )}
          </Flex>
        )}
      </Modal>
    </div>
  );
}

function EvaluatorsTab() {
  const { t, i18n } = useTranslation("common");
  const { message } = App.useApp();
  const currentLang = (i18n.language || "zh").startsWith("zh") ? "zh" : "en";
  const [evaluators, refreshEval] = useList(API_ENDPOINTS.evaluators.list);
  const { availableLlmModels } = useModelList();
  const [agents] = useList(API_ENDPOINTS.agent.list);
  const [drawer, setDrawer] = useState(false);
  const [f, setF] = useState({
    name: "",
    desc: "",
    type: "llm" as "llm" | "code",
    prompt: "",
    code: "",
    sMin: 0,
    sMax: 1,
    threshold: 0.5,
    modelId: undefined as number | undefined,
  });
  const [selEvalIds, setSelEvalIds] = useState<Key[]>([]);
  const importFileRef = useRef<HTMLInputElement>(null);
  const [importBusy, setImportBusy] = useState(false);
  const resetF = () =>
    setF({
      name: "",
      desc: "",
      type: "llm",
      prompt: "",
      code: "",
      sMin: 0,
      sMax: 1,
      threshold: 0.5,
      modelId: undefined,
    });
  const validateF = (): boolean => {
    if (!f.name.trim()) {
      message.warning(t("agentEvaluation.validation.nameRequired"));
      return false;
    }
    if (f.sMin >= f.sMax) {
      message.warning(t("agentEvaluation.validation.scoreMinMax"));
      return false;
    }
    if (f.threshold < f.sMin || f.threshold > f.sMax) {
      message.warning(t("agentEvaluation.validation.thresholdRange"));
      return false;
    }
    if (f.sMax > 100) {
      message.warning(t("agentEvaluation.validation.scoreMaxLimit"));
      return false;
    }
    return true;
  };
  const [genDesc, setGenDesc] = useState("");
  const [genModel, setGenModel] = useState<number | undefined>(undefined);
  const [genAgent, setGenAgent] = useState<number | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [editTarget, setEditTarget] = useState<any>(null);
  const [viewMode, setViewMode] = useState<"card" | "list">("card");
  const [evalTab, setEvalTab] = useState<string>("custom");
  const builtin = evaluators.filter((e: any) => e.source === "builtin"),
    custom = evaluators.filter((e: any) => e.source === "custom");
  const tl: Record<string, string> = {
    llm: t("agentEvaluation.evaluatorType.llm"),
    code: t("agentEvaluation.evaluatorType.code"),
  };

  // Version management
  const [versionDrawer, setVersionDrawer] = useState(false);
  const [versions, setVersions] = useState<any[]>([]);
  const [versionEval, setVersionEval] = useState<any>(null);
  const [versionBusy, setVersionBusy] = useState(false);
  const fetchVersions = async (evaluatorId: number) => {
    setVersionBusy(true);
    try {
      const r = await fetch(`/api/evaluators/${evaluatorId}/versions`, {
        headers: getAuthHeaders(),
      });
      const d = await r.json();
      setVersions(d.data || []);
    } finally {
      setVersionBusy(false);
    }
  };
  const restoreVersion = async (versionId: number) => {
    setVersionBusy(true);
    try {
      await fetch(
        `/api/evaluators/${versionEval?.evaluator_id}/versions/${versionId}/restore`,
        { method: "POST", headers: getAuthHeaders() }
      );
      await fetchVersions(versionEval.evaluator_id);
      refreshEval();
    } catch {
      message.error(t("agentEvaluation.saveFailed"));
    } finally {
      setVersionBusy(false);
    }
  };
  const deleteVersion = async (versionId: number) => {
    setVersionBusy(true);
    try {
      await fetch(
        `/api/evaluators/${versionEval?.evaluator_id}/versions/${versionId}`,
        { method: "DELETE", headers: getAuthHeaders() }
      );
      await fetchVersions(versionEval.evaluator_id);
      refreshEval();
    } catch {
      message.error(t("agentEvaluation.saveFailed"));
    } finally {
      setVersionBusy(false);
    }
  };

  useEffect(() => {
    if (!genModel && availableLlmModels.length > 0)
      setGenModel(availableLlmModels[0].id);
  }, [availableLlmModels]);

  const customTableCols = [
    {
      title: t("agentEvaluation.colHeader.name"),
      dataIndex: "name",
      ellipsis: true,
      render: (v: string, e: any) =>
        currentLang === "en" ? e.name_en || e.name : e.name || e.name_en,
      filterDropdown: ({
        setSelectedKeys,
        selectedKeys,
        confirm,
        clearFilters,
      }: any) => (
        <div style={{ padding: 8 }}>
          <Input
            placeholder={t("agentEvaluation.searchName")}
            value={selectedKeys[0]}
            onChange={(e) =>
              setSelectedKeys(e.target.value ? [e.target.value] : [])
            }
            onPressEnter={() => confirm()}
            onBlur={() => confirm()}
            size="small"
            style={{ width: 180 }}
          />
        </div>
      ),
      onFilter: (value: any, record: any) =>
        record.name?.toLowerCase().includes(String(value).toLowerCase()),
    },
    {
      title: t("agentEvaluation.colHeader.type"),
      dataIndex: "evaluator_type",
      width: 90,
      render: (v: string) => tl[v] || v,
      filters: [
        { text: t("agentEvaluation.evaluatorType.llm"), value: "llm" },
        { text: t("agentEvaluation.evaluatorType.code"), value: "code" },
      ],
      onFilter: (value: any, record: any) => record.evaluator_type === value,
    },
    {
      title: t("agentEvaluation.colHeader.status"),
      dataIndex: "status",
      width: 80,
      render: (v: string) => (
        <Tag color={v === "PUBLISHED" ? "green" : "orange"}>
          {v === "PUBLISHED"
            ? t("agentEvaluation.published")
            : t("agentEvaluation.draft")}
        </Tag>
      ),
      filters: [
        { text: t("agentEvaluation.published"), value: "PUBLISHED" },
        { text: t("agentEvaluation.draft"), value: "DRAFT" },
      ],
      onFilter: (value: any, record: any) => record.status === value,
    },
    {
      title: t("agentEvaluation.colHeader.description"),
      dataIndex: "description",
      ellipsis: true,
      render: (v: string, e: any) =>
        currentLang === "en"
          ? e.description_en || e.description || ""
          : e.description || e.description_en || "",
    },
    {
      title: t("agentEvaluation.colHeader.actions"),
      width: 130,
      render: (_: any, e: any) => (
        <Space size={0}>
          <Tooltip title={t("agentEvaluation.edit")}>
            <Button
              type="link"
              size="small"
              icon={<Pencil className="size-3.5" />}
              onClick={async () => {
                const r = await fetch(
                  `${API_ENDPOINTS.evaluators.detail(e.evaluator_id)}`,
                  { headers: getAuthHeaders() }
                );
                const d = await r.json();
                if (d.data) setEditTarget(d.data);
              }}
            />
          </Tooltip>
          {e.status === "DRAFT" && (
            <Tooltip title={t("agentEvaluation.publish")}>
              <Button
                type="link"
                size="small"
                icon={<CheckCircle className="size-3.5" />}
                onClick={async () => {
                  await fetch(
                    API_ENDPOINTS.evaluators.publish(e.evaluator_id),
                    { method: "POST", headers: getAuthHeaders() }
                  );
                  refreshEval();
                }}
              />
            </Tooltip>
          )}
          {e.status === "PUBLISHED" && (
            <Tooltip title={t("agentEvaluation.version")}>
              <Button
                type="link"
                size="small"
                icon={<GitBranch className="size-3.5" />}
                onClick={() => {
                  setVersionEval(e);
                  fetchVersions(e.evaluator_id);
                  setVersionDrawer(true);
                }}
              />
            </Tooltip>
          )}
          <Popconfirm
            title={t("agentEvaluation.deleteConfirm")}
            onConfirm={async () => {
              await fetch(API_ENDPOINTS.evaluators.delete(e.evaluator_id), {
                method: "DELETE",
                headers: getAuthHeaders(),
              });
              refreshEval();
            }}
          >
            <Tooltip title={t("agentEvaluation.delete")}>
              <Button
                type="link"
                size="small"
                danger
                icon={<Trash2 className="size-3.5" />}
              />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const handleExportEvaluators = async () => {
    if (selEvalIds.length === 0) return;
    try {
      const resp = await fetch(API_ENDPOINTS.evaluators.export, {
        method: "POST",
        headers: getAuthHeaders(),
        body: JSON.stringify({ evaluator_ids: selEvalIds.map(Number) }),
      });
      if (!resp.ok) {
        const d = await resp.json();
        message.warning(
          d.code
            ? getI18nErrorMessage(d.code, t)
            : typeof d?.detail === "string"
              ? d.detail
              : t("agentEvaluation.exportError")
        );
        return;
      }
      const blob = await resp.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "evaluators_export.json";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      message.success(
        t("agentEvaluation.exportSuccess", { n: selEvalIds.length })
      );
    } catch {
      message.error(t("agentEvaluation.exportError"));
    }
  };

  const handleImportEvaluators = async (file: File) => {
    setImportBusy(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const resp = await fetch(API_ENDPOINTS.evaluators.import, {
        method: "POST",
        // 不设 Content-Type：multipart 需由浏览器自动生成 boundary；
        // Authorization 已由 server.js 代理根据 cookie 自动注入。
        headers: { "User-Agent": "AgentFrontEnd/1.0" },
        body: formData,
      });
      const result = await resp.json();
      if (resp.status !== 200) {
        message.warning(
          result.code
            ? getI18nErrorMessage(result.code, t)
            : result.detail ||
                result.message ||
                t("agentEvaluation.importError")
        );
        return;
      }
      const { imported, skipped, errors } = result.data || {};
      const parts: string[] = [];
      if (imported > 0)
        parts.push(t("agentEvaluation.exportSuccess", { n: imported }));
      if (skipped > 0)
        parts.push(
          t("agentEvaluation.importResult", { imported, skipped, errors: 0 })
        );
      if (errors?.length > 0) {
        parts.push(
          t("agentEvaluation.importWithErrors", {
            imported,
            skipped,
            errors: errors.length,
          })
        );
        errors
          .slice(0, 3)
          .forEach((e: any) =>
            parts.push(`  - ${e.name || `#${e.index}`}: ${e.reason}`)
          );
      }
      message.info(parts.join("；"));
      refreshEval();
    } catch {
      message.error(t("agentEvaluation.importError"));
    } finally {
      setImportBusy(false);
      if (importFileRef.current) importFileRef.current.value = "";
    }
  };

  return (
    <div>
      <input
        ref={importFileRef}
        type="file"
        accept=".json"
        style={{ display: "none" }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) handleImportEvaluators(f);
        }}
      />
      <Flex justify="space-between" className="mb-3">
        <Tabs
          activeKey={evalTab}
          onChange={setEvalTab}
          size="small"
          style={{ marginBottom: -16 }}
          items={[
            {
              key: "builtin",
              label: `${t("agentEvaluation.builtin")} (${builtin.length})`,
            },
            {
              key: "custom",
              label: `${t("agentEvaluation.custom")} (${custom.length})`,
            },
          ]}
        />
        <Space>
          {evalTab === "custom" && (
            <Button
              icon={
                viewMode === "card" ? (
                  <List className="size-4" />
                ) : (
                  <LayoutGrid className="size-4" />
                )
              }
              onClick={() =>
                setViewMode((v) => (v === "card" ? "list" : "card"))
              }
            >
              {viewMode === "card"
                ? t("agentEvaluation.viewList")
                : t("agentEvaluation.viewCard")}
            </Button>
          )}
          {evalTab === "custom" && (
            <Button
              icon={<Upload className="size-4" />}
              loading={importBusy}
              onClick={() => importFileRef.current?.click()}
            >
              {t("agentEvaluation.import")}
            </Button>
          )}
          {evalTab === "custom" && (
            <Button
              icon={<Download className="size-4" />}
              disabled={selEvalIds.length === 0}
              onClick={handleExportEvaluators}
            >
              {t("agentEvaluation.exportSelected")}
              {selEvalIds.length > 0 ? ` (${selEvalIds.length})` : ""}
            </Button>
          )}
          <Button
            type="primary"
            icon={<Plus className="size-4" />}
            onClick={() => {
              resetF();
              setDrawer(true);
            }}
          >
            {t("agentEvaluation.evaluatorCreate")}
          </Button>
        </Space>
      </Flex>
      <div className="mt-4" />
      {/* Builtin — always card view */}
      {evalTab === "builtin" && (
        <div className="grid grid-cols-3 gap-3">
          {builtin.map((e: any) => (
            <Card
              key={e.evaluator_id}
              size="small"
              title={
                currentLang === "en" ? e.name_en || e.name : e.name || e.name_en
              }
            >
              <Space wrap>
                <Tag color={e.evaluator_type === "llm" ? "blue" : "purple"}>
                  {tl[e.evaluator_type] || e.evaluator_type}
                </Tag>
                <Tag color="green">{t("agentEvaluation.published")}</Tag>
              </Space>
              <div className="text-xs text-gray-400 mt-1">
                {currentLang === "en"
                  ? e.description_en || e.description || ""
                  : e.description || e.description_en || ""}
              </div>
            </Card>
          ))}
        </div>
      )}
      {/* Custom — card or list */}
      {evalTab === "custom" &&
        (viewMode === "card" ? (
          <div className="grid grid-cols-3 gap-3">
            {custom.map((e: any) => (
              <Card
                key={e.evaluator_id}
                size="small"
                title={
                  currentLang === "en"
                    ? e.name_en || e.name
                    : e.name || e.name_en
                }
                extra={
                  <Space size={0}>
                    <Button
                      type="text"
                      size="small"
                      icon={<Pencil className="size-4" />}
                      onClick={async () => {
                        const r = await fetch(
                          `${API_ENDPOINTS.evaluators.detail(e.evaluator_id)}`,
                          { headers: getAuthHeaders() }
                        );
                        const d = await r.json();
                        if (d.data) setEditTarget(d.data);
                      }}
                    />
                    <Popconfirm
                      title={t("agentEvaluation.deleteConfirm")}
                      onConfirm={async () => {
                        await fetch(
                          API_ENDPOINTS.evaluators.delete(e.evaluator_id),
                          { method: "DELETE", headers: getAuthHeaders() }
                        );
                        refreshEval();
                      }}
                    >
                      <Button
                        type="text"
                        size="small"
                        danger
                        icon={<Trash2 className="size-4" />}
                      />
                    </Popconfirm>
                    {e.status === "DRAFT" && (
                      <Button
                        type="link"
                        size="small"
                        onClick={async () => {
                          await fetch(
                            API_ENDPOINTS.evaluators.publish(e.evaluator_id),
                            { method: "POST", headers: getAuthHeaders() }
                          );
                          refreshEval();
                        }}
                      >
                        {t("agentEvaluation.publish")}
                      </Button>
                    )}
                  </Space>
                }
              >
                <Space wrap>
                  <Tag color={e.evaluator_type === "llm" ? "blue" : "purple"}>
                    {tl[e.evaluator_type] || e.evaluator_type}
                  </Tag>
                  <Tag color={e.status === "PUBLISHED" ? "green" : "orange"}>
                    {e.status === "PUBLISHED"
                      ? t("agentEvaluation.published")
                      : t("agentEvaluation.draft")}
                  </Tag>
                  {e.status === "PUBLISHED" && (
                    <Button
                      type="link"
                      size="small"
                      onClick={() => {
                        setVersionEval(e);
                        fetchVersions(e.evaluator_id);
                        setVersionDrawer(true);
                      }}
                    >
                      v{e.version_no} {t("agentEvaluation.versionHistory")}
                    </Button>
                  )}
                </Space>
                <div className="text-xs text-gray-400 mt-1">
                  {currentLang === "en"
                    ? e.description_en || e.description || ""
                    : e.description || e.description_en || ""}
                </div>
              </Card>
            ))}
          </div>
        ) : (
          <Table
            columns={customTableCols}
            dataSource={custom}
            rowKey="evaluator_id"
            size="small"
            pagination={{ pageSize: 10 }}
            rowSelection={{
              selectedRowKeys: selEvalIds,
              onChange: setSelEvalIds,
            }}
          />
        ))}
      <Drawer
        title={t("agentEvaluation.evaluatorCreate")}
        open={drawer}
        onClose={() => setDrawer(false)}
        size="large"
        maskClosable={!busy}
        closable={!busy}
      >
        <Spin
          spinning={busy}
          description={t("agentEvaluation.aiGenerate") + "..."}
        >
          <Flex vertical gap={20}>
            {/* AI Generate section */}
            <Card
              size="small"
              title={
                <Flex gap={6} align="center">
                  <Zap className="size-4" />
                  <Text>{t("agentEvaluation.evaluatorAiGen")}</Text>
                </Flex>
              }
            >
              <Flex vertical gap={8}>
                <Text className="text-xs" type="secondary">
                  {t("agentEvaluation.evaluatorAiGenHint")}
                </Text>
                <Input.TextArea
                  rows={3}
                  maxLength={500}
                  showCount
                  value={genDesc}
                  onChange={(e) => setGenDesc(e.target.value)}
                  placeholder={t("agentEvaluation.evaluatorAiGenPlaceholder")}
                />
                <Flex gap={8} align="center" wrap>
                  <Text className="text-xs" style={{ whiteSpace: "nowrap" }}>
                    {t("agentEvaluation.aiGenModel")}
                  </Text>
                  <Select
                    style={{ width: 200 }}
                    value={genModel}
                    onChange={setGenModel}
                    options={availableLlmModels.map((m) => ({
                      label: m.displayName || m.name,
                      value: m.id,
                    }))}
                  />
                  <Text className="text-xs" style={{ whiteSpace: "nowrap" }}>
                    {t("agentEvaluation.aiGenAgent")}
                  </Text>
                  <Select
                    style={{ width: 180 }}
                    value={genAgent}
                    onChange={setGenAgent}
                    allowClear
                    placeholder={t("agentEvaluation.genSelectAgent")}
                    options={agents.map((a: any) => ({
                      label: a.display_name || a.name,
                      value: a.agent_id,
                    }))}
                  />
                  <Button
                    type="primary"
                    icon={<Zap className="size-4" />}
                    loading={busy}
                    onClick={async () => {
                      if (!genDesc.trim()) return;
                      if (!genModel) {
                        message.warning(t("agentEvaluation.selectGenModel"));
                        return;
                      }
                      setBusy(true);
                      try {
                        const r = await fetch(
                          API_ENDPOINTS.evaluators.generate,
                          {
                            method: "POST",
                            headers: {
                              ...getAuthHeaders(),
                              "Content-Type": "application/json",
                            },
                            body: JSON.stringify({
                              description: genDesc.trim(),
                              model_id: genModel,
                              agent_id: genAgent ?? undefined,
                              language: currentLang,
                            }),
                          }
                        );
                        const d = await r.json();
                        if (d?.data) {
                          setF({
                            name: d.data.name || "",
                            desc: d.data.description || "",
                            type: d.data.evaluator_type || "llm",
                            prompt: d.data.prompt || "",
                            code: d.data.code || "",
                            sMin: d.data.score_range_min ?? 0,
                            sMax: d.data.score_range_max ?? 1,
                            threshold: d.data.pass_threshold ?? 0.5,
                            modelId: genModel,
                          });
                        } else {
                          message.error(
                            d?.detail || t("agentEvaluation.genFailed")
                          );
                        }
                      } catch {
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    {t("agentEvaluation.aiGenerate")}
                  </Button>
                </Flex>
              </Flex>
            </Card>
            {/* Manual edit section */}
            <Card size="small" title={t("agentEvaluation.evaluatorConfig")}>
              <Flex vertical gap={12}>
                <Flex gap={12}>
                  <Flex vertical gap={4} flex={1}>
                    <Text className="text-xs">
                      {t("agentEvaluation.evaluatorName")}{" "}
                      <Text type="danger">*</Text>
                    </Text>
                    <Input
                      value={f.name}
                      onChange={(e) => setF({ ...f, name: e.target.value })}
                      placeholder={t("agentEvaluation.evaluatorName")}
                      maxLength={50}
                      showCount
                    />
                  </Flex>
                  <Flex vertical gap={4} style={{ width: 120 }}>
                    <Text className="text-xs">
                      {t("agentEvaluation.evaluatorTypeLabel")}
                    </Text>
                    <Select
                      value={f.type}
                      onChange={(v) => setF({ ...f, type: v })}
                      options={[
                        {
                          value: "llm",
                          label: t("agentEvaluation.evaluatorType.llm"),
                        },
                        {
                          value: "code",
                          label: t("agentEvaluation.evaluatorType.code"),
                        },
                      ]}
                    />
                  </Flex>
                </Flex>
                <Flex vertical gap={4}>
                  <Text className="text-xs">
                    {t("agentEvaluation.evaluatorDesc")}
                  </Text>
                  <Input
                    value={f.desc}
                    onChange={(e) => setF({ ...f, desc: e.target.value })}
                    placeholder={t("agentEvaluation.evaluatorDesc")}
                    maxLength={200}
                    showCount
                  />
                </Flex>
                {f.type === "llm" && (
                  <Flex vertical gap={4}>
                    <Text className="text-xs">
                      {t("agentEvaluation.evaluatorPrompt")}{" "}
                      <Text type="danger">*</Text>
                    </Text>
                    <Text className="text-xs" type="secondary">
                      {currentLang === "zh" ? (
                        <>
                          评估 Prompt，使用 {"{{query}}"}、{"{{expected}}"}、
                          {"{{actual}}"} 作为占位变量；过程判定类评估器可用{" "}
                          {"{{runtime_stats}}"} 替代 {"{{expected}}"}； prompt
                          内置语言指令，LLM 会按用户问题的语言输出
                        </>
                      ) : (
                        <>
                          Evaluation prompt template. Use {"{{query}}"},{" "}
                          {"{{expected}}"}, {"{{actual}}"} as placeholders;
                          process evaluators may use {"{{runtime_stats}}"}{" "}
                          instead of {"{{expected}}"}
                        </>
                      )}
                    </Text>
                    <Input.TextArea
                      rows={8}
                      maxLength={5000}
                      showCount
                      value={f.prompt}
                      onChange={(e) => setF({ ...f, prompt: e.target.value })}
                    />
                  </Flex>
                )}
                {f.type === "code" && (
                  <Flex vertical gap={4}>
                    <Text className="text-xs">
                      {t("agentEvaluation.evaluatorCode")}{" "}
                      <Text type="danger">*</Text>
                    </Text>
                    <Text className="text-xs" type="secondary">
                      {t("agentEvaluation.evaluatorCodeHintCode")}
                    </Text>
                    <Input.TextArea
                      rows={6}
                      maxLength={20000}
                      showCount
                      value={f.code}
                      onChange={(e) => setF({ ...f, code: e.target.value })}
                    />
                  </Flex>
                )}
                <Flex gap={12}>
                  <Flex vertical gap={4} flex={1}>
                    <Text className="text-xs">
                      {t("agentEvaluation.scoreMin")}
                    </Text>
                    <InputNumber
                      step={0.1}
                      value={f.sMin}
                      onChange={(v) => setF({ ...f, sMin: v ?? 0 })}
                      style={{ width: "100%" }}
                    />
                  </Flex>
                  <Flex vertical gap={4} flex={1}>
                    <Text className="text-xs">
                      {t("agentEvaluation.scoreMax")}
                    </Text>
                    <InputNumber
                      step={0.1}
                      max={100}
                      value={f.sMax}
                      onChange={(v) => setF({ ...f, sMax: v ?? 1 })}
                      style={{ width: "100%" }}
                    />
                  </Flex>
                  <Flex vertical gap={4} flex={1}>
                    <Text className="text-xs">
                      {t("agentEvaluation.passThreshold")}
                    </Text>
                    <InputNumber
                      step={0.1}
                      value={f.threshold}
                      onChange={(v) => setF({ ...f, threshold: v ?? 0.5 })}
                      style={{ width: "100%" }}
                    />
                  </Flex>
                </Flex>
                <Text className="text-xs" type="secondary">
                  {t("agentEvaluation.scoreRangeHint")}
                </Text>
              </Flex>
            </Card>
            <Button
              type="primary"
              loading={busy}
              onClick={async () => {
                if (!validateF()) return;
                setBusy(true);
                try {
                  const body: any = {
                    name: f.name,
                    description: f.desc,
                    evaluator_type: f.type,
                    prompt: f.type === "llm" ? f.prompt : null,
                    code: f.type === "code" ? f.code : null,
                    score_range_min: f.sMin,
                    score_range_max: f.sMax,
                    pass_threshold: f.threshold,
                    model_id: f.modelId,
                    input_fields: [
                      { name: "query", type: "string", required: true },
                      { name: "expected", type: "string", required: true },
                      { name: "actual", type: "string", required: true },
                    ],
                  };
                  const r = await fetch(API_ENDPOINTS.evaluators.create, {
                    method: "POST",
                    headers: {
                      ...getAuthHeaders(),
                      "Content-Type": "application/json",
                    },
                    body: JSON.stringify(body),
                  });
                  if (r.ok) {
                    setDrawer(false);
                    resetF();
                    refreshEval();
                  } else {
                    const d = await r.json();
                    const arrayDetail = Array.isArray(d?.detail)
                      ? d.detail
                          .map(
                            (e: any) => `${e.loc?.join(".") || ""}: ${e.msg}`
                          )
                          .join("; ")
                      : t("agentEvaluation.saveFailed");
                    const detail = d.code
                      ? getI18nErrorMessage(d.code, t)
                      : typeof d?.detail === "string"
                        ? d.detail
                        : arrayDetail;
                    message.error(detail);
                  }
                } catch {
                } finally {
                  setBusy(false);
                }
              }}
              block
            >
              {t("agentEvaluation.save")}
            </Button>
          </Flex>
        </Spin>
      </Drawer>
      <Drawer
        title={`${t("agentEvaluation.versionHistory")} · ${versionEval?.name || ""}`}
        open={versionDrawer}
        onClose={() => setVersionDrawer(false)}
        size="medium"
        extra={
          versionEval?.is_current ? (
            <Tag color="blue">
              v{versionEval?.version_no} {t("agentEvaluation.currentVersion")}
            </Tag>
          ) : null
        }
      >
        <Spin spinning={versionBusy}>
          <Flex vertical gap={12}>
            {versions.map((v: any) => (
              <Card
                key={v.evaluator_id}
                size="small"
                title={
                  <Space>
                    v{v.version_no}
                    {v.is_current && (
                      <Tag color="blue">
                        {t("agentEvaluation.currentVersion")}
                      </Tag>
                    )}
                  </Space>
                }
                extra={
                  !v.is_current && (
                    <Space size={4}>
                      <Popconfirm
                        title={t("agentEvaluation.versionRestoreConfirm")}
                        onConfirm={() => restoreVersion(v.evaluator_id)}
                      >
                        <Button type="link" size="small">
                          {t("agentEvaluation.restore")}
                        </Button>
                      </Popconfirm>
                      <Popconfirm
                        title={t("agentEvaluation.versionDeleteConfirm")}
                        onConfirm={() => deleteVersion(v.evaluator_id)}
                      >
                        <Button type="link" size="small" danger>
                          {t("agentEvaluation.delete")}
                        </Button>
                      </Popconfirm>
                    </Space>
                  )
                }
              >
                <Flex vertical gap={4}>
                  <Text className="text-xs" type="secondary">
                    {v.create_time
                      ? new Date(v.create_time).toLocaleString("zh-CN")
                      : ""}
                  </Text>
                  <Flex gap={8}>
                    <Tag>{tl[v.evaluator_type] || v.evaluator_type}</Tag>
                    <Tag color={v.status === "PUBLISHED" ? "green" : "orange"}>
                      {v.status === "PUBLISHED"
                        ? t("agentEvaluation.published")
                        : t("agentEvaluation.draft")}
                    </Tag>
                  </Flex>
                  <Text className="text-xs">
                    {t("agentEvaluation.scoreRange")}: {v.score_range_min} ~{" "}
                    {v.score_range_max} | {t("agentEvaluation.threshold")}:{" "}
                    {v.pass_threshold}
                  </Text>
                  {v.prompt &&
                    (v.prompt.length > 80 ? (
                      <details style={{ maxWidth: "100%" }}>
                        <summary style={{ cursor: "pointer" }}>
                          <Text className="text-xs" type="secondary">
                            {v.prompt.slice(0, 80)}...
                          </Text>
                        </summary>
                        <Text
                          className="text-xs"
                          type="secondary"
                          style={{
                            whiteSpace: "pre-wrap",
                            wordBreak: "break-word",
                          }}
                        >
                          {v.prompt}
                        </Text>
                      </details>
                    ) : (
                      <Text className="text-xs" type="secondary">
                        {v.prompt}
                      </Text>
                    ))}
                </Flex>
              </Card>
            ))}
            {versions.length === 0 && (
              <Text type="secondary">
                {t("agentEvaluation.noVersionHistory")}
              </Text>
            )}
          </Flex>
        </Spin>
      </Drawer>
      <Drawer
        title={t("agentEvaluation.edit")}
        open={!!editTarget}
        onClose={() => setEditTarget(null)}
        size="large"
      >
        {editTarget && (
          <Flex vertical gap={16}>
            <Flex vertical gap={4}>
              <Text className="text-xs">
                {t("agentEvaluation.evaluatorName")}
              </Text>
              <Input
                value={editTarget.name}
                onChange={(e) =>
                  setEditTarget({ ...editTarget, name: e.target.value })
                }
                maxLength={50}
                showCount
              />
            </Flex>
            <Flex vertical gap={4}>
              <Text className="text-xs">
                {t("agentEvaluation.evaluatorDesc")}
              </Text>
              <Input
                value={editTarget.description}
                onChange={(e) =>
                  setEditTarget({ ...editTarget, description: e.target.value })
                }
                maxLength={200}
                showCount
              />
            </Flex>
            {editTarget.evaluator_type === "llm" && (
              <Flex vertical gap={4}>
                <Text className="text-xs">
                  {t("agentEvaluation.evaluatorPrompt")}
                </Text>
                <Input.TextArea
                  rows={6}
                  maxLength={5000}
                  showCount
                  value={editTarget.prompt || ""}
                  onChange={(e) =>
                    setEditTarget({ ...editTarget, prompt: e.target.value })
                  }
                />
              </Flex>
            )}
            <Flex gap={12}>
              <Flex vertical gap={4} flex={1}>
                <Text className="text-xs">{t("agentEvaluation.scoreMin")}</Text>
                <InputNumber
                  step={0.1}
                  value={editTarget.score_range_min ?? 0}
                  onChange={(v) =>
                    setEditTarget({ ...editTarget, score_range_min: v ?? 0 })
                  }
                  style={{ width: "100%" }}
                />
              </Flex>
              <Flex vertical gap={4} flex={1}>
                <Text className="text-xs">{t("agentEvaluation.scoreMax")}</Text>
                <InputNumber
                  step={0.1}
                  max={100}
                  value={editTarget.score_range_max ?? 1}
                  onChange={(v) =>
                    setEditTarget({ ...editTarget, score_range_max: v ?? 1 })
                  }
                  style={{ width: "100%" }}
                />
              </Flex>
              <Flex vertical gap={4} flex={1}>
                <Text className="text-xs">
                  {t("agentEvaluation.passThreshold")}
                </Text>
                <InputNumber
                  step={0.1}
                  value={editTarget.pass_threshold ?? 0.5}
                  onChange={(v) =>
                    setEditTarget({ ...editTarget, pass_threshold: v ?? 0.5 })
                  }
                  style={{ width: "100%" }}
                />
              </Flex>
            </Flex>
            <Text className="text-xs" type="secondary">
              {t("agentEvaluation.scoreRangeHint")}
            </Text>
            <Button
              type="primary"
              onClick={async () => {
                const lo = editTarget.score_range_min ?? 0,
                  hi = editTarget.score_range_max ?? 1,
                  th = editTarget.pass_threshold ?? 0.5;
                if (lo >= hi) {
                  message.warning(t("agentEvaluation.validation.scoreMinMax"));
                  return;
                }
                if (th <= lo || th >= hi) {
                  message.warning(
                    t("agentEvaluation.validation.thresholdRange")
                  );
                  return;
                }
                if (hi > 100) {
                  message.warning(
                    t("agentEvaluation.validation.scoreMaxLimit")
                  );
                  return;
                }
                const res = await fetch(
                  `${API_ENDPOINTS.evaluators.detail(editTarget.evaluator_id)}`,
                  {
                    method: "PUT",
                    headers: {
                      ...getAuthHeaders(),
                      "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                      name: editTarget.name,
                      description: editTarget.description,
                      prompt: editTarget.prompt,
                      score_range_min: editTarget.score_range_min,
                      score_range_max: editTarget.score_range_max,
                      pass_threshold: editTarget.pass_threshold,
                    }),
                  }
                );
                if (!res.ok) {
                  const d = await res.json().catch(() => ({}));
                  message.error(getI18nErrorMessage(d.code, t));
                  return;
                }
                setEditTarget(null);
                refreshEval();
              }}
              block
            >
              {t("agentEvaluation.save")}
            </Button>
          </Flex>
        )}
      </Drawer>
    </div>
  );
}

function SetsTab() {
  const { t } = useTranslation("common");
  const { message } = App.useApp();
  const [sets, setSets] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const [uploadD, setUploadD] = useState(false);
  const [genD, setGenD] = useState(false);
  const [detailD, setDetailD] = useState(false);
  const [detailSet, setDetailSet] = useState<any>(null);
  const [detailCases, setDetailCases] = useState<any[]>([]);
  const [ulName, setUlName] = useState("");
  const [ulDesc, setUlDesc] = useState("");
  const [ulFile, setUlFile] = useState<File | null>(null);
  const [fileErr, setFileErr] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const validateFile = (file: File) => {
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!["xlsx", "xls"].includes(ext || "")) {
      setFileErr(t("agentEvaluation.uploadFileInvalid"));
      return false;
    }
    if (file.size > 20 * 1024 * 1024) {
      setFileErr(t("agentEvaluation.uploadFileTooBig"));
      return false;
    }
    setFileErr("");
    return true;
  };
  const [genDesc, setGenDesc] = useState("");
  const [genDescError, setGenDescError] = useState<string | null>(null);
  const [genCount, setGenCount] = useState(10);
  const [genSetModel, setGenSetModel] = useState<number | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [genAgentId, setGenAgentId] = useState<number | undefined>(undefined);
  const [genFiles, setGenFiles] = useState<File[]>([]);
  const [genFileErr, setGenFileErr] = useState("");
  const [genKbIds, setGenKbIds] = useState<number[]>([]);
  const [kbList, setKbList] = useState<any[]>([]);
  const [genSetName, setGenSetName] = useState("");
  const [genSetDesc, setGenSetDesc] = useState("");
  const [genTargetSetId, setGenTargetSetId] = useState<number | undefined>(
    undefined
  );
  const { availableLlmModels } = useModelList();
  const [agentList] = useList("/api/agent/published_list");
  const genFileRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!genSetModel && availableLlmModels.length > 0)
      setGenSetModel(availableLlmModels[0].id);
  }, [availableLlmModels]);
  const [editingCase, setEditingCase] = useState<any>(null);
  const [adding, setAdding] = useState(false);
  const [newQ, setNewQ] = useState("");
  const [newA, setNewA] = useState("");
  const [newSid, setNewSid] = useState("");
  const [newTurn, setNewTurn] = useState<number | null>(null);
  const [selKeys, setSelKeys] = useState<Key[]>([]);
  const [batchDeleting, setBatchDeleting] = useState(false);
  const [setCasePage, setSetCasePage] = useState(1);
  const [setCaseQuery, setSetCaseQuery] = useState("");
  const [setCaseInput, setSetCaseInput] = useState("");
  const [setCaseTotal, setSetCaseTotal] = useState(0);
  const SET_CASE_PAGE_SIZE = 10;

  const refreshSets = () =>
    fetch("/api/evaluation-sets", { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => {
        setSets(d.data || d.items || []);
      });

  useEffect(() => {
    setLoading(true);
    refreshSets().finally(() => setLoading(false));
  }, []);

  // Poll when any set is GENERATING
  useEffect(() => {
    const hasGen = sets.some((s: any) => s.generation_status === "GENERATING");
    if (!hasGen) return;
    const t = setInterval(refreshSets, 2000);
    return () => clearInterval(t);
  }, [sets]);

  const loadSetCasesPage = async (setId: number, page: number, q?: string) => {
    const sq = q ?? setCaseQuery;
    const offset = (page - 1) * SET_CASE_PAGE_SIZE;
    let url = `/api/evaluation-sets/${setId}/cases?limit=${SET_CASE_PAGE_SIZE}&offset=${offset}`;
    if (sq) url += `&query=${encodeURIComponent(sq)}`;
    const r = await fetch(url, { headers: getAuthHeaders() });
    const d = await r.json();
    setDetailCases(d.data || d.items || []);
    if (d.total != null) setSetCaseTotal(d.total);
  };

  const showDetail = async (s: any) => {
    setDetailSet(s);
    setDetailD(true);
    setSetCasePage(1);
    setSetCaseQuery("");
    setSetCaseTotal(0);
    await loadSetCasesPage(s.evaluation_set_id, 1, "");
  };

  const cols = [
    {
      title: t("agentEvaluation.colHeader.name"),
      dataIndex: "name",
      ellipsis: true,
      width: 160,
      filterDropdown: ({ setSelectedKeys, selectedKeys, confirm }: any) => (
        <div style={{ padding: 8 }}>
          <Input
            placeholder={t("agentEvaluation.searchName")}
            value={selectedKeys[0]}
            onChange={(e) =>
              setSelectedKeys(e.target.value ? [e.target.value] : [])
            }
            onPressEnter={() => confirm()}
            onBlur={() => confirm()}
            size="small"
            style={{ width: 160 }}
          />
        </div>
      ),
      onFilter: (value: any, record: any) =>
        record.name?.toLowerCase().includes(String(value).toLowerCase()),
    },
    {
      title: t("agentEvaluation.colHeader.description"),
      dataIndex: "description",
      ellipsis: true,
      render: (v: any) => v || "-",
    },
    {
      title: t("agentEvaluation.caseCount"),
      dataIndex: "case_count",
      width: 60,
    },
    {
      title: t("agentEvaluation.colHeader.status"),
      key: "gs",
      width: 120,
      render: (_: any, r: any) => {
        if (r.generation_status === "GENERATING")
          return (
            <Flex vertical gap={2}>
              <Text className="text-xs" type="secondary">
                {t("agentEvaluation.genStatusGenerating")}{" "}
                {r.generation_progress || 0}%
              </Text>
              <Progress
                percent={r.generation_progress || 0}
                size="small"
                showInfo={false}
              />
            </Flex>
          );
        if (r.generation_status === "FAILED")
          return <Tag color="red">{t("agentEvaluation.genStatusFailed")}</Tag>;
        return <Tag color="green">{t("agentEvaluation.genStatusReady")}</Tag>;
      },
    },
    {
      title: t("agentEvaluation.colHeader.actions"),
      width: 110,
      render: (_: any, r: any) => (
        <Space size={0}>
          <Tooltip title={t("agentEvaluation.view")}>
            <Button
              type="link"
              size="small"
              icon={<Eye className="size-3.5" />}
              onClick={() => showDetail(r)}
            />
          </Tooltip>
          <Tooltip title={t("agentEvaluation.export")}>
            <Button
              type="link"
              size="small"
              icon={<Download className="size-3.5" />}
              onClick={async () => {
                try {
                  const blobUrl = await fetch(
                    API_ENDPOINTS.evaluationSets.export(r.evaluation_set_id),
                    { headers: getAuthHeaders() }
                  );
                  if (!blobUrl.ok) {
                    const d = await blobUrl.json();
                    const msg = d.code
                      ? getI18nErrorMessage(d.code, t)
                      : typeof d?.detail === "string"
                        ? d.detail
                        : t("agentEvaluation.exportError");
                    message.warning(msg);
                    return;
                  }
                  const blob = await blobUrl.blob();
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `${r.name}.xlsx`;
                  document.body.appendChild(a);
                  a.click();
                  document.body.removeChild(a);
                  URL.revokeObjectURL(url);
                } catch {
                  message.warning(t("agentEvaluation.exportError"));
                }
              }}
            />
          </Tooltip>
          <Popconfirm
            title={t("agentEvaluation.deleteConfirm")}
            onConfirm={async () => {
              const resp = await fetch(
                API_ENDPOINTS.evaluationSets.delete(r.evaluation_set_id),
                { method: "DELETE", headers: getAuthHeaders() }
              );
              if (!resp.ok) {
                const d = await resp.json();
                message.warning(
                  d.code
                    ? getI18nErrorMessage(d.code, t)
                    : d.detail || d.message || t("agentEvaluation.deleteFailed")
                );
              }
              refreshSets();
            }}
          >
            <Tooltip title={t("agentEvaluation.delete")}>
              <Button
                type="link"
                size="small"
                danger
                icon={<Trash2 className="size-3.5" />}
              />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];
  const isNewRow = (r: any) => r?.__isNew;
  const isEditingRow = (r: any) =>
    editingCase &&
    r?.evaluation_set_case_id === editingCase.evaluation_set_case_id;
  const saveNewCase = async () => {
    if (!newQ.trim() || !newA.trim()) return;
    try {
      const r = await fetch(
        `/api/evaluation-sets/${detailSet.evaluation_set_id}/cases`,
        {
          method: "POST",
          headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
          body: JSON.stringify({
            inputs: { query: newQ.trim() },
            label: { answer: newA.trim() },
            session_id: newSid.trim() || null,
            turn_order: newTurn,
          }),
        }
      );
      if (!r.ok) {
        const d = await r.json();
        const errorMsg = d.code
          ? getI18nErrorMessage(d.code, t)
          : d.detail || d.message || "Failed to add case";
        message.error(errorMsg);
        return;
      }
      setAdding(false);
      setNewQ("");
      setNewA("");
      setNewSid("");
      setNewTurn(null);
      loadSetCasesPage(detailSet.evaluation_set_id, setCasePage);
    } catch {
      message.error("Network error");
    }
  };
  const saveEditCase = async () => {
    if (!editingCase) return;
    const c = editingCase;
    try {
      const r = await fetch(
        `/api/evaluation-sets/${detailSet.evaluation_set_id}/cases/${c.evaluation_set_case_id}`,
        {
          method: "PUT",
          headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
          body: JSON.stringify({
            inputs: c.inputs,
            label: c.label,
            session_id: c.session_id || null,
            turn_order: c.turn_order ?? null,
          }),
        }
      );
      if (!r.ok) {
        const d = await r.json();
        const errorMsg = d.code
          ? getI18nErrorMessage(d.code, t)
          : d.detail || d.message || "Failed to update case";
        message.error(errorMsg);
        return;
      }
      setEditingCase(null);
      loadSetCasesPage(detailSet.evaluation_set_id, setCasePage);
    } catch {
      message.error("Network error");
    }
  };
  const startEdit = (r: any) => {
    setAdding(false);
    setEditingCase({ ...r, inputs: { ...r.inputs }, label: { ...r.label } });
  };
  const getSessionColor = (sid?: string | null) => {
    if (!sid) return "#bfbfbf";
    let h = 0;
    for (let i = 0; i < sid.length; i++) {
      h = (h << 5) - h + sid.charCodeAt(i);
      h = Math.trunc(h);
    }
    const colors = [
      "#1677ff",
      "#52c41a",
      "#faad14",
      "#722ed1",
      "#eb2f96",
      "#13c2c2",
      "#f5222d",
      "#2f54eb",
    ];
    return colors[Math.abs(h) % colors.length];
  };
  const caseCols = [
    {
      title: "#",
      width: 40,
      render: (_: any, __: any, i: number) =>
        isNewRow(__) ? (
          <Plus className="size-3.5 text-blue-500" />
        ) : isEditingRow(__) ? (
          <Pencil className="size-3.5 text-amber-500" />
        ) : (
          (setCasePage - 1) * SET_CASE_PAGE_SIZE + (adding ? i : i + 1)
        ),
    },
    {
      title: t("agentEvaluation.colHeader.session"),
      key: "session_id",
      width: 130,
      render: (_: any, r: any) => {
        if (isNewRow(r))
          return (
            <Input
              size="small"
              value={newSid}
              onChange={(e) => setNewSid(e.target.value)}
              placeholder={t("agentEvaluation.inputSessionId")}
              style={{ width: "100%" }}
            />
          );
        if (isEditingRow(r))
          return (
            <Input
              size="small"
              value={editingCase.session_id || ""}
              onChange={(e) =>
                setEditingCase({ ...editingCase, session_id: e.target.value })
              }
              placeholder={t("agentEvaluation.inputSessionId")}
              style={{ width: "100%" }}
            />
          );
        const sid = r.session_id;
        if (!sid || sid === "__single__")
          return (
            <Tag color="default" className="text-xs">
              --
            </Tag>
          );
        return (
          <Tag
            color={getSessionColor(sid)}
            className="text-xs"
            style={{
              maxWidth: 120,
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {sid}
          </Tag>
        );
      },
    },
    {
      title: t("agentEvaluation.colHeader.turnOrder"),
      key: "turn_order",
      width: 80,
      render: (_: any, r: any) => {
        if (isNewRow(r))
          return (
            <InputNumber
              size="small"
              value={newTurn}
              onChange={(v) => setNewTurn(v)}
              min={1}
              placeholder={t("agentEvaluation.inputTurnOrder")}
              style={{ width: "100%" }}
            />
          );
        if (isEditingRow(r))
          return (
            <InputNumber
              size="small"
              value={editingCase.turn_order ?? null}
              onChange={(v) =>
                setEditingCase({ ...editingCase, turn_order: v })
              }
              min={1}
              placeholder={t("agentEvaluation.inputTurnOrder")}
              style={{ width: "100%" }}
            />
          );
        const to = r.turn_order;
        if (to == null || to == undefined)
          return (
            <Text type="secondary" className="text-xs">
              -
            </Text>
          );
        return <Text className="text-xs">{to}</Text>;
      },
    },
    {
      title: t("agentEvaluation.colHeader.query"),
      key: "q",
      ellipsis: true,
      render: (_: any, r: any) => {
        if (isNewRow(r))
          return (
            <Input
              size="small"
              value={newQ}
              onChange={(e) => setNewQ(e.target.value)}
              onPressEnter={saveNewCase}
              placeholder={t("agentEvaluation.inputQuestion")}
              maxLength={2000}
              style={{ width: "100%" }}
            />
          );
        if (isEditingRow(r))
          return (
            <Input
              size="small"
              value={editingCase.inputs?.query || ""}
              onChange={(e) =>
                setEditingCase({
                  ...editingCase,
                  inputs: { ...editingCase.inputs, query: e.target.value },
                })
              }
              onPressEnter={saveEditCase}
              maxLength={2000}
              style={{ width: "100%" }}
            />
          );
        return r.inputs?.query || "-";
      },
      filterDropdown:
        adding || editingCase
          ? undefined
          : ({ confirm }: any) => (
              <div
                style={{ padding: 8 }}
                onKeyDown={(e) => e.stopPropagation()}
              >
                <Input
                  placeholder={t("agentEvaluation.searchQuestion")}
                  value={setCaseInput}
                  onChange={(e) => setSetCaseInput(e.target.value)}
                  onPressEnter={() => {
                    setSetCaseQuery(setCaseInput);
                    setSetCasePage(1);
                    loadSetCasesPage(
                      detailSet.evaluation_set_id,
                      1,
                      setCaseInput
                    );
                  }}
                  size="small"
                  style={{ width: 200 }}
                />
              </div>
            ),
    },
    {
      title: t("agentEvaluation.colHeader.answer"),
      key: "a",
      ellipsis: true,
      render: (_: any, r: any) => {
        if (isNewRow(r))
          return (
            <Input
              size="small"
              value={newA}
              onChange={(e) => setNewA(e.target.value)}
              onPressEnter={saveNewCase}
              placeholder={t("agentEvaluation.inputAnswer")}
              maxLength={5000}
              style={{ width: "100%" }}
            />
          );
        if (isEditingRow(r))
          return (
            <Input
              size="small"
              value={editingCase.label?.answer || ""}
              onChange={(e) =>
                setEditingCase({
                  ...editingCase,
                  label: { ...editingCase.label, answer: e.target.value },
                })
              }
              onPressEnter={saveEditCase}
              maxLength={5000}
              style={{ width: "100%" }}
            />
          );
        return r.label?.answer || "-";
      },
    },
    {
      title: t("agentEvaluation.colHeader.actions"),
      width: 100,
      render: (_: any, r: any) => {
        if (isNewRow(r))
          return (
            <Space size={4}>
              <Button type="link" size="small" onClick={saveNewCase}>
                {t("agentEvaluation.save")}
              </Button>
              <Button
                type="link"
                size="small"
                onClick={() => {
                  setAdding(false);
                  setNewQ("");
                  setNewA("");
                  setNewSid("");
                  setNewTurn(null);
                }}
              >
                {t("agentEvaluation.cancel")}
              </Button>
            </Space>
          );
        if (isEditingRow(r))
          return (
            <Space size={4}>
              <Button type="link" size="small" onClick={saveEditCase}>
                {t("agentEvaluation.save")}
              </Button>
              <Button
                type="link"
                size="small"
                onClick={() => setEditingCase(null)}
              >
                {t("agentEvaluation.cancel")}
              </Button>
            </Space>
          );
        return (
          <Space size={4}>
            <Button type="link" size="small" onClick={() => startEdit(r)}>
              {t("agentEvaluation.edit")}
            </Button>
            <Popconfirm
              title={t("agentEvaluation.deleteConfirm")}
              onConfirm={async () => {
                try {
                  const resp = await fetch(
                    `/api/evaluation-sets/${detailSet.evaluation_set_id}/cases/${r.evaluation_set_case_id}`,
                    { method: "DELETE", headers: getAuthHeaders() }
                  );
                  if (!resp.ok) {
                    const d = await resp.json();
                    const errorMsg = d.code
                      ? getI18nErrorMessage(d.code, t)
                      : d.detail || d.message || "Delete failed";
                    message.error(errorMsg);
                    return;
                  }
                  loadSetCasesPage(detailSet.evaluation_set_id, setCasePage);
                } catch {
                  message.error("Network error");
                }
              }}
            >
              <Button type="link" size="small" danger>
                {t("agentEvaluation.delete")}
              </Button>
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  return (
    <div>
      <Flex justify="space-between" align="center" style={{ marginBottom: 16 }}>
        <Text strong>{t("agentEvaluation.setsHeader")}</Text>
        <Space>
          <Button onClick={() => setUploadD(true)}>
            {t("agentEvaluation.uploadButton")}
          </Button>
          <Button type="primary" onClick={() => setGenD(true)}>
            {t("agentEvaluation.genSection")}
          </Button>
        </Space>
      </Flex>
      <Table
        columns={cols}
        dataSource={sets}
        rowKey="evaluation_set_id"
        size="small"
        loading={loading}
        pagination={{ pageSize: 10 }}
      />
      <Drawer
        title={t("agentEvaluation.uploadTitle")}
        open={uploadD}
        onClose={() => setUploadD(false)}
        size="large"
      >
        <Flex vertical gap={20}>
          <Flex vertical gap={4}>
            <Text className="text-xs">
              {t("agentEvaluation.uploadSetName")} <Text type="danger">*</Text>
            </Text>
            <Input
              value={ulName}
              onChange={(e) => setUlName(e.target.value)}
              maxLength={64}
              showCount
            />
          </Flex>
          <Flex vertical gap={4}>
            <Text className="text-xs">{t("agentEvaluation.description")}</Text>
            <Input
              value={ulDesc}
              onChange={(e) => setUlDesc(e.target.value)}
              placeholder={t("agentEvaluation.uploadDescPlaceholder")}
              maxLength={200}
              showCount
            />
          </Flex>
          <Flex vertical gap={4}>
            <Text className="text-xs">
              {t("agentEvaluation.uploadSetFile")} <Text type="danger">*</Text>
            </Text>
            <Text className="text-xs" type="secondary">
              {t("agentEvaluation.uploadSetHint")}
            </Text>
            <div
              style={{
                border: "1px dashed #d9d9d9",
                borderRadius: 8,
                padding: "24px",
                textAlign: "center",
                background: "#fafafa",
                cursor: "pointer",
              }}
              role="button"
              tabIndex={0}
              onClick={() => fileRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  fileRef.current?.click();
                }
              }}
            >
              {ulFile ? (
                <Flex vertical gap={4} align="center">
                  <Tag
                    color="blue"
                    closable
                    onClose={(e) => {
                      e.stopPropagation();
                      setUlFile(null);
                      setFileErr("");
                    }}
                  >
                    {ulFile.name}
                  </Tag>
                  <Text className="text-xs" type="secondary">
                    {(ulFile.size / 1024).toFixed(1)} KB
                  </Text>
                </Flex>
              ) : (
                <Flex vertical gap={4} align="center">
                  <Upload className="size-6 text-gray-400" />
                  <Text className="text-xs" type="secondary">
                    {t("agentEvaluation.uploadFileArea")}
                  </Text>
                </Flex>
              )}
              <input
                ref={fileRef}
                type="file"
                accept=".xlsx,.xls"
                style={{ display: "none" }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (!f) return;
                  const ok = validateFile(f);
                  if (ok) {
                    setUlFile(f);
                  } else {
                    setUlFile(null);
                  }
                }}
              />
            </div>
            {fileErr && (
              <Text type="danger" className="text-xs">
                {fileErr}
              </Text>
            )}
          </Flex>
          <Flex gap={8}>
            <Button
              href={`${API_ENDPOINTS.evaluationSets.template}`}
              icon={<Download className="size-4" />}
              target="_blank"
            >
              {t("agentEvaluation.downloadTemplate")}
            </Button>
            <Button
              type="primary"
              loading={busy}
              onClick={async () => {
                if (!ulName || !ulFile) return;
                const fd = new FormData();
                fd.append("name", ulName);
                fd.append("files", ulFile);
                if (ulDesc) fd.append("description", ulDesc);
                setBusy(true);
                setFileErr("");
                try {
                  const headers: any = { ...getAuthHeaders() };
                  delete headers["Content-Type"];
                  const r = await fetch(API_ENDPOINTS.evaluationSets.upload, {
                    method: "POST",
                    headers,
                    body: fd,
                  });
                  if (r.ok) {
                    setUploadD(false);
                    setUlName("");
                    setUlDesc("");
                    setUlFile(null);
                    refreshSets();
                  } else {
                    const d = await r.json();
                    const arrayDetail = Array.isArray(d?.detail)
                      ? d.detail
                          .map(
                            (e: any) => `${e.loc?.join(".") || ""}: ${e.msg}`
                          )
                          .join("; ")
                      : t("agentEvaluation.uploadErrorFormat");
                    const msg =
                      typeof d?.detail === "string" ? d.detail : arrayDetail;
                    setFileErr(msg);
                  }
                } catch {
                  setFileErr(t("agentEvaluation.uploadErrorNetwork"));
                } finally {
                  setBusy(false);
                }
              }}
            >
              {t("agentEvaluation.uploadButton")}
            </Button>
          </Flex>
        </Flex>
      </Drawer>
      <Drawer
        title={t("agentEvaluation.genTitle")}
        open={genD}
        onClose={() => {
          setGenD(false);
          setGenDescError(null);
          setGenTargetSetId(undefined);
          setGenSetName("");
          setGenSetDesc("");
          setGenKbIds([]);
          setGenFiles([]);
        }}
        size="large"
        maskClosable={!busy}
        closable={!busy}
      >
        <Spin spinning={busy} description={t("agentEvaluation.genRunningHint")}>
          <Flex vertical gap={16}>
            <Card size="small" title={t("agentEvaluation.genTargetSetTitle")}>
              <Flex vertical gap={8}>
                <Flex vertical gap={4}>
                  <Text className="text-xs">
                    {t("agentEvaluation.genSetLabel")}{" "}
                    <Text type="secondary" className="text-xs">
                      {t("agentEvaluation.genSetOptionalHint")}
                    </Text>
                  </Text>
                  <Select
                    allowClear
                    showSearch
                    placeholder={t("agentEvaluation.genSelectExistingSet")}
                    value={genTargetSetId}
                    onChange={(v) => {
                      setGenTargetSetId(v);
                      if (v) {
                        const s = sets.find(
                          (x: any) => x.evaluation_set_id === v
                        );
                        setGenSetName(s?.name || "");
                        setGenSetDesc(s?.description || "");
                      } else {
                        setGenSetName("");
                        setGenSetDesc("");
                      }
                    }}
                    options={sets.map((s: any) => ({
                      label: `${s.name} (${s.case_count || 0} ${t("agentEvaluation.history.pieces")})`,
                      value: s.evaluation_set_id,
                    }))}
                  />
                  <Text className="text-xs" type="secondary">
                    {t("agentEvaluation.genExistingSetHint")}
                  </Text>
                </Flex>
                <Flex vertical gap={4}>
                  <Text className="text-xs">
                    {t("agentEvaluation.colHeader.name")}{" "}
                    <Text type="danger">*</Text>
                  </Text>
                  <Input
                    value={genSetName}
                    onChange={(e) => setGenSetName(e.target.value)}
                    placeholder={
                      genTargetSetId
                        ? t("agentEvaluation.genSetNameAutoHint")
                        : t("agentEvaluation.genSetNameHint")
                    }
                    maxLength={64}
                    disabled={!!genTargetSetId}
                  />
                </Flex>
                <Flex vertical gap={4}>
                  <Text className="text-xs">
                    {t("agentEvaluation.description")}
                  </Text>
                  <Input
                    value={genSetDesc}
                    onChange={(e) => setGenSetDesc(e.target.value)}
                    placeholder={t("agentEvaluation.aiGenPlaceholder")}
                    maxLength={200}
                    showCount
                    disabled={!!genTargetSetId}
                  />
                </Flex>
              </Flex>
            </Card>
            <Card
              size="small"
              title={
                <Flex gap={6} align="center">
                  <Zap className="size-4" />
                  <Text>
                    {t("agentEvaluation.genSceneDescTitle")}{" "}
                    <Text type="danger">*</Text>
                  </Text>
                </Flex>
              }
            >
              <Flex vertical gap={8}>
                <Text className="text-xs" type="secondary">
                  {t("agentEvaluation.genSceneDescHint")}
                </Text>
                <Input.TextArea
                  rows={3}
                  maxLength={1000}
                  value={genDesc}
                  status={genDescError ? "error" : undefined}
                  onChange={(e) => {
                    setGenDesc(e.target.value);
                    if (genDescError && e.target.value.trim()) {
                      setGenDescError(null);
                    }
                  }}
                  placeholder={t("agentEvaluation.genSceneDescPlaceholder")}
                />
                {genDescError && (
                  <Text type="danger" className="text-xs">
                    {genDescError}
                  </Text>
                )}
              </Flex>
            </Card>
            <Card
              size="small"
              title={t("agentEvaluation.genOptionalContextTitle")}
            >
              <Flex vertical gap={12}>
                {/* Knowledge base */}
                <Flex vertical gap={4}>
                  <Text className="text-xs">
                    {t("agentEvaluation.genKbLabel")}
                  </Text>
                  <Select
                    mode="multiple"
                    maxCount={5}
                    allowClear
                    placeholder={t("agentEvaluation.genSelectKb")}
                    value={genKbIds}
                    onChange={setGenKbIds}
                    options={kbList.map((k: any) => ({
                      label: k.display_name || k.name || k,
                      value: k.display_name || k.name || k,
                    }))}
                    onOpenChange={(open) => {
                      if (open) {
                        fetch("/api/indices?include_stats=true", {
                          headers: getAuthHeaders(),
                        })
                          .then((r) => r.json())
                          .then((d) => {
                            const info = d.indices_info || [];
                            setKbList(
                              info.map((x: any) => ({
                                name: x.name,
                                display_name: x.display_name,
                                kb_id: x.display_name,
                              }))
                            );
                          });
                      }
                    }}
                  />
                </Flex>
                {/* Agent context */}
                <Flex vertical gap={4}>
                  <Text className="text-xs">
                    {t("agentEvaluation.genAgentLabel")}
                  </Text>
                  <Select
                    allowClear
                    placeholder={t("agentEvaluation.genSelectAgent")}
                    value={genAgentId}
                    onChange={setGenAgentId}
                    options={agentList.map((a: any) => ({
                      label: a.display_name || a.name || `#${a.agent_id}`,
                      value: a.agent_id,
                    }))}
                  />
                </Flex>
                {/* File upload */}
                <Flex vertical gap={4}>
                  <Text className="text-xs">
                    {t("agentEvaluation.genRefDocLabel")}{" "}
                    <Text className="text-xs" type="secondary">
                      {t("agentEvaluation.refDocHint")}
                    </Text>
                  </Text>
                  <Flex gap={8} align="center" wrap>
                    <Button
                      icon={<Upload className="size-4" />}
                      disabled={genFiles.length >= 1}
                      onClick={() => genFileRef.current?.click()}
                    >
                      {t("agentEvaluation.selectFileButton")}
                    </Button>
                    <input
                      ref={genFileRef}
                      type="file"
                      accept=".docx"
                      style={{ display: "none" }}
                      onChange={(e) => {
                        const files = Array.from(e.target.files || []);
                        const valid = files.filter((f) => {
                          if (f.size > 20 * 1024 * 1024) {
                            setGenFileErr(
                              t("agentEvaluation.over20MBHint", {
                                name: f.name,
                              })
                            );
                            return false;
                          }
                          return true;
                        });
                        setGenFileErr("");
                        setGenFiles(valid.slice(0, 1));
                      }}
                    />
                    {genFiles.map((f, i) => (
                      <Tag
                        key={`${f.name}_${f.size}`}
                        closable
                        onClose={() =>
                          setGenFiles((p) => p.filter((_, j) => j !== i))
                        }
                      >
                        {f.name} ({(f.size / 1024).toFixed(1)}KB)
                      </Tag>
                    ))}
                  </Flex>
                  {genFileErr && (
                    <Text type="danger" className="text-xs">
                      {genFileErr}
                    </Text>
                  )}
                </Flex>
              </Flex>
            </Card>
            <Flex gap={12} align="center">
              <Flex vertical gap={4} style={{ width: 100 }}>
                <Text className="text-xs">
                  {t("agentEvaluation.genCountLabel")}
                </Text>
                <InputNumber
                  min={1}
                  max={200}
                  value={genCount}
                  onChange={(v) => setGenCount(v ?? 10)}
                  style={{ width: "100%" }}
                />
              </Flex>
              <Flex vertical gap={4} style={{ flex: 1 }}>
                <Text className="text-xs">
                  {t("agentEvaluation.aiGenModel")}
                </Text>
                <Select
                  value={genSetModel}
                  onChange={setGenSetModel}
                  options={availableLlmModels.map((m) => ({
                    label: m.displayName || m.name,
                    value: m.id,
                  }))}
                />
              </Flex>
              <Button
                type="primary"
                icon={<Zap className="size-4" />}
                loading={busy}
                style={{ marginTop: 18 }}
                onClick={async () => {
                  if (!genDesc.trim()) {
                    setGenDescError(t("agentEvaluation.genSceneDescRequired"));
                    return;
                  }
                  if (!genSetModel) {
                    message.warning(t("agentEvaluation.selectGenModel"));
                    return;
                  }
                  if (!genTargetSetId && !genSetName.trim()) {
                    message.warning(t("agentEvaluation.selectSetOrName"));
                    return;
                  }
                  setBusy(true);
                  try {
                    const body: any = {
                      description: genDesc.trim(),
                      count: genCount,
                      model_id: genSetModel,
                    };
                    if (genKbIds.length > 0)
                      body.knowledge_base_names = genKbIds;
                    if (genAgentId) body.agent_id = genAgentId;
                    if (genTargetSetId) {
                      body.target_set_id = genTargetSetId;
                    } else {
                      body.set_name = genSetName.trim();
                      if (genSetDesc) body.set_description = genSetDesc;
                    }
                    let r: Response;
                    if (genFiles.length > 0) {
                      const fd = new FormData();
                      fd.append("payload", JSON.stringify(body));
                      fd.append("file", genFiles[0]);
                      r = await fetch(
                        "/api/evaluation-sets/generate-cases-async",
                        {
                          method: "POST",
                          headers: { ...getAuthHeaders() },
                          body: fd,
                        }
                      );
                    } else {
                      r = await fetch(
                        "/api/evaluation-sets/generate-cases-async",
                        {
                          method: "POST",
                          headers: {
                            ...getAuthHeaders(),
                            "Content-Type": "application/json",
                          },
                          body: JSON.stringify(body),
                        }
                      );
                    }
                    const d = await r.json();
                    if (d?.data?.evaluation_set_id) {
                      setGenD(false);
                      setGenDesc("");
                      setGenDescError(null);
                      setGenAgentId(undefined);
                      setGenFiles([]);
                      setGenSetName("");
                      setGenSetDesc("");
                      setGenTargetSetId(undefined);
                      refreshSets();
                    } else {
                      message.error(
                        d?.detail || t("agentEvaluation.createFailedShort")
                      );
                    }
                  } catch {
                  } finally {
                    setBusy(false);
                  }
                }}
              >
                {t("agentEvaluation.genButton")}
              </Button>
            </Flex>
          </Flex>
        </Spin>
      </Drawer>
      <Drawer
        title={t("agentEvaluation.casesTitle", { name: detailSet?.name || "" })}
        open={detailD}
        onClose={() => {
          setDetailD(false);
          setAdding(false);
          setEditingCase(null);
          setSelKeys([]);
          // Refresh the main set table so case_count stays in sync after
          // any add/edit/delete performed inside the detail drawer.
          refreshSets();
        }}
        size="large"
        extra={
          <Space>
            {selKeys.length > 0 && (
              <Popconfirm
                title={t("agentEvaluation.deleteSelectedCasesConfirm", {
                  n: selKeys.length,
                })}
                onConfirm={async () => {
                  setBatchDeleting(true);
                  try {
                    const resp = await fetch(
                      `/api/evaluation-sets/${detailSet.evaluation_set_id}/cases/batch-delete`,
                      {
                        method: "POST",
                        headers: {
                          ...getAuthHeaders(),
                          "Content-Type": "application/json",
                        },
                        body: JSON.stringify({ case_ids: selKeys.map(Number) }),
                      }
                    );
                    if (!resp.ok) {
                      const d = await resp.json();
                      const errorMsg = d.code
                        ? getI18nErrorMessage(d.code, t)
                        : d.detail || d.message || "Batch delete failed";
                      message.error(errorMsg);
                      return;
                    }
                    setSelKeys([]);
                    loadSetCasesPage(detailSet.evaluation_set_id, setCasePage);
                  } catch {
                    message.error("Network error");
                  } finally {
                    setBatchDeleting(false);
                  }
                }}
              >
                <Button size="small" danger loading={batchDeleting}>
                  {t("agentEvaluation.delete")} ({selKeys.length})
                </Button>
              </Popconfirm>
            )}
            {!adding && !editingCase && (
              <Button
                size="small"
                type="primary"
                icon={<Plus className="size-4" />}
                onClick={() => setAdding(true)}
              >
                {t("agentEvaluation.addCase")}
              </Button>
            )}
          </Space>
        }
      >
        <Table
          columns={caseCols}
          dataSource={
            adding ? [{ __isNew: true }, ...detailCases] : detailCases
          }
          rowKey={
            adding
              ? (r: any) => (r.__isNew ? "__new" : r.evaluation_set_case_id)
              : "evaluation_set_case_id"
          }
          size="small"
          rowSelection={{
            selectedRowKeys: selKeys,
            onChange: (keys) => setSelKeys(keys),
            getCheckboxProps: () => ({ disabled: adding || !!editingCase }),
          }}
          pagination={{
            current: setCasePage,
            pageSize: SET_CASE_PAGE_SIZE,
            total: setCaseTotal || detailSet?.case_count || 0,
            showTotal: (total: number) =>
              t("agentEvaluation.pagination.total", { total }),
          }}
          onChange={(p: any) => {
            setSetCasePage(p.current);
            loadSetCasesPage(detailSet.evaluation_set_id, p.current);
          }}
        />
      </Drawer>
    </div>
  );
}

export default function EvaluationPage() {
  const { t } = useTranslation("common");
  const searchParams = useSearchParams();
  const defaultTab = searchParams?.get("tab") || "runs";
  return (
    <div className="p-6">
      <Title level={4} className="!mb-4">
        {t("agentEvaluation.pageTitle")}
      </Title>
      <Tabs
        destroyOnHidden={false}
        size="large"
        defaultActiveKey={defaultTab}
        items={[
          {
            key: "runs",
            label: t("agentEvaluation.tabRuns"),
            children: <RunsTab />,
          },
          {
            key: "evaluators",
            label: t("agentEvaluation.tabEvaluators"),
            children: <EvaluatorsTab />,
          },
          {
            key: "sets",
            label: t("agentEvaluation.tabSets"),
            children: <SetsTab />,
          },
          {
            key: "labels",
            label: t("agentEvaluation.annotationLabels"),
            children: <AnnotationLabels embedded />,
          },
        ]}
      />
    </div>
  );
}
