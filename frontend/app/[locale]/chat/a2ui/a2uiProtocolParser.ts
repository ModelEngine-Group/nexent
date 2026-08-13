/**
 * A2UI Protocol Parser
 * Parses A2UI protocol JSON into the internal component tree format.
 *
 * Supports multiple formats:
 *
 * 1. Standard A2UI protocol format:
 *    {
 *      "type": "card",
 *      "version": "1.0",
 *      "card": {
 *        "header": { "title": "...", "subtitle": "...", "icon": "info" },
 *        "body": { "sections": [...] }
 *      }
 *    }
 *
 * 2. Simplified format (Agent-generated):
 *    {
 *      "type": "form" | "info" | "feedback" | "confirmation" | "rating",
 *      "title": "...",
 *      "description": "...",
 *      "fields": [...],
 *      "actions": [...]
 *    }
 */

import type { A2UIComponent, A2UISurface } from "@/types/chat";

/**
 * Safely extract a display string from a value that may be a plain string
 * or a structured object like `{ display: "inline", text: "..." }`.
 * Returns a plain string suitable for React rendering.
 */
function safeText(value: any): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (typeof value === "object") {
    if (typeof value.text === "string") return value.text;
    if (typeof value.content === "string") return value.content;
    if (typeof value.label === "string") return value.label;
    try {
      return JSON.stringify(value);
    } catch {
      return "";
    }
  }
  return String(value);
}

/** A2UI card types that we support */
const A2UI_TYPES = new Set([
  "card",
  "form",
  "info",
  "feedback",
  "confirmation",
  "rating",
  "chart",
]);

/** List of A2UI XML tags that should be stripped from text */
const A2UI_XML_TAGS = [
  "card",
  "avatar",
  "header",
  "body",
  "section",
  "text",
  "divider",
  "key-value",
  "action",
  "rating",
  "form",
  "button",
  "input",
  "select",
  "checkbox",
  "icon",
  "image",
  "link",
  "columns",
  "column",
  "row",
];

/** Check if a JSON object is any A2UI protocol message */
export function isA2UIProtocol(json: any): boolean {
  if (!json || typeof json !== "object") return false;
  const type = json.type;
  if (!type || typeof type !== "string") return false;
  if (!A2UI_TYPES.has(type)) return false;
  // For "card" type, validate card structure
  if (type === "card") {
    if (!json.card || typeof json.card !== "object") return false;
  }
  return true;
}

/** Strip A2UI XML-like tags from text to prevent React rendering errors */
function stripA2UIXMLTags(text: string): string {
  let result = text;
  // Remove self-closing tags like <card />, <avatar />
  for (const tag of A2UI_XML_TAGS) {
    const selfClosingRegex = new RegExp(`<${tag}\\s*/>`, "gi");
    result = result.replace(selfClosingRegex, "");
  }
  // Remove opening and closing tag pairs like <card>...</card>
  for (const tag of A2UI_XML_TAGS) {
    const tagPairRegex = new RegExp(`<${tag}[^>]*>[\\s\\S]*?</${tag}>`, "gi");
    result = result.replace(tagPairRegex, "");
  }
  return result;
}

/** Extract A2UI JSON blocks from text content */
export function extractA2UIFromText(text: string): {
  surfaces: A2UISurface[];
  remainingText: string;
} {
  const surfaces: A2UISurface[] = [];
  let remainingText = text;

  const a2uiBlocks: { start: number; end: number; json: string }[] = [];

  // Pattern 1: a2ui code blocks
  const a2uiCodeBlockRegex = /```a2ui\s*\n([\s\S]*?)```/g;
  let match: RegExpExecArray | null;

  while ((match = a2uiCodeBlockRegex.exec(text)) !== null) {
    a2uiBlocks.push({
      start: match.index,
      end: match.index + match[0].length,
      json: match[1],
    });
  }

  // Pattern 2: A2UI JSON in markdown code blocks (json/javascript/a2ui)
  const codeBlockRegex = /```(?:json|javascript|a2ui)?\s*\n([\s\S]*?)```/g;
  while ((match = codeBlockRegex.exec(text)) !== null) {
    try {
      const parsed = JSON.parse(match[1]);
      if (isA2UIProtocol(parsed)) {
        a2uiBlocks.push({
          start: match.index,
          end: match.index + match[0].length,
          json: match[1],
        });
      }
    } catch {
      // Not A2UI JSON in code block
    }
  }

  // Pattern 3: Raw JSON objects with A2UI type field
  // Match JSON objects containing "type" followed by one of A2UI types
  for (const type of A2UI_TYPES) {
    const typeRegex = new RegExp(
      `\\{[^{}]*"type"\\s*:\\s*"${type}"[\\s\\S]*?\\}`,
      "g"
    );
    while ((match = typeRegex.exec(text)) !== null) {
      try {
        const parsed = JSON.parse(match[0]);
        if (isA2UIProtocol(parsed)) {
          a2uiBlocks.push({
            start: match.index,
            end: match.index + match[0].length,
            json: match[0],
          });
        }
      } catch {
        // Not valid JSON, skip
      }
    }
  }

  // Remove duplicate blocks (overlapping ranges)
  const uniqueBlocks = removeOverlappingBlocks(a2uiBlocks);

  // Sort blocks by start position (descending) to remove from text correctly
  uniqueBlocks.sort((a, b) => b.start - a.start);

  for (const block of uniqueBlocks) {
    try {
      const parsed = JSON.parse(block.json);
      if (isA2UIProtocol(parsed)) {
        const surface = convertA2UIToSurface(parsed);
        surfaces.push(surface);
        // Remove the JSON block from remaining text
        remainingText =
          remainingText.slice(0, block.start) +
          remainingText.slice(block.end);
      }
    } catch {
      // Skip invalid blocks
    }
  }

  // Strip any remaining A2UI XML-like tags to prevent React rendering errors
  remainingText = stripA2UIXMLTags(remainingText);

  return { surfaces, remainingText: remainingText.trim() };
}

/** Remove overlapping blocks, keeping the longest match */
function removeOverlappingBlocks(
  blocks: { start: number; end: number; json: string }[]
): { start: number; end: number; json: string }[] {
  if (blocks.length === 0) return blocks;

  // Sort by start position, then by length (longer first)
  const sorted = [...blocks].sort((a, b) => {
    if (a.start !== b.start) return a.start - b.start;
    return (b.end - b.start) - (a.end - a.start);
  });

  const result: { start: number; end: number; json: string }[] = [];
  const usedRanges: { start: number; end: number }[] = [];

  for (const block of sorted) {
    const overlaps = usedRanges.some(
      (range) => block.start < range.end && block.end > range.start
    );
    if (!overlaps) {
      result.push(block);
      usedRanges.push({ start: block.start, end: block.end });
    }
  }

  return result;
}

/** Convert A2UI protocol JSON to our internal surface format */
function convertA2UIToSurface(a2uiJson: any): A2UISurface {
  const type = a2uiJson.type;

  if (type === "chart") {
    const chartType = a2uiJson.chart_type || a2uiJson.chartType || "bar";
    const chartData = a2uiJson.chart_data || a2uiJson.chartData || a2uiJson.data || {};
    const chartOptions = a2uiJson.chart_options || a2uiJson.chartOptions || a2uiJson.options || {};
    const surfaceId = `a2ui_chart_${Date.now()}`;

    return {
      surfaceId: surfaceId,
      catalog: "basic",
      components: [{
        id: `chart_${surfaceId}`,
        component: "Chart",
        props: {
          chartType: chartType,
          data: chartData,
          options: chartOptions,
        },
      }],
      dataModel: {},
    };
  }

  if (type === "card" && a2uiJson.card) {
    return convertStandardCard(a2uiJson);
  } else {
    return convertSimplifiedFormat(a2uiJson);
  }
}

/** Convert standard A2UI card format */
function convertStandardCard(a2uiJson: any): A2UISurface {
  const card = a2uiJson.card;
  const components: A2UIComponent[] = [];

  // Build card header components
  if (card.header) {
    const headerComps = buildHeaderComponents(card.header);
    components.push(...headerComps);
  }

  // Build card body components
  if (card.body && card.body.sections) {
    const bodyComps = buildBodyComponents(card.body.sections);
    components.push(...bodyComps);
  }

  // Wrap in a Card component
  const cardComponent: A2UIComponent = {
    id: `a2ui_card_${Date.now()}`,
    component: "Card",
    text: card.header?.title || "",
    children: components,
  };

  return {
    surfaceId: `a2ui_proto_${Date.now()}`,
    components: [cardComponent],
    dataModel: {},
  };
}

/** Convert simplified format (Agent-generated) */
function convertSimplifiedFormat(a2uiJson: any): A2UISurface {
  const components: A2UIComponent[] = [];
  const type = a2uiJson.type;

  // Build title
  if (a2uiJson.title) {
    components.push({
      id: `title_${Date.now()}`,
      component: "Text",
      text: safeText(a2uiJson.title),
      variant: "h3",
    });
  }

  // Build description
  if (a2uiJson.description) {
    components.push({
      id: `desc_${Date.now()}`,
      component: "Text",
      text: safeText(a2uiJson.description),
      variant: "body",
    });
  }

  // Build fields for form/feedback types
  if (a2uiJson.fields && Array.isArray(a2uiJson.fields)) {
    for (const field of a2uiJson.fields) {
      components.push(...buildFieldComponent(field));
    }
  }

  // Build actions/buttons
  if (a2uiJson.actions && Array.isArray(a2uiJson.actions)) {
    for (const action of a2uiJson.actions) {
      components.push({
        id: `action_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        component: "Button",
        text: action.text || action.label || "Action",
        variant: action.type === "primary" ? "primary" : "default",
        action: action.action || action.name || action.text,
      });
    }
  }

  // Build options for feedback/confirmation types
  if (a2uiJson.options && Array.isArray(a2uiJson.options)) {
    for (const option of a2uiJson.options) {
      const optionText = typeof option === "string" ? option : option.label || option.text;
      components.push({
        id: `option_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        component: "Button",
        text: optionText,
        variant: "default",
        action: optionText,
      });
    }
  }

  // Wrap in a Card component
  const cardComponent: A2UIComponent = {
    id: `a2ui_card_${Date.now()}`,
    component: "Card",
    text: safeText(a2uiJson.title),
    children: components,
  };

  return {
    surfaceId: `a2ui_simple_${Date.now()}`,
    components: [cardComponent],
    dataModel: {},
  };
}

/** Build field component from simplified format */
function buildFieldComponent(field: any): A2UIComponent[] {
  const comps: A2UIComponent[] = [];
  const fieldType = field.type;
  const fieldId = field.id || field.name || `field_${Date.now()}`;
  const label = safeText(field.label || field.placeholder);
  const placeholder = safeText(field.placeholder);
  const required = field.required || false;

  switch (fieldType) {
    case "text":
    case "textfield":
    case "email":
    case "textarea": {
      // Label
      if (label) {
        comps.push({
          id: `label_${fieldId}_${Date.now()}`,
          component: "Text",
          text: `${label}${required ? " *" : ""}`,
          variant: "body",
        });
      }
      // Input field
      comps.push({
        id: fieldId,
        component: "TextField",
        text: "",
        label: label,
        placeholder: placeholder,
        required: required,
        value: safeText(field.default),
      });
      break;
    }

    case "select":
    case "dropdown": {
      if (label) {
        comps.push({
          id: `label_${fieldId}_${Date.now()}`,
          component: "Text",
          text: `${label}${required ? " *" : ""}`,
          variant: "body",
        });
      }
      comps.push({
        id: fieldId,
        component: "TextField",
        text: "",
        label: label,
        placeholder: placeholder,
        required: required,
      });
      break;
    }

    case "checkbox":
    case "toggle": {
      comps.push({
        id: `checkbox_${fieldId}_${Date.now()}`,
        component: "Button",
        text: label || fieldId,
        variant: "default",
      });
      break;
    }

    case "rating": {
      comps.push({
        id: `label_${fieldId}_${Date.now()}`,
        component: "Text",
        text: label || "",
        variant: "body",
      });
      comps.push({
        id: fieldId,
        component: "Rating",
        text: "",
        variant: "",
      });
      break;
    }

    default: {
      // Unknown field type, try to render as text
      if (label || placeholder) {
        comps.push({
          id: `field_${fieldId}_${Date.now()}`,
          component: "Text",
          text: `${label || ""}${placeholder ? ` - ${placeholder}` : ""}`,
          variant: "body",
        });
      }
    }
  }

  return comps;
}

/** Build components from A2UI card header */
function buildHeaderComponents(header: any): A2UIComponent[] {
  const comps: A2UIComponent[] = [];

  // Title
  if (header.title) {
    comps.push({
      id: `header_title_${Date.now()}`,
      component: "Text",
      text: safeText(header.title),
      variant: "h3",
    });
  }

  // Subtitle
  if (header.subtitle) {
    comps.push({
      id: `header_subtitle_${Date.now()}`,
      component: "Text",
      text: safeText(header.subtitle),
      variant: "subtitle",
    });
  }

  // Icon
  if (header.icon) {
    comps.push({
      id: `header_icon_${Date.now()}`,
      component: "Icon",
      text: safeText(header.icon),
    });
  }

  return comps;
}

/** Build components from A2UI card body sections */
function buildBodyComponents(sections: any[]): A2UIComponent[] {
  const comps: A2UIComponent[] = [];

  for (const section of sections) {
    const sectionType = section.type;

    switch (sectionType) {
      case "text": {
        comps.push({
          id: `text_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
          component: "Text",
          text: safeText(section.content),
          variant: mapTextStyle(section.style),
        });
        break;
      }

      case "divider": {
        comps.push({
          id: `divider_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
          component: "Text",
          text: "---",
          variant: "body",
        });
        break;
      }

      case "key-value": {
        if (section.items && Array.isArray(section.items)) {
          for (const item of section.items) {
            const keyText = item.key ? `**${safeText(item.key)}**: ` : "";
            const valueText = safeText(item.value);
            const highlightHtml =
              item.highlight === "success"
                ? `<span style="color: #52c41a; font-weight: 500">${valueText}</span>`
                : item.highlight === "warning"
                ? `<span style="color: #faad14; font-weight: 500">${valueText}</span>`
                : item.highlight === "error"
                ? `<span style="color: #ff4d4f; font-weight: 500">${valueText}</span>`
                : valueText;

            comps.push({
              id: `kv_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
              component: "Text",
              text: `${keyText}${highlightHtml}`,
              variant: "body",
            });
          }
        }
        break;
      }

      case "action": {
        if (section.buttons && Array.isArray(section.buttons)) {
          for (const btn of section.buttons) {
            comps.push({
              id: `btn_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
              component: "Button",
              text: safeText(btn.label || btn.text || "Action"),
              variant: btn.style === "primary" ? "primary" : "default",
              action: btn.action || btn.name,
            });
          }
        }
        break;
      }

      case "rating": {
        comps.push({
          id: `rating_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
          component: "Rating",
          text: "",
          variant: "",
        });
        break;
      }

      default: {
        // Unknown section type, try to render as text
        if (section.content) {
          comps.push({
            id: `unknown_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
            component: "Text",
            text: safeText(section.content),
            variant: "body",
          });
        }
      }
    }
  }

  return comps;
}

/** Map A2UI text style to internal variant */
function mapTextStyle(style?: string): string {
  switch (style) {
    case "title":
      return "h3";
    case "subtitle":
      return "subtitle";
    case "caption":
      return "secondary";
    case "body":
    default:
      return "body";
  }
}
