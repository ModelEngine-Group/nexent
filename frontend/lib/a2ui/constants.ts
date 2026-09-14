/**
 * A2UI Protocol Constants
 *
 * Mirrors the backend protocol defined in sdk/nexent/core/a2ui/constants.py
 */

export const A2UI_PROTOCOL_VERSION = '0.9';

export const A2UI_OPEN_TAG = '<a2ui-json>';
export const A2UI_CLOSE_TAG = '</a2ui-json>';
export const A2UI_BLOCK_PATTERN = /<a2ui-json>([\s\S]*?)<\/a2ui-json>/;

export const A2UI_MESSAGE_TYPES = {
  BEGIN_RENDERING: 'beginRendering',
  END_RENDERING: 'endRendering',
  BATCH: 'batch',
} as const;

export type A2UIMessageType = (typeof A2UI_MESSAGE_TYPES)[keyof typeof A2UI_MESSAGE_TYPES];

/**
 * Default renderer schema used when the model output is missing or incomplete
 */
export const DEFAULT_A2UI_SCHEMA = {
  version: A2UI_PROTOCOL_VERSION,
  type: 'object',
  properties: {},
};

/**
 * ProcessType for A2UI messages in the backend protocol
 */
export const A2UI_PROCESS_TYPE = 'a2ui' as const;