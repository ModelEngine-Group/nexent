/**
 * A2UI Module - Main Entry Point
 *
 * Provides structured UI rendering for agent responses.
 * Import this module to use A2UI parsing and rendering capabilities.
 */

export { A2UIRenderer, A2UIChatMessage, type A2UIRendererProps, type A2UIAction } from './A2UIRenderer';
export { parseA2UIMessage, mightContainA2UI, getDefaultSchema, type A2UIParseResult, type A2UIBlock } from './parser';
export { A2UI_PROCESS_TYPE } from './constants';