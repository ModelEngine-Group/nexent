'use client';

import React, { useMemo, useState, useCallback, createContext, useContext, useRef, useEffect } from 'react';
import { BarChart, Bar, LineChart, Line, PieChart, Pie, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';
import { parseA2UIMessage, type A2UIParseResult, type A2UIBlock } from './parser';
import { A2UI_OPEN_TAG, A2UI_CLOSE_TAG } from './constants';

// ---------------------------------------------------------------------------
// A2UI Form Context - shared state for interactive form components
// ---------------------------------------------------------------------------
interface A2UIFormState {
  values: Record<string, unknown>;
  registerField: (path: string, value: unknown) => void;
  unregisterField: (path: string) => void;
  updateField: (path: string, value: unknown) => void;
  getFormValues: () => Record<string, unknown>;
}

const A2UIFormContext = createContext<A2UIFormState | null>(null);

function useA2UIFormContext(): A2UIFormState | null {
  return useContext(A2UIFormContext);
}

function A2UIFormProvider({ children }: { children: React.ReactNode }) {
  const valuesRef = useRef<Record<string, unknown>>({});
  const [, forceUpdate] = useState(0);

  const registerField = useCallback((path: string, value: unknown) => {
    if (path && !(path in valuesRef.current)) {
      valuesRef.current[path] = value;
    }
  }, []);

  const unregisterField = useCallback((path: string) => {
    if (path && path in valuesRef.current) {
      delete valuesRef.current[path];
    }
  }, []);

  const updateField = useCallback((path: string, value: unknown) => {
    if (path) {
      valuesRef.current[path] = value;
      forceUpdate((n) => n + 1);
    }
  }, []);

  const getFormValues = useCallback(() => {
    return { ...valuesRef.current };
  }, []);

  const state = useMemo(() => ({
    values: valuesRef.current,
    registerField,
    unregisterField,
    updateField,
    getFormValues,
  }), [registerField, unregisterField, updateField, getFormValues]);

  return (
    <A2UIFormContext.Provider value={state}>
      {children}
    </A2UIFormContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Global A2UI action handler - ultimate fallback when neither onAction prop nor Context is available
// ---------------------------------------------------------------------------
let globalA2UIActionHandler: ((action: A2UIAction) => void) | null = null;

export function setGlobalA2UIActionHandler(handler: ((action: A2UIAction) => void) | null) {
  globalA2UIActionHandler = handler;
}

// ---------------------------------------------------------------------------
// A2UI Action Context - provides a default action handler when onAction prop is not passed
// ---------------------------------------------------------------------------
const A2UIActionContext = createContext<((action: A2UIAction) => void) | null>(null);

export function A2UIActionProvider({ onAction, children }: { onAction: (action: A2UIAction) => void; children: React.ReactNode }) {
  return (
    <A2UIActionContext.Provider value={onAction}>
      {children}
    </A2UIActionContext.Provider>
  );
}

function useA2UIActionContext(): ((action: A2UIAction) => void) | null {
  return useContext(A2UIActionContext);
}

// A2UI message type keys (matching backend constants)
const A2UI_MSG_KEYS = new Set([
  'beginRendering',
  'surfaceUpdate',
  'dataModelUpdate',
  'deleteSurface',
]);

function getMessageType(obj: Record<string, unknown>): string | null {
  if (obj.messageType && typeof obj.messageType === 'string') return obj.messageType;
  for (const key of A2UI_MSG_KEYS) {
    if (key in obj) return key;
  }
  return null;
}

function getMessagePayload(obj: Record<string, unknown>): Record<string, unknown> {
  for (const key of A2UI_MSG_KEYS) {
    if (key in obj && typeof obj[key] === 'object' && obj[key] !== null) {
      return obj[key] as Record<string, unknown>;
    }
  }
  return dataMap;
}

/**
 * Group flat valueList items (individual key-value pairs) into objects.
 * Detects repeating key patterns to determine group boundaries.
 * E.g., [{key:"avatar",...}, {key:"name",...}, {key:"role",...}, {key:"avatar",...}, ...]
 * becomes [{avatar:..., name:..., role:...}, {avatar:..., name:..., role:...}]
 */
function groupFlatListItems(rawItems: unknown[]): unknown[] {
  if (rawItems.length === 0) return rawItems;

  const firstItem = rawItems[0] as Record<string, unknown> | undefined;
  if (!firstItem) return rawItems;

  // If items have 'valueMap', they're already grouped - extract the fields
  if ('valueMap' in firstItem) {
    return rawItems.map((item) => {
      const entry = item as Record<string, unknown>;
      const valueMap = entry.valueMap as Record<string, unknown>[] | undefined;
      if (valueMap) {
        const obj: Record<string, unknown> = {};
        for (const vm of valueMap) {
          if (vm.key) {
            obj[vm.key as string] = vm.valueString || vm.valueNumber || vm.valueBoolean;
          }
        }
        return obj;
      }
      return entry;
    });
  }

  // If items have 'key' (flat key-value pairs), try to group by detecting repetition
  if ('key' in firstItem && typeof firstItem.key === 'string') {
    const firstKey = firstItem.key;
    let groupSize = rawItems.length;
    for (let i = 1; i < rawItems.length; i++) {
      const item = rawItems[i] as Record<string, unknown> | undefined;
      if (item && item.key === firstKey) {
        groupSize = i;
        break;
      }
    }

    if (groupSize < rawItems.length) {
      const grouped: Record<string, unknown>[] = [];
      for (let i = 0; i < rawItems.length; i += groupSize) {
        const group: Record<string, unknown> = {};
        for (let j = 0; j < groupSize && i + j < rawItems.length; j++) {
          const item = rawItems[i + j] as Record<string, unknown>;
          if (item && item.key) {
            const k = item.key as string;
            group[k] = item.valueString || item.valueNumber || item.valueBoolean;
          }
        }
        if (Object.keys(group).length > 0) {
          grouped.push(group);
        }
      }
      if (grouped.length > 0) return grouped;
    }
  }

  return rawItems;
}

export interface A2UIRendererProps {
  content: string;
  onAction?: (action: A2UIAction) => void;
  className?: string;
}

export interface A2UIAction {
  type: 'submit' | 'click' | 'input' | 'select';
  path?: string;
  value?: unknown;
  label?: string;
  messageType?: string;
}

/**
 * Build a flat data map from dataModelUpdate messages.
 * Traverses contents recursively to resolve paths like /form/name, /users/0/name, etc.
 */
function buildDataMap(blocks: A2UIBlock[]): Map<string, unknown> {
  const dataMap = new Map<string, unknown>();

  function traverse(contents: unknown[], prefix: string) {
    for (let i = 0; i < contents.length; i++) {
      const item = contents[i];
      if (!item || typeof item !== 'object') continue;
      const entry = item as Record<string, unknown>;
      const key = entry.key as string | undefined;
      if (!key) continue;
      const fullPath = prefix ? `${prefix}/${key}` : `/${key}`;
      if ('valueString' in entry) {
        dataMap.set(fullPath, entry.valueString);
        // Also set with leading '/' for template path resolution
        dataMap.set(`/${key}`, entry.valueString);
        dataMap.set(key, entry.valueString);
      } else if ('valueNumber' in entry) {
        dataMap.set(fullPath, entry.valueNumber);
        dataMap.set(`/${key}`, entry.valueNumber);
        dataMap.set(key, entry.valueNumber);
      } else if ('valueBoolean' in entry) {
        dataMap.set(fullPath, entry.valueBoolean);
        dataMap.set(`/${key}`, entry.valueBoolean);
        dataMap.set(key, entry.valueBoolean);
      } else if ('valueList' in entry && Array.isArray(entry.valueList)) {
        // Store the valueList as an array for List component iteration
        dataMap.set(fullPath, entry.valueList);
        dataMap.set(`/${key}`, entry.valueList);
        dataMap.set(key, entry.valueList);
        // Also traverse to index individual items
        traverse(entry.valueList, fullPath);
      } else if ('valueMap' in entry && Array.isArray(entry.valueMap)) {
        traverse(entry.valueMap, fullPath);
      }
    }
  }

  for (const block of blocks) {
    if (!block.parsed) continue;
    const payload = getMessagePayload(block.parsed);
    const msgType = getMessageType(block.parsed);
    if (msgType === 'dataModelUpdate' && Array.isArray(payload.contents)) {
      traverse(payload.contents as unknown[], '');
    }
  }

  return dataMap;
}

/**
 * Strip verbose reasoning text outside <a2ui-json> tags, keeping only the A2UI content.
 */
function stripVerboseText(content: string): string {
  const openIdx = content.indexOf(A2UI_OPEN_TAG);
  const closeIdx = content.lastIndexOf(A2UI_CLOSE_TAG);
  if (openIdx !== -1 && closeIdx !== -1) {
    return content.slice(openIdx, closeIdx + A2UI_CLOSE_TAG.length);
  }
  return content;
}

/**
 * Main A2UI Renderer component
 *
 * Renders structured A2UI JSON content as interactive React components.
 * Falls back to plain text rendering when A2UI content is not detected.
 */
export function A2UIRenderer({ content, onAction, className = '' }: A2UIRendererProps) {
  const actionFromContext = useA2UIActionContext();
  const effectiveOnAction = onAction ?? actionFromContext ?? globalA2UIActionHandler ?? undefined;

  const cleanContent = useMemo(() => stripVerboseText(content), [content]);
  const parsed = useMemo(() => parseA2UIMessage(cleanContent), [cleanContent]);
  const dataMap = useMemo(() => buildDataMap(parsed.blocks), [parsed.blocks]);

  const renderId = useMemo(() => Math.random().toString(36).slice(2, 8), []);
  console.log(`[A2UI_RENDERER:${renderId}] entry: onAction type:`, typeof effectiveOnAction, 'isA2UI:', parsed.isA2UI, 'blocks:', parsed.blocks.length);
  if (typeof effectiveOnAction !== 'function') {
    console.log(`[A2UI_RENDERER:${renderId}] onAction is NOT a function! Call stack:\n`, new Error('A2UI_RENDERER no onAction').stack);
  }

  if (!parsed.isA2UI) {
    return <div className={className}>{cleanContent}</div>;
  }

  return (
    <A2UIFormProvider>
      <div className={`a2ui-container ${className}`}>
        {parsed.blocks.length === 0 ? (
          <A2UISchemaRenderer
            schema={parsed.schema}
            onAction={effectiveOnAction}
            dataMap={dataMap}
          />
        ) : (
          parsed.blocks.map((block, idx) => (
            <A2UIBlockRenderer
              key={`a2ui-block-${idx}`}
              block={block}
              onAction={effectiveOnAction}
              defaultSchema={parsed.schema}
              dataMap={dataMap}
            />
          ))
        )}
      </div>
    </A2UIFormProvider>
  );
}

interface A2UIBlockRendererProps {
  block: A2UIBlock;
  onAction?: (action: A2UIAction) => void;
  defaultSchema: Record<string, unknown> | null;
  dataMap: Map<string, unknown>;
}

function A2UIBlockRenderer({ block, onAction, defaultSchema, dataMap }: A2UIBlockRendererProps) {
  if (!block.parsed) {
    return <div className="text-sm text-muted-foreground">{block.content}</div>;
  }

  const parsed = block.parsed as Record<string, unknown>;
  const messageType = getMessageType(parsed);
  const payload = getMessagePayload(parsed);

  // Lifecycle messages
  if (messageType === 'beginRendering') {
    const schema = payload.schema as Record<string, unknown> | undefined;
    return (
      <A2UIBeginRenderingBlock
        schema={schema || defaultSchema}
        dataMap={dataMap}
      />
    );
  }

  if (messageType === 'endRendering') {
    return <A2UIEndRenderingBlock />;
  }

  // surfaceUpdate - render components
  if (messageType === 'surfaceUpdate') {
    const components = payload.components as Record<string, unknown>[] | undefined;
    if (components && components.length > 0) {
      return (
        <A2UIComponentsRenderer
          components={components}
          onAction={onAction}
          defaultSchema={defaultSchema}
          dataMap={dataMap}
        />
      );
    }
    return null;
  }

  // dataModelUpdate - handled internally, no visible render
  if (messageType === 'dataModelUpdate') {
    return null;
  }

  // deleteSurface
  if (messageType === 'deleteSurface') {
    return null;
  }

  // Schema-only rendering (no messageType)
  if (block.type === 'schema') {
    return (
      <A2UISchemaRenderer
        schema={parsed}
        onAction={onAction}
      />
    );
  }

  // Unknown format - try to render as generic JSON
  return <pre className="text-xs bg-muted p-2 rounded overflow-auto">{JSON.stringify(parsed, null, 2)}</pre>;
}

function A2UIBeginRenderingBlock({ schema, dataMap }: { schema: Record<string, unknown> | null; dataMap: Map<string, unknown> }) {
  if (!schema) return null;
  return (
    <div className="a2ui-begin-rendering rounded-lg border border-border bg-card p-4">
      <div className="text-xs text-muted-foreground mb-2">A2UI Schema v{getSchemaVersion(schema)}</div>
      <A2UISchemaRenderer schema={schema} dataMap={dataMap} />
    </div>
  );
}

/**
 * Renders A2UI components from a surfaceUpdate message.
 * Each component has: {id, component: {type, props}}
 */
interface A2UIComponentNode {
  id: string;
  type: string;
  props: Record<string, unknown>;
  childIds: string[];
}

interface A2UIComponentsRendererProps {
  components: Record<string, unknown>[];
  onAction?: (action: A2UIAction) => void;
  defaultSchema: Record<string, unknown> | null;
  dataMap: Map<string, unknown>;
}

function A2UIComponentsRenderer({ components, onAction, defaultSchema, dataMap }: A2UIComponentsRendererProps) {
  // Build a map of component nodes
  const nodeMap = useMemo(() => {
    const map = new Map<string, A2UIComponentNode>();
    for (const comp of components) {
      const id = comp.id as string;
      const inner = comp.component as Record<string, unknown> | undefined;
      if (!id || !inner) continue;
      const type = (inner.type as string) || 'Text';
      const props = (inner.props as Record<string, unknown>) || {};
      // Collect child component IDs from explicitList, single child, or template
      const childIds: string[] = [];
      const child = props.child as string | undefined;
      if (child) childIds.push(child);
      const template = props.template as string | undefined;
      if (template) childIds.push(template);
      const children = props.children as Record<string, unknown> | undefined;
      if (children?.template && typeof children.template === 'string') {
        childIds.push(children.template as string);
      }
      if (children?.explicitList && Array.isArray(children.explicitList)) {
        childIds.push(...(children.explicitList as string[]));
      }
      map.set(id, { id, type, props, childIds });
    }
    return map;
  }, [components]);

  // Find root components (not referenced as children by any other component)
  const rootIds = useMemo(() => {
    const allIds = new Set(nodeMap.keys());
    for (const node of nodeMap.values()) {
      for (const childId of node.childIds) {
        allIds.delete(childId);
      }
    }
    return Array.from(allIds);
  }, [nodeMap]);

  if (rootIds.length === 0) return null;

  return (
    <div className="a2ui-components flex flex-col gap-3">
      {rootIds.map((id) => (
        <A2UIComponentNodeRenderer
          key={id}
          nodeId={id}
          nodeMap={nodeMap}
          onAction={onAction}
          defaultSchema={defaultSchema}
          dataMap={dataMap}
        />
      ))}
    </div>
  );
}

interface A2UIComponentNodeRendererProps {
  nodeId: string;
  nodeMap: Map<string, A2UIComponentNode>;
  onAction?: (action: A2UIAction) => void;
  defaultSchema: Record<string, unknown> | null;
  dataMap: Map<string, unknown>;
}

// ---------------------------------------------------------------------------
// Module-level utility functions (no Hooks, safe to call from any context)
// ---------------------------------------------------------------------------

/** Extract the data model path from component props for form field binding. */
function extractFieldPath(p: Record<string, unknown>, dataMap: Map<string, unknown>): string {
  // Use label as the primary display key (Chinese-friendly)
  if (p.label) {
    const label = resolveTextValue(p.label, dataMap);
    if (label) return label;
  }
  // Try props.path (explicit path object)
  if (p.path && typeof p.path === 'object') {
    const path = (p.path as Record<string, unknown>).path;
    if (typeof path === 'string' && path) return path;
  }
  // Try props.text.path (TextField binding)
  if (p.text && typeof p.text === 'object') {
    const path = (p.text as Record<string, unknown>).path;
    if (typeof path === 'string' && path) return path;
  }
  // Try props.value.path (CheckBox, ChoicePicker, Slider, DateTimeInput)
  if (p.value && typeof p.value === 'object') {
    const path = (p.value as Record<string, unknown>).path;
    if (typeof path === 'string' && path) return path;
  }
  // Try props.name as fallback
  if (typeof p.name === 'string' && p.name) return p.name;
  return '';
}

/** Resolve text from literalString, path, or direct string value. */
function resolveTextValue(textValue: unknown, dataMap: Map<string, unknown>): string {
  // Clean up backtick-wrapped values from agent output
  const cleanValue = (val: string): string => {
    return val.replace(/^\s*`+|`+\s*$/g, '').trim();
  };
  if (typeof textValue === 'string') return cleanValue(textValue);
  if (typeof textValue === 'number' || typeof textValue === 'boolean') return String(textValue);
  if (textValue && typeof textValue === 'object') {
    const obj = textValue as Record<string, unknown>;
    if (typeof obj.literalString === 'string') return cleanValue(obj.literalString);
    if (typeof obj.literal === 'string') return cleanValue(obj.literal);
    if (typeof obj.path === 'string') {
      const path = obj.path as string;
      const value = dataMap.get(path);
      if (value !== undefined) return cleanValue(String(value));
      return '';
    }
  }
  return '';
}

/** Shared props for interactive form components */
interface A2UIInteractiveProps {
  node: A2UIComponentNode;
  nodeMap: Map<string, A2UIComponentNode>;
  onAction?: (action: A2UIAction) => void;
  defaultSchema: Record<string, unknown> | null;
  dataMap: Map<string, unknown>;
  renderChildren: () => React.ReactNode;
}

function A2UIComponentNodeRenderer({ nodeId, nodeMap, onAction, defaultSchema, dataMap }: A2UIComponentNodeRendererProps) {
  const node = nodeMap.get(nodeId);
  if (!node) return null;

  const { type, props } = node;

  const renderChildren = () => {
    if (node.childIds.length === 0) return null;
    return node.childIds.map((childId) => (
      <A2UIComponentNodeRenderer
        key={childId}
        nodeId={childId}
        nodeMap={nodeMap}
        onAction={onAction}
        defaultSchema={defaultSchema}
        dataMap={dataMap}
      />
    ));
  };

  const title = resolveTextValue(props.title, dataMap);
  const subtitle = props.subtitle ? resolveTextValue(props.subtitle, dataMap) : '';
  const text = resolveTextValue(props.text, dataMap);
  const url = resolveTextValue(props.url, dataMap);
  const label = resolveTextValue(props.label, dataMap);
  const gap = (props.gap as number) || 8;

  const interactiveProps: A2UIInteractiveProps = { node, nodeMap, onAction, defaultSchema, dataMap, renderChildren };

  switch (type) {
    case 'Card':
      return (
        <div className="a2ui-card rounded-lg border border-border bg-card overflow-hidden">
          {title && (
            <div className="px-4 pt-4 pb-0">
              <h3 className="text-base font-semibold">{title}</h3>
              {subtitle && <p className="text-sm text-muted-foreground mt-1">{subtitle}</p>}
            </div>
          )}
          <div className="p-4">{renderChildren()}</div>
        </div>
      );

    case 'Column':
      return (
        <div className="a2ui-column flex flex-col" style={{ gap: `${gap}px` }}>
          {renderChildren()}
        </div>
      );

    case 'Row':
      return (
        <div className="a2ui-row flex flex-row items-center" style={{ gap: `${gap}px` }}>
          {renderChildren()}
        </div>
      );

    case 'Text': {
      const usageHint = props.usageHint as string | undefined;
      if (usageHint === 'h1') return <h1 className="text-2xl font-bold">{text}</h1>;
      if (usageHint === 'h2') return <h2 className="text-xl font-semibold">{text}</h2>;
      if (usageHint === 'h3') return <h3 className="text-lg font-medium">{text}</h3>;
      if (usageHint === 'caption') return <span className="text-xs text-muted-foreground">{text}</span>;
      return <span className="text-sm">{text}</span>;
    }

    case 'Button':
      return <A2UIButtonComponent {...interactiveProps} />;

    case 'TextField':
      return <A2UITextFieldComponent {...interactiveProps} />;

    case 'CheckBox':
      return <A2UICheckBoxComponent {...interactiveProps} />;

    case 'ChoicePicker':
      return <A2UIChoicePickerComponent {...interactiveProps} />;

    case 'Slider':
      return <A2UISliderComponent {...interactiveProps} />;

    case 'DateTimeInput':
      return <A2UIDateTimeInputComponent {...interactiveProps} />;

    case 'Image':
      return url ? (
        <img src={url} alt={title} className="a2ui-image rounded-md max-w-full" />
      ) : null;

    case 'Divider':
      return <hr className="my-2 border-border" />;

    case 'Chart':
      return <A2UIChart {...props} dataMap={dataMap} />;

    case 'LineChart':
    case 'BarChart':
    case 'PieChart':
      return <A2UIChart {...props} chartType={type.replace('Chart', '').toLowerCase()} dataMap={dataMap} />;

    case 'List': {
      // Get the items data from the dataMap
      // items can be a string path "/users" or an object {path: "/users"}
      let itemsPath: string | undefined;
      if (typeof props.items === 'string') {
        itemsPath = props.items;
      } else if (props.items && typeof props.items === 'object') {
        itemsPath = (props.items as Record<string, unknown>).path as string | undefined;
      }
      let items: unknown[] | null = null;
      if (itemsPath) {
        const raw = dataMap.get(itemsPath);
        if (Array.isArray(raw)) {
          items = groupFlatListItems(raw);
        }
      }
      // If we have items and a template, render each item
      if (items && items.length > 0 && node.childIds.length > 0) {
        const templateId = node.childIds[0];
        return (
          <div className="a2ui-list flex flex-col gap-2">
            {items.map((item, idx) => {
              // Create a temporary dataMap with the item's data for path resolution
              const itemDataMap = new Map(dataMap);
              if (item && typeof item === 'object' && !Array.isArray(item)) {
                const obj = item as Record<string, unknown>;
                for (const [k, v] of Object.entries(obj)) {
                  itemDataMap.set(`/${k}`, v);
                  itemDataMap.set(k, v);
                }
              }
              return (
                <A2UIComponentNodeRenderer
                  key={`list-item-${idx}`}
                  nodeId={templateId}
                  nodeMap={nodeMap}
                  onAction={onAction}
                  defaultSchema={defaultSchema}
                  dataMap={itemDataMap}
                />
              );
            })}
          </div>
        );
      }
      // Fallback: render children once
      return (
        <div className="a2ui-list">
          {renderChildren()}
        </div>
      );
    }
    case 'Tabs':
      return (
        <div className="a2ui-list">
          {renderChildren()}
        </div>
      );

    default:
      return (
        <div className="a2ui-unknown">
          {renderChildren() || <span className="text-sm text-muted-foreground">[{type}]</span>}
        </div>
      );
  }
}

// ---------------------------------------------------------------------------
// Interactive form sub-components (each calls Hooks at top level, no switch/case violation)
// ---------------------------------------------------------------------------

function A2UIButtonComponent({ node, nodeMap, onAction, defaultSchema, dataMap, renderChildren }: A2UIInteractiveProps) {
  const { props } = node;
  const formCtx = useA2UIFormContext();
  const actionFromContext = useA2UIActionContext();
  const effectiveOnAction = onAction ?? actionFromContext ?? globalA2UIActionHandler ?? undefined;
  const actionName = (props.action as Record<string, unknown> | undefined)?.name as string;
  const actionLabel = (props.action as Record<string, unknown> | undefined)?.label as string || '';
  const isSubmit = actionName === 'submit' || (actionName && actionName.startsWith('submit')) || (props.primary as boolean) === true;
  const text = resolveTextValue(props.text, dataMap);
  const label = resolveTextValue(props.label, dataMap);

  const handleClick = useCallback(() => {
    const formValues = formCtx?.getFormValues() || {};
    const handler = onAction ?? actionFromContext ?? globalA2UIActionHandler ?? undefined;
    console.log('[A2UI_BUTTON] handleClick called, actionName:', actionName, 'formValues:', formValues, 'onAction defined:', typeof handler === 'function');
    handler?.({
      type: isSubmit ? 'submit' : 'click',
      value: actionName,
      label: actionLabel,
      messageType: 'button',
      path: JSON.stringify(formValues),
    });
  }, [effectiveOnAction, actionName, formCtx, isSubmit]);

  return (
    <button
      type="button"
      className="a2ui-button inline-flex items-center px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 transition-colors cursor-pointer"
      onClick={handleClick}
    >
      {renderChildren() || text || label || 'Button'}
    </button>
  );
}

function A2UITextFieldComponent({ node, nodeMap, onAction, defaultSchema, dataMap, renderChildren }: A2UIInteractiveProps) {
  const { props } = node;
  const formCtx = useA2UIFormContext();
  const actionFromContext = useA2UIActionContext();
  const effectiveOnAction = onAction ?? actionFromContext ?? undefined;
  const initialValue = resolveTextValue(props.text, dataMap) || resolveTextValue(props.value, dataMap) || '';
  const [fieldValue, setFieldValue] = useState(initialValue);
  const fieldPath = extractFieldPath(props, dataMap);
  const label = resolveTextValue(props.label, dataMap);
  const placeholder = resolveTextValue(props.text, dataMap);

  useEffect(() => {
    formCtx?.registerField(fieldPath, initialValue);
  }, [fieldPath]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setFieldValue(e.target.value);
    formCtx?.updateField(fieldPath, e.target.value);
    effectiveOnAction?.({ type: 'input', path: fieldPath, value: e.target.value });
  }, [effectiveOnAction, fieldPath, formCtx]);

  return (
    <div className="a2ui-textfield flex flex-col gap-1">
      {label && <label className="text-sm font-medium">{label}</label>}
      <input
        type="text"
        className="border border-border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-primary/20"
        placeholder={placeholder}
        value={fieldValue}
        onChange={handleChange}
      />
    </div>
  );
}

function A2UICheckBoxComponent({ node, nodeMap, onAction, defaultSchema, dataMap, renderChildren }: A2UIInteractiveProps) {
  const { props } = node;
  const formCtx = useA2UIFormContext();
  const actionFromContext = useA2UIActionContext();
  const effectiveOnAction = onAction ?? actionFromContext ?? undefined;
  const initialChecked = props.checked === true || props.value === true;
  const [checked, setChecked] = useState(initialChecked);
  const fieldPath = extractFieldPath(props, dataMap);
  const label = resolveTextValue(props.label, dataMap);

  useEffect(() => {
    formCtx?.registerField(fieldPath, initialChecked);
  }, [fieldPath]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setChecked(e.target.checked);
    formCtx?.updateField(fieldPath, e.target.checked);
    effectiveOnAction?.({ type: 'input', path: fieldPath, value: e.target.checked });
  }, [effectiveOnAction, fieldPath, formCtx]);

  return (
    <div className="a2ui-checkbox flex items-center gap-2">
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-border cursor-pointer"
        checked={checked}
        onChange={handleChange}
      />
      {label && <label className="text-sm cursor-pointer">{label}</label>}
    </div>
  );
}

function A2UIChoicePickerComponent({ node, nodeMap, onAction, defaultSchema, dataMap, renderChildren }: A2UIInteractiveProps) {
  const { props } = node;
  const formCtx = useA2UIFormContext();
  const actionFromContext = useA2UIActionContext();
  const effectiveOnAction = onAction ?? actionFromContext ?? undefined;
  const initialValue = resolveTextValue(props.value, dataMap) || '';
  const [selectedValue, setSelectedValue] = useState(initialValue);
  const options = (props.options as Array<{ label: string; value: string }>) || [];
  const fieldPath = extractFieldPath(props, dataMap);
  const label = resolveTextValue(props.label, dataMap);

  useEffect(() => {
    formCtx?.registerField(fieldPath, initialValue);
  }, [fieldPath]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = useCallback((value: string) => {
    setSelectedValue(value);
    formCtx?.updateField(fieldPath, value);
    effectiveOnAction?.({ type: 'select', path: fieldPath, value });
  }, [effectiveOnAction, fieldPath, formCtx]);

  return (
    <div className="a2ui-choice-picker flex flex-col gap-1">
      {label && <label className="text-sm font-medium">{label}</label>}
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`px-3 py-1.5 rounded-md text-sm border transition-colors cursor-pointer ${
              selectedValue === opt.value
                ? 'bg-primary text-primary-foreground border-primary'
                : 'bg-background border-border hover:bg-accent'
            }`}
            onClick={() => handleChange(opt.value)}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function A2UISliderComponent({ node, nodeMap, onAction, defaultSchema, dataMap, renderChildren }: A2UIInteractiveProps) {
  const { props } = node;
  const formCtx = useA2UIFormContext();
  const actionFromContext = useA2UIActionContext();
  const effectiveOnAction = onAction ?? actionFromContext ?? undefined;
  const min = (props.min as number) || 0;
  const max = (props.max as number) || 100;
  const step = (props.step as number) || 1;
  const initialValue = (props.value as number) || min;
  const [sliderValue, setSliderValue] = useState(initialValue);
  const fieldPath = extractFieldPath(props, dataMap);
  const label = resolveTextValue(props.label, dataMap);

  useEffect(() => {
    formCtx?.registerField(fieldPath, initialValue);
  }, [fieldPath]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const val = Number(e.target.value);
    setSliderValue(val);
    formCtx?.updateField(fieldPath, val);
    effectiveOnAction?.({ type: 'input', path: fieldPath, value: val });
  }, [effectiveOnAction, fieldPath, formCtx]);

  return (
    <div className="a2ui-slider flex flex-col gap-1">
      {label && <label className="text-sm font-medium">{label} ({sliderValue})</label>}
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={sliderValue}
        onChange={handleChange}
        className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
      />
    </div>
  );
}

function A2UIDateTimeInputComponent({ node, nodeMap, onAction, defaultSchema, dataMap, renderChildren }: A2UIInteractiveProps) {
  const { props } = node;
  const formCtx = useA2UIFormContext();
  const actionFromContext = useA2UIActionContext();
  const effectiveOnAction = onAction ?? actionFromContext ?? undefined;
  const initialValue = resolveTextValue(props.value, dataMap) || '';
  const [dateValue, setDateValue] = useState(initialValue);
  const fieldPath = extractFieldPath(props, dataMap);
  const label = resolveTextValue(props.label, dataMap);

  useEffect(() => {
    formCtx?.registerField(fieldPath, initialValue);
  }, [fieldPath]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setDateValue(e.target.value);
    formCtx?.updateField(fieldPath, e.target.value);
    effectiveOnAction?.({ type: 'input', path: fieldPath, value: e.target.value });
  }, [effectiveOnAction, fieldPath, formCtx]);

  return (
    <div className="a2ui-datetime flex flex-col gap-1">
      {label && <label className="text-sm font-medium">{label}</label>}
      <input
        type="datetime-local"
        className="border border-border rounded-md px-3 py-2 text-sm bg-background focus:outline-none focus:ring-2 focus:ring-primary/20"
        value={dateValue}
        onChange={handleChange}
      />
    </div>
  );
}

function A2UIEndRenderingBlock() {
  return (
    <div className="a2ui-end-rendering text-xs text-muted-foreground text-center py-2">
      ▇▇▇ End of structured response ▇▇▇
    </div>
  );
}

interface A2UIChartProps {
  title?: unknown;
  chartType?: string;
  xAxis?: string;
  series?: unknown;
  data?: unknown;
  dataMap?: Map<string, unknown>;
  [key: string]: unknown;
}

/**
 * Extract chart data from dataMap using series key configuration.
 * Looks for valueList entries in the dataMap and groups flat key-value
 * items into object arrays suitable for recharts.
 */
function extractChartData(
  dataMap: Map<string, unknown>,
  xAxis: string,
  series: Array<Record<string, unknown>>
): Array<Record<string, unknown>> {
  // Collect all configured keys (xAxis + series data keys)
  const configuredKeys = new Set<string>();
  configuredKeys.add(xAxis);
  for (const s of series) {
    const key = (s.key as string) || (s.name as string) || '';
    if (key) configuredKeys.add(key);
  }

  // Look for a valueList in the dataMap under common paths
  const candidatePaths = ['/data', '/chartData', '/items'];
  for (const path of candidatePaths) {
    const raw = dataMap.get(path);
    if (Array.isArray(raw) && raw.length > 0) {
      const grouped = groupFlatListItems(raw);
      return grouped as Array<Record<string, unknown>>;
    }
  }

  // Fallback: iterate through dataMap to find any array values that
  // contain key-value pairs matching chart data structure
  for (const [, value] of dataMap) {
    if (Array.isArray(value) && value.length > 0) {
      const first = value[0];
      if (first && typeof first === 'object' && ('key' in first || 'valueMap' in first)) {
        const grouped = groupFlatListItems(value);
        if (grouped.length > 0 && grouped[0] && typeof grouped[0] === 'object') {
          // Check that at least some configured keys are present
          const objKeys = Object.keys(grouped[0] as Record<string, unknown>);
          const hasMatch = objKeys.some((k) => configuredKeys.has(k));
          if (hasMatch) {
            return grouped as Array<Record<string, unknown>>;
          }
        }
      }
    }
  }

  return [];
}

function A2UIChart(props: A2UIChartProps) {
  const title = typeof props.title === 'string' ? props.title
    : (props.title as Record<string, unknown> | undefined)?.literalString as string || '';
  const chartType = (props.chartType as string) || 'line';
  const xAxis = (props.xAxis as string) || 'date';
  const series = (props.series as Array<Record<string, unknown>>) || [];
  const dataMap = props.dataMap;

  // Extract chart data from dataMap using series key configuration
  const chartData = useMemo(() => {
    if (!dataMap || dataMap.size === 0) return [];
    return extractChartData(dataMap, xAxis, series);
  }, [dataMap, xAxis, series]);

  return (
    <div className="a2ui-chart rounded-lg border border-border bg-card p-4">
      {title && <h4 className="text-sm font-semibold mb-3">{title}</h4>}
      <A2UISimpleChart chartType={chartType} series={series} xAxis={xAxis} chartData={chartData} />
    </div>
  );
}

interface A2UISimpleChartProps {
  chartType: string;
  series: Array<Record<string, unknown>>;
  xAxis: string;
  chartData: Array<Record<string, unknown>>;
}

function A2UISimpleChart({ chartType, series, xAxis, chartData }: A2UISimpleChartProps) {
  const colors = series.map((s) => (s.color as string) || '#3b82f6');
  const names = series.map((s) => (s.name as string) || (s.key as string) || 'Value');
  const dataKeys = series.map((s) => (s.key as string) || (s.name as string) || 'value');

  if (chartData.length === 0) {
    return (
      <div className="text-sm text-muted-foreground text-center py-8">
        Chart data not available
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {/* Legend */}
      <div className="flex gap-4 mb-2">
        {series.map((s, i) => (
          <div key={i} className="flex items-center gap-1.5">
            <span
              className="inline-block w-3 h-3 rounded-full"
              style={{ backgroundColor: colors[i] }}
            />
            <span className="text-xs text-muted-foreground">{names[i]}</span>
          </div>
        ))}
      </div>
      {/* Chart */}
      <ResponsiveContainer width="100%" height={300}>
        {chartType === 'bar' ? (
          <BarChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={xAxis} />
            <YAxis />
            <Tooltip />
            <Legend />
            {dataKeys.map((key, i) => (
              <Bar key={key} dataKey={key} fill={colors[i % colors.length]} />
            ))}
          </BarChart>
        ) : chartType === 'pie' ? (
          <PieChart>
            <Pie
              data={chartData}
              dataKey={dataKeys[0]}
              nameKey={xAxis}
              cx="50%"
              cy="50%"
              outerRadius={100}
              label
            >
              {chartData.map((_entry, index) => (
                <Cell key={`cell-${index}`} fill={colors[index % colors.length]} />
              ))}
            </Pie>
            <Tooltip />
            <Legend />
          </PieChart>
        ) : (
          <LineChart data={chartData}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey={xAxis} />
            <YAxis />
            <Tooltip />
            <Legend />
            {dataKeys.map((key, i) => (
              <Line key={key} type="monotone" dataKey={key} stroke={colors[i % colors.length]} />
            ))}
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

interface A2UIBatchBlockProps {
  items: Record<string, unknown>[];
  onAction?: (action: A2UIAction) => void;
  defaultSchema: Record<string, unknown> | null;
}

function A2UIBatchBlock({ items, onAction, defaultSchema }: A2UIBatchBlockProps) {
  if (items.length === 0) return null;

  return (
    <div className="a2ui-batch flex flex-col gap-3">
      {items.map((item, idx) => (
        <A2UIItemRenderer
          key={`a2ui-item-${idx}`}
          item={item}
          onAction={onAction}
          schema={defaultSchema}
        />
      ))}
    </div>
  );
}

interface A2UIItemRendererProps {
  item: Record<string, unknown>;
  onAction?: (action: A2UIAction) => void;
  schema: Record<string, unknown> | null;
}

function A2UIItemRenderer({ item, onAction, schema }: A2UIItemRendererProps) {
  const type = (item.type as string) || 'div';
  const path = item.path as string | undefined;
  const props = (item.props as Record<string, unknown>) || {};
  const children = item.children as Record<string, unknown>[] | undefined;

  switch (type) {
    case 'heading':
      return <A2UIHeading item={item} />;
    case 'paragraph':
    case 'text':
      return <A2UIText item={item} />;
    case 'button':
      return <A2UIButton item={item} onAction={onAction} path={path} />;
    case 'input':
      return <A2UIInput item={item} onAction={onAction} path={path} />;
    case 'select':
      return <A2UISelect item={item} onAction={onAction} path={path} />;
    case 'list':
      return <A2UIList item={item} onAction={onAction} schema={schema} />;
    case 'card':
    case 'container':
      return <A2UIContainer item={item} onAction={onAction} schema={schema} />;
    case 'image':
      return <A2UIImage item={item} />;
    case 'table':
      return <A2UITable item={item} />;
    case 'divider':
      return <hr className="my-2 border-border" />;
    case 'spacer':
      return <div className="h-4" />;
    case 'badge':
      return <A2UIBadge item={item} />;
    case 'code':
      return <A2UICode item={item} />;
    default:
      // Generic container for unknown types
      return (
        <div className="a2ui-generic">
          {children?.map((child, idx) => (
            <A2UIItemRenderer
              key={`generic-child-${idx}`}
              item={child}
              onAction={onAction}
              schema={schema}
            />
          )) || <pre className="text-xs bg-muted p-2 rounded">{JSON.stringify(item, null, 2)}</pre>}
        </div>
      );
  }
}

function A2UIHeading({ item }: { item: Record<string, unknown> }) {
  const props = (item.props as Record<string, unknown>) || {};
  const level = (props.level as number) || 2;
  const text = props.text || '';
  const Tag = `h${Math.min(level, 6)}` as keyof JSX.IntrinsicElements;
  const className = level === 1 ? 'text-2xl font-bold' : level === 2 ? 'text-xl font-semibold' : 'text-lg font-medium';
  return React.createElement(Tag, { className }, text);
}

function A2UIText({ item }: { item: Record<string, unknown> }) {
  const props = (item.props as Record<string, unknown>) || {};
  const text = props.text || props.children || '';
  return <p className="text-sm leading-relaxed">{text}</p>;
}

function A2UIButton({ item, onAction, path }: { item: Record<string, unknown>; onAction?: (a: A2UIAction) => void; path?: string }) {
  const props = (item.props as Record<string, unknown>) || {};
  const label = props.label || props.text || 'Click';
  const variant = (props.variant as string) || 'default';
  const disabled = props.disabled as boolean | undefined;
  const onClick = useCallback(() => {
    onAction?.({ type: 'click', path, messageType: 'button' });
  }, [onAction, path]);

  const variantClass = variant === 'primary'
    ? 'bg-primary text-primary-foreground hover:bg-primary/90'
    : variant === 'secondary'
    ? 'bg-secondary text-secondary-foreground hover:bg-secondary/90'
    : variant === 'destructive'
    ? 'bg-destructive text-destructive-foreground hover:bg-destructive/90'
    : 'bg-background border border-input hover:bg-accent';

  return (
    <button
      className={`inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors px-4 py-2 ${variantClass} ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
      disabled={disabled}
      onClick={onClick}
    >
      {label}
    </button>
  );
}

function A2UIInput({ item, onAction, path }: { item: Record<string, unknown>; onAction?: (a: A2UIAction) => void; path?: string }) {
  const props = (item.props as Record<string, unknown>) || {};
  const label = props.label as string | undefined;
  const placeholder = props.placeholder as string | undefined;
  const type = (props.type as string) || 'text';
  const [value, setValue] = useState(props.defaultValue as string || '');

  const onChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setValue(e.target.value);
    onAction?.({ type: 'input', path, value: e.target.value, messageType: 'input' });
  }, [onAction, path]);

  return (
    <div className="flex flex-col gap-1">
      {label && <label className="text-sm font-medium">{label}</label>}
      <input
        type={type}
        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        placeholder={placeholder}
        value={value}
        onChange={onChange}
      />
    </div>
  );
}

function A2UISelect({ item, onAction, path }: { item: Record<string, unknown>; onAction?: (a: A2UIAction) => void; path?: string }) {
  const props = (item.props as Record<string, unknown>) || {};
  const label = props.label as string | undefined;
  const options = (props.options as Array<{ label: string; value: string }>) || [];
  const [value, setValue] = useState(props.defaultValue as string || '');

  const onChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    setValue(e.target.value);
    onAction?.({ type: 'select', path, value: e.target.value, messageType: 'select' });
  }, [onAction, path]);

  return (
    <div className="flex flex-col gap-1">
      {label && <label className="text-sm font-medium">{label}</label>}
      <select
        className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        value={value}
        onChange={onChange}
      >
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
    </div>
  );
}

function A2UIList({ item, onAction, schema }: { item: Record<string, unknown>; onAction?: (a: A2UIAction) => void; schema: Record<string, unknown> | null }) {
  const props = (item.props as Record<string, unknown>) || {};
  const items = props.items as Record<string, unknown>[] | undefined;
  const ordered = props.ordered as boolean || false;

  if (!items || items.length === 0) return null;

  const ListTag = ordered ? 'ol' : 'ul';
  const listClass = ordered ? 'list-decimal pl-6 space-y-1' : 'list-disc pl-6 space-y-1';

  return (
    <ListTag className={listClass}>
      {items.map((li, idx) => (
        <li key={`li-${idx}`} className="text-sm">
          {typeof li === 'string' ? li : (
            <A2UIItemRenderer item={li} onAction={onAction} schema={schema} />
          )}
        </li>
      ))}
    </ListTag>
  );
}

function A2UIContainer({ item, onAction, schema }: { item: Record<string, unknown>; onAction?: (a: A2UIAction) => void; schema: Record<string, unknown> | null }) {
  const props = (item.props as Record<string, unknown>) || {};
  const children = item.children as Record<string, unknown>[] | undefined;
  const gap = (props.gap as string) || 'normal';
  const gapClass = gap === 'small' ? 'gap-2' : gap === 'large' ? 'gap-6' : 'gap-4';
  const direction = (props.direction as string) || 'column';
  const flexClass = direction === 'row' ? 'flex flex-row' : 'flex flex-col';

  return (
    <div className={`${flexClass} ${gapClass}`}>
      {children?.map((child, idx) => (
        <A2UIItemRenderer key={`container-child-${idx}`} item={child} onAction={onAction} schema={schema} />
      ))}
    </div>
  );
}

function A2UIImage({ item }: { item: Record<string, unknown> }) {
  const props = (item.props as Record<string, unknown>) || {};
  const src = props.src as string || '';
  const alt = props.alt as string || '';
  const width = props.width as string | undefined;
  const height = props.height as string | undefined;

  return (
    <img
      src={src}
      alt={alt}
      width={width}
      height={height}
      className="rounded-md max-w-full"
    />
  );
}

function A2UITable({ item }: { item: Record<string, unknown> }) {
  const props = (item.props as Record<string, unknown>) || {};
  const headers = props.headers as string[] || [];
  const rows = props.rows as string[][] || [];

  if (headers.length === 0) return null;

  return (
    <table className="w-full text-sm border-collapse">
      <thead>
        <tr>
          {headers.map((h, idx) => (
            <th key={`th-${idx}`} className="border border-border px-3 py-2 text-left font-semibold bg-muted">{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, rIdx) => (
          <tr key={`tr-${rIdx}`}>
            {row.map((cell, cIdx) => (
              <td key={`td-${rIdx}-${cIdx}`} className="border border-border px-3 py-2">{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function A2UIBadge({ item }: { item: Record<string, unknown> }) {
  const props = (item.props as Record<string, unknown>) || {};
  const text = props.text as string || '';
  const variant = (props.variant as string) || 'default';

  const variantClass = variant === 'success'
    ? 'bg-green-100 text-green-800'
    : variant === 'warning'
    ? 'bg-yellow-100 text-yellow-800'
    : variant === 'error'
    ? 'bg-red-100 text-red-800'
    : 'bg-secondary text-secondary-foreground';

  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${variantClass}`}>
      {text}
    </span>
  );
}

function A2UICode({ item }: { item: Record<string, unknown> }) {
  const props = (item.props as Record<string, unknown>) || {};
  const code = props.code || props.text || '';
  const language = props.language as string | undefined;

  return (
    <pre className="bg-muted rounded-md p-3 text-xs overflow-auto font-mono">
      {language && <div className="text-xs text-muted-foreground mb-1">{language}</div>}
      <code>{code}</code>
    </pre>
  );
}

interface A2UISchemaRendererProps {
  schema: Record<string, unknown> | null;
  onAction?: (action: A2UIAction) => void;
  dataMap?: Map<string, unknown>;
}

function A2UISchemaRenderer({ schema, onAction, dataMap: _dataMap }: A2UISchemaRendererProps) {
  if (!schema) {
    return <div className="text-sm text-muted-foreground">No A2UI schema available</div>;
  }

  const schemaObj = schema as Record<string, unknown>;
  const properties = schemaObj.properties as Record<string, Record<string, unknown>> | undefined;

  if (!properties || Object.keys(properties).length === 0) {
    return <pre className="text-xs bg-muted p-2 rounded">{JSON.stringify(schema, null, 2)}</pre>;
  }

  return (
    <div className="a2ui-schema-renderer">
      <div className="text-xs text-muted-foreground mb-2">
        Schema: {getSchemaVersion(schema)}
      </div>
      {Object.entries(properties).map(([key, propSchema]) => (
        <SchemaFieldRenderer
          key={key}
          name={key}
          schema={propSchema}
          onAction={onAction}
        />
      ))}
    </div>
  );
}

interface SchemaFieldRendererProps {
  name: string;
  schema: Record<string, unknown>;
  onAction?: (action: A2UIAction) => void;
}

function SchemaFieldRenderer({ name, schema, onAction }: SchemaFieldRendererProps) {
  const fieldType = schema.type as string || 'string';
  const description = schema.description as string | undefined;
  const title = schema.title as string || name;

  return (
    <div className="mb-3">
      <label className="text-sm font-medium">{title}</label>
      {description && <p className="text-xs text-muted-foreground mb-1">{description}</p>}
      <SchemaInputRenderer name={name} schema={schema} onAction={onAction} />
    </div>
  );
}

function SchemaInputRenderer({ name, schema, onAction }: SchemaFieldRendererProps) {
  const fieldType = schema.type as string || 'string';
  const [value, setValue] = useState('');

  const handleChange = useCallback((newValue: string) => {
    setValue(newValue);
    onAction?.({ type: 'input', path: name, value: newValue, messageType: 'schema_input' });
  }, [onAction, name]);

  switch (fieldType) {
    case 'string':
      const format = schema.format as string | undefined;
      if (format === 'textarea') {
        return (
          <textarea
            className="flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            placeholder={`Enter ${name}`}
            value={value}
            onChange={(e) => handleChange(e.target.value)}
          />
        );
      }
      return (
        <input
          type="text"
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          placeholder={`Enter ${name}`}
          value={value}
          onChange={(e) => handleChange(e.target.value)}
        />
      );
    case 'number':
      return (
        <input
          type="number"
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          placeholder={`Enter ${name}`}
          value={value}
          onChange={(e) => handleChange(e.target.value)}
        />
      );
    case 'boolean':
      return (
        <input
          type="checkbox"
          className="h-4 w-4 rounded border-input"
          checked={value === 'true'}
          onChange={(e) => handleChange(String(e.target.checked))}
        />
      );
    case 'enum':
    case 'select':
      const enumValues = (schema.enum as string[]) || [];
      return (
        <select
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          value={value}
          onChange={(e) => handleChange(e.target.value)}
        >
          <option value="">Select...</option>
          {enumValues.map((v) => (
            <option key={v} value={v}>{v}</option>
          ))}
        </select>
      );
    default:
      return (
        <input
          type="text"
          className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
          placeholder={`Enter ${name}`}
          value={value}
          onChange={(e) => handleChange(e.target.value)}
        />
      );
  }
}

function getSchemaVersion(schema: Record<string, unknown>): string {
  return (schema.version as string) || 'unknown';
}

/**
 * Convenience component that wraps A2UIRenderer with action handling
 * for chat interfaces
 */
export function A2UIChatMessage({ content, className = '' }: { content: string; className?: string }) {
  const handleAction = useCallback((_action: A2UIAction) => {
    // Action handling is delegated to the parent chat component
    // via the message transformer system
  }, []);

  return (
    <A2UIRenderer
      content={content}
      onAction={handleAction}
      className={`a2ui-chat-message ${className}`}
    />
  );
}