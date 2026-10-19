// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import {
  cloneElement,
  type ComponentPropsWithoutRef,
  type ReactElement,
  type ReactNode,
} from "react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  render as renderComponent,
  screen,
  within,
  act,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import {
  ComposerAttachment,
  ComposerDictation,
} from "@/app/newchat/assistant-ui/composer-tools";
import { Composer } from "@/app/newchat/assistant-ui/composer";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useParams: () => ({ locale: "zh" }),
}));
vi.mock("@/components/providers/deploymentProvider", () => ({
  useDeployment: () => ({
    enableAidpKnowledge: false,
    isDeploymentReady: true,
  }),
}));
const resourceQueries = vi.hoisted(() => ({
  knowledge: vi.fn(() => ({ data: [], isLoading: false })),
  skills: vi.fn(() => ({ data: [], isLoading: false })),
}));
vi.mock("@/hooks/chat/useComposerResources", () => ({
  useComposerKnowledgeBases: resourceQueries.knowledge,
  useComposerSkills: resourceQueries.skills,
}));
vi.mock("@/hooks/agent/useToolList", () => ({
  useToolList: () => ({
    isLoading: false,
    availableTools: [
      {
        name: "knowledge_base_search",
        initParams: [{ name: "top_k", type: "number", value: 5 }],
      },
    ],
  }),
}));

function render(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return renderComponent(ui, {
    wrapper: ({ children }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    ),
  });
}

const runtime = vi.hoisted(() => ({
  thread: { isRunning: false, messages: [] },
  threads: { mainThreadId: "fixture-thread" },
  composer: { text: "question", dictation: false, attachments: [] },
  cancel: vi.fn(),
}));
beforeEach(() => {
  runtime.thread.isRunning = false;
  runtime.composer.text = "question";
  runtime.cancel.mockReset();
  resourceQueries.knowledge.mockClear();
  resourceQueries.skills.mockClear();
});
vi.mock("@assistant-ui/react", () => {
  const Wrapper = ({ children }: { children: ReactNode }) => <>{children}</>;
  return {
    useAui: () => ({
      composer: () => ({ setText: vi.fn() }),
      threads: () => ({ __internal_getAssistantRuntime: () => undefined }),
    }),
    useAuiState: (select: (state: typeof runtime) => unknown) =>
      select(runtime),
    AuiIf: ({
      condition,
      children,
    }: {
      condition: (state: typeof runtime) => boolean;
      children: ReactNode;
    }) => (condition(runtime) ? children : null),
    ComposerPrimitive: {
      Root: Wrapper,
      Unstable_TriggerPopoverRoot: Wrapper,
      AddAttachment: Wrapper,
      Input: ({
        submitMode: _submitMode,
        ...props
      }: ComponentPropsWithoutRef<"textarea"> & { submitMode?: string }) => {
        void _submitMode;
        return <textarea {...props} defaultValue={runtime.composer.text} />;
      },
      Send: Wrapper,
      Cancel: ({
        children,
      }: {
        children: ReactElement<{ onClick?: () => void }>;
      }) => cloneElement(children, { onClick: runtime.cancel }),
      Dictate: Wrapper,
      StopDictation: Wrapper,
    },
  };
});
vi.mock("react-i18next", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-i18next")>()),
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "zh-CN" },
  }),
}));
const lexicalInputProps = vi.hoisted(() => vi.fn());
vi.mock("@assistant-ui/react-lexical", () => ({
  LexicalComposerInput: (props: {
    placeholder?: string;
    "aria-label"?: string;
    formatter?: unknown;
    submitMode?: string;
  }) => {
    lexicalInputProps(props);
    return (
      <textarea
        aria-label={props["aria-label"]}
        placeholder={props.placeholder}
        defaultValue={runtime.composer.text}
      />
    );
  },
}));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  planRegistry: { subscribe: () => () => {}, data: null },
}));
const selectorProps = vi.hoisted(() => vi.fn());
vi.mock("@/app/newchat/ui/model-selector", () => ({
  ModelSelector: (props: unknown) => {
    selectorProps(props);
    return <button>模型</button>;
  },
}));

it("forwards every known effort through Composer without fabricating a default", () => {
  const changed = vi.fn();
  render(
    <Composer
      models={[{ id: "1", name: "model" }]}
      selectedModelId="1"
      chatMode="execution"
      onChatModeChange={vi.fn()}
      onThinkingEffortChange={changed}
    />
  );
  const props = selectorProps.mock.lastCall?.[0] as {
    effort?: string;
    onEffortChange: (value: string) => void;
  };
  expect(props.effort).toBeUndefined();
  for (const level of [
    "auto",
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
  ]) {
    props.onEffortChange(level);
    expect(changed).toHaveBeenLastCalledWith(level);
  }
  const count = changed.mock.calls.length;
  props.onEffortChange("provider-invalid");
  expect(changed).toHaveBeenCalledTimes(count);
});
vi.mock("@/app/newchat/ui/attachment", () => ({
  ComposerAttachments: () => null,
  ComposerAddAttachment: ({
    label,
    tooltip,
    icon,
  }: {
    label?: string;
    tooltip?: string;
    icon?: ReactNode;
  }) => (
    <button aria-label={tooltip ?? "附件"} title={tooltip}>
      {icon}
      {label}
    </button>
  ),
}));
const drawerProps = vi.hoisted(() => ({ knowledge: vi.fn(), skills: vi.fn() }));
vi.mock(
  "@/app/newchat/assistant-ui/conversation-knowledge-scope-modal",
  () => ({
    ConversationKnowledgeScopeModal: (props: {
      open: boolean;
      onCancel: () => void;
    }) => {
      drawerProps.knowledge(props);
      return props.open ? (
        <div role="dialog" aria-label="knowledge drawer">
          <button onClick={props.onCancel}>Cancel knowledge</button>
        </div>
      ) : null;
    },
  })
);
vi.mock("@/features/workbench/components/SkillPicker", () => ({
  SkillPicker: (props: { open: boolean; onCancel: () => void }) => {
    drawerProps.skills(props);
    return props.open ? (
      <div role="dialog" aria-label="skill drawer">
        <button onClick={props.onCancel}>Cancel skills</button>
      </div>
    ) : null;
  },
}));
vi.mock("@/app/newchat/ui/skill-file-mention", () => ({
  SkillFileMentionPopover: () => null,
}));
vi.mock("@/app/newchat/ui/directive-text", () => ({
  DirectiveChip: () => null,
}));
vi.mock("@/app/newchat/ui/skill-directives", () => ({
  combinedSkillDirectiveFormatter: {},
  skillDirectiveIconMap: {},
}));
vi.mock("@/components/chat/RuntimeMetadataEditor", () => ({
  RuntimeMetadataEditor: () => null,
}));
vi.mock("@/components/ui/tooltip", () => ({
  Tooltip: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: ReactNode }) => <>{children}</>,
  TooltipContent: () => null,
}));

const base = {
  models: [],
  chatMode: "execution" as const,
  onChatModeChange: vi.fn(),
};

const entryConfigurations = [
  { name: "default", props: {} },
  { name: "newchat", props: { onKnowledgeScopeChange: vi.fn() } },
  { name: "nl2agent", props: { onChatModeChange: undefined } },
  {
    name: "workbench",
    props: {
      workbenchPresentation: {
        mode: "generic_chat" as const,
        onExitCreation: vi.fn(),
        actions: null,
      },
    },
  },
];

it.each([
  ...entryConfigurations,
  { name: "nl2agent configuration", props: { configurationLayout: true } },
  { name: "debug and compare", props: { debugLayout: true } },
  {
    name: "workbench agent creation",
    props: {
      workbenchPresentation: {
        mode: "agent_create" as const,
        actions: null,
        onExitCreation: vi.fn(),
      },
    },
  },
  {
    name: "workbench skill creation",
    props: {
      workbenchPresentation: {
        mode: "skill_create" as const,
        actions: null,
        onExitCreation: vi.fn(),
      },
    },
  },
  { name: "nl2skill Lexical", props: { skillFiles: [] } },
  {
    name: "workbench skill draft Lexical",
    props: {
      skillFiles: [{ path: "scripts/test.py", content: "print(1)" }],
      workbenchPresentation: {
        mode: "skill_create" as const,
        actions: null,
        onExitCreation: vi.fn(),
      },
    },
  },
])(
  "$name has no visible hint and preserves editable drafts",
  async ({ props }) => {
    const view = render(<Composer {...base} {...props} />);
    const input = screen.getByRole("textbox", {
      name: "chat.composer.inputLabel",
    });
    expect(input).toHaveAttribute("placeholder", "");
    expect(input).toHaveValue("question");
    await userEvent.clear(input);
    expect(input).toHaveValue("");
    await userEvent.type(input, "A draft / @ reference");
    expect(input).toHaveValue("A draft / @ reference");
    expect(view.container).not.toHaveTextContent("chat.composer.placeholder");
    if ("skillFiles" in props) {
      expect(lexicalInputProps.mock.lastCall?.[0]).toMatchObject({
        formatter: {},
        submitMode: "enter",
      });
    }
  }
);

it("shares the default shell, text input, model and paper-plane send presentation across entries", () => {
  const presentation = entryConfigurations.map(({ props }) => {
    const view = render(<Composer {...base} {...props} />);
    const send = screen.getByRole("button", { name: "chat.composer.send" });
    expect(send).toHaveClass("bg-transparent", "text-muted-foreground");
    expect(send.querySelector(".lucide-send")).not.toBeNull();
    expect(view.container.querySelector("fieldset")).toHaveClass("bg-white");
    const result = {
      shell: view.container.querySelector("fieldset")!.className,
      input: screen.getByRole("textbox").className,
      send: send.className,
      model: selectorProps.mock.lastCall?.[0].className,
    };
    view.unmount();
    return result;
  });
  for (const entry of presentation.slice(1))
    expect(entry).toEqual(presentation[0]);
});

it.each(entryConfigurations)(
  "$name keeps empty and disabled drafts unsendable",
  ({ props }) => {
    runtime.composer.text = "  ";
    const view = render(<Composer {...base} {...props} />);
    expect(
      screen.getByRole("button", { name: "chat.composer.send" })
    ).toBeDisabled();
    runtime.composer.text = "draft";
    view.rerender(<Composer {...base} {...props} disabled />);
    expect(
      screen.getByRole("button", { name: "chat.composer.send" })
    ).toBeDisabled();
    view.rerender(<Composer {...base} {...props} />);
    expect(
      screen.getByRole("button", { name: "chat.composer.send" })
    ).toBeEnabled();
  }
);

it("omitting optional controls skips resource queries and retain model changes and cancellation", async () => {
  const changed = vi.fn();
  const view = render(
    <Composer {...base} onChatModeChange={undefined} onModelChange={changed} />
  );
  expect(resourceQueries.knowledge).toHaveBeenLastCalledWith(false, false);
  expect(resourceQueries.skills).not.toHaveBeenCalled();
  expect(screen.getAllByRole("button")).toHaveLength(2);
  expect(
    screen.queryByRole("button", { name: "chat.composer.executionMode" })
  ).toBeNull();
  const props = selectorProps.mock.lastCall?.[0];
  props.onValueChange("model-b");
  expect(changed).toHaveBeenCalledExactlyOnceWith("model-b");
  runtime.thread.isRunning = true;
  view.rerender(
    <Composer {...base} onChatModeChange={undefined} onModelChange={changed} />
  );
  expect(selectorProps.mock.lastCall?.[0].disabled).toBe(true);
  await userEvent.click(
    screen.getByRole("button", { name: "chat.composer.stopGenerating" })
  );
  expect(runtime.cancel).toHaveBeenCalledOnce();
});

it("composes attachment and voice controls independently without enabling mode or resource controls", () => {
  const view = render(<Composer {...base} onChatModeChange={undefined} />);
  expect(screen.getAllByRole("button")).toHaveLength(2);
  view.rerender(
    <Composer {...base} onChatModeChange={undefined}>
      <ComposerAttachment />
    </Composer>
  );
  expect(
    screen.getByRole("button", { name: "workbench.controls.uploadAttachment" })
  ).toBeInTheDocument();
  expect(view.container.querySelector(".lucide-mic")).toBeNull();
  view.rerender(
    <Composer {...base} onChatModeChange={undefined}>
      <ComposerDictation configured={false} />
    </Composer>
  );
  expect(
    screen.queryByRole("button", {
      name: "workbench.controls.uploadAttachment",
    })
  ).toBeNull();
  expect(
    view.container.querySelector(".lucide-mic")!.closest("button")
  ).toBeDisabled();
  expect(resourceQueries.knowledge).toHaveBeenLastCalledWith(false, false);
  expect(resourceQueries.skills).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "chat.composer.executionMode" })
  ).toBeNull();
});

it("conversation controls enable resource queries and mode changes without an agent picker", async () => {
  const changed = vi.fn();
  const view = render(
    <Composer
      {...base}
      onChatModeChange={changed}
      onKnowledgeScopeChange={vi.fn()}
    />
  );
  expect(resourceQueries.knowledge).toHaveBeenLastCalledWith(true, false);
  expect(resourceQueries.skills).not.toHaveBeenCalled();
  expect(
    screen.queryByRole("button", { name: "workbench.controls.agents" })
  ).toBeNull();
  await userEvent.click(
    screen.getByRole("button", { name: "chat.composer.executionMode" })
  );
  await userEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "chat.composer.planningMode",
    })
  );
  expect(changed).toHaveBeenCalledExactlyOnceWith("planning");
  runtime.thread.isRunning = true;
  view.rerender(
    <Composer
      {...base}
      onChatModeChange={changed}
      onKnowledgeScopeChange={vi.fn()}
    />
  );
  expect(
    screen.getByRole("button", { name: "chat.composer.executionMode" })
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "chat.composer.knowledgeBase" })
  ).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: "chat.composer.skills" })
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: "chat.composer.plus" })
  ).toBeNull();
});

it.each(["skill_create", "agent_create"] as const)(
  "%s examples appear below the Workbench composer",
  (mode) => {
    runtime.composer.text = "";
    const { container } = render(
      <Composer
        {...base}
        workbenchPresentation={{
          mode,
          onExitCreation: vi.fn(),
          actions: null,
        }}
      />
    );
    const input = container.querySelector("fieldset");
    const examples = screen.getByRole("region", {
      name: mode === "skill_create" ? "Skill 创建示例" : "Agent创建示例",
    });
    expect(input).not.toBeNull();
    expect(
      input!.compareDocumentPosition(examples) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(examples.parentElement).not.toHaveClass("absolute");
    runtime.composer.text = "question";
  }
);
it("UT-FE-WB-014 composer keeps resources between text and ordered toolbar", async () => {
  runtime.thread.isRunning = false;
  const onChatModeChange = vi.fn();
  const onSelectAgent = vi.fn();
  render(
    <Composer
      {...base}
      onChatModeChange={onChatModeChange}
      onKnowledgeScopeChange={vi.fn()}
      onOpenWorkbenchSkillPicker={vi.fn()}
      workbenchPresentation={{
        mode: "generic_chat",
        onExitCreation: vi.fn(),
        actions: <button>Skill 创建</button>,
      }}
      workbenchResources={{
        agentName: "Agent A",
        onSelectAgent,
        onRemoveAgent: vi.fn(),
        skills: [{ id: 2, name: "Skill B" }],
      }}
      knowledgeScope={{
        schema_version: 1,
        local: { mode: "override", knowledge_ids: ["3"] },
        aidp: { mode: "disabled", kds_ids: [] },
      }}
    >
      <ComposerAttachment />
      <ComposerDictation configured={false} />
    </Composer>
  );
  const before = (left: Element, right: Element) =>
    expect(
      left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  const mode = screen.getByRole("button", {
    name: "chat.composer.executionMode",
  });
  expect(
    screen.getByRole("button", { name: "Skill 创建" })
  ).toBeInTheDocument();
  const chips = screen.getByLabelText("当前挂载资源");
  before(screen.getByRole("textbox"), chips);
  before(chips, mode);
  const labels = [
    "chat.composer.executionMode",
    "workbench.controls.agents",
    "chat.composer.knowledgeBase",
    "chat.composer.skills",
    "模型",
    "workbench.controls.uploadAttachment",
  ];
  for (let index = 1; index < labels.length; index++) {
    before(
      screen.getByRole("button", { name: labels[index - 1] }),
      screen.getByRole("button", { name: labels[index] })
    );
  }
  for (const label of labels.slice(1, 4)) {
    expect(screen.getByRole("button", { name: label }).textContent).toBe(label);
  }
  const attachment = screen.getByRole("button", {
    name: "workbench.controls.uploadAttachment",
  });
  expect(attachment).toBeEnabled();
  expect(attachment.textContent).toBe("");
  expect(attachment).toHaveAttribute(
    "title",
    "workbench.controls.uploadAttachment"
  );
  expect(attachment.querySelector(".lucide-paperclip")).not.toBeNull();
  expect(
    attachment.nextElementSibling?.querySelector(".lucide-mic")
  ).not.toBeNull();
  expect(
    screen.getByRole("button", { name: "chat.composer.send" })
  ).toBeEnabled();
  const agentButton = screen.getByRole("button", {
    name: "workbench.controls.agents",
  });
  expect(agentButton?.tagName).toBe("BUTTON");
  await userEvent.click(agentButton as HTMLButtonElement);
  expect(onSelectAgent).toHaveBeenCalledOnce();
  await userEvent.click(mode);
  const choices = within(screen.getByRole("dialog"));
  expect(
    choices.getByRole("button", { name: "chat.composer.executionMode" })
  ).toBeEnabled();
  await userEvent.click(
    choices.getByRole("button", { name: "chat.composer.planningMode" })
  );
  expect(onChatModeChange).toHaveBeenCalledExactlyOnceWith("planning");
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("UT-FE-WB-015 creation composer excludes resources and keeps the draft editable when its adapter is unavailable", () => {
  runtime.thread.isRunning = false;
  render(
    <Composer
      {...base}
      workbenchPresentation={{
        mode: "skill_create",
        onExitCreation: vi.fn(),
        actions: null,
      }}
      disabled
      disabledReason="创建能力尚未接入"
    >
      <ComposerAttachment />
      <ComposerDictation configured={false} />
    </Composer>
  );
  expect(screen.queryByRole("button", { name: "Agent" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Skills" })).toBeNull();
  expect(
    screen.queryByRole("button", { name: "chat.composer.planning" })
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: "chat.composer.execution" })
  ).toBeNull();
  expect(screen.queryByRole("button", { name: /knowledgeScope/ })).toBeNull();
  expect(screen.getByRole("textbox")).toBeEnabled();
  expect(screen.getByRole("button", { name: "模型" })).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "workbench.controls.uploadAttachment" })
  ).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "chat.composer.send" })
  ).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("创建能力尚未接入");
});

it.each([
  ["", false, true],
  ["   ", false, true],
  ["Hello", false, false],
  ["Hello", true, true],
])(
  "Workbench send state for text=%s disabled=%s",
  (text, disabled, unavailable) => {
    runtime.thread.isRunning = false;
    runtime.composer.text = text as string;
    render(
      <Composer
        {...base}
        disabled={disabled as boolean}
        workbenchPresentation={{
          mode: "generic_chat",
          onExitCreation: vi.fn(),
          actions: null,
        }}
      />
    );
    const send = screen.getByRole("button", { name: "chat.composer.send" });
    expect(send).toHaveClass(
      "bg-transparent",
      "text-muted-foreground",
      "disabled:text-muted-foreground"
    );
    expect(send.hasAttribute("disabled")).toBe(unavailable);
    expect(send.parentElement).toHaveClass("inline-flex");
    runtime.composer.text = "question";
  }
);

it("UT-FE-WB-004 stop remains reachable while running and input recovers when idle", async () => {
  runtime.thread.isRunning = true;
  runtime.cancel.mockReset();
  const { rerender } = render(<Composer {...base} />);
  await userEvent.click(
    screen.getByRole("button", { name: "chat.composer.stopGenerating" })
  );
  expect(runtime.cancel).toHaveBeenCalledOnce();
  runtime.thread.isRunning = false;
  rerender(<Composer {...base} />);
  expect(
    screen.queryByRole("button", { name: "chat.composer.stopGenerating" })
  ).toBeNull();
  expect(screen.getByRole("textbox")).toHaveValue("question");
  expect(
    screen.getByRole("button", { name: "chat.composer.send" })
  ).toBeEnabled();
});

it("hides unconnected ordinary-chat skill selection and retains knowledge cancellation", async () => {
  const save = vi.fn();
  const view = render(<Composer {...base} onKnowledgeScopeChange={save} />);
  expect(
    screen.queryByRole("button", { name: "chat.composer.skills" })
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: "chat.composer.plus" })
  ).toBeNull();
  await userEvent.click(
    screen.getByRole("button", { name: "chat.composer.knowledgeBase" })
  );
  expect(drawerProps.knowledge.mock.lastCall?.[0].presentation).toBe("drawer");
  await userEvent.click(
    screen.getByRole("button", { name: "Cancel knowledge" })
  );
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(save).not.toHaveBeenCalled();
  view.rerender(<Composer {...base} onKnowledgeScopeChange={save} disabled />);
  expect(
    screen.queryByRole("button", { name: "chat.composer.skills" })
  ).toBeNull();
});

it("retains the Workbench skill action through its existing callback", async () => {
  const open = vi.fn();
  render(
    <Composer
      {...base}
      workbenchPresentation={{
        mode: "generic_chat",
        actions: null,
        onExitCreation: vi.fn(),
      }}
      onOpenWorkbenchSkillPicker={open}
    />
  );
  await userEvent.click(
    screen.getByRole("button", { name: "chat.composer.skills" })
  );
  expect(open).toHaveBeenCalledOnce();
});

it("forwards knowledge drafts and previews, keeps failed saves open, and closes after successful retry", async () => {
  const scope = {
    schema_version: 1 as const,
    local: { mode: "override" as const, knowledge_ids: ["1"] },
    aidp: { mode: "disabled" as const, kds_ids: [] },
    retrieval_config: { top_k: 6 },
  };
  const save = vi
    .fn()
    .mockRejectedValueOnce(new Error("save unavailable"))
    .mockResolvedValueOnce(undefined);
  render(
    <Composer {...base} knowledgeScope={scope} onKnowledgeScopeChange={save} />
  );
  await userEvent.click(
    screen.getByRole("button", { name: "chat.composer.knowledgeBase" })
  );
  const next = { ...scope, retrieval_config: { top_k: 8 } },
    preview = { local: { knowledge_ids: ["1"], display_names: ["Alpha"] } };
  await act(async () => {
    await expect(
      drawerProps.knowledge.mock.lastCall?.[0].onConfirm(next, preview)
    ).rejects.toThrow("save unavailable");
  });
  expect(
    screen.getByRole("dialog", { name: "knowledge drawer" })
  ).toBeInTheDocument();
  expect(scope.retrieval_config).toEqual({ top_k: 6 });
  await act(async () => {
    await drawerProps.knowledge.mock.lastCall?.[0].onConfirm(next, preview);
  });
  expect(save).toHaveBeenLastCalledWith(next, preview);
  expect(screen.queryByRole("dialog")).toBeNull();
});

it("ordinary chat scopes shared parameters to the active thread and locks them while running", () => {
  runtime.threads.mainThreadId = "thread-a";
  runtime.thread.isRunning = false;
  const { rerender } = render(<Composer {...base} />);
  expect(selectorProps.mock.lastCall?.[0]).toMatchObject({
    parameterSettingsScopeKey: "thread-a",
    parameterSettingsDisabled: false,
  });
  runtime.threads.mainThreadId = "thread-b";
  runtime.thread.isRunning = true;
  rerender(<Composer {...base} />);
  expect(selectorProps.mock.lastCall?.[0]).toMatchObject({
    parameterSettingsScopeKey: "thread-b",
    parameterSettingsDisabled: true,
  });
  runtime.thread.isRunning = false;
  rerender(<Composer {...base} disabled />);
  expect(selectorProps.mock.lastCall?.[0].parameterSettingsDisabled).toBe(true);
  runtime.threads.mainThreadId = "fixture-thread";
});
