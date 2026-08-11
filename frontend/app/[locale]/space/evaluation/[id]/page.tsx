"use client";
import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Alert,
  Card,
  Typography,
  Table,
  Tag,
  Flex,
  Tabs,
  Button,
  Space,
  Tooltip,
  Breadcrumb,
  Modal,
  Select,
  InputNumber,
  Input,
  App,
  List,
  type TableProps,
} from "antd";
import { Download, Zap, RotateCw, Tags } from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  ResponsiveContainer,
  Cell,
  LabelList,
} from "recharts";
import { useTranslation } from "react-i18next";
import { API_ENDPOINTS } from "@/services/api";
import { getAuthHeaders } from "@/lib/auth";
import { parseScore } from "@/utils/evaluationUtils";

const { Text, Title } = Typography;

// ── helpers ──────────────────────────────────────────────────

function fmtTime(iso?: string) {
  // Localised time display — MM/DD hh:mm.  Falls back to the raw
  // substring (first 16 chars) when the string fails to parse (so users
  // still see SOMETHING instead of "-").
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    // NaN timestamp → raw prefix so we never silently hide bad data.
    return String(iso).slice(0, 16);
  }
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDuration(start?: string, end?: string) {
  // Human-friendly wall-clock duration between two ISO timestamps.
  // Used for the "took how long" label in the detail header.
  if (!start || !end) return "-";
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 0) return "-";
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec} seconds`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}

const SESSION_COLORS = [
  "#1677ff",
  "#52c41a",
  "#faad14",
  "#ff7a45",
  "#722ed1",
  "#13c2c2",
  "#eb2f96",
  "#fa8c16",
  "#2f54eb",
  "#a0d911",
  "#f5222d",
  "#531dab",
];
const COLORS = SESSION_COLORS; // reuse same palette for charts
const TOOLTIP_STYLE = {
  container: { background: "#fff", color: "#333" },
} as const;

function getSessionColor(sessionId?: string | null): string {
  // Stable hash-based colouring: the SAME session_id always draws the
  // SAME tag colour across page re-renders AND across pages so humans can
  // spot session groupings visually.
  if (!sessionId) return "#bfbfbf";
  let hash = 0;
  for (let i = 0; i < sessionId.length; i++) {
    hash = (hash << 5) - hash + sessionId.charCodeAt(i);
    hash |= 0;
  }
  return SESSION_COLORS[Math.abs(hash) % SESSION_COLORS.length];
}

// ── component ────────────────────────────────────────────────

export default function EvaluationDetailPage() {
  const { t } = useTranslation("common");
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;

  // ── Core data state ────────────────────────────────────────
  // `run` = top-level metadata (status, overall score, judge model, config).
  const [run, setRun] = useState<any>(null);

  // ── Case table state (paginated, server-driven) ─────────────
  // Cases are NOT fully local — we fetch `casePageSize` rows per page
  // from the backend because 10 000-case runs would freeze the browser
  // if rendered client-side.
  const [cases, setCases] = useState<any[]>([]);
  const [caseTotal, setCaseTotal] = useState(0);
  const [casePage, setCasePage] = useState(1);
  const [casePageSize, setCasePageSize] = useState(10);
  const [caseSortBy, setCaseSortBy] = useState<string | null>(null);
  const [caseSortOrder, setCaseSortOrder] = useState<"asc" | "desc">("asc");
  // caseTab: "all" / "pass" / "fail" — becomes the `pass_filter` URL param.
  const [caseTab, setCaseTab] = useState<string>("all");
  const [caseLoading, setCaseLoading] = useState(true);
  const [initialLoading, setInitialLoading] = useState(true);

  // ── AI analysis (root cause) state ──────────────────────────
  // `analyzing` drives the spinner on the "Regenerate" button.
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisReport, setAnalysisReport] = useState<any>(null);
  // `scoreEvaluator` selects which single evaluator to show as a compact
  // number column in the case table; when null, the Score column shows
  // "name:0.95 / name2:0.60" joined text.
  const [scoreEvaluator, setScoreEvaluator] = useState<string | null>(null);

  // ── Chart-ready aggregates ─────────────────────────────────
  // `stats` = { per_evaluator, histogram, pass_count, fail_count, total }
  // returned by GET /{run_id}/stats.  Charts hide when this is null.
  const [stats, setStats] = useState<any>(null);

  // ── Filter state ────────────────────────────────────────────
  // `annoFilters[schema_id] = value` — parallel arrays sent to
  // `anno_schema_id` / `anno_value` URL pairs.  `sessionIdFilter` drives
  // the client-side session dropdown filter (NOT sent to the backend).
  const [annoFilters, setAnnoFilters] = useState<Record<number, string>>({});
  const [sessionIdFilter, setSessionIdFilter] = useState<string | null>(null);
  const [sessionIdOptions, setSessionIdOptions] = useState<
    { text: string; value: string }[]
  >([]);

  // ── Per-evaluator pass thresholds (copied from backend DB) ─
  // Coloured score highlights (green = pass, red = fail) compare against
  // EACH evaluator's own threshold instead of a hard-coded 0.5 so the UI
  // stays consistent with the backend's pass_status decision.
  const [evalThresholds, setEvalThresholds] = useState<Record<string, number>>(
    {}
  );
  const { message: msg, modal } = App.useApp();

  // ── Annotation state ──────────────────────────────────────
  // `annotations` is keyed outer by (case_id) → inner by (schema_id) → string value.
  // This sparse map is cheap to re-render because most cells are empty.
  const [annoModal, setAnnoModal] = useState(false);
  const [schemas, setSchemas] = useState<any[]>([]);
  const [activeSchemaIds, setActiveSchemaIds] = useState<number[]>([]);
  const [annotations, setAnnotations] = useState<
    Record<number, Record<number, string>>
  >({});
  // `annoStats[schema_id]` = [{value, count}] option frequencies rendered
  // as inline mini-bars next to each option in the annotate modal.
  const [annoStats, setAnnoStats] = useState<Record<number, any[]>>({});

  // Fetch all annotation rows for this run.  Result is a nested map:
  // { case_id: [ {schema_id, value}, ... ] } on the wire → flattened to
  // { case_id: {schema_id: value} } in local state for O(1) lookups.
  const fetchAnnotations = useCallback(() => {
    if (!id) return;
    fetch(`/api/evaluation-annotations/${id}/annotations`, {
      headers: getAuthHeaders(),
    })
      .then((r) => r.json())
      .then((d) => {
        const map: Record<number, Record<number, string>> = {};
        const grouped = d.data || {};
        for (const [caseId, anns] of Object.entries(grouped)) {
          map[Number(caseId)] = {};
          for (const a of anns as any[]) {
            map[Number(caseId)][a.schema_id] = a.value;
          }
        }
        setAnnotations(map);
      });
  }, [id]);

  const fetchSchemas = useCallback(() => {
    fetch("/api/evaluation-annotations/schemas", { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => setSchemas(d.data || []));
  }, []);

  // Fetch option-counts for ONE enabled schema.  Called once per schema
  // when the user activates it, and again after every annotation save
  // so the mini-bar chart refreshes live.
  const fetchAnnoStats = useCallback(
    (schemaId: number) => {
      fetch(
        `/api/evaluation-annotations/${id}/annotation-stats?schema_id=${schemaId}`,
        { headers: getAuthHeaders() }
      )
        .then((r) => r.json())
        .then((d) => {
          setAnnoStats((prev) => ({ ...prev, [schemaId]: d.data || [] }));
        });
    },
    [id]
  );

  // Mount-time: fetch schemas global list + current run's annotations.
  useEffect(() => {
    fetchSchemas();
    if (id) fetchAnnotations();
  }, [id, fetchSchemas, fetchAnnotations]);

  // Re-pull stats per enabled schema when the enabled list changes (user
  // toggled a label on/off, or mount-time just loaded r.annotation_schema_ids).
  useEffect(() => {
    activeSchemaIds.forEach((sid) => fetchAnnoStats(sid));
  }, [activeSchemaIds, fetchAnnoStats]);

  // Load evaluator thresholds ONCE — used to color per-evaluator scores
  // aligned with each evaluator's own pass_threshold (not hard-coded 0.5).
  useEffect(() => {
    fetch(API_ENDPOINTS.evaluators.list, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => {
        const arr: any[] = d?.data || [];
        const m: Record<string, number> = {};
        arr.forEach((e) => {
          if (e?.name) m[String(e.name)] = Number(e.pass_threshold ?? 0.5);
        });
        setEvalThresholds(m);
      })
      .catch(() => {
        /* fall back to the default 0.5 everywhere silently */
      });
  }, []);

  // Optimistic annotation save: update the local map FIRST so the user
  // sees the change instantly, then PUT to backend, then refresh stats.
  // If the network call fails we RESTORE `previousValue` so UI/DB stay
  // consistent.
  const saveAnnotation = useCallback(
    async (
      caseId: number,
      schemaId: number,
      value: string,
      previousValue?: string
    ) => {
      // Optimistic update
      setAnnotations((prev) => ({
        ...prev,
        [caseId]: { ...(prev[caseId] || {}), [schemaId]: value },
      }));
      try {
        await fetch(`/api/evaluation-annotations/${id}/annotations`, {
          method: "PUT",
          headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
          body: JSON.stringify({
            annotations: [{ case_id: caseId, schema_id: schemaId, value }],
          }),
        });
        fetchAnnoStats(schemaId);
      } catch {
        // Rollback on failure
        if (previousValue !== undefined) {
          setAnnotations((prev) => ({
            ...prev,
            [caseId]: { ...(prev[caseId] || {}), [schemaId]: previousValue },
          }));
        }
        msg.error(t("agentEvaluation.annotationSaveFailed"));
      }
    },
    [id, fetchAnnoStats]
  );

  const persistSchemaIds = async (ids: number[]) => {
    try {
      await fetch(`/api/agent-evaluations/${id}/annotation-schemas`, {
        method: "PUT",
        headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ schema_ids: ids }),
      });
    } catch {
      /* silent — toast not needed for a background update */
    }
  };

  // Toggle a label on/off. When disabling a label that already has (non-empty)
  // annotation data, prompt for confirmation and cascade-delete the data so it
  // does not silently linger and reappear if the label is re-enabled later.
  const toggleLabel = useCallback(
    async (schemaId: number) => {
      const isActive = activeSchemaIds.includes(schemaId);
      if (!isActive) {
        const next = [...activeSchemaIds, schemaId];
        setActiveSchemaIds(next);
        persistSchemaIds(next);
        return;
      }
      try {
        // Fresh backend count — do not rely on possibly-stale local state.
        const r = await fetch(
          `/api/evaluation-annotations/${id}/annotation-stats?schema_id=${schemaId}`,
          { headers: getAuthHeaders() }
        );
        const d = await r.json();
        const items: any[] = d.data || [];
        const nonEmpty = items
          .filter(
            (it: any) => it.value != null && String(it.value).trim() !== ""
          )
          .reduce((sum: number, it: any) => sum + (it.count || 0), 0);
        if (nonEmpty > 0) {
          const ok = await new Promise<boolean>((resolve) => {
            modal.confirm({
              title: t("agentEvaluation.disableLabelConfirmTitle"),
              content: t("agentEvaluation.disableLabelConfirmContent"),
              okText: t("agentEvaluation.delete"),
              okType: "danger",
              cancelText: t("agentEvaluation.cancel"),
              onOk: () => resolve(true),
              onCancel: () => resolve(false),
            });
          });
          if (!ok) return;
        }
        // Cascade-delete all annotation rows for this schema within this run.
        await fetch(
          `/api/evaluation-annotations/${id}/annotations?schema_id=${schemaId}`,
          { method: "DELETE", headers: getAuthHeaders() }
        );
        // Drop this schema from local annotation + stats caches.
        setAnnotations((prev) => {
          const next: Record<number, Record<number, string>> = {};
          for (const [caseId, anns] of Object.entries(prev)) {
            const cid = Number(caseId);
            const { [schemaId]: _drop, ...rest } = anns as Record<
              number,
              string
            >;
            next[cid] = rest;
          }
          return next;
        });
        setAnnoStats((prev) => {
          const { [schemaId]: _drop, ...rest } = prev;
          return rest;
        });
        const nextActive = activeSchemaIds.filter((sid) => sid !== schemaId);
        setActiveSchemaIds(nextActive);
        persistSchemaIds(nextActive);
      } catch {
        msg.error(t("agentEvaluation.disableLabelFailed"));
      }
    },
    [activeSchemaIds, id, t, modal, msg, persistSchemaIds]
  );

  // ── Server-side data fetching ────────────────────────────

  const fetchStats = useCallback(() => {
    if (!id) return;
    fetch(`/api/agent-evaluations/${id}/stats`, { headers: getAuthHeaders() })
      .then((r) => r.json())
      .then((d) => {
        if (d.data) setStats(d.data);
      })
      .catch(() => {
        /* stats fail silently, charts hide themselves */
      });
  }, [id]);

  // AbortController guard: if the user clicks "next page" twice before
  // the first fetch returns, we abort the stale first request so its
  // items never overwrite the newer items (classic pagination race).
  const abortRef = useRef<AbortController | null>(null);

  const fetchCases = useCallback(
    (
      page: number,
      size: number,
      tab: string,
      sortBy: string | null,
      sortOrder: string,
      filters?: Record<number, string>,
      sessionId?: string | null
    ) => {
      if (!id) return;
      // Always cancel the previous in-flight request to prevent race
      // conditions when users rapidly toggle the pass / fail tab or
      // change sort column.  Without this, a slow sort=alpha response
      // that lands AFTER a newer sort=score response would briefly show
      // stale rows.
      if (abortRef.current) abortRef.current.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      setCaseLoading(true);
      const offset = (page - 1) * size;
      let url = `/api/agent-evaluations/${id}/cases?limit=${size}&offset=${offset}`;
      if (sortBy)
        url += `&sort_by=${encodeURIComponent(sortBy)}&sort_order=${sortOrder}`;
      if (tab !== "all") url += `&pass_filter=${tab}`;
      // Session filter is server-side (same as pass_filter / annotations)
      // so pagination total and page boundaries stay consistent with the
      // visible rows.
      if (sessionId) url += `&session_id=${encodeURIComponent(sessionId)}`;
      if (filters) {
        // Parallel arrays: i-th schema-id pairs with i-th value.  The
        // backend DB layer verifies lengths match and returns a 400 if
        // not, so we just serialize both here.
        for (const [sid, val] of Object.entries(filters)) {
          url += `&anno_schema_id=${sid}&anno_value=${encodeURIComponent(val)}`;
        }
      }
      fetch(url, { headers: getAuthHeaders(), signal: controller.signal })
        .then((r) => r.json())
        .then((d) => {
          if (controller.signal.aborted) return;
          const data = d.data || d;
          let items = data.items || [];
          // NOTE: server-side default ORDER BY already guarantees session-level
          // ordering (NULL session_ids first, then by session_id ASC, turn_order ASC,
          // then by PK) so session context is preserved *across* page boundaries
          // (not only within a page).  We no longer re-sort the local page.
          //
          // Collect unique session_ids for the session filter dropdown,
          // capped at 50 entries to avoid rendering an unusably long SELECT.
          // We MERGE (union) with the existing options instead of replacing
          // them so that filtering by one session does not permanently drop
          // the other sessions from the dropdown.
          setSessionIdOptions((prev) => {
            const merged = new Map<string, { text: string; value: string }>();
            (prev || []).forEach((o) => merged.set(o.value, o));
            items.forEach((c: any) => {
              if (c.session_id && !merged.has(c.session_id)) {
                merged.set(c.session_id, {
                  text: c.session_id,
                  value: c.session_id,
                });
              }
            });
            return Array.from(merged.values()).slice(0, 50);
          });
          setCases(items);
          setCaseTotal(data.total || 0);
        })
        .catch((err) => {
          if (err.name !== "AbortError") throw err;
        })
        .finally(() => {
          if (!controller.signal.aborted) setCaseLoading(false);
        });
    },
    [id]
  );

  // Full-page refresh used by the manual refresh button AND the 30-second
  // poll.  Reads all the CURRENT values of the filter/sort/page state via
  // dependencies so the poll does not accidentally page back to page 1.
  const refreshData = useCallback(() => {
    if (!id) return;
    fetch(API_ENDPOINTS.agentEvaluations.detail(Number(id)), {
      headers: getAuthHeaders(),
    })
      .then((r) => r.json())
      .then((runR) => {
        const r = runR.data || runR;
        setRun(r);
        if (r.analysis_report) setAnalysisReport(r.analysis_report);
        if (r.annotation_schema_ids?.length)
          setActiveSchemaIds(r.annotation_schema_ids);
      });
    fetchCases(
      casePage,
      casePageSize,
      caseTab,
      caseSortBy,
      caseSortOrder,
      annoFilters,
      sessionIdFilter
    );
    fetchStats();
  }, [
    id,
    casePage,
    casePageSize,
    caseTab,
    caseSortBy,
    caseSortOrder,
    annoFilters,
    sessionIdFilter,
    fetchCases,
    fetchStats,
  ]);

  // Initial mount-time fetch.  Starts with page-1, sort-default so the
  // user sees a deterministic first page, then pulls the detail header.
  useEffect(() => {
    setInitialLoading(true);
    fetch(API_ENDPOINTS.agentEvaluations.detail(Number(id)), {
      headers: getAuthHeaders(),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then((runR) => {
        const r = runR.data || runR;
        setRun(r);
        if (r.analysis_report) setAnalysisReport(r.analysis_report);
        if (r.annotation_schema_ids?.length)
          setActiveSchemaIds(r.annotation_schema_ids);
      })
      .catch(() => {
        setRun(null);
      })
      .finally(() => setInitialLoading(false));
    fetchCases(1, 10, "all", null, "asc", {});
    fetchStats();
  }, [id]);

  // ── Polling ─────────────────────────────────────────────
  // While run.status ∈ {PENDING, RUNNING} we call `refreshData` every 30s.
  // Much slower than the list page (2s) because the detail page has a
  // much heavier payload: header + paginated cases + stats.  `pollRef`
  // lives on a ref so it survives effect re-runs when `isRunning`
  // transiently dips.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isRunning = run?.status === "PENDING" || run?.status === "RUNNING";
  useEffect(() => {
    if (isRunning && !pollRef.current) {
      pollRef.current = setInterval(refreshData, 30000);
    } else if (!isRunning && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [isRunning, refreshData]);

  // ── Stats from API ───────────────────────────────────────

  // Recharts bar chart data: one row per evaluator, coloured from a
  // rotating palette.  `useMemo` ensures rows don't get re-created every
  // render (recharts deep-compares props so new object references =
  // spurious re-paints).
  const barData = useMemo<{ name: string; raw: number; fill: string }[]>(() => {
    if (!stats?.per_evaluator?.length) return [];
    return stats.per_evaluator.map((e: any, i: number) => ({
      name: e.name,
      raw: e.avg,
      fill: COLORS[i % COLORS.length],
    }));
  }, [stats]);

  const histogram = stats?.histogram || [];
  const passCount = stats?.pass_count ?? 0;
  const failCount = stats?.fail_count ?? 0;
  const totalCases = stats?.total || run?.progress_total || caseTotal || 0;

  // Evaluator names: from stats or fallback to evaluator_config
  const evaluatorNames = useMemo(() => {
    if (stats?.per_evaluator?.length)
      return stats.per_evaluator.map((e: any) => e.name);
    // Fallback: extract from first case's score, or from evaluator_config
    if (cases.length > 0) {
      const firstScore = parseScore(cases[0].score);
      return Object.keys(firstScore).filter(
        (k) => typeof firstScore[k] === "number"
      );
    }
    return [];
  }, [stats, cases]);

  const isNoSet = run?.evaluator_config?.no_set_mode === true;

  // ── case columns ────────────────────────────────────────

  const caseCols = useMemo(() => {
    const base: TableProps<any>["columns"] = [
      {
        title: "#",
        width: 40,
        render: (_: any, __: any, i: number) =>
          (casePage - 1) * casePageSize + i + 1,
      },
      {
        title: t("agentEvaluation.colHeader.session"),
        key: "session_id",
        width: 110,
        filters: sessionIdOptions,
        filteredValue: sessionIdFilter ? [sessionIdFilter] : null,
        filterMultiple: false,
        filterSearch: true,
        // NOTE: no `onFilter` here — session filtering is server-side
        // (handleTableChange sends `session_id=` to the backend), matching
        // how the annotation columns behave.
        render: (_: any, r: any) => {
          const sid = r.session_id;
          if (!sid)
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
                maxWidth: 100,
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
        title: t("agentEvaluation.colHeader.turn"),
        key: "turn",
        width: 60,
        render: (_: any, r: any) =>
          r.turn_order !== undefined && r.turn_order !== null
            ? r.turn_order
            : "-",
      },
      {
        title: t("agentEvaluation.colHeader.question"),
        key: "q",
        ellipsis: true,
        render: (_: any, r: any) => r.inputs?.query || r.input?.query || "-",
      },
      ...(isNoSet
        ? []
        : [
            {
              title: t("agentEvaluation.colHeader.expectedAnswer"),
              key: "ea",
              ellipsis: true,
              width: 150,
              render: (_: any, r: any) => {
                const v = r.label?.answer || "-";
                if (v === "-") return "-";
                return (
                  <Tooltip
                    styles={TOOLTIP_STYLE}
                    title={<div style={{ maxWidth: 400 }}>{v}</div>}
                  >
                    <Text ellipsis style={{ maxWidth: 140 }}>
                      {v.slice(0, 30)}
                      {v.length > 30 ? "..." : ""}
                    </Text>
                  </Tooltip>
                );
              },
            },
          ]),
      {
        title: t("agentEvaluation.colHeader.actualOutput"),
        key: "ao",
        ellipsis: true,
        width: 150,
        render: (_: any, r: any) => {
          const p = r.predict;
          if (!p) return "-";
          let text = "";
          if (typeof p === "string") text = p;
          else if (typeof p === "object")
            text = p.answer || p.text || JSON.stringify(p);
          else text = String(p);
          const plain = text.replace(/\*\*(.+?)\*\*/g, "$1");
          return (
            <Tooltip
              styles={TOOLTIP_STYLE}
              title={<div style={{ maxWidth: 400 }}>{plain}</div>}
            >
              <Text ellipsis style={{ maxWidth: 140 }}>
                {plain.slice(0, 30)}
                {plain.length > 30 ? "..." : ""}
              </Text>
            </Tooltip>
          );
        },
      },
    ];

    base.push({
      title: t("agentEvaluation.colHeader.score"),
      dataIndex: "score",
      key: "score",
      width: 140,
      sorter: scoreEvaluator ? true : false,
      showSorterTooltip: false,
      render: (v: any) => {
        if (v == null) return "-";
        const obj = parseScore(v);
        const entries = Object.entries(obj);
        const summary = scoreEvaluator
          ? typeof obj[scoreEvaluator] === "number"
            ? Number(obj[scoreEvaluator]).toFixed(2)
            : "-"
          : entries
              .map(([k, val]) => `${k}:${Number(val).toFixed(2)}`)
              .join(" / ");
        const detail = entries.map(([k, val]) => {
          const th = Number(evalThresholds[k] ?? 0.5);
          return (
            <div key={k}>
              {k}:{" "}
              <Text
                strong
                style={{ color: Number(val) >= th ? "#52c41a" : "#ff4d4f" }}
              >
                {Number(val).toFixed(2)}
              </Text>
            </div>
          );
        });
        return (
          <Tooltip
            styles={TOOLTIP_STYLE}
            title={<div style={{ maxWidth: 400 }}>{detail}</div>}
          >
            <Text
              ellipsis
              className="text-xs"
              style={{ maxWidth: scoreEvaluator ? 70 : 130 }}
            >
              {summary}
            </Text>
          </Tooltip>
        );
      },
    });

    base.push({
      title: t("agentEvaluation.colHeader.reason"),
      dataIndex: "reason",
      width: 140,
      render: (v: any) => {
        if (!v) return "-";
        const obj = parseScore(v);
        const entries = Object.entries(obj);
        const summary = entries
          .map(
            ([k, val]) =>
              `${k}: ${String(val).slice(0, 20)}${String(val).length > 20 ? "..." : ""}`
          )
          .join(" | ");
        const detail = entries.map(([k, val]: [string, any]) => (
          <div key={k}>
            <Text strong>{k}:</Text> {String(val)}
          </div>
        ));
        return (
          <Tooltip
            styles={TOOLTIP_STYLE}
            title={<div style={{ maxWidth: 400 }}>{detail}</div>}
          >
            <Text ellipsis className="text-xs" style={{ maxWidth: 130 }}>
              {summary}
            </Text>
          </Tooltip>
        );
      },
    });

    // Dynamic annotation columns
    const annoCols = activeSchemaIds
      .map((schemaId) => {
        const schema = schemas.find((s: any) => s.schema_id === schemaId);
        if (!schema) return null;
        const isClassification = schema.annotation_type === "classification";
        const isBoolean = schema.annotation_type === "boolean";
        const isNumber = schema.annotation_type === "number";
        const options = schema.options || [];
        // Filter values from stats
        const filterValues = (annoStats[schemaId] || []).map((s: any) => ({
          text: `${s.value} (${s.count})`,
          value: s.value,
        }));
        const annoVal = annoFilters[schemaId];
        return {
          title: (
            <Tooltip
              styles={TOOLTIP_STYLE}
              title={schema.description || schema.name}
            >
              <Text ellipsis style={{ maxWidth: 100 }}>
                {schema.name}
              </Text>
            </Tooltip>
          ),
          key: `anno_${schemaId}`,
          width: isNumber ? 90 : 130,
          filters: filterValues,
          filteredValue: annoVal != null ? [annoVal] : null,
          filterMultiple: false,
          render: (_: any, r: any) => {
            const caseId = r.agent_evaluation_case_id;
            const val = annotations[caseId]?.[schemaId];
            if (isClassification || isBoolean) {
              const selOptions = isBoolean
                ? [
                    { label: "True", value: "True" },
                    { label: "False", value: "False" },
                  ]
                : options.map((o: any) => ({ label: o.label, value: o.label }));
              return (
                <Select
                  size="small"
                  allowClear
                  style={{ width: "100%", minWidth: 100 }}
                  placeholder="-"
                  value={val || undefined}
                  options={selOptions}
                  onChange={(v) => {
                    const newVal = v || "";
                    if (newVal !== (val || ""))
                      saveAnnotation(caseId, schemaId, newVal, val);
                  }}
                />
              );
            }
            if (isNumber) {
              return (
                <InputNumber
                  size="small"
                  style={{ width: "100%" }}
                  placeholder="-"
                  value={val != null ? Number(val) : undefined}
                  onChange={(v) => {
                    const newVal = v != null ? String(v) : "";
                    if (newVal !== (val || ""))
                      saveAnnotation(caseId, schemaId, newVal, val);
                  }}
                />
              );
            }
            return (
              <Input
                size="small"
                style={{ width: "100%" }}
                placeholder="-"
                defaultValue={val || ""}
                onBlur={(e) => {
                  const newVal = e.target.value;
                  if (newVal !== (val || ""))
                    saveAnnotation(caseId, schemaId, newVal, val);
                }}
                onPressEnter={(e) => {
                  const newVal = (e.target as HTMLInputElement).value;
                  if (newVal !== (val || ""))
                    saveAnnotation(caseId, schemaId, newVal, val);
                }}
              />
            );
          },
        };
      })
      .filter(Boolean) as any[];

    return [...base, ...annoCols];
  }, [
    t,
    isNoSet,
    activeSchemaIds,
    schemas,
    annotations,
    saveAnnotation,
    scoreEvaluator,
    evaluatorNames,
    casePage,
    casePageSize,
    fetchCases,
    caseSortOrder,
    caseTab,
    annoStats,
    annoFilters,
    sessionIdFilter,
    sessionIdOptions,
  ]);

  // NOTE: session filtering is server-side now (fetchCases sends
  // `session_id=`), so the raw `cases` list is rendered directly — no
  // client-side post-filtering is needed and pagination stays consistent.

  // Table change handler for server-side pagination + sorting
  const handleTableChange = useCallback(
    (pagination: any, filters: any, sorter: any, extra: any) => {
      // Handle annotation filter changes
      if (extra.action === "filter") {
        const newFilters = { ...annoFilters };
        let sessionFilterChanged = false;
        let newSessionFilter: string | null = sessionIdFilter;
        for (const key of Object.keys(filters || {})) {
          if (key.startsWith("anno_")) {
            const sid = Number(key.replace("anno_", ""));
            if (filters[key]?.length) {
              newFilters[sid] = filters[key][0];
            } else {
              delete newFilters[sid];
            }
          }
          if (key === "session_id") {
            // Only treat this as a session-filter change when the value
            // actually differs from the current one. The `filters` object
            // always contains the session_id column (even with null), so
            // unconditionally flagging it here would swallow anno filters.
            const nextVal = filters[key]?.length ? filters[key][0] : null;
            if (nextVal !== sessionIdFilter) {
              sessionFilterChanged = true;
              newSessionFilter = nextVal;
            }
          }
        }
        setSessionIdFilter(newSessionFilter);
        setAnnoFilters(newFilters);
        setCasePage(1);
        fetchCases(
          1,
          pagination.pageSize || 10,
          caseTab,
          caseSortBy,
          caseSortOrder,
          newFilters,
          // Session filter is server-side now — send it with the fetch so
          // the pagination total and page boundaries match the visible rows.
          newSessionFilter
        );
        return;
      }

      const newPage = pagination.current || 1;
      const newPageSize = pagination.pageSize || 10;
      setCasePage(newPage);
      setCasePageSize(newPageSize);
      if (sorter.order) {
        const sortBy = sorter.field === "score" ? scoreEvaluator : null;
        setCaseSortBy(sortBy);
        setCaseSortOrder(sorter.order === "ascend" ? "asc" : "desc");
        fetchCases(
          newPage,
          newPageSize,
          caseTab,
          sortBy,
          sorter.order === "ascend" ? "asc" : "desc",
          annoFilters,
          sessionIdFilter
        );
      } else {
        setCaseSortBy(null);
        setCaseSortOrder("asc");
        fetchCases(
          newPage,
          newPageSize,
          caseTab,
          null,
          "asc",
          annoFilters,
          sessionIdFilter
        );
      }
    },
    [
      caseTab,
      caseSortBy,
      caseSortOrder,
      scoreEvaluator,
      fetchCases,
      annoFilters,
      sessionIdFilter,
    ]
  );

  // When tab changes, reset page and refetch
  const handleTabChange = useCallback(
    (tab: string) => {
      setCaseTab(tab);
      setCasePage(1);
      setCaseSortBy(null);
      setCaseSortOrder("asc");
      setScoreEvaluator(null);
      setSessionIdFilter(null);
      // Session filter resets with the tab, so fetch without session_id.
      fetchCases(1, casePageSize, tab, null, "asc", annoFilters, null);
    },
    [casePageSize, fetchCases, annoFilters]
  );

  // ── render ──────────────────────────────────────────────

  if (initialLoading)
    return (
      <div className="p-6">
        <Text type="secondary">{t("agentEvaluation.loading")}</Text>
      </div>
    );
  if (!run)
    return (
      <div className="p-6">
        <Flex vertical gap={12}>
          <Text type="secondary">{t("agentEvaluation.notFound")}</Text>
          <Button
            size="small"
            onClick={() => {
              setInitialLoading(true);
              refreshData();
            }}
          >
            {t("agentEvaluation.retry")}
          </Button>
        </Flex>
      </div>
    );

  return (
    <div className="p-6 max-w-7xl mx-auto">
      {/* ── Breadcrumb header ── */}
      <Flex vertical gap={10} className="mb-6">
        <Breadcrumb
          items={[
            {
              title: (
                <a
                  onClick={() =>
                    router.push(
                      `/space/evaluation?agent_id=${run?.agent_id || ""}`
                    )
                  }
                  style={{ cursor: "pointer" }}
                >
                  {t("agentEvaluation.breadcrumbEval")}
                </a>
              ),
            },
            { title: t("agentEvaluation.breadcrumbDetail") },
          ]}
        />
        <Flex
          justify="space-between"
          align="center"
          style={{ marginBottom: 24 }}
        >
          <Flex gap={10} align="center">
            <Title level={4} style={{ margin: 0 }}>
              {run.agent_name || `#${run.agent_evaluation_id}`}
            </Title>
            <Tag
              color={
                run.status === "COMPLETED"
                  ? "green"
                  : run.status === "RUNNING"
                    ? "blue"
                    : "red"
              }
              style={{ fontSize: 13 }}
            >
              {run.status}
            </Tag>
          </Flex>
          <Space>
            {run.status === "COMPLETED" && (
              <Button
                icon={<Tags className="size-4" />}
                onClick={() => setAnnoModal(true)}
              >
                {t("agentEvaluation.annotationLabels")}
              </Button>
            )}
            {run.status === "COMPLETED" && (
              <>
                <Button
                  icon={
                    analysisReport ? (
                      <RotateCw className="size-4" />
                    ) : (
                      <Zap className="size-4" />
                    )
                  }
                  type={analysisReport ? "default" : "primary"}
                  ghost={!analysisReport}
                  loading={analyzing}
                  disabled={analyzing}
                  onClick={async () => {
                    setAnalyzing(true);
                    try {
                      const r = await fetch(
                        `/api/agent-evaluations/${run.agent_evaluation_id}/analyze?force=true`,
                        { method: "POST", headers: getAuthHeaders() }
                      );
                      const d = await r.json();
                      if (d.data) setAnalysisReport(d.data);
                    } finally {
                      setAnalyzing(false);
                    }
                  }}
                >
                  {analysisReport
                    ? t("agentEvaluation.reAnalyze")
                    : t("agentEvaluation.aiAnalysis")}
                </Button>
                <Button
                  icon={<Download className="size-4" />}
                  onClick={() =>
                    window.open(
                      API_ENDPOINTS.agentEvaluations.report(
                        run.agent_evaluation_id
                      ),
                      "_blank"
                    )
                  }
                >
                  {t("agentEvaluation.downloadReport")}
                </Button>
              </>
            )}
          </Space>
        </Flex>
      </Flex>

      {/* ── Score hero + meta ── */}
      <Flex gap={24} align="stretch" className="mb-8">
        {(() => {
          // Align hero colour with the same per-case pass criterion used by the
          // backend (i.e. the evaluator pass_thresholds), not the hard-coded 0.5.
          // If we have no cases yet, fall back to score_overall >= 0.5.
          const overallPass =
            totalCases > 0
              ? passCount >= Math.ceil(totalCases / 2)
              : Number(run.score_overall ?? 0) >= 0.5;
          return (
            <div
              style={{
                width: 130,
                textAlign: "center",
                padding: "24px 12px",
                borderRadius: 12,
                background: overallPass ? "#f6ffed" : "#fff2f0",
                border: `1px solid ${overallPass ? "#b7eb8f" : "#ffccc7"}`,
                flexShrink: 0,
              }}
            >
              <Text
                className="text-xs"
                type="secondary"
                style={{ display: "block", marginBottom: 8 }}
              >
                {t("agentEvaluation.overallScore")}
              </Text>
              <Text
                strong
                style={{
                  fontSize: 36,
                  lineHeight: 1,
                  color: overallPass ? "#52c41a" : "#ff4d4f",
                }}
              >
                {run.score_overall != null
                  ? Number(run.score_overall).toFixed(2)
                  : "-"}
              </Text>
              <div style={{ marginTop: 8 }}>
                <Text className="text-xs" type="secondary">
                  {passCount}/{totalCases} {t("agentEvaluation.tabPass")}
                </Text>
              </div>
            </div>
          );
        })()}
        <Flex vertical style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 1fr",
              gap: "12px 24px",
            }}
          >
            <Flex vertical gap={2}>
              <Text style={{ fontSize: 12, color: "#8c8c8c" }}>
                {t("agentEvaluation.agentLabel")}
              </Text>
              <Text style={{ fontSize: 14 }} strong>
                {run.agent_name || `#${run.agent_id}`}
              </Text>
            </Flex>
            <Flex vertical gap={2}>
              <Text style={{ fontSize: 12, color: "#8c8c8c" }}>
                {t("agentEvaluation.evalSetLabel")}
              </Text>
              <Text style={{ fontSize: 14 }} strong>
                {isNoSet ? (
                  <Tag color="orange">{t("agentEvaluation.noSetTag")}</Tag>
                ) : (
                  run.evaluation_set_name || "-"
                )}
              </Text>
            </Flex>
            <Flex vertical gap={2}>
              <Text style={{ fontSize: 12, color: "#8c8c8c" }}>
                {t("agentEvaluation.judgeModelLabel")}
              </Text>
              <Text style={{ fontSize: 14 }} strong>
                {run.judge_model_name || "-"}
              </Text>
            </Flex>
            <Flex vertical gap={2}>
              <Text style={{ fontSize: 12, color: "#8c8c8c" }}>
                {t("agentEvaluation.createTimeLabel")}
              </Text>
              <Text style={{ fontSize: 14 }} strong>
                {fmtTime(run.create_time)}
              </Text>
            </Flex>
            <Flex vertical gap={2}>
              <Text style={{ fontSize: 12, color: "#8c8c8c" }}>
                {t("agentEvaluation.endTimeLabel")}
              </Text>
              <Text style={{ fontSize: 14 }} strong>
                {run.status === "COMPLETED" ? fmtTime(run.update_time) : "-"}
              </Text>
            </Flex>
            <Flex vertical gap={2}>
              <Text style={{ fontSize: 12, color: "#8c8c8c" }}>
                {t("agentEvaluation.durationLabel")}
              </Text>
              <Text style={{ fontSize: 14 }} strong>
                {fmtDuration(run.create_time, run.update_time)}
              </Text>
            </Flex>
            <Flex vertical gap={2}>
              <Text style={{ fontSize: 12, color: "#8c8c8c" }}>
                {t("agentEvaluation.progressLabel")}
              </Text>
              <Text style={{ fontSize: 14 }} strong>
                {run.progress_done ?? 0} / {run.progress_total ?? 0}
              </Text>
            </Flex>
          </div>
        </Flex>
      </Flex>

      {/* ── Analysis Report ── */}
      {analysisReport && (
        <div
          style={{
            marginTop: 24,
            marginBottom: 24,
            padding: "20px 24px",
            borderRadius: 8,
            background: "#fff",
            border: "1px solid #f0f0f0",
            borderLeft: "3px solid #1677ff",
          }}
        >
          <Flex
            justify="space-between"
            align="center"
            style={{ marginBottom: 16 }}
          >
            <Space>
              <Zap className="size-4 text-blue-500" />
              <Text strong>{t("agentEvaluation.aiAnalysisReport")}</Text>
            </Space>
            <Text type="secondary" style={{ fontSize: 12 }}>
              {t("agentEvaluation.aiAnalysisDisclaimer")}
            </Text>
          </Flex>
          <Flex vertical gap={16}>
            {/* ── Top issues ── */}
            {analysisReport.top_issues?.length > 0 && (
              <Flex vertical gap={8}>
                <Text strong>{t("agentEvaluation.hotQuestions")}</Text>
                <List
                  size="small"
                  dataSource={analysisReport.top_issues}
                  renderItem={(item: any, i: number) => (
                    <List.Item
                      key={`${item.problem}_${i}`}
                      style={{
                        padding: "10px 12px",
                        background: "#fafafa",
                        borderRadius: 8,
                        borderLeft: `3px solid ${
                          item.severity === "high"
                            ? "#ff4d4f"
                            : item.severity === "medium"
                              ? "#faad14"
                              : "#1677ff"
                        }`,
                      }}
                    >
                      <Flex vertical gap={4} style={{ width: "100%" }}>
                        <Flex gap={8} align="center" wrap>
                          <Tag
                            color={
                              item.severity === "high"
                                ? "red"
                                : item.severity === "medium"
                                  ? "orange"
                                  : "blue"
                            }
                          >
                            {item.severity === "high"
                              ? t("agentEvaluation.severity.high")
                              : item.severity === "medium"
                                ? t("agentEvaluation.severity.medium")
                                : t("agentEvaluation.severity.low")}
                          </Tag>
                          <Text strong>{item.problem}</Text>
                        </Flex>
                        {item.detail ? (
                          <Text type="secondary" className="text-xs">
                            {item.detail}
                          </Text>
                        ) : null}
                        {item.fix ? (
                          <Text type="secondary" className="text-xs">
                            → {item.fix}
                          </Text>
                        ) : null}
                      </Flex>
                    </List.Item>
                  )}
                />
              </Flex>
            )}

            {/* ── Overall review ── */}
            {analysisReport.summary && (
              <Alert
                type="info"
                showIcon
                message={t("agentEvaluation.overallReview")}
                description={
                  <Text style={{ fontSize: 13, color: "#555" }}>
                    {analysisReport.summary}
                  </Text>
                }
                style={{ background: "#f0f7ff", border: "1px solid #d6e8ff" }}
              />
            )}

            {/* ── Suggestions ── */}
            {analysisReport.suggestions?.length > 0 && (
              <Flex vertical gap={8}>
                <Text strong>
                  {t("agentEvaluation.optimizationSuggestions")}
                </Text>
                <List
                  size="small"
                  dataSource={analysisReport.suggestions}
                  renderItem={(s: any, i: number) => (
                    <List.Item
                      key={`${s.action}_${i}`}
                      style={{ padding: "6px 0" }}
                    >
                      <Flex
                        gap={8}
                        align="flex-start"
                        style={{ width: "100%" }}
                      >
                        <span
                          style={{
                            flexShrink: 0,
                            width: 18,
                            height: 18,
                            borderRadius: 9,
                            background: "#e6f4ff",
                            color: "#1677ff",
                            fontSize: 11,
                            lineHeight: "18px",
                            textAlign: "center",
                            fontWeight: 600,
                          }}
                        >
                          {i + 1}
                        </span>
                        <Text
                          className="text-xs"
                          style={{ lineHeight: "20px" }}
                        >
                          {s.action}
                        </Text>
                      </Flex>
                    </List.Item>
                  )}
                />
              </Flex>
            )}
          </Flex>
        </div>
      )}

      {/* ── Charts ── */}
      {totalCases > 0 && (
        <Flex vertical gap={20} className="mb-6">
          <Card size="small" title={t("agentEvaluation.chartPerEvaluator")}>
            {barData.length > 0 ? (
              (() => {
                const VB = 580;
                const cx = VB / 2,
                  cy = VB * 0.5;
                const maxR = Math.min(cx, cy) * 0.72;
                const innerR = maxR * 0.38;
                const barAngle = (2 * Math.PI) / barData.length;
                const halfAngularWidth = barAngle * 0.44;
                const sectorPath = (
                  r1: number,
                  r2: number,
                  a1: number,
                  a2: number
                ) => {
                  const x1i = cx + r1 * Math.cos(a1),
                    y1i = cy + r1 * Math.sin(a1);
                  const x2i = cx + r1 * Math.cos(a2),
                    y2i = cy + r1 * Math.sin(a2);
                  const x1o = cx + r2 * Math.cos(a1),
                    y1o = cy + r2 * Math.sin(a1);
                  const x2o = cx + r2 * Math.cos(a2),
                    y2o = cy + r2 * Math.sin(a2);
                  const large = a2 - a1 > Math.PI ? 1 : 0;
                  return `M${x1i},${y1i} A${r1},${r1} 0 ${large} 1 ${x2i},${y2i} L${x2o},${y2o} A${r2},${r2} 0 ${large} 0 ${x1o},${y1o} Z`;
                };
                return (
                  <div
                    style={{ maxWidth: VB, margin: "0 auto", aspectRatio: "1" }}
                  >
                    <svg
                      viewBox={`0 0 ${VB} ${VB}`}
                      width="100%"
                      height="100%"
                      style={{
                        display: "block",
                        overflow: "visible",
                        aspectRatio: "1",
                      }}
                    >
                      {[0.25, 0.5, 0.75, 1.0].map((pct) => {
                        const r = innerR + (maxR - innerR) * pct;
                        return (
                          <circle
                            key={pct}
                            cx={cx}
                            cy={cy}
                            r={r}
                            fill="none"
                            stroke="#f0f0f0"
                            strokeWidth={1}
                            strokeDasharray="3 3"
                          />
                        );
                      })}
                      {barData.map((entry, i) => {
                        const midAngle = i * barAngle - Math.PI / 2;
                        const a1 = midAngle - halfAngularWidth,
                          a2 = midAngle + halfAngularWidth;
                        const r2 = innerR + (maxR - innerR) * entry.raw;
                        const lx = cx + (r2 + 10) * Math.cos(midAngle),
                          ly = cy + (r2 + 10) * Math.sin(midAngle);
                        const anchor =
                          midAngle > Math.PI / 2 || midAngle < -Math.PI / 2
                            ? "end"
                            : "start";
                        const maxChars = 8;
                        const shortName =
                          entry.name.length > maxChars
                            ? entry.name.slice(0, maxChars) + "..."
                            : entry.name;
                        return (
                          <g key={entry.name}>
                            <path
                              d={sectorPath(innerR, r2, a1, a2)}
                              fill={entry.fill}
                              opacity={0.85}
                              stroke="#fff"
                              strokeWidth={1.5}
                            />
                            <text
                              x={lx}
                              y={ly - 6}
                              textAnchor={anchor}
                              dominantBaseline="auto"
                              fontSize={11}
                              fill="#333"
                              fontWeight={500}
                            >
                              {shortName}
                              {entry.name.length > maxChars && (
                                <title>{entry.name}</title>
                              )}
                            </text>
                            <text
                              x={lx}
                              y={ly + 8}
                              textAnchor={anchor}
                              dominantBaseline="auto"
                              fontSize={12}
                              fill={entry.fill}
                              fontWeight={700}
                            >
                              {entry.raw.toFixed(2)}
                            </text>
                          </g>
                        );
                      })}
                      <circle
                        cx={cx}
                        cy={cy}
                        r={innerR - 2}
                        fill="#fff"
                        stroke="#e8e8e8"
                        strokeWidth={2}
                      />
                      <text
                        x={cx}
                        y={cy - 6}
                        textAnchor="middle"
                        dominantBaseline="middle"
                        fontSize={22}
                        fontWeight={700}
                        fill={
                          totalCases > 0
                            ? passCount >= Math.ceil(totalCases / 2)
                              ? "#52c41a"
                              : "#ff4d4f"
                            : (run.score_overall ?? 0) >= 0.5
                              ? "#52c41a"
                              : "#ff4d4f"
                        }
                      >
                        {run.score_overall != null
                          ? Number(run.score_overall).toFixed(2)
                          : "-"}
                      </text>
                      <text
                        x={cx}
                        y={cy + 16}
                        textAnchor="middle"
                        dominantBaseline="middle"
                        fontSize={10}
                        fill="#999"
                      >
                        {t("agentEvaluation.chart.composite")}
                      </text>
                    </svg>
                  </div>
                );
              })()
            ) : (
              <Text type="secondary" className="text-xs">
                {t("agentEvaluation.chartNoData")}
              </Text>
            )}
            <Flex gap={12} wrap justify="center" className="mt-2">
              {barData.map((entry) => (
                <Tooltip key={entry.name} title={entry.name}>
                  <Flex gap={4} align="center">
                    <div
                      style={{
                        width: 9,
                        height: 9,
                        borderRadius: "50%",
                        background: entry.fill,
                      }}
                    />
                    <Text
                      className="text-xs"
                      type="secondary"
                      style={{
                        maxWidth: 80,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      {entry.name}
                    </Text>
                  </Flex>
                </Tooltip>
              ))}
            </Flex>
          </Card>

          <Card size="small" title={t("agentEvaluation.chartDistribution")}>
            {histogram.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <BarChart
                  data={histogram}
                  margin={{ top: 30, right: 10, left: 10, bottom: 5 }}
                >
                  <CartesianGrid strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 10 }} />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]} maxBarSize={48}>
                    {histogram.map((entry: any, idx: number) => (
                      <Cell key={`${entry.name}_${idx}`} fill={entry.fill} />
                    ))}
                    <LabelList
                      dataKey="count"
                      position="top"
                      style={{ fontSize: 12, fontWeight: 600 }}
                    />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <Text type="secondary" className="text-xs">
                {t("agentEvaluation.chartNoDataShort")}
              </Text>
            )}
            <Flex gap={16} justify="center" className="mt-2">
              <Text className="text-xs" type="secondary">
                {t("agentEvaluation.chartLegendLow")}
              </Text>
              <Text className="text-xs" type="secondary">
                {t("agentEvaluation.chartLegendMid")}
              </Text>
              <Text className="text-xs" type="secondary">
                {t("agentEvaluation.chartLegendHigh")}
              </Text>
            </Flex>
          </Card>
        </Flex>
      )}

      {/* ── Annotation stats ── */}
      {activeSchemaIds.length > 0 && (
        <Flex gap={16} wrap style={{ marginBottom: 16 }}>
          {activeSchemaIds.map((sid) => {
            const schema = schemas.find((s: any) => s.schema_id === sid);
            const statItems = annoStats[sid] || [];
            const annotated = statItems.reduce(
              (sum: number, s: any) => sum + s.count,
              0
            );
            const coverage =
              totalCases > 0 ? Math.round((annotated / totalCases) * 100) : 0;
            const maxCount = Math.max(1, ...statItems.map((s: any) => s.count));
            return (
              <Card
                key={sid}
                size="small"
                title={schema?.name || `#${sid}`}
                style={{ flex: "1 1 320px", maxWidth: 420 }}
              >
                <Flex vertical gap={8}>
                  <Flex gap={4}>
                    <Text className="text-xs" type="secondary">
                      {t("agentEvaluation.annotatedCount")}:
                    </Text>
                    <Text className="text-xs" strong>
                      {annotated}/{totalCases} ({coverage}%)
                    </Text>
                  </Flex>
                  {statItems.length > 0 ? (
                    <Flex vertical gap={4}>
                      {statItems.map((s: any, i: number) => (
                        <Flex key={`${s.value}_${i}`} align="center" gap={8}>
                          <Tooltip styles={TOOLTIP_STYLE} title={s.value}>
                            <Text
                              className="text-xs"
                              ellipsis
                              style={{ width: 70, flexShrink: 0 }}
                            >
                              {s.value}
                            </Text>
                          </Tooltip>
                          <div
                            style={{
                              flex: 1,
                              height: 14,
                              borderRadius: 6,
                              background: "#f0f0f0",
                              overflow: "hidden",
                            }}
                          >
                            <div
                              style={{
                                width: `${Math.max(2, Math.round((s.count / maxCount) * 100))}%`,
                                height: "100%",
                                borderRadius: 6,
                                background: COLORS[i % COLORS.length],
                                minWidth: s.count > 0 ? 2 : 0,
                              }}
                            />
                          </div>
                          <Tooltip
                            styles={TOOLTIP_STYLE}
                            title={`${s.value}: ${s.count} (${Math.round(s.ratio * 100)}%)`}
                          >
                            <Text
                              className="text-xs"
                              type="secondary"
                              ellipsis
                              style={{ width: 60, flexShrink: 0 }}
                            >
                              {s.count} ({Math.round(s.ratio * 100)}%)
                            </Text>
                          </Tooltip>
                        </Flex>
                      ))}
                    </Flex>
                  ) : (
                    <Text type="secondary" className="text-xs">
                      {t("agentEvaluation.noAnnotations")}
                    </Text>
                  )}
                </Flex>
              </Card>
            );
          })}
        </Flex>
      )}

      {/* ── Case table with server-side pagination ── */}
      <Flex vertical gap={4}>
        <Flex justify="space-between" align="center">
          <Tabs
            activeKey={caseTab}
            onChange={handleTabChange}
            size="small"
            style={{ marginBottom: 0 }}
            items={[
              {
                key: "all",
                label: `${t("agentEvaluation.tabAll")} (${caseTab === "all" ? caseTotal : totalCases})`,
              },
              {
                key: "pass",
                label: `${t("agentEvaluation.tabPass")} (${caseTab === "pass" ? caseTotal : passCount})`,
              },
              {
                key: "fail",
                label: `${t("agentEvaluation.tabFail")} (${caseTab === "fail" ? caseTotal : failCount})`,
              },
            ]}
          />
          {evaluatorNames.length > 0 && (
            <Flex align="center" gap={6}>
              <Text className="text-xs" type="secondary">
                {t("agentEvaluation.scoreBy")}
              </Text>
              <Select
                size="small"
                allowClear
                placeholder={t("agentEvaluation.selectAll")}
                value={scoreEvaluator}
                style={{ minWidth: 80, border: "none" }}
                onChange={(v) => {
                  setScoreEvaluator(v || null);
                  setCaseSortBy(v || null);
                  setCasePage(1);
                  fetchCases(
                    1,
                    casePageSize,
                    caseTab,
                    v || null,
                    caseSortOrder,
                    annoFilters,
                    sessionIdFilter
                  );
                }}
                options={evaluatorNames.map((n: string) => ({
                  label: n,
                  value: n,
                }))}
              />
            </Flex>
          )}
        </Flex>
        <Table
          columns={caseCols}
          dataSource={cases}
          rowKey="agent_evaluation_case_id"
          size="small"
          loading={caseLoading}
          scroll={{
            x: Math.max(
              1000,
              110 +
                (3 + (isNoSet ? 0 : 1) + 2) * 120 +
                activeSchemaIds.length * 130
            ),
          }}
          pagination={{
            current: casePage,
            pageSize: casePageSize,
            total: caseTotal,
            showSizeChanger: true,
            pageSizeOptions: [10, 20, 50],
            showTotal: (total: number) =>
              t("agentEvaluation.paginationTotal", { total }),
          }}
          onChange={handleTableChange}
        />
      </Flex>

      {/* ── Annotation schema selection modal ── */}
      <Modal
        title={t("agentEvaluation.annotationLabels")}
        open={annoModal}
        onCancel={() => setAnnoModal(false)}
        footer={null}
        width={500}
      >
        <Flex vertical gap={12}>
          <Text type="secondary" className="text-xs">
            {t("agentEvaluation.annotationLabelsHintPlain")}
          </Text>
          {schemas.length === 0 ? (
            <Text type="secondary">{t("agentEvaluation.noLabelSchemas")}</Text>
          ) : (
            schemas.map((s: any) => {
              const active = activeSchemaIds.includes(s.schema_id);
              const typeLabelMap: Record<string, string> = {
                classification: t("分类"),
                boolean: t("agentEvaluation.booleanLabel"),
                number: t("agentEvaluation.numberLabel"),
                text: t("agentEvaluation.textLabel"),
              };
              const typeLabel =
                typeLabelMap[s.annotation_type] || s.annotation_type;
              return (
                <Flex
                  key={s.schema_id}
                  justify="space-between"
                  align="center"
                  style={{
                    padding: "8px 12px",
                    borderRadius: 6,
                    background: active ? "#e6f4ff" : "#fafafa",
                    border: `1px solid ${active ? "#91caff" : "#f0f0f0"}`,
                  }}
                >
                  <Flex vertical gap={2}>
                    <Text strong>{s.name}</Text>
                    <Text className="text-xs" type="secondary">
                      {s.description || typeLabel} · {typeLabel}
                    </Text>
                  </Flex>
                  <Button
                    size="small"
                    type={active ? "default" : "primary"}
                    onClick={() => toggleLabel(s.schema_id)}
                  >
                    {active
                      ? t("agentEvaluation.disable")
                      : t("agentEvaluation.enable")}
                  </Button>
                </Flex>
              );
            })
          )}
          <Button onClick={() => setAnnoModal(false)} style={{ marginTop: 8 }}>
            {t("agentEvaluation.done")}
          </Button>
        </Flex>
      </Modal>
    </div>
  );
}
