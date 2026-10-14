import { cloneElement, type ReactElement, type ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";
import {
  render as renderComponent,
  screen,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
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
vi.mock("@/hooks/chat/useComposerResources", () => ({
  useComposerKnowledgeBases: () => ({ data: [], isLoading: false }),
  useComposerSkills: () => ({ data: [], isLoading: false }),
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
  composer: { text: "question", dictation: false, attachments: [] },
  cancel: vi.fn(),
}));
beforeEach(() => {
  runtime.thread.isRunning = false;
  runtime.composer.text = "question";
  runtime.cancel.mockReset();
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
      Input: () => (
        <textarea aria-label="正文" defaultValue={runtime.composer.text} />
      ),
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
vi.mock("@assistant-ui/react-lexical", () => ({
  LexicalComposerInput: () => null,
}));
vi.mock("@/app/newchat/adapter/remote-chat-model-adapter", () => ({
  planRegistry: { subscribe: () => () => {}, data: null },
}));
vi.mock("@/app/newchat/ui/model-selector", () => ({
  ModelSelector: () => <button>模型</button>,
}));
vi.mock("@/app/newchat/ui/attachment", () => ({
  ComposerAttachments: () => null,
  ComposerAddAttachment: () => <button>附件</button>,
}));
vi.mock(
  "@/app/newchat/assistant-ui/conversation-knowledge-scope-modal",
  () => ({
    ConversationKnowledgeScopeModal: () => null,
  })
);
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
    expect(examples.parentElement).toHaveClass("absolute", "top-full");
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
    />
  );
  const before = (left: Element, right: Element) =>
    expect(
      left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  const mode = screen.getByRole("button", {
    name: "chat.composer.executionMode",
  });
  expect(screen.queryByRole("button", { name: "Skill 创建" })).toBeNull();
  const chips = screen.getByLabelText("当前挂载资源");
  before(screen.getByRole("textbox"), chips);
  before(chips, mode);
  const labels = [
    "chat.composer.executionMode",
    "chat.composer.skills",
    "chat.composer.knowledgeBase",
    "附件",
    "模型",
  ];
  for (let index = 1; index < labels.length; index++) {
    before(
      screen.getByRole("button", { name: labels[index - 1] }),
      screen.getByRole("button", { name: labels[index] })
    );
  }
  expect(screen.getByRole("button", { name: "附件" })).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "chat.composer.send" })
  ).toBeEnabled();
  await userEvent.click(
    screen.getByRole("button", { name: "Agent · Agent A" })
  );
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
    />
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
  expect(screen.getByRole("button", { name: "附件" })).toBeEnabled();
  expect(
    screen.getByRole("button", { name: "chat.composer.send" })
  ).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("创建能力尚未接入");
});

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

it("retrieval configuration stays a draft until the composer confirms it", async () => {
  const scope = {
    schema_version: 1 as const,
    local: { mode: "override" as const, knowledge_ids: ["1", "2"] },
    aidp: { mode: "disabled" as const, kds_ids: [] },
    retrieval_config: { top_k: 6 },
  };
  const save = vi.fn().mockResolvedValue(undefined);
  render(
    <Composer
      {...base}
      newChatDesign
      knowledgeScope={scope}
      onKnowledgeScopeChange={save}
    />
  );
  await userEvent.click(
    screen.getByRole("button", { name: "chat.composer.plus" })
  );
  await userEvent.click(
    screen.getByRole("button", { name: "chat.composer.knowledge" })
  );
  await userEvent.click(
    screen.getByRole("button", { name: "agent.knowledge.button.configure" })
  );
  const dialog = within(
    screen.getByRole("dialog", { name: "agent.knowledge.configModal.title" })
  );
  const input = dialog.getByRole("spinbutton");
  expect(input).toHaveValue("6");
  await userEvent.tripleClick(input);
  await userEvent.keyboard("8");
  expect(save).not.toHaveBeenCalled();
  expect(scope.retrieval_config).toEqual({ top_k: 6 });
  await userEvent.click(dialog.getByRole("button", { name: "common.confirm" }));
  expect(save).toHaveBeenCalledExactlyOnceWith({
    ...scope,
    retrieval_config: { top_k: 8 },
  });
  expect(scope.retrieval_config).toEqual({ top_k: 6 });
});

it("canceling retrieval configuration discards edits before reopening", async () => {
  const scope = {
    schema_version: 1 as const,
    local: { mode: "override" as const, knowledge_ids: ["1"] },
    aidp: { mode: "disabled" as const, kds_ids: [] },
    retrieval_config: { top_k: 6 },
  };
  const save = vi.fn();
  render(
    <Composer
      {...base}
      newChatDesign
      knowledgeScope={scope}
      onKnowledgeScopeChange={save}
    />
  );
  const openConfig = async () => {
    await userEvent.click(
      screen.getByRole("button", { name: "chat.composer.plus" })
    );
    await userEvent.click(
      screen.getByRole("button", { name: "chat.composer.knowledge" })
    );
    await userEvent.click(
      screen.getByRole("button", { name: "agent.knowledge.button.configure" })
    );
    return within(
      screen.getByRole("dialog", { name: "agent.knowledge.configModal.title" })
    );
  };
  const dialog = await openConfig();
  await userEvent.tripleClick(dialog.getByRole("spinbutton"));
  await userEvent.keyboard("8");
  await userEvent.click(dialog.getByRole("button", { name: "common.cancel" }));
  expect(save).not.toHaveBeenCalled();
  expect(scope.retrieval_config).toEqual({ top_k: 6 });
  const reopened = await openConfig();
  expect(reopened.getByRole("spinbutton")).toHaveValue("6");
  expect(save).not.toHaveBeenCalled();
});
