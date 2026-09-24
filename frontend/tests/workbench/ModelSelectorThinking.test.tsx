import { expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { ModelSelector } from "@/app/newchat/ui/model-selector";

const register = vi.hoisted(() =>
  vi.fn((entry: { getModelContext: () => unknown }) => {
    void entry;
    return () => undefined;
  })
);
const modelApi = vi.hoisted(() => ({
  modelContext: () => ({ register }),
}));
vi.mock("@assistant-ui/react", () => ({
  useAui: () => modelApi,
}));
vi.mock("@/components/ui/popover", () => ({
  Popover: ({ children }: { children: ReactNode }) => <>{children}</>,
  PopoverTrigger: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  PopoverContent: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
}));
vi.mock("@/components/ui/command", () => ({
  Command: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CommandInput: () => <input />,
  CommandList: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CommandEmpty: () => null,
  CommandGroup: ({ children }: { children: ReactNode }) => (
    <div>{children}</div>
  ),
  CommandItem: ({
    children,
    onSelect,
    value,
  }: {
    children: ReactNode;
    onSelect?: (value: string) => void;
    value: string;
  }) => (
    <button type="button" onClick={() => onSelect?.(value)}>
      {children}
    </button>
  ),
  CommandSeparator: () => null,
}));

const models = [{ id: "12", name: "Qwen", efforts: true }];

it("does not re-register model context when equivalent model objects rerender", () => {
  register.mockClear();
  const { rerender } = render(
    <ModelSelector models={[{ ...models[0] }]} value="12" deepThinking />
  );
  const firstRegistrationCount = register.mock.calls.length;
  rerender(
    <ModelSelector models={[{ ...models[0] }]} value="12" deepThinking />
  );
  expect(register).toHaveBeenCalledTimes(firstRegistrationCount);
});

it("shows settings even without a selected model and forwards the first selection", async () => {
  const user = userEvent.setup();
  const onValueChange = vi.fn();
  const { container } = render(
    <ModelSelector models={models} value="" onValueChange={onValueChange} />
  );

  expect(
    container.querySelector('[data-slot="model-selector-value"]')
  ).not.toHaveTextContent("Qwen");
  expect(screen.getByRole("switch")).toBeInTheDocument();
  expect(screen.getByRole("combobox")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Qwen" }));
  expect(onValueChange).toHaveBeenCalledExactlyOnceWith("12");
});

it("lets Start Chat toggle deep thinking and choose an effort in the shared selector", async () => {
  const user = userEvent.setup();
  render(<ModelSelector models={models} value="12" />);
  const thinking = screen.getByRole("switch");
  expect(thinking).toHaveAttribute("aria-checked", "false");
  await user.click(thinking);
  expect(thinking).toHaveAttribute("aria-checked", "true");
  const effort = screen.getByRole("combobox");
  await user.click(effort);
  await user.click(screen.getByText("Low"));
  expect(register.mock.lastCall?.[0].getModelContext()).toMatchObject({
    config: { modelName: "12", deepThinking: true, reasoningEffort: "low" },
  });
});

it("lets Workbench control the same selector settings", async () => {
  const user = userEvent.setup();
  const onDeepThinkingChange = vi.fn();
  const onEffortChange = vi.fn();
  render(
    <ModelSelector
      models={models}
      value="12"
      deepThinking
      effort="medium"
      onDeepThinkingChange={onDeepThinkingChange}
      onEffortChange={onEffortChange}
    />
  );
  await user.click(screen.getByRole("switch"));
  expect(onDeepThinkingChange).toHaveBeenCalledWith(false);
  await user.click(screen.getByRole("combobox"));
  await user.click(screen.getByText("High"));
  expect(onEffortChange).toHaveBeenCalledWith("high");
});
