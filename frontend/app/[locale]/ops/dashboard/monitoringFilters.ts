// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.
import dayjs from "dayjs";
import utc from "dayjs/plugin/utc";

dayjs.extend(utc);

export const monitoringTabs = [
  "overview",
  "agent",
  "model",
  "skill",
  "mcp",
] as const;
export type MonitoringTab = (typeof monitoringTabs)[number];
export type ResourceTab = Exclude<MonitoringTab, "overview">;
export type DatePreset = "week" | "month" | "custom";
export type MonitoringRange = [start: string, end: string];

export const dateFormat = "YYYY-MM-DD";
export const maxRangeDays = 366;

interface MonitoringFilters {
  tenant: string;
  group: string;
  resources: Partial<Record<ResourceTab, string>>;
  tool: string;
  datePreset: DatePreset;
  customRange: MonitoringRange | null;
}

type FilterAction =
  | { type: "tenant" | "group" | "tool"; value: string }
  | { type: "resource"; tab: ResourceTab; value: string }
  | { type: "datePreset"; value: DatePreset }
  | { type: "customRange"; value: MonitoringRange | null };

export const initialMonitoringFilters: MonitoringFilters = {
  tenant: "",
  group: "",
  resources: {},
  tool: "",
  datePreset: "week",
  customRange: null,
};

export function updateMonitoringFilters(
  state: MonitoringFilters,
  action: FilterAction
): MonitoringFilters {
  switch (action.type) {
    case "tenant":
      return action.value === state.tenant
        ? state
        : {
            ...state,
            tenant: action.value,
            group: "",
            resources: {},
            tool: "",
          };
    case "group":
      return action.value === state.group
        ? state
        : {
            ...state,
            group: action.value,
            // The MCP service directory follows the group filter; drop a
            // selection the new group may exclude, like the tenant reset.
            resources: { ...state.resources, mcp: "" },
            tool: "",
          };
    case "resource":
      if (action.value === (state.resources[action.tab] ?? "")) return state;
      return {
        ...state,
        resources: { ...state.resources, [action.tab]: action.value },
        tool: action.tab === "mcp" ? "" : state.tool,
      };
    case "customRange": {
      if (action.value) {
        const [start, end] = action.value;
        const days = dayjs.utc(end).diff(dayjs.utc(start), "day");
        if (!(days >= 0 && days < maxRangeDays)) return state;
      }
      return { ...state, customRange: action.value };
    }
    default:
      return { ...state, [action.type]: action.value };
  }
}

export function getMonitoringRange(
  preset: DatePreset,
  custom: MonitoringRange | null,
  now = new Date()
): MonitoringRange | null {
  if (preset === "custom") return custom;
  // The deployed Ops default is UTC. Send calendar dates without timestamp conversion.
  const today = dayjs.utc(now);
  const days = preset === "week" ? 7 : 30;
  return [
    today.subtract(days - 1, "day").format(dateFormat),
    today.format(dateFormat),
  ];
}
