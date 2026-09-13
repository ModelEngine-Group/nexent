"use client";

import {
  JSONGenerativeUI,
  createActionRegistry,
  defaultGenerativeUILibrary,
} from "@assistant-ui/react-generative-ui";
import { useAui } from "@assistant-ui/react";
import { memo, useEffect, useState } from "react";
import { jsx, jsxs } from "react/jsx-runtime";
import {
  BarChart, Bar, LineChart, Line, AreaChart, Area,
  PieChart, Pie, Cell,
  ScatterChart, Scatter,
  RadarChart, Radar,
  CartesianGrid, XAxis, YAxis, Tooltip, Legend,
  ResponsiveContainer,
} from "recharts";

// ---------------------------------------------------------------------------
// RechartsChartRenderer — REAL React component (not jsx() call) so recharts
// context/hooks initialize correctly. Wraps BarChart / LineChart / etc with
// CartesianGrid + XAxis + YAxis + Tooltip + Legend.
// ---------------------------------------------------------------------------
interface RechartsChartRendererProps {
  variant: string;
  data: Array<Record<string, unknown>>;
  series: Array<{ dataKey: string; name: string; color: string }>;
  xAxisKey: string;
  stacked?: boolean;
  showLegend?: boolean;
}

const RechartsChartRenderer = memo(function RechartsChartRenderer({
  variant,
  data,
  series,
  xAxisKey,
  stacked = false,
  showLegend = true,
}: RechartsChartRendererProps) {
  // eslint-disable-next-line no-console
  console.warn("[RechartsChartRenderer] CALLED", { variant, dataRows: data.length, seriesCount: series.length, xAxisKey });

  const containerStyle: React.CSSProperties = {
    width: "100%",
    maxWidth: "100%",
    height: 320,
    boxSizing: "border-box",
  };

  // Wrap every recharts chart in ResponsiveContainer — it uses ResizeObserver
  // to read parent width and passes it to the chart. This is the standard
  // recharts pattern and eliminates all overflow issues.
  const responsive = (chart: React.ReactNode) => (
    <div style={containerStyle}>
      <ResponsiveContainer width="100%" height="100%">
        {chart}
      </ResponsiveContainer>
    </div>
  );

  // Pie / Doughnut
  if (variant === "pie" || variant === "doughnut") {
    const total = data.reduce(
      (sum, row) => sum + Number(row[series[0]?.dataKey ?? "value"] ?? 0),
      0
    );
    return responsive(
      <PieChart>
        <Tooltip />
        {showLegend && <Legend />}
        <Pie
          data={data}
          dataKey={series[0]?.dataKey ?? "value"}
          nameKey={xAxisKey}
          cx="50%"
          cy="45%"
          outerRadius="80%"
          innerRadius={variant === "doughnut" ? "40%" : 0}
          label={({ name, percent }) =>
            total > 0 ? `${name} ${(percent * 100).toFixed(0)}%` : name
          }
          isAnimationActive={false}
        >
          {data.map((_, i) => (
            <Cell
              key={i}
              fill={series[i % Math.max(series.length, 1)]?.color ?? "#3b82f6"}
            />
          ))}
        </Pie>
      </PieChart>
    );
  }

  // Radar
  if (variant === "radar") {
    return responsive(
      <RadarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <Tooltip />
        {showLegend && <Legend />}
        {data.map((row: any) => (
          <Radar key={String(row[xAxisKey])} name={String(row[xAxisKey])} />
        ))}
        {series.map((s, i) => (
          <Radar
            key={s.dataKey}
            name={s.name}
            dataKey={s.dataKey}
            stroke={s.color}
            fill={s.color}
            fillOpacity={0.25}
            isAnimationActive={false}
          />
        ))}
      </RadarChart>
    );
  }

  // Scatter
  if (variant === "scatter") {
    return responsive(
      <ScatterChart margin={{ top: 20, right: 24, bottom: 48, left: 56 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey={xAxisKey} type="category" />
        <YAxis />
        <Tooltip />
        {showLegend && <Legend />}
        {series.map((s) => (
          <Scatter
            key={s.dataKey}
            name={s.name}
            dataKey={s.dataKey}
            fill={s.color}
            isAnimationActive={false}
          />
        ))}
      </ScatterChart>
    );
  }

  // Bar / Column / Horizontal Bar
  if (variant === "bar" || variant === "column" || variant === "barh") {
    const isHorizontal = variant === "barh";
    return responsive(
      <BarChart
        data={data}
        layout={isHorizontal ? "vertical" : "horizontal"}
        margin={{ top: 20, right: 24, bottom: 48, left: isHorizontal ? 80 : 56 }}
      >
        <CartesianGrid strokeDasharray="3 3" />
        {isHorizontal
          ? <XAxis type="number" />
          : <XAxis dataKey={xAxisKey} type="category" />
        }
        {isHorizontal
          ? <YAxis dataKey={xAxisKey} type="category" width={70} />
          : <YAxis />
        }
        <Tooltip />
        {showLegend && <Legend />}
        {series.map((s) => (
          <Bar
            key={s.dataKey}
            name={s.name}
            dataKey={s.dataKey}
            fill={s.color}
            stackId={stacked ? "stack" : undefined}
            isAnimationActive={false}
            radius={[2, 2, 0, 0]}
          />
        ))}
      </BarChart>
    );
  }

  // Line / Area (default fallback)
  if (variant === "line" || variant === "area") {
    return responsive(
      variant === "area" ? (
        <AreaChart data={data} margin={{ top: 20, right: 24, bottom: 48, left: 56 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={xAxisKey} />
          <YAxis />
          <Tooltip />
          {showLegend && <Legend />}
          {series.map((s) => (
            <Area
              key={s.dataKey}
              name={s.name}
              dataKey={s.dataKey}
              stroke={s.color}
              fill={s.color}
              fillOpacity={0.2}
              isAnimationActive={false}
              type="monotone"
            />
          ))}
        </AreaChart>
      ) : (
        <LineChart data={data} margin={{ top: 20, right: 24, bottom: 48, left: 56 }}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey={xAxisKey} />
          <YAxis />
          <Tooltip />
          {showLegend && <Legend />}
          {series.map((s) => (
            <Line
              key={s.dataKey}
              name={s.name}
              dataKey={s.dataKey}
              stroke={s.color}
              isAnimationActive={false}
              type="monotone"
              dot={{ r: 3, strokeWidth: 2, fill: "#fff" }}
              activeDot={{ r: 5 }}
            />
          ))}
        </LineChart>
      )
    );
  }

  // Unknown variant — show debug info
  // eslint-disable-next-line no-console
  console.warn("[RechartsChartRenderer] UNKNOWN variant:", variant);
  return (
    <div style={{ padding: 16, color: "#6b7280", fontSize: 13, height: 120, display: "flex", alignItems: "center", justifyContent: "center" }}>
      Chart variant "{variant}" not supported ({data.length} rows × {series.length} series)
    </div>
  );
});

// ---------------------------------------------------------------------------
// TodoListRenderer — interactive todo list with pure client-side state.
// Items added/deleted/toggled live only in useState; no new chat messages,
// no round-trip to model. Model emits initial items, client owns mutations.
// ---------------------------------------------------------------------------

interface TodoItem {
  id: string;
  text: string;
  done?: boolean;
}

interface TodoListRendererProps {
  items?: TodoItem[];
  placeholder?: string; // input placeholder
}

const TodoListRenderer = memo(function TodoListRenderer({
  items: initialItems,
  placeholder = "添加新待办...",
}: TodoListRendererProps) {
  // Normalize initial items from model (may be inline array or undefined)
  const normalizedInitial: TodoItem[] = Array.isArray(initialItems)
    ? initialItems.map((it, i) => ({
        id: String(it?.id ?? i),
        text: String(it?.text ?? ""),
        done: Boolean(it?.done),
      }))
    : [];

  const [items, setItems] = useState<TodoItem[]>(normalizedInitial);
  const [input, setInput] = useState("");

  const handleDelete = (id: string) => {
    setItems((prev) => prev.filter((it) => it.id !== id));
  };

  const handleToggle = (id: string) => {
    setItems((prev) =>
      prev.map((it) =>
        it.id === id ? { ...it, done: !it.done } : it
      )
    );
  };

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text) return;
    setItems((prev) => [
      ...prev,
      { id: String(Date.now()), text, done: false },
    ]);
    setInput("");
  };

  return (
    <div
      data-aui="todolist"
      style={{
        width: "100%",
        maxWidth: "100%",
        boxSizing: "border-box",
        height: "auto", // override globals.css fixed heights
      }}
    >
      {/* Item list */}
      <ul
        style={{
          listStyle: "none",
          margin: 0,
          padding: 0,
          display: "flex",
          flexDirection: "column",
          gap: 6,
        }}
      >
        {items.length === 0 ? (
          <li
            style={{
              padding: "12px 8px",
              color: "#6b7280",
              fontSize: 13,
              textAlign: "center",
              border: "1px dashed #e5e7eb",
              borderRadius: 8,
            }}
          >
            暂无待办，添加一个吧
          </li>
        ) : (
          items.map((item) => (
            <li
              key={item.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                padding: "6px 8px",
                borderRadius: 6,
                background: item.done ? "#f9fafb" : "#ffffff",
              }}
            >
              <input
                type="checkbox"
                checked={!!item.done}
                onChange={() => handleToggle(item.id)}
                style={{ flexShrink: 0 }}
              />
              <span
                style={{
                  flex: 1,
                  fontSize: 14,
                  color: item.done ? "#9ca3af" : "#1f2937",
                  textDecoration: item.done ? "line-through" : "none",
                  wordBreak: "break-word",
                }}
              >
                {item.text}
              </span>
              <button
                onClick={() => handleDelete(item.id)}
                aria-label="删除待办"
                style={{
                  flexShrink: 0,
                  padding: "2px 8px",
                  fontSize: 12,
                  color: "#ef4444",
                  background: "transparent",
                  border: "1px solid #fecaca",
                  borderRadius: 4,
                  cursor: "pointer",
                  lineHeight: 1.4,
                }}
              >
                删除
              </button>
            </li>
          ))
        )}
      </ul>

      {/* Add form */}
      <form
        onSubmit={handleSubmit}
        style={{
          display: "flex",
          gap: 8,
          marginTop: 12,
        }}
      >
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={placeholder}
          style={{
            flex: 1,
            padding: "6px 10px",
            fontSize: 14,
            border: "1px solid #d1d5db",
            borderRadius: 6,
            outline: "none",
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              handleSubmit();
            }
          }}
        />
        <button
          type="submit"
          style={{
            padding: "6px 14px",
            fontSize: 14,
            color: "#ffffff",
            background: "#2563eb",
            border: "none",
            borderRadius: 6,
            cursor: "pointer",
            whiteSpace: "nowrap",
          }}
        >
          添加
        </button>
      </form>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Custom library overrides — supplement the default library where the model's
// A2UI components need richer visual rendering than the minimal default.
// Currently: Input needs a visible label (default only sets aria-label).
// ---------------------------------------------------------------------------

const customLibrary = {
  ...defaultGenerativeUILibrary,
  Input: {
    ...defaultGenerativeUILibrary.Input,
    render: ({ placeholder, multiline, label, name, $action, $dispatch }) => {
      const key = name || "input";
      const store =
        typeof window !== "undefined"
          ? ((window as unknown as { __auiFormStore__?: Map<string, string> }).__auiFormStore__ ??= new Map())
          : null;
      const submit = (v: unknown) => {
        if ($action && $dispatch) {
          $dispatch({ type: $action.type, payload: v });
        }
      };
      const onChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
        if (store) store.set(key, e.currentTarget.value);
        if ($action && $dispatch) {
          $dispatch({ type: $action.type, payload: e.currentTarget.value });
        }
      };
      const input = multiline
        ? jsx("textarea", {
            "data-aui": "input",
            "data-aui-multiline": true,
            "data-aui-name": key,
            name,
            "aria-label": label,
            placeholder,
            onChange,
            onKeyDown: (e: React.KeyboardEvent) => {
              if (
                e.key !== "Enter" ||
                !(e.ctrlKey || e.metaKey) ||
                e.nativeEvent.isComposing
              )
                return;
              if (e.currentTarget.form) {
                e.preventDefault();
                e.currentTarget.form.requestSubmit();
              } else submit(e.currentTarget.value);
            },
          })
        : jsx("input", {
            "data-aui": "input",
            "data-aui-name": key,
            name,
            type: "text",
            "aria-label": label,
            placeholder,
            onChange,
            onKeyDown: (e: React.KeyboardEvent) => {
              if (e.key === "Enter" && !e.nativeEvent.isComposing && !e.currentTarget.form)
                submit(e.currentTarget.value);
            },
          });
      // Wrap with visible <label> when label is provided
      if (label) {
        return jsxs("label", {
          "data-aui": "input-wrapper",
          children: [
            jsx("span", { "data-aui": "input-label", children: label }),
            input,
          ],
        });
      }
      return input;
    },
  },

  // Chart: override assistant-ui's tiny SVG with real recharts visualizations.
  // Nexus model emits { chartType, xAxis: "fieldName", series: [{key, name, color}] }
  // + dataModel valueList. convertSurfaceToUISpec reads props.variant + props.data
  // (but model sends chartType, not variant, and data lives in dataModel, not inline).
  // We handle BOTH formats — if data/series is empty, try to resolve from
  // Nexus-style chartType/xAxis/series props as a best-effort fallback.
  Chart: {
    ...defaultGenerativeUILibrary.Chart,
    render: (props) => {
      const {
        variant,
        data,
        series,
        stacked,
        showAxis,
        showLegend,
        // Nexus format props (may be present if preprocess didn't run)
        chartType,
        xAxis,
      } = props as Record<string, unknown>;

      // eslint-disable-next-line no-console
      console.warn("[Chart customLibrary]", {
        variant,
        chartType,
        dataLength: Array.isArray(data) ? data.length : 0,
        seriesLength: Array.isArray(series) ? series.length : 0,
        xAxis,
        propsKeys: Object.keys(props as object),
      });

      // Determine variant
      const v = String(
        variant ?? chartType ?? "line"
      ).toLowerCase();
      const variantMap: Record<string, string> = {
        bar: "bar", column: "bar",
        line: "line", area: "area",
        pie: "pie", doughnut: "doughnut", donut: "doughnut",
        scatter: "scatter",
        radar: "radar",
        barh: "barh", "horizontal-bar": "barh", horizontal: "barh",
      };
      const normalizedVariant = variantMap[v] ?? v;

      // Normalize data: assistant-ui format [{label, value}, ...] or Nexus rows [{field: val}]
      let chartData: Array<Record<string, unknown>> = [];
      if (Array.isArray(data) && data.length > 0) {
        chartData = data.map((d: any) => {
          if (typeof d === "object" && d !== null) return d;
          return { value: d };
        });
      }

      // Normalize series
      let rechartsSeries: Array<{ dataKey: string; name: string; color: string }> = [];
      if (Array.isArray(series) && series.length > 0) {
        rechartsSeries = series.map((s: any, i: number) => ({
          dataKey: String(s.key ?? s.dataKey ?? `series_${i}`),
          name: String(s.name ?? s.label ?? `Series ${i + 1}`),
          color: String(s.color ?? s.fill ?? "#3b82f6"),
        }));
      }

      // Fallback: if no data and no series, show placeholder
      if (chartData.length === 0) {
        // eslint-disable-next-line no-console
        console.warn("[Chart customLibrary] NO DATA — showing placeholder");
        return jsxs("div", {
          "data-aui": "chart",
          "data-aui-variant": normalizedVariant,
          style: {
            height: 200,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            border: "1px dashed hsl(var(--border))",
            borderRadius: 8,
            color: "hsl(var(--muted-foreground))",
            fontSize: 13,
          },
          children: [`Chart (${normalizedVariant}) — 暂无数据`],
        });
      }

      // Determine X axis key from xAxis prop or first series dataKey
      const xAxisKey =
        typeof xAxis === "string"
          ? xAxis
          : rechartsSeries.length > 0
            ? Object.keys(chartData[0] || {}).find(
                (k) => !rechartsSeries.some((s) => s.dataKey === k)
              ) ?? "x"
            : "x";

      // Single series fallback
      if (rechartsSeries.length === 0) {
        const valueKeys = Object.keys(chartData[0] || {}).filter(
          (k) => k !== xAxisKey
        );
        if (valueKeys.length > 0) {
          rechartsSeries = [
            { dataKey: valueKeys[0], name: valueKeys[0], color: "#3b82f6" },
          ];
        }
      }

      // eslint-disable-next-line no-console
      console.warn("[Chart customLibrary] RENDERING", {
        normalizedVariant,
        chartDataRows: chartData.length,
        xAxisKey,
        rechartsSeries,
      });

      // ===== Recharts render — REAL React component for proper context/hooks =====
      return jsx("div", {
        "data-aui": "chart",
        "data-aui-variant": normalizedVariant,
        style: {
          width: "100%",
          maxWidth: "100%",
          boxSizing: "border-box",
          height: "auto", // CRITICAL: override globals.css [data-aui="chart"] { height: 120px }
          padding: "4px 0", // give recharts Y-axis labels / Legend some breathing room
        },
        children: jsx(RechartsChartRenderer, {
          variant: normalizedVariant,
          data: chartData,
          series: rechartsSeries,
          xAxisKey,
          stacked: stacked as boolean | undefined,
          showLegend: showLegend as boolean | undefined,
        }),
      });
    },
  },

  // TodoList — interactive, client-side state only. Model emits initial items;
  // user mutations (add/delete/toggle) live purely in React useState inside
  // TodoListRenderer. No $dispatch, no new chat messages.
  // NOTE: JSONGenerativeUI.buildPresentParameters iterates ALL library keys and
  // reads .properties and .description from each entry. We MUST provide both.
  // We use plain JSON Schema7 (supported by toJSONSchema in assistant-stream)
  // instead of Zod — avoids adding a dependency.
  TodoList: {
    description:
      "An interactive to-do list with checkboxes, per-item delete buttons, and a bottom input+submit form. All mutations are client-side only — no new chat messages.",
    properties: {
      type: "object",
      properties: {
        items: {
          type: "array",
          items: {
            type: "object",
            properties: {
              id: { type: "string" },
              text: { type: "string" },
              done: { type: "boolean" },
            },
          },
        },
        placeholder: { type: "string" },
      },
    },
    render: ({ items, placeholder }) => {
      const normalizedItems = Array.isArray(items) ? items : [];
      return jsx(TodoListRenderer, {
        items: normalizedItems as TodoItem[],
        placeholder: placeholder as string | undefined,
      });
    },
  },
};
export { customLibrary };

// ---------------------------------------------------------------------------
// Module-level bridge ref — set by <A2uiActionProvider> once mounted.
// The action registry is created eagerly (outside any hook) because
// JSONGenerativeUI is a pure factory; only the handler needs a hook value.
// ---------------------------------------------------------------------------

type SendA2uiActionFn = (action: unknown) => void;

let _sendA2uiAction: SendA2uiActionFn | null = null;

/** Internal: install the sendA2uiAction hook return value into the module bridge. */
export function _setSendA2uiAction(fn: SendA2uiActionFn | null): void {
  _sendA2uiAction = fn;
}

// ---------------------------------------------------------------------------
// Action registry — routes $action.type through the hook-backed bridge.
// ---------------------------------------------------------------------------

const a2uiActionRegistry = createActionRegistry({
  /**
   * The single action type AG-UI runtime emits for every interactive A2UI
   * component click (Button submit, Form submit, etc.).
   *
   * `ctx.payload` contains the original model-emitted action plus any runtime
   * user input merged under `$input`.  We forward the whole thing through
   * `useAgUiSendA2uiAction`, which wraps it into forwardedProps.a2uiAction
   * for the backend agent run.
   */
  "a2ui:action": ({ payload }) => {
    console.warn("[A2UI] action handler called, payload:", payload);
    if (!_sendA2uiAction) {
      // Bridge not yet connected — this should never happen since the Provider
      // mounts before any A2UI surface can render, but be defensive.
      console.warn("[A2UI] sendA2uiAction bridge not mounted; action dropped", payload);
      return undefined;
    }

    // Merge live Input values from window.__auiFormStore__ into payload.context.
    const action = payload as Record<string, unknown>;
    const ctx = action.context as Record<string, unknown> | undefined;
    const win = typeof window !== "undefined" ? (window as unknown as { __auiFormStore__?: Map<string, string> }) : null;
    console.warn("[A2UI] store debug:", {
      hasContext: !!ctx,
      ctxKeys: ctx ? Object.keys(ctx) : [],
      store: win?.__auiFormStore__ ? Object.fromEntries(win.__auiFormStore__.entries()) : null,
    });
    if (ctx && win?.__auiFormStore__) {
      const store = win.__auiFormStore__;
      const overrides: Record<string, string> = {};
      for (const key of Object.keys(ctx)) {
        const val = store.get(key);
        if (val !== undefined) overrides[key] = val;
      }
      if (Object.keys(overrides).length > 0) {
        action.context = { ...ctx, ...overrides };
        console.warn("[A2UI] store overrides applied:", overrides, "→ final context:", action.context);
      } else {
        console.warn("[A2UI] store has no matching keys — skipping override");
      }
    }

    _sendA2uiAction(payload);
    return undefined;
  },
});

// ---------------------------------------------------------------------------
// JSONGenerativeUI + present tool
// ---------------------------------------------------------------------------

const generativeUI = new JSONGenerativeUI({
  library: customLibrary,
  actions: a2uiActionRegistry,
});

/**
 * The `present` frontend tool.  useAgUiRuntime automatically synthesises
 * tool-call parts with `toolCallName: "present"` from ACTIVITY_SNAPSHOT
 * events (activityType: "a2ui-surface").  Registering this tool installs
 * the renderer that actually paints the card into the message stream.
 *
 * `.present({ display: "standalone" })` tells the UI renderer to paint the
 * card outside the chain-of-thought trace — as a full surface artifact.
 */
export const presentTool = generativeUI.present({
  display: "standalone",
});

// ---------------------------------------------------------------------------
// Tool UI registration — called once from a React component inside the
// AssistantRuntimeProvider tree so `useAui()` resolves.
// ---------------------------------------------------------------------------

/**
 * Register the `present` tool's renderer with the aui client's tools scope.
 * Mount this as the first child inside AssistantRuntimeProvider (after
 * A2uiActionProvider so the action bridge is ready).
 *
 * We use `useAui().tools.setToolUI()` directly instead of the `config` prop
 * because `AuiConfig` lives in `@assistant-ui/store`, which Next.js doesn't
 * resolve as a transitive dependency of `@assistant-ui/core`.
 */
export function A2uiToolRegistry() {
  const aui = useAui();

  useEffect(() => {
    console.log("[A2uiToolRegistry] mounting...", {
      hasAui: !!aui,
      tools: aui.tools,
      presentToolRender: presentTool.render,
    });
    const unsub = aui.tools.setToolUI("present", presentTool.render, {
      standalone: true,
    });
    console.log("[A2uiToolRegistry] present tool registered! unsub=", typeof unsub);
    return () => {
      console.log("[A2uiToolRegistry] unregistering...");
      unsub();
    };
  }, [aui]);

  return null;
}
