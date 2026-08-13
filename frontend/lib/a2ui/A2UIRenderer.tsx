'use client';

import React, { useMemo, useState, useCallback } from 'react';
import { parseA2UIMessage, type A2UIParseResult, type A2UIBlock } from './parser';

export interface A2UIRendererProps {
  content: string;
  onAction?: (action: A2UIAction) => void;
  className?: string;
}

export interface A2UIAction {
  type: 'submit' | 'click' | 'input' | 'select';
  path?: string;
  value?: unknown;
  messageType?: string;
}

/**
 * Main A2UI Renderer component
 *
 * Renders structured A2UI JSON content as interactive React components.
 * Falls back to plain text rendering when A2UI content is not detected.
 */
export function A2UIRenderer({ content, onAction, className = '' }: A2UIRendererProps) {
  const parsed = useMemo(() => parseA2UIMessage(content), [content]);

  if (!parsed.isA2UI) {
    return <div className={className}>{content}</div>;
  }

  return (
    <div className={`a2ui-container ${className}`}>
      {parsed.blocks.length === 0 ? (
        <A2UISchemaRenderer
          schema={parsed.schema}
          onAction={onAction}
        />
      ) : (
        parsed.blocks.map((block, idx) => (
          <A2UIBlockRenderer
            key={`a2ui-block-${idx}`}
            block={block}
            onAction={onAction}
            defaultSchema={parsed.schema}
          />
        ))
      )}
    </div>
  );
}

interface A2UIBlockRendererProps {
  block: A2UIBlock;
  onAction?: (action: A2UIAction) => void;
  defaultSchema: Record<string, unknown> | null;
}

function A2UIBlockRenderer({ block, onAction, defaultSchema }: A2UIBlockRendererProps) {
  if (!block.parsed) {
    return <div className="text-sm text-muted-foreground">{block.content}</div>;
  }

  const parsed = block.parsed as Record<string, unknown>;
  const messageType = parsed.messageType as string | undefined;

  // Lifecycle messages
  if (messageType === 'beginRendering') {
    const schema = parsed.schema as Record<string, unknown> | undefined;
    return (
      <A2UIBeginRenderingBlock
        schema={schema || defaultSchema}
      />
    );
  }

  if (messageType === 'endRendering') {
    return <A2UIEndRenderingBlock />;
  }

  if (messageType === 'batch') {
    const items = parsed.items as Record<string, unknown>[] | undefined;
    return (
      <A2UIBatchBlock
        items={items || []}
        onAction={onAction}
        defaultSchema={defaultSchema}
      />
    );
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

function A2UIBeginRenderingBlock({ schema }: { schema: Record<string, unknown> | null }) {
  if (!schema) return null;
  return (
    <div className="a2ui-begin-rendering rounded-lg border border-border bg-card p-4">
      <div className="text-xs text-muted-foreground mb-2">A2UI Schema v{getSchemaVersion(schema)}</div>
      <A2UISchemaRenderer schema={schema} />
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
}

function A2UISchemaRenderer({ schema, onAction }: A2UISchemaRendererProps) {
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