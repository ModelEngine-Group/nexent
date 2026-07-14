// Tool function for processing chat streaming response

import { chatConfig } from "@/const/chatConfig";
import { ChatMessageType, AgentStep } from "@/types/chat";
import log from "@/lib/logger";
import { MESSAGE_ROLES } from "@/const/chatConfig";

// Streaming message types for recovery
export interface StreamingUnit {
  unit_id: number;
  unit_type: string;
  unit_content: string;
  unit_index: number;
  unit_status: string;
}

export interface StreamingMessage {
  message_id: number;
  message_index: number;
  status: string;
  message_content: string;
  last_unit: StreamingUnit | null;
  units: StreamingUnit[];
}

export interface ResumeConfig {
  streamingMessage: StreamingMessage;
  lastUnitIndex: number;
}

// Merge new search results into an existing list, skipping duplicates by `text` field
const deduplicateSearchResults = (
  existingResults: any[],
  newResults: any[]
): any[] => {
  const uniqueResults = [...existingResults];
  const existingTexts = new Set(existingResults.map((item) => item.text));
  for (const result of newResults) {
    if (!existingTexts.has(result.text)) {
      uniqueResults.push(result);
      existingTexts.add(result.text);
    }
  }
  return uniqueResults;
};

// Merge new image URLs into an existing list, skipping duplicates
const deduplicateImages = (
  existingImages: string[],
  newImages: string[]
): string[] => {
  const uniqueImages = [...existingImages];
  const existingUrls = new Set(existingImages);
  for (const imageUrl of newImages) {
    if (!existingUrls.has(imageUrl)) {
      uniqueImages.push(imageUrl);
      existingUrls.add(imageUrl);
    }
  }
  return uniqueImages;
};

// function: process the user break tag
const processUserBreakTag = (content: string, t: any): string => {
  if (!content || typeof content !== "string") {
    return content;
  }

  // check if the content is equal to <user_break> tag
  if (content == "<user_break>") {
    // replace the content with the corresponding natural language according to the current language environment
    const userBreakMessage = t("chatStreamHandler.userInterrupted");
    return userBreakMessage;
  }

  return content;
};

interface JsonData {
  type: string;
  content: any;
  status?: string;
  last_unit_index?: number;
  replay_chunk_count?: number;
  conversation_id?: number;
}

const normalizeMessageContent = (content: unknown): string => {
  if (typeof content === "string") {
    return content;
  }
  if (content === null || content === undefined) {
    return "";
  }
  try {
    return JSON.stringify(content);
  } catch {
    return String(content);
  }
};

// Reconstruct streaming state from persisted units (for tab-switch recovery)
// maxUnitIndex: only process units up to this index (for resume mode)

// Types for unit processing
type ReconstructionState = {
  currentStep: AgentStep | null;
  lastContentType: string | null;
  lastModelOutputIndex: number;
  lastCodeOutputIndex: number;
  finalAnswer: string;
  steps: AgentStep[];
  stepCounter: number;
};

// Helper to create a new step
const createNewStep = (
  stepCounter: number,
  existingStepsLength: number,
  id: string,
  title: string,
  content: string,
  unitType: string
): AgentStep => ({
  id,
  title,
  content,
  expanded: true,
  contents: [{
    id,
    type: unitType as any,
    content,
    expanded: true,
    timestamp: Date.now(),
  }],
  metrics: null,
  thinking: { content: '', expanded: true },
  code: { content: '', expanded: true },
  output: { content: '', expanded: true },
});

// Helper to finalize current step and prepare for next
const finalizeCurrentStep = (state: ReconstructionState): void => {
  if (state.currentStep && state.currentStep.contents.length > 0) {
    state.steps.push(state.currentStep);
  }
  state.currentStep = null;
  state.lastContentType = null;
  state.lastModelOutputIndex = -1;
  state.lastCodeOutputIndex = -1;
};

// Helper to get step number
const getStepNumber = (state: ReconstructionState): number =>
  state.stepCounter > 0 ? state.stepCounter : state.steps.length + 1;

// Helper to process model output type units
const processModelOutputUnit = (unit: StreamingUnit, state: ReconstructionState): void => {
  const stepNum = getStepNumber(state);
  state.currentStep = createNewStep(
    stepNum,
    state.steps.length,
    `step-${stepNum}`,
    '',
    unit.unit_content,
    chatConfig.messageTypes.MODEL_OUTPUT
  );
  state.currentStep.contents[0].id = `model-${unit.unit_index}`;
  state.currentStep.contents[0].type = chatConfig.messageTypes.MODEL_OUTPUT;
  state.lastContentType = chatConfig.messageTypes.MODEL_OUTPUT;
  state.lastModelOutputIndex = 0;
};

// Helper to get output subtype
const getOutputSubType = (unitType: string): "thinking" | "deep_thinking" | undefined => {
  switch (unitType) {
    case 'model_output_thinking': return 'thinking';
    case 'model_output_deep_thinking': return 'deep_thinking';
    default: return undefined;
  }
};

// Helper to append or create content block for thinking/code units
const processThinkingCodeUnit = (unit: StreamingUnit, state: ReconstructionState): void => {
  const outputSubType = getOutputSubType(unit.unit_type);
  const lastContentBlock = state.currentStep?.contents[state.currentStep.contents.length - 1];
  const lastContentBlockType = lastContentBlock?.type;
  const shouldAppend = lastContentBlock && lastContentBlockType === unit.unit_type;
  const unitType = unit.unit_type as typeof chatConfig.messageTypes.MODEL_OUTPUT_THINKING | typeof chatConfig.messageTypes.MODEL_OUTPUT_DEEP_THINKING | typeof chatConfig.messageTypes.MODEL_OUTPUT_CODE;

  if (!state.currentStep) {
    const stepNumNew = getStepNumber(state);
    state.currentStep = createNewStep(
      stepNumNew,
      state.steps.length,
      `step-${stepNumNew}`,
      '',
      '',
      unit.unit_type
    );
    state.currentStep.contents[0].id = `model-${unit.unit_index}`;
    state.currentStep.contents[0].subType = outputSubType;
    state.currentStep.contents[0].content = unit.unit_content;
    state.lastModelOutputIndex = 0;
  } else if (shouldAppend) {
    lastContentBlock.content += unit.unit_content;
  } else {
    state.currentStep.contents.push({
      id: `model-${unit.unit_index}`,
      type: unitType,
      subType: outputSubType,
      content: unit.unit_content,
      expanded: true,
      timestamp: Date.now(),
    });
    state.lastModelOutputIndex = state.currentStep.contents.length - 1;
  }
  state.lastContentType = unit.unit_type;
};

// Check if unit type should be skipped during reconstruction
const isSkippedUnitType = (unitType: string): boolean => {
  const skippedTypes = [
    'search_content_placeholder',
    'token_count',
    'parse',
    'execution_logs',
    'agent_new_run',
    'tool',
    'verification',
    'memory_search',
    'max_steps_reached',
    'card',
  ];
  return skippedTypes.includes(unitType);
};

export function reconstructFromStreamingMessage(streamingMessage: StreamingMessage, maxUnitIndex?: number): {
  currentStep: AgentStep | null;
  lastContentType: string | null;
  lastModelOutputIndex: number;
  lastCodeOutputIndex: number;
  finalAnswer: string;
  steps: AgentStep[];
} {
  const state: ReconstructionState = {
    currentStep: null,
    lastContentType: null,
    lastModelOutputIndex: -1,
    lastCodeOutputIndex: -1,
    finalAnswer: streamingMessage.message_content || '',
    steps: [],
    stepCounter: 0,
  };

  // Sort units by index (should already be sorted)
  const sortedUnits = [...streamingMessage.units].sort(
    (a, b) => a.unit_index - b.unit_index
  );

  for (const unit of sortedUnits) {
    // Skip units beyond maxUnitIndex (for resume mode - only reconstruct state up to last received unit)
    if (maxUnitIndex !== undefined && unit.unit_index > maxUnitIndex) {
      continue;
    }

    // Handle unit types
    switch (unit.unit_type) {
      case 'step_count':
        state.stepCounter++;
        finalizeCurrentStep(state);
        break;

      case 'model_output':
        processModelOutputUnit(unit, state);
        break;

      case 'model_output_thinking':
      case 'model_output_deep_thinking':
      case 'model_output_code':
        processThinkingCodeUnit(unit, state);
        break;

      case 'final_answer':
        state.finalAnswer = unit.unit_content;
        break;

      default: {
        if (isSkippedUnitType(unit.unit_type)) {
          break;
        }
        // For unknown types, create a generic step
        finalizeCurrentStep(state);
        const stepNumUnknown = getStepNumber(state);
        state.currentStep = createNewStep(
          stepNumUnknown,
          state.steps.length,
          `step-${stepNumUnknown}`,
          unit.unit_type,
          unit.unit_content,
          unit.unit_type
        );
        state.currentStep.contents[0].id = `content-${unit.unit_index}`;
        break;
      }
    }
  }

  // Don't forget to save the last currentStep if it has contents
  finalizeCurrentStep(state);

  return {
    currentStep: state.steps[state.steps.length - 1] || null,
    lastContentType: state.lastContentType,
    lastModelOutputIndex: state.lastModelOutputIndex,
    lastCodeOutputIndex: state.lastCodeOutputIndex,
    finalAnswer: state.finalAnswer,
    steps: state.steps,
  };
}

// Processing Streaming Response Data
export const handleStreamResponse = async (
  reader: ReadableStreamDefaultReader<Uint8Array>,
  setMessages: React.Dispatch<React.SetStateAction<ChatMessageType[]>>,
  resetTimeout: () => void,
  stepIdCounter: React.MutableRefObject<number>,
  setIsSwitchedConversation: React.Dispatch<React.SetStateAction<boolean>>,
  onConversationCreated: (conversationId: number) => void,
  isDebug: boolean = false,
  t: any,
  resumeConfig?: ResumeConfig
) => {
  const decoder = new TextDecoder();
  let buffer = "";

  // Resume mode: skip chunks that are already received
  let skipUntilUnitIndex = resumeConfig?.lastUnitIndex ?? -1;

  // Create an empty step object
  let currentStep: AgentStep = {
    id: ``,
    title: "",
    content: "",
    expanded: true,
    contents: [],
    metrics: null,
    thinking: { content: "", expanded: true },
    code: { content: "", expanded: true },
    output: { content: "", expanded: true },
  };

  // If resuming, initialize state from the recovered streaming message
  const pendingMetrics: Map<string, any> = new Map();
  let searchResultsContent: any[] = [];
  let allSearchResults: any[] = [];
  let finalAnswer = "";
  let lastModelOutputIndex = -1;
  let lastContentType: string | null = null;

  if (resumeConfig) {
    const recovered = reconstructFromStreamingMessage(
      resumeConfig.streamingMessage,
      resumeConfig.lastUnitIndex
    );
    currentStep = recovered.currentStep || currentStep;
    lastContentType = recovered.lastContentType;
    lastModelOutputIndex = recovered.lastModelOutputIndex;
    finalAnswer = recovered.finalAnswer;
  }

  try {
    while (true) {
      let readResult;
      try {
        readResult = await reader.read();
      } catch (readError: any) {
        // If read is aborted, break the loop gracefully
        if (
          readError?.name === "AbortError" ||
          readError?.name === "AbortSignal"
        ) {
          break;
        }
        throw readError;
      }
      const { done, value } = readResult;
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      // Track if we're in a stream_status event block
      let isInStreamStatusBlock = false;

      for (const line of lines) {
        // Handle stream_status event header (used in resume mode)
        if (line.startsWith("event: stream_status") || line.startsWith("event:stream_status")) {
          isInStreamStatusBlock = true;
          continue;
        }

        if (line.startsWith("data:")) {
          resetTimeout(); // Reset the timeout timer each time new data is received
          const jsonStr = line.substring(5).trim();

          try {
            // Parse the JSON data received each time
            const jsonData: JsonData = JSON.parse(jsonStr);

            // Handle stream_status data - contains resume information
            // The data format is {"status": "resumed", "last_unit_index": N}
            // Check both the isInStreamStatusBlock flag and the status field
            if ((isInStreamStatusBlock && jsonData.status === 'resumed') ||
                (jsonData.status === 'resumed' && typeof jsonData.last_unit_index === 'number')) {
              // Extract last_unit_index from the status message
              skipUntilUnitIndex = jsonData.last_unit_index as number;
              isInStreamStatusBlock = false;
              continue;
            }

            // Reset stream_status block flag for other data
            isInStreamStatusBlock = false;

            // In resume mode, skip chunks that we've already processed before disconnect.
            // The backend sends buffered chunks during resume, and we need to skip those
            // that were already processed by the original stream.
            // We use unit_index (included in chunks by backend) to determine which chunks to skip.
            if (resumeConfig) {
              // Extract unit_index from the chunk data
              const chunkUnitIndex = (jsonData as any).unit_index;
              if (typeof chunkUnitIndex === 'number' && chunkUnitIndex <= skipUntilUnitIndex) {
                // This chunk was already processed before disconnect (unit_index <= last processed index)
                continue;
              }
            }

            if (jsonData.type && jsonData.content) {
              const messageType = jsonData.type;

              // Handle conversation_created event - notify frontend of new conversation ID
              if (messageType === 'conversation_created') {
                const convId = jsonData.content?.conversation_id;
                if (typeof convId === 'number') {
                  onConversationCreated(convId);
                }
                continue;
              }

              const messageContent = normalizeMessageContent(jsonData.content);

              // In resume mode, skip metadata messages to prevent creating duplicate steps or indicators.
              // Steps are already reconstructed from the persisted streaming message.
              // TOKEN_COUNT metrics should be matched with existing steps by step_number.
              if (resumeConfig && (
                messageType === chatConfig.messageTypes.STEP_COUNT ||
                messageType === chatConfig.messageTypes.TOKEN_COUNT ||
                messageType === chatConfig.messageTypes.SEARCH_CONTENT_PLACEHOLDER ||
                messageType === chatConfig.messageTypes.PARSE ||
                messageType === chatConfig.messageTypes.EXECUTION_LOGS ||
                messageType === chatConfig.messageTypes.TOOL ||
                messageType === chatConfig.messageTypes.CARD ||
                messageType === chatConfig.messageTypes.AGENT_NEW_RUN ||
                messageType === chatConfig.messageTypes.VERIFICATION ||
                messageType === chatConfig.messageTypes.MEMORY_SEARCH ||
                messageType === chatConfig.messageTypes.MAX_STEPS_REACHED
              )) {
                continue;
              }

              // Process different types of messages
              switch (messageType) {
                case chatConfig.messageTypes.STEP_COUNT:
                  // Increment the counter for each new step (for unique ID generation)
                  stepIdCounter.current += 1;

                  // Extract the raw numeric step number from formatted content like "\n**Step 1** \n"
                  // TOKEN_COUNT sends step_number as an integer, so IDs must use only the digit
                  const stepTitle = messageContent.trim();
                  const stepNumMatch = stepTitle.match(/\d+/);
                  const stepNumber = stepNumMatch ? stepNumMatch[0] : String(stepIdCounter.current);

                  // Create a new step - use step number as part of ID for reliable matching
                  currentStep = {
                    id: `step-${stepNumber}`,
                    title: stepTitle,
                    content: "",
                    expanded: true,
                    contents: [], // Use an array to store all content in order
                    metrics: null,
                    thinking: { content: "", expanded: true },
                    code: { content: "", expanded: true },
                    output: { content: "", expanded: true },
                  };

                  // Reset status tracking variables
                  lastContentType = null;
                  lastModelOutputIndex = -1;

                  break;

                case chatConfig.messageTypes.TOKEN_COUNT:
                  try {
                    const metricsData = JSON.parse(messageContent);
                    const metricsStepId = `step-${metricsData.step_number}`;

                    // If currentStep matches the metrics step number, set directly
                    if (currentStep && currentStep.id === metricsStepId) {
                      currentStep.metrics = metricsData;
                    } else {
                      // currentStep was already reset to a new step, store metrics for later application
                      pendingMetrics.set(metricsStepId, metricsData);
                    }
                  } catch {
                    // Failed to parse metrics
                  }
                  break;

                case chatConfig.messageTypes.MODEL_OUTPUT:
                case chatConfig.messageTypes.MODEL_OUTPUT_THINKING:
                case chatConfig.messageTypes.MODEL_OUTPUT_DEEP_THINKING:
                  // Each model output type creates its own content block for proper visual separation
                  // thinking and deep_thinking should be shown as separate nodes

                  // If there's no currentStep, create one
                  if (!currentStep) {
                    currentStep = {
                      id: `step-streaming-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 9)}`,
                      title: "",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: null,
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                    lastModelOutputIndex = -1;
                  }

                  // Determine subType for styling
                  const subType = messageType === chatConfig.messageTypes.MODEL_OUTPUT_THINKING ? "thinking" :
                                 messageType === chatConfig.messageTypes.MODEL_OUTPUT_DEEP_THINKING ? "deep_thinking" : undefined;

                  // Check if we have a matching content block to append to
                  // Only append if the last block has the EXACT same type
                  const lastContentBlock = currentStep.contents[lastModelOutputIndex];
                  const shouldAppend = lastContentBlock && lastContentBlock.type === messageType;

                  if (shouldAppend) {
                    // Same type - append to existing block
                    lastContentBlock.content += messageContent;
                  } else {
                    // Different type or no existing block - create new content block
                    // This ensures thinking and deep_thinking are shown as separate nodes
                    currentStep.contents.push({
                      id: `model-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 7)}`,
                      type: messageType,
                      subType,
                      content: messageContent,
                      expanded: true,
                      timestamp: Date.now(),
                    });
                    lastModelOutputIndex = currentStep.contents.length - 1;
                  }

                  lastContentType = messageType;
                  break;

                case chatConfig.messageTypes.MODEL_OUTPUT_CODE:
                  // Process code generation - append to main content block
                  // If there's no currentStep, create one
                  if (!currentStep) {
                    currentStep = {
                      id: `step-code-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 9)}`,
                      title: "",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: null,
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                    lastModelOutputIndex = -1;
                  }

                  if (isDebug) {
                    // In debug mode, append to main content block
                    let processedContent = messageContent;

                    // Remove incomplete "<end" suffix if present (streaming artifact)
                    if (processedContent.endsWith("<end")) {
                      processedContent = processedContent.slice(0, -4);
                    }

                    // If we have a main content block, append to it
                    if (lastModelOutputIndex >= 0 && currentStep.contents[lastModelOutputIndex]) {
                      currentStep.contents[lastModelOutputIndex].content += processedContent;
                    } else {
                      // Create new main content block for code
                      currentStep.contents.push({
                        id: `model-code-${Date.now()}-${Math.random()
                          .toString(36)
                          .substring(2, 7)}`,
                        type: chatConfig.messageTypes.MODEL_OUTPUT_CODE,
                        content: processedContent,
                        expanded: true,
                        timestamp: Date.now(),
                      });
                      lastModelOutputIndex = currentStep.contents.length - 1;
                    }

                    lastContentType = chatConfig.messageTypes.MODEL_OUTPUT_CODE;
                  } else {
                    // In non-debug mode, use the original logic - add a stable loading prompt
                    // Check if there is a code generation prompt
                    if (
                      lastContentType ===
                      chatConfig.contentTypes.GENERATING_CODE
                    ) {
                      break;
                    }

                    // If it does not exist, add one
                    const newGeneratingItem = {
                      id: `generating-code-${stepIdCounter.current}`,
                      type: chatConfig.messageTypes.GENERATING_CODE,
                      content: t("chatStreamHandler.callingTool"),
                      expanded: true,
                      timestamp: Date.now(),
                      isLoading: true,
                    };

                    currentStep.contents.push(newGeneratingItem);

                    // Mark as code generation type
                    lastContentType = chatConfig.contentTypes.GENERATING_CODE;
                  }
                  break;

                case chatConfig.messageTypes.CARD:
                  // If there's no currentStep, create one
                  if (!currentStep) {
                    currentStep = {
                      id: `step-card-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 9)}`,
                      title: "Card Content",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: null,
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                  }

                  // Process card content
                  currentStep.contents.push({
                    id: `card-${Date.now()}-${Math.random()
                      .toString(36)
                      .substring(2, 7)}`,
                    type: chatConfig.messageTypes.CARD,
                    content: messageContent,
                    expanded: true,
                    timestamp: Date.now(),
                  });

                  // Update the last processed content type
                  lastContentType = chatConfig.contentTypes.CARD;
                  break;

                case chatConfig.messageTypes.SEARCH_CONTENT:
                  try {
                    // Parse search result content
                    const searchResults = JSON.parse(messageContent);
                    if (Array.isArray(searchResults)) {
                      // Modify mapping to match the SearchResult type at the component level
                      const newSearchResults = searchResults.map((item) => ({
                        title: item.title || t("chatRightPanel.unknownTitle"),
                        url: item.url || "#",
                        text:
                          item.text || t("chatRightPanel.noContentDescription"),
                        published_date: item.published_date || "",
                        source_type: item.source_type || "",
                        search_type: item.search_type || "",
                        filename: item.filename || "",
                        score:
                          typeof item.score === "number"
                            ? item.score
                            : undefined,
                        score_details: item.score_details || {},
                        tool_sign: item.tool_sign || "",
                        cite_index:
                          typeof item.cite_index === "number"
                            ? item.cite_index
                            : -1,
                      }));

                      // Accumulate search results
                      searchResultsContent = [
                        ...searchResultsContent,
                        ...newSearchResults,
                      ];
                      allSearchResults = [
                        ...allSearchResults,
                        ...newSearchResults,
                      ];

                      // If there's no currentStep, create one
                      if (!currentStep) {
                        currentStep = {
                          id: `step-search-${Date.now()}-${Math.random()
                            .toString(36)
                            .substring(2, 9)}`,
                          title: "Search Results",
                          content: "",
                          expanded: true,
                          contents: [],
                          metrics: null,
                          thinking: { content: "", expanded: true },
                          code: { content: "", expanded: true },
                          output: { content: "", expanded: true },
                        };
                      }

                      // Add to the current step's contents array
                      // Add as a search_content type message
                      currentStep.contents.push({
                        id: `search-content-${Date.now()}-${Math.random()
                          .toString(36)
                          .substring(2, 7)}`,
                        type: chatConfig.messageTypes.SEARCH_CONTENT,
                        content: messageContent, // Keep the original JSON string
                        expanded: true,
                        timestamp: Date.now(),
                      });

                      // Update the last processed content type
                      lastContentType = chatConfig.contentTypes.SEARCH_CONTENT;
                    }

                    // Update the search results of the current message
                    setMessages((prev) => {
                      const recordMessages = [...prev];
                      const lastMsg = recordMessages[recordMessages.length - 1];

                      // Check if lastMsg exists before accessing its properties
                      if (!lastMsg) {
                        return recordMessages;
                      }

                      // Use the public deduplication function to process search results
                      if (
                        searchResultsContent &&
                        searchResultsContent.length > 0
                      ) {
                        const updatedMsg = {
                          ...lastMsg,
                          searchResults: deduplicateSearchResults(
                            lastMsg.searchResults || [],
                            searchResultsContent
                          ),
                        };
                        recordMessages[recordMessages.length - 1] = updatedMsg;
                      }

                      return recordMessages;
                    });
                  } catch (e) {
                    log.error(
                      t("chatStreamHandler.parseSearchContentFailed"),
                      e
                    );
                  }
                  break;

                case chatConfig.messageTypes.PICTURE_WEB:
                  try {
                    const parsedData = JSON.parse(messageContent);
                    const imageUrls = parsedData.images_url || [];

                    if (imageUrls.length > 0) {
                      setMessages((prev) => {
                        const newMessages = [...prev];
                        const lastMsg = newMessages[newMessages.length - 1];

                        if (!lastMsg) {
                          return newMessages;
                        }

                        const updatedMsg = {
                          ...lastMsg,
                          images: deduplicateImages(
                            lastMsg.images || [],
                            imageUrls
                          ),
                        };
                        newMessages[newMessages.length - 1] = updatedMsg;
                        return newMessages;
                      });
                    }
                  } catch (error) {
                    log.error(
                      t("chatStreamHandler.processImageDataFailed"),
                      error
                    );
                  }
                  break;

                case chatConfig.messageTypes.FINAL_ANSWER:
                  // Accumulate final answer content and process user break tag
                  finalAnswer += processUserBreakTag(messageContent, t);
                  break;

                case chatConfig.messageTypes.PARSE:
                  // Code display message, skip
                  break;

                case chatConfig.messageTypes.TOOL:
                  // Only create a new execution prompt if the previous type is not executing
                  // This keeps the animation effect continuous
                  if (lastContentType === chatConfig.contentTypes.EXECUTION) {
                    break;
                  }

                  // If there's no currentStep, create one
                  if (!currentStep) {
                    currentStep = {
                      id: `step-tool-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 9)}`,
                      title: "Tool Execution",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: null,
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                  }

                  // Add temporary content for executing code
                  currentStep.contents.push({
                    id: `executing-${Date.now()}-${Math.random()
                      .toString(36)
                      .substring(2, 7)}`,
                    type: chatConfig.messageTypes.EXECUTING,
                    content: messageContent,
                    expanded: true,
                    timestamp: Date.now(),
                    isLoading: true,
                  });

                  // Save the original parsing content, but do not display it in the frontend
                  currentStep.parsingContent = messageContent;

                  // Update the last processed content type
                  lastContentType = chatConfig.contentTypes.EXECUTION;
                  break;

                case chatConfig.messageTypes.EXECUTION_LOGS:
                  // Execution result message, skip
                  break;

                case chatConfig.messageTypes.AGENT_NEW_RUN:
                  // If there's no currentStep, create one
                  if (!currentStep) {
                    currentStep = {
                      id: `step-agent-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 9)}`,
                      title: "Agent Run",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: null,
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                  }
                  const content =
                    messageContent === "<MCP_START>"
                      ? t("chatStreamHandler.connectingMcpServer")
                      : t("chatStreamHandler.thinking");
                  // Add a "Thinking..." content
                  currentStep.contents.push({
                    id: `agent-run-${Date.now()}-${Math.random()
                      .toString(36)
                      .substring(2, 7)}`,
                    type: chatConfig.messageTypes.AGENT_NEW_RUN,
                    content: content,
                    expanded: true,
                    timestamp: Date.now(),
                  });
                  break;

                case chatConfig.messageTypes.ERROR:
                  // If there's no currentStep, create one
                  if (!currentStep) {
                    currentStep = {
                      id: `step-error-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 9)}`,
                      title: "Error",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: null,
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                  }

                  // Add error content to the current step's contents array
                  currentStep.contents.push({
                    id: `error-${Date.now()}-${Math.random()
                      .toString(36)
                      .substring(2, 7)}`,
                    type: chatConfig.messageTypes.ERROR,
                    content: messageContent,
                    expanded: true,
                    timestamp: Date.now(),
                  });
                  break;

                case chatConfig.messageTypes.VERIFICATION:
                  if (!currentStep) {
                    currentStep = {
                      id: `step-verification-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 9)}`,
                      title: "Verification",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: null,
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                  }

                  currentStep.contents.push({
                    id: `verification-${Date.now()}-${Math.random()
                      .toString(36)
                      .substring(2, 7)}`,
                    type: chatConfig.messageTypes.VERIFICATION,
                    subType: "verification",
                    content: messageContent,
                    expanded: true,
                    timestamp: Date.now(),
                  });
                  lastContentType = chatConfig.contentTypes.VERIFICATION;
                  break;

                case chatConfig.messageTypes.MEMORY_SEARCH:
                  // If there's no currentStep, create one
                  if (!currentStep) {
                    currentStep = {
                      id: `step-memory-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 9)}`,
                      title: "Memory Search",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: null,
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                  }

                  // Check if there's already a memory_search message to update
                  const existingMemoryIndex = currentStep.contents.findIndex(
                    (item) =>
                      item.type === chatConfig.messageTypes.MEMORY_SEARCH
                  );

                  if (existingMemoryIndex >= 0) {
                    // Update existing memory search message
                    currentStep.contents[existingMemoryIndex].content =
                      messageContent;
                    currentStep.contents[existingMemoryIndex].timestamp =
                      Date.now();
                  } else {
                    // Add new memory search content to the current step's contents array
                    let memMsg = "";
                    try {
                      const m = JSON.parse(messageContent);
                      let txt = m.message || "";
                      switch (txt) {
                        case "<MEM_START>":
                          m.message = t("chatStreamHandler.memoryRetrieving");
                          break;
                        case "<MEM_DONE>":
                          m.message = t("chatStreamHandler.memoryRetrieved");
                          try {
                            const evt = new Event("nexent:new-memory");
                            window.dispatchEvent(evt);
                          } catch (_) { }
                          break;
                        case "<MEM_FAILED>":
                          m.message = t("chatStreamHandler.memoryFailed");
                          break;
                        default:
                          break;
                      }
                      memMsg = JSON.stringify(m);
                    } catch (_) {
                      memMsg = messageContent;
                    }
                    currentStep.contents.push({
                      id: `memory-search-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 7)}`,
                      type: chatConfig.messageTypes.MEMORY_SEARCH,
                      content: memMsg, // translated JSON string
                      expanded: true,
                      timestamp: Date.now(),
                    });
                  }

                  // Update the last processed content type
                  lastContentType = "memory_search";
                  break;

                case chatConfig.contentTypes.PREPROCESS:
                  // If there's no currentStep, create one
                  if (!currentStep) {
                    currentStep = {
                      id: `step-preprocess-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
                      title: "File Preprocessing",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: null,
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                  }

                  const normalizedPreprocessData = {
                    id: `preprocess-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
                    type: chatConfig.contentTypes.PREPROCESS,
                    content: messageContent,
                    expanded: true,
                    timestamp: Date.now(),
                  };

                  currentStep.contents.push(normalizedPreprocessData);

                  // Update the last processed content type
                  lastContentType = chatConfig.contentTypes.PREPROCESS;
                  break;

                case chatConfig.messageTypes.MAX_STEPS_REACHED:
                  // Parse the max steps reached event data
                  try {
                    const maxStepsData = JSON.parse(messageContent);
                    const completedSteps = maxStepsData.completedSteps || 0;

                    // If there's no currentStep, create one
                    if (!currentStep) {
                      currentStep = {
                        id: `step-max-steps-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
                        title: t("chatStreamHandler.maxStepsReached"),
                        content: "",
                        expanded: true,
                        contents: [],
                        metrics: null,
                        thinking: { content: "", expanded: true },
                        code: { content: "", expanded: true },
                        output: { content: "", expanded: true },
                      };
                    }

                    // Store the max steps info in the step
                    currentStep.maxStepsInfo = {
                      completedSteps: completedSteps,
                      maxSteps: maxStepsData.maxSteps || 0,
                      message: t("chatStreamHandler.maxStepsNotification", {
                        completedSteps,
                      }),
                    };

                    // Add the max steps content to current step's contents
                    currentStep.contents.push({
                      id: `max-steps-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
                      type: chatConfig.messageTypes.MAX_STEPS_REACHED,
                      content: messageContent,
                      expanded: true,
                      timestamp: Date.now(),
                    });
                  } catch (e) {
                    log.error(
                      t("chatStreamHandler.parseMaxStepsDataFailed"),
                      e
                    );
                  }
                  break;

                case chatConfig.messageTypes.SKILL_FILES:
                  // Process skill-generated file uploads (e.g., documents created by skills)
                  try {
                    const skillFilesData = JSON.parse(messageContent);
                    const skillUploads = skillFilesData.skill_file_uploads || [];

                    // Convert uploads to AttachmentItem format
                    const newAttachments = skillUploads
                      .filter((upload: any) => upload.status === "success")
                      .map((upload: any) => ({
                        type: "file",
                        name: upload.file_name || "document",
                        size: upload.file_size || 0,
                        object_name: upload.object_name,
                        url: upload.preview_url || upload.presigned_url || upload.object_name,
                        contentType: upload.mime_type,
                      }));

                    if (newAttachments.length > 0) {
                      setMessages((prev) => {
                        const newMessages = [...prev];
                        const lastMsg = newMessages[newMessages.length - 1];
                        if (lastMsg && lastMsg.role === MESSAGE_ROLES.ASSISTANT) {
                          const existingAttachments = lastMsg.attachments || [];
                          newMessages[newMessages.length - 1] = {
                            ...lastMsg,
                            attachments: [...existingAttachments, ...newAttachments],
                          };
                        }
                        return newMessages;
                      });
                    }
                  } catch (e) {
                    log.error(t("chatStreamHandler.streamResponseError"), e);
                  }
                  break;

                default:
                  // Process other types of messages
                  break;
              }

              // Update message content, display in real time
              setMessages((prev) => {
                const newMessages = [...prev];
                const lastMsg = newMessages[newMessages.length - 1];

                if (lastMsg && lastMsg.role === MESSAGE_ROLES.ASSISTANT) {
                  // Create a new object reference so React.memo detects the change
                  const updatedMsg = { ...lastMsg };

                  // Update the current step
                  if (currentStep) {
                    const steps = updatedMsg.steps ? [...updatedMsg.steps] : [];

                    // Find and update existing steps
                    const stepIndex = steps.findIndex(
                      (s) => s.id === currentStep?.id
                    );
                    if (stepIndex >= 0) {
                      steps[stepIndex] = currentStep;
                    } else {
                      // Only add new steps when there is content
                      if (
                        currentStep.contents &&
                        currentStep.contents.length > 0
                      ) {
                        steps.push(currentStep);
                      }
                    }

                    // Apply any pending metrics to existing steps
                    pendingMetrics.forEach((metrics, stepId) => {
                      const pendingStepIndex = steps.findIndex((s) => s.id === stepId);
                      if (pendingStepIndex >= 0) {
                        steps[pendingStepIndex] = { ...steps[pendingStepIndex], metrics };
                        pendingMetrics.delete(stepId);
                      }
                    });

                    updatedMsg.steps = steps;
                  }

                  // Update other special content
                  if (finalAnswer) updatedMsg.finalAnswer = finalAnswer;

                  newMessages[newMessages.length - 1] = updatedMsg;
                }

                return newMessages;
              });
            }
          } catch (parseError) { }
        }
      }
    }

    // Process the last line of buffer
    if (buffer.trim() && buffer.startsWith("data:")) {
      // Process the last line of data...
      resetTimeout(); // The last line of data also resets the timeout timer
      try {
        const jsonStr = buffer.substring(5).trim();
        const jsonData: JsonData = JSON.parse(jsonStr);

        if (jsonData.type && jsonData.content) {
          const messageType = jsonData.type;
          const messageContent = normalizeMessageContent(jsonData.content);

          // Process the last message, focusing on final_answer and card
          if (messageType === chatConfig.messageTypes.FINAL_ANSWER) {
            finalAnswer += messageContent;
          }
        }
      } catch (error) {
        log.error(t("chatStreamHandler.processRemainingDataFailed"), error);
      }
    }

    // Mark message as complete, and check all steps again to prevent duplicates
    setMessages((prev) => {
      const newMessages = [...prev];
      const lastMsg = newMessages[newMessages.length - 1];

      if (lastMsg && lastMsg.role === MESSAGE_ROLES.ASSISTANT) {
        // Create a new object reference so React.memo detects the change
        const updatedMsg = { ...lastMsg, isComplete: true };

        // Check and remove duplicate steps
        if (updatedMsg.steps && updatedMsg.steps.length > 0) {
          const uniqueSteps = [];
          const seenTitles = new Set();

          for (const step of updatedMsg.steps) {
            // If it is an empty step or there is already a step with the same title, skip it
            if (
              !step.contents ||
              step.contents.length === 0 ||
              seenTitles.has(step.title.trim())
            ) {
              continue;
            }

            seenTitles.add(step.title.trim());
            uniqueSteps.push(step);
          }

          // Update to the deduplicated step list
          updatedMsg.steps = uniqueSteps;
        }

        // Also persist any finalAnswer accumulated in the trailing buffer
        if (finalAnswer) updatedMsg.finalAnswer = finalAnswer;

        newMessages[newMessages.length - 1] = updatedMsg;
      }

      return newMessages;
    });

    // Reset the conversation switch status
    setIsSwitchedConversation(false);
  } catch (error) {
    // Don't log AbortError as it's expected when user stops the stream
    const err = error as Error;
    if (err.name !== "AbortError") {
      log.error(t("chatStreamHandler.streamResponseError"), error);
    }
    throw error; // Pass the error back to the original function for processing
  }

  return { finalAnswer };
};
