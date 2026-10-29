// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

"use client";

import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useId,
  useRef,
  useState,
  createContext,
  useContext,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { automaticModelId } from "@/lib/modelSelection";
import { ConversationModelParameters, ConversationModelParameterSummary } from "@/components/model/ConversationModelParameters";
import type { ModelParameterValue } from "@/types/modelParameterSettings";
import { CheckIcon, ChevronDownIcon, CpuIcon } from "lucide-react";
import { useAui } from "@assistant-ui/react";
import { cn } from "@/lib/utils";
import { useTranslation } from "react-i18next";
import { Tooltip } from "antd";
import { resolveReasoningAvailability } from "@/lib/modelReasoning";
import type { ReasoningCapability } from "@/types/modelConfig";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";

export type ModelSelectorEffortOption = {
  id: string;
  name: string;
};

export const DEFAULT_EFFORT_OPTIONS: readonly ModelSelectorEffortOption[] = [
  { id: "auto", name: "Auto" },
  { id: "low", name: "Low" },
  { id: "medium", name: "Medium" },
  { id: "high", name: "High" },
];

export type ModelOption = {
  connectStatus?: string;
  profileSchemaVersion?: number;
  agentParameterDefaults?: Record<string, unknown>;
  id: string;
  name: string;
  description?: string;
  icon?: ReactNode;
  disabled?: boolean;
  /** Extra terms matched by ModelSelector.Search, in addition to id and name. */
  keywords?: readonly string[];
  /**
   * Reasoning effort levels the model supports. Pass `true` for the default
   * The catalog-provided effort levels, or a custom list. Omit for models
   * without configurable reasoning.
   */
  efforts?: boolean | readonly ModelSelectorEffortOption[];
  /** Default effort from the model capability profile. */
  defaultEffort?: string;
  defaultDeepThinking?: boolean;
  /** Token budget range for models whose reasoning control is numeric. */
  budgetTokens?: { min: number; max: number };
  /** Persisted model/agent budget, when one was explicitly configured. */
  defaultBudgetTokens?: number;
  /** Effective Agent/model sampling defaults, separate from turn overrides. */
  defaultSampling?: ModelParameterValue;
  reasoningCapability?: ReasoningCapability;
};

function useControllableState<T>({
  prop,
  defaultProp,
  onChange,
}: {
  prop: T | undefined;
  defaultProp: T | undefined;
  onChange: ((next: T) => void) | undefined;
}) {
  const [internal, setInternal] = useState(defaultProp);
  const isControlled = prop !== undefined;
  const value = isControlled ? prop : internal;
  // Read onChange through a ref so inline callbacks don't recreate the setter
  // (and with it the memoized context value) every render.
  const onChangeRef = useRef(onChange);
  useEffect(() => {
    onChangeRef.current = onChange;
  });
  const setValue = useCallback(
    (next: T) => {
      if (!isControlled) setInternal(next);
      onChangeRef.current?.(next);
    },
    [isControlled]
  );
  return [value, setValue] as const;
}

type ModelSelectorContextValue = {
  models: readonly ModelOption[];
  value: string | undefined;
  setValue: (value: string) => void;
  /** The model matching `value`, derived once for all sub-components. */
  selectedModel: ModelOption | undefined;
  setOpen: (open: boolean) => void;
};

const ModelSelectorContext = createContext<ModelSelectorContextValue | null>(
  null
);

function useModelSelectorContext() {
  const ctx = useContext(ModelSelectorContext);
  if (!ctx) {
    throw new Error(
      "ModelSelector sub-components must be used within ModelSelector.Root"
    );
  }
  return ctx;
}

export type ModelSelectorRootProps = {
  models: readonly ModelOption[];
  value?: string;
  defaultValue?: string;
  onValueChange?: (value: string) => void;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: ReactNode;
};

function ModelSelectorRoot({
  models,
  value: valueProp,
  defaultValue,
  onValueChange,
  open: openProp,
  defaultOpen,
  onOpenChange,
  children,
}: ModelSelectorRootProps) {
  const [value, setValue] = useControllableState({
    prop: valueProp,
    defaultProp: defaultValue ?? automaticModelId(models),
    onChange: onValueChange,
  });
  const [open, setOpen] = useControllableState({
    prop: openProp,
    defaultProp: defaultOpen ?? false,
    onChange: onOpenChange,
  });
  const selectedModel = models.find((model) => model.id === value);
  useEffect(() => {
    const fallback = automaticModelId(models);
    if (value === undefined && fallback) setValue(fallback);
  }, [models, value, setValue]);
  const contextValue = useMemo(
    () => ({ models, value, setValue, selectedModel, setOpen }),
    [models, value, setValue, selectedModel, setOpen]
  );
  return (
    <ModelSelectorContext.Provider value={contextValue}>
      <Popover open={open ?? false} onOpenChange={setOpen}>
        {children}
      </Popover>
    </ModelSelectorContext.Provider>
  );
}

export const modelSelectorTriggerVariants = cva(
  "focus-visible:ring-ring/50 flex w-fit min-w-0 cursor-pointer items-center justify-between gap-2 overflow-hidden rounded-md text-sm whitespace-nowrap transition-colors outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        outline:
          "border-input hover:bg-accent hover:text-accent-foreground border bg-transparent",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        muted: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
      },
      size: {
        default: "h-9 px-3 py-2",
        sm: "h-8 px-1 py-1.5 text-xs",
        lg: "h-10 px-4 py-2.5",
      },
    },
    defaultVariants: {
      variant: "outline",
      size: "default",
    },
  }
);

export type ModelSelectorTriggerProps = ComponentPropsWithoutRef<
  typeof PopoverTrigger
> &
  VariantProps<typeof modelSelectorTriggerVariants>;

function ModelSelectorTrigger({
  className,
  variant,
  size,
  children,
  ...props
}: ModelSelectorTriggerProps) {
  return (
    <PopoverTrigger
      data-slot="model-selector-trigger"
      data-variant={variant ?? "outline"}
      data-size={size ?? "default"}
      role="combobox"
      className={cn(modelSelectorTriggerVariants({ variant, size }), className)}
      {...props}
    >
      <CpuIcon className="size-4" />
      {children ?? <ModelSelectorValue />}
      <ChevronDownIcon className="size-4 opacity-50 ml-1.5" />
    </PopoverTrigger>
  );
}

export type ModelSelectorValueProps = {
  conversationId?: number;
  draftScope?: string;
  placeholder?: ReactNode;
  /** Show the active effort level next to the model name. */
  showEffort?: boolean;
  className?: string;
};

function ModelIcon({ children }: { children: ReactNode }) {
  return (
    <span className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4">
      {children}
    </span>
  );
}

function ModelSelectorValue({
  placeholder,
  className,
  showEffort,
  conversationId,
  draftScope,
}: ModelSelectorValueProps) {
  const { t } = useTranslation();
  const { selectedModel } = useModelSelectorContext();
  const resolvedPlaceholder =
    placeholder ?? t("chat.modelSelector.selectModel");

  if (!selectedModel) {
    return (
      <span
        data-slot="model-selector-value"
        className={cn("text-muted-foreground", className)}
      >
        {resolvedPlaceholder}
      </span>
    );
  }

  return (
    <span
      data-slot="model-selector-value"
      className={cn("flex min-w-0 items-center gap-2", className)}
    >
      {selectedModel.icon && <ModelIcon>{selectedModel.icon}</ModelIcon>}
      <span className="truncate font-medium" title={selectedModel.name}>{selectedModel.name}</span>
      {showEffort && selectedModel.profileSchemaVersion && (
        <ConversationModelParameterSummary conversationId={conversationId} draftScope={draftScope}
          modelId={Number(selectedModel.id)} agentDefaults={selectedModel.agentParameterDefaults} />
      )}
    </span>
  );
}

export type ModelSelectorContentProps = ComponentPropsWithoutRef<
  typeof PopoverContent
>;

function ModelSelectorContent({
  className,
  align = "start",
  sideOffset = 6,
  children,
  onInteractOutside,
  onEscapeKeyDown,
  ...props
}: ModelSelectorContentProps) {
  const { value } = useModelSelectorContext();

  return (
    <PopoverContent
      data-slot="model-selector-content"
      align={align}
      sideOffset={sideOffset}
      className={cn(
        "z-[1100] bg-popover/95 w-72 min-w-(--radix-popover-trigger-width) overflow-hidden rounded-xl p-0 shadow-lg backdrop-blur-sm",
        className
      )}
      {...props}
      onEscapeKeyDown={(event) => {
        event.stopPropagation();
        onEscapeKeyDown?.(event);
      }}
      onInteractOutside={(event) => {
        if (
          event.target instanceof Element &&
          (event.target.closest("[data-model-parameter-panel]") ||
            event.target.closest("[data-model-effort-popup]"))
        )
          event.preventDefault();
        onInteractOutside?.(event);
      }}
    >
      {/* Seeding cmdk with the selected id makes it the active item, which
          cmdk scrolls into view when the popover opens. */}
      <Command
        className="bg-transparent"
        {...(value !== undefined ? { defaultValue: value } : {})}
      >
        {children ?? (
          <>
            <ModelSelectorList />
          </>
        )}
      </Command>
    </PopoverContent>
  );
}

export type ModelSelectorSearchProps = ComponentPropsWithoutRef<
  typeof CommandInput
>;

function ModelSelectorSearch({
  placeholder,
  ...props
}: ModelSelectorSearchProps) {
  const { t } = useTranslation();

  return (
    <CommandInput
      data-slot="model-selector-search"
      placeholder={placeholder ?? t("chat.modelSelector.searchModels")}
      {...props}
    />
  );
}

export type ModelSelectorListProps = ComponentPropsWithoutRef<
  typeof CommandList
>;

function ModelSelectorList({
  className,
  children,
  ...props
}: ModelSelectorListProps) {
  const { models } = useModelSelectorContext();

  return (
    <CommandList
      data-slot="model-selector-list"
      className={cn(
        "[-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden",
        className
      )}
      {...props}
    >
      {children ?? (
        <>
          <ModelSelectorEmpty />
          <CommandGroup>
            {models.map((model) => (
              <ModelSelectorItem key={model.id} model={model} />
            ))}
          </CommandGroup>
        </>
      )}
    </CommandList>
  );
}

export type ModelSelectorEmptyProps = ComponentPropsWithoutRef<
  typeof CommandEmpty
>;

function ModelSelectorEmpty({ children, ...props }: ModelSelectorEmptyProps) {
  const { t } = useTranslation();

  return (
    <CommandEmpty data-slot="model-selector-empty" {...props}>
      {children ?? t("chat.modelSelector.noModels")}
    </CommandEmpty>
  );
}

export type ModelSelectorGroupProps = ComponentPropsWithoutRef<
  typeof CommandGroup
>;

function ModelSelectorGroup(props: ModelSelectorGroupProps) {
  return <CommandGroup data-slot="model-selector-group" {...props} />;
}

export type ModelSelectorSeparatorProps = ComponentPropsWithoutRef<
  typeof CommandSeparator
>;

function ModelSelectorSeparator(props: ModelSelectorSeparatorProps) {
  return <CommandSeparator data-slot="model-selector-separator" {...props} />;
}

export type ModelSelectorItemProps = Omit<
  ComponentPropsWithoutRef<typeof CommandItem>,
  "value"
> & {
  model: ModelOption;
};

function ModelSelectorItem({
  model,
  className,
  children,
  onSelect,
  ...props
}: ModelSelectorItemProps) {
  const { value, setValue, setOpen } = useModelSelectorContext();
  const isSelected = value === model.id;
  const { t } = useTranslation();

  return (
    <CommandItem
      data-slot="model-selector-item"
      value={model.id}
      keywords={[model.name, ...(model.keywords ?? [])]}
      {...(model.disabled ? { disabled: true } : undefined)}
      onSelect={(selectedValue) => {
        setValue(model.id);
        setOpen(false);
        onSelect?.(selectedValue);
      }}
      className={cn("relative gap-2 rounded-lg py-2 ps-3 pe-9", className)}
      {...props}
    >
      {children ?? (
        <>
          {model.icon && <ModelIcon>{model.icon}</ModelIcon>}
          <span className="flex min-w-0 flex-col">
            <span className="truncate font-medium">{model.name}</span>
            {model.connectStatus && model.connectStatus !== "available" && (
              <span className="text-muted-foreground text-xs">
                {t(
                  model.connectStatus === "unavailable"
                    ? "modelProfile.selectionCheckFailed"
                    : "modelProfile.selectionUnchecked"
                )}
              </span>
            )}
            {model.description && (
              <span className="text-muted-foreground truncate text-xs">
                {model.description}
              </span>
            )}
          </span>
        </>
      )}
      {isSelected && (
        <span className="absolute end-3 flex size-4 items-center justify-center">
          <CheckIcon className="size-4" />
        </span>
      )}
    </CommandItem>
  );
}

export type ModelSelectorProps = {
  conversationId?: number;
  disabled?: boolean;
  parameterSettingsScopeKey?: string;
  parameterSettingsDisabled?: boolean;
} & Omit<ModelSelectorRootProps, "children"> &
  VariantProps<typeof modelSelectorTriggerVariants> & {
    /** Render a search input above the model list. */
    searchable?: boolean;
    /** Show the active effort level next to the model name. */
    showEffort?: boolean;
    className?: string;
    contentClassName?: string;
  };

/** Registers the selection with assistant-ui's ModelContext system. The
 * context's effort is already resolved against the selected model. */
function ModelSelectorModelContext() {
  const { value } = useModelSelectorContext();
  const api = useAui();
  useEffect(() => {
    if (value === undefined) return;
    return api
      .modelContext()
      .register({ getModelContext: () => ({ config: { modelName: value } }) });
  }, [api, value]);
  return null;
}

export interface ModelSelectorAdvancedSettingsProps {
  conversationId?: number;
  scopeKey?: string;
  disabled?: boolean;
}

/** Controlled sampling settings with a scoped fallback for composed selectors. */
function ModelSelectorAdvancedSettings({
  conversationId,
  scopeKey,
  disabled = false,
}: ModelSelectorAdvancedSettingsProps) {
  const { selectedModel } = useModelSelectorContext();
  if (!selectedModel?.profileSchemaVersion) return null;
  return (
    <ConversationModelParameters
      key={`${conversationId}:${selectedModel.id}`}
      conversationId={conversationId}
      draftScope={scopeKey}
      modelId={Number(selectedModel.id)}
      agentDefaults={selectedModel.agentParameterDefaults}
      disabled={disabled}
    />
  );
}

const ModelSelectorBody = ({
  conversationId,
  disabled = false,
  parameterSettingsScopeKey,
  parameterSettingsDisabled,
  searchable,
  showEffort,
  variant,
  size,
  className,
  contentClassName,
}: ModelSelectorProps) => {
  return (
    <>
      <ModelSelectorModelContext />
      <ModelSelectorTrigger
        disabled={disabled}
        variant={variant}
        size={size}
        className={className}
      >
        <ModelSelectorValue showEffort={showEffort} conversationId={conversationId} draftScope={parameterSettingsScopeKey} />
      </ModelSelectorTrigger>
      <ModelSelectorContent align="end" className={contentClassName}>
        {searchable && <ModelSelectorSearch />}
        <ModelSelectorAdvancedSettings
          conversationId={conversationId}
          scopeKey={parameterSettingsScopeKey}
          disabled={disabled || parameterSettingsDisabled}
        />
        <ModelSelectorList />
      </ModelSelectorContent>
    </>
  );
};

const ModelSelectorImpl = ({
  conversationId,
  ...props
}: ModelSelectorProps) => (
  <ModelSelectorRoot {...props} open={props.disabled ? false : props.open}>
    <ModelSelectorBody {...props} conversationId={conversationId} />
  </ModelSelectorRoot>
);

type ModelSelectorComponent = typeof ModelSelectorImpl & {
  displayName?: string;
  Root: typeof ModelSelectorRoot;
  Trigger: typeof ModelSelectorTrigger;
  Value: typeof ModelSelectorValue;
  Content: typeof ModelSelectorContent;
  Search: typeof ModelSelectorSearch;
  List: typeof ModelSelectorList;
  Empty: typeof ModelSelectorEmpty;
  Group: typeof ModelSelectorGroup;
  Separator: typeof ModelSelectorSeparator;
  Item: typeof ModelSelectorItem;
  AdvancedSettings: typeof ModelSelectorAdvancedSettings;
};

const ModelSelector = memo(
  ModelSelectorImpl
) as unknown as ModelSelectorComponent;

ModelSelector.displayName = "ModelSelector";
ModelSelector.Root = ModelSelectorRoot;
ModelSelector.Trigger = ModelSelectorTrigger;
ModelSelector.Value = ModelSelectorValue;
ModelSelector.Content = ModelSelectorContent;
ModelSelector.Search = ModelSelectorSearch;
ModelSelector.List = ModelSelectorList;
ModelSelector.Empty = ModelSelectorEmpty;
ModelSelector.Group = ModelSelectorGroup;
ModelSelector.Separator = ModelSelectorSeparator;
ModelSelector.Item = ModelSelectorItem;
ModelSelector.AdvancedSettings = ModelSelectorAdvancedSettings;

export {
  ModelSelector,
  ModelSelectorRoot,
  ModelSelectorTrigger,
  ModelSelectorValue,
  ModelSelectorContent,
  ModelSelectorSearch,
  ModelSelectorList,
  ModelSelectorEmpty,
  ModelSelectorGroup,
  ModelSelectorSeparator,
  ModelSelectorItem,
  ModelSelectorAdvancedSettings,
};
