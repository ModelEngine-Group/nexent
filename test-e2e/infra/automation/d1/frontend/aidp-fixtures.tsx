import React from "react";
import { afterEach, beforeEach, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { App, ConfigProvider, Modal, message } from "antd";
import { setImmediate } from "node:timers";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import translations from "@/public/locales/zh/common.json";
import type { AidpKnowledgeBaseItem } from "@/ext_components/aidp/shared/types/knowledge";
import type {
  AidpDocumentItem,
  AidpKbDetail,
} from "@/ext_components/aidp/shared/types/management";

const context = vi.hoisted(() => ({
  user: { id: "owner-a", tenantId: "tenant-a", role: "USER" } as {
    id: string;
    tenantId: string;
    role: string;
  } | null,
  enabled: true,
  push: vi.fn(),
  groups: {
    groups: [
      { group_id: 1, group_name: "Group A" },
      { group_id: 2, group_name: "Group B" },
    ],
  },
  can: () => true,
}));
export const identity = context;
vi.mock("@/components/providers/AuthorizationProvider", () => ({
  useAuthorizationContext: () => ({ user: context.user }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({
    enableAidpKnowledge: context.enabled,
    isDeploymentReady: true,
  }),
}));
vi.mock("@/hooks/permission/usePermission", () => ({
  usePermission: () => ({
    can: context.can,
    canAny: context.can,
    isReady: true,
  }),
}));
vi.mock("@/hooks/group/useGroupList", () => ({
  useGroupList: () => ({
    data: context.groups,
    isFetching: false,
    error: null,
  }),
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: context.push }),
  useParams: () => ({ locale: "zh" }),
  useSearchParams: () => new URLSearchParams(),
}));
vi.mock("@/lib/auth", () => ({ getAuthHeaders: () => ({}) }));
vi.mock("@/lib/session", () => ({ handleSessionExpired: vi.fn() }));
vi.mock("@/lib/logger", () => ({
  default: { error: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

const i18n = createInstance();
void i18n.init({
  lng: "zh",
  fallbackLng: "zh",
  keySeparator: false,
  initImmediate: false,
  resources: { zh: { translation: translations } },
  interpolation: { escapeValue: false },
});
export const t = (key: string, options?: Record<string, unknown>) =>
  String(i18n.t(key, options));
export const base = "/api/aidp-mgmt/knowledge-bases";
export const kb: AidpKnowledgeBaseItem & Pick<AidpKbDetail, "document_count"> =
  {
    kds_id: "kb-a",
    kds_name: "ComponentKnowledge",
    description: "Component description",
    permission: "EDIT",
    ingroup_permission: "PRIVATE",
    group_ids: [],
    resource_status: "ACTIVE",
    creator_name: null,
    created_at: "2026-10-01T10:00:00+08:00",
    document_count: null,
  };
export const models = {
  models: [
    {
      model_name: "embed-a",
      display_name: "Vector A",
      model_type: "embedding",
    },
    { model_name: "llm-a", display_name: "Language A", model_type: "llm" },
    { model_name: "vlm-a", display_name: "Vision A", model_type: "vlm" },
    {
      model_name: "rerank-a",
      display_name: "Rerank A",
      model_type: "reranker",
    },
  ],
};
export const prompt = (language: string, domain: string) =>
  `${language}/${domain}: ` +
  "Extract specific entities and meaningful relationships.\n".repeat(8);
export const template = (language: string) => ({
  value: [
    ["retrieve_subgraph_hop", "2", "^[1-3]$"],
    ["no_think_mode", "是", "^(是|否)$"],
    [
      "prompt_language",
      language === "english" ? "英文" : "中文",
      "^(中文|英文)$",
    ],
    ["domain", "常规", "^(医疗|金融|常规|法律法规)$"],
    ["prompt_text", prompt(language, "常规"), "^[\\s\\S]{1,4096}$"],
    ["synonym_merge_enable", "否", "^(是|否)$"],
    ["disambiguation_enable", "否", "^(是|否)$"],
  ].map(([param_key, param_value, regexp]) => ({
    param_key,
    param_value,
    regexp,
    is_modifiable: true,
    ...(param_key === "prompt_text"
      ? {
          template: Object.fromEntries(
            ["常规", "医疗", "金融", "法律法规"].map((domain) => [
              domain,
              prompt(language, domain),
            ]),
          ),
        }
      : {}),
  })),
});
export const file: AidpDocumentItem = {
  file_uuid: "7f1c9c37-8d83-4e3d-8472-457a74aa4e52",
  file_ino_no: "1",
  file_name: "guide.txt",
  file_type: "txt",
  file_size: 1024,
  created_at: "2026-10-01T10:00:00Z",
  updated_at: "2026-10-01T10:00:00Z",
};
export const listResponse = (items = [kb], total = items.length) => ({
  value: items,
  total_count: total,
  total_reliable: true,
  has_more: false,
});
export const filesResponse = (items = [file], total = items.length) => ({
  value: items,
  total_count: total,
  total_reliable: true,
  has_more: false,
});
export interface RequestRecord {
  url: URL;
  method: string;
  body: Record<string, unknown>;
}
export const requests: RequestRecord[] = [];
export const server: {
  handler: (request: RequestRecord) => Response | Promise<Response>;
} = {
  handler: () => {
    throw new Error("No HTTP fixture configured");
  },
};
export const reply = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
export const matching = (path: string, method = "GET") =>
  requests.filter((r) => r.url.pathname === path && r.method === method);
export function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
const clients: QueryClient[] = [];
const nativeComputedStyle = window.getComputedStyle.bind(window);

export function mount(
  ui: React.ReactNode,
  client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  }),
) {
  clients.push(client);
  const wrap = (child: React.ReactNode) => (
    <I18nextProvider i18n={i18n}>
      <ConfigProvider
        button={{ autoInsertSpace: false }}
        theme={{ token: { motion: false } }}
      >
        <App>
          <QueryClientProvider client={client}>{child}</QueryClientProvider>
        </App>
      </ConfigProvider>
    </I18nextProvider>
  );
  const view = render(wrap(ui));
  return {
    ...view,
    client,
    rerender: (child: React.ReactNode) => view.rerender(wrap(child)),
  };
}
export async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}
export async function advance(ms: number) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1);
  });
}
export async function select(id: string, option: string) {
  const input = document.getElementById(id)!;
  fireEvent.mouseDown(input);
  await waitFor(() =>
    expect(
      document.querySelector(
        ".ant-select-dropdown:not(.ant-select-dropdown-hidden)",
      ),
    ).toBeTruthy(),
  );
  const options = Array.from(
    document
      .querySelector(".ant-select-dropdown:not(.ant-select-dropdown-hidden)")!
      .querySelectorAll(".ant-select-item-option-content"),
  );
  fireEvent.click(options.find((element) => element.textContent === option)!);
  await settle();
}
export function fillBasic(name = "CreatedKnowledge") {
  fireEvent.change(
    screen.getByPlaceholderText(t("aidpKnowledge.kbNamePlaceholder")),
    { target: { value: name } },
  );
  fireEvent.change(
    screen.getByPlaceholderText(t("aidpKnowledge.kbDescriptionPlaceholder")),
    { target: { value: "Description" } },
  );
}
export async function chooseFiles(files: File[]) {
  fireEvent.change(document.querySelector("input[type=file]")!, {
    target: { files },
  });
  await settle();
  await settle();
}
export function expandSection(section: string) {
  const button = document.querySelector<HTMLButtonElement>(
    `button[aria-controls="aidp-create-${section}-panel"]`,
  )!;
  if (button.getAttribute("aria-expanded") === "false") fireEvent.click(button);
}

export class UploadTransport {
  static sent: UploadTransport[] = [];
  status = 0;
  statusText = "";
  responseText = "";
  withCredentials = false;
  headers: Record<string, string> = {};
  body!: FormData;
  upload: { onprogress?: (event: unknown) => void; onload?: () => void } = {};
  onload?: () => void;
  onerror?: () => void;
  onabort?: () => void;
  open = vi.fn();
  setRequestHeader(key: string, value: string) {
    this.headers[key] = value;
  }
  send(body: FormData) {
    this.body = body;
    UploadTransport.sent.push(this);
  }
  abort() {
    this.onabort?.();
  }
  progress(loaded: number, total: number) {
    this.upload.onprogress?.({ lengthComputable: true, loaded, total });
  }
  complete(body: unknown, status = 200) {
    this.status = status;
    this.responseText = typeof body === "string" ? body : JSON.stringify(body);
    this.onload?.();
  }
}
beforeEach(() => {
  identity.user = { id: "owner-a", tenantId: "tenant-a", role: "USER" };
  identity.enabled = true;
  requests.length = 0;
  UploadTransport.sent = [];
  sessionStorage.clear();
  localStorage.clear();
  vi.stubGlobal("XMLHttpRequest", UploadTransport);
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, options: RequestInit = {}) => {
      const request = {
        url: new URL(input),
        method: options.method || "GET",
        body: options.body ? JSON.parse(String(options.body)) : {},
      };
      requests.push(request);
      return server.handler(request);
    }),
  );
  server.handler = (request) => {
    if (request.url.pathname === "/api/aidp-mgmt/models") return reply(models);
    if (request.url.pathname === base + "/graph-template")
      return reply(template(request.url.searchParams.get("language")!));
    if (request.url.pathname === base && request.method === "GET")
      return reply(listResponse());
    if (request.url.pathname === base + "/kb-a") return reply(kb);
    if (
      request.url.pathname === base + "/kb-a/documents" &&
      request.method === "GET"
    )
      return reply(filesResponse());
    throw new Error(
      `Unhandled component HTTP request: ${request.method} ${request.url.pathname}`,
    );
  };
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
    setTimeout(() => callback(0), 0),
  );
  vi.stubGlobal("cancelAnimationFrame", clearTimeout);
  HTMLElement.prototype.scrollIntoView = vi.fn();
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
    nativeComputedStyle(element),
  );
});
afterEach(async () => {
  cleanup();
  await act(async () => {
    Modal.destroyAll();
    message.destroy();
    if (vi.isFakeTimers()) await vi.advanceTimersByTimeAsync(100);
    else await new Promise((resolve) => setTimeout(resolve, 0));
  });
  clients.splice(0).forEach((client) => client.clear());
  vi.useRealTimers();
  vi.unstubAllGlobals();
  await act(async () => {
    await new Promise((resolve) => setImmediate(resolve));
  });
  vi.mocked(window.getComputedStyle).mockRestore();
});
