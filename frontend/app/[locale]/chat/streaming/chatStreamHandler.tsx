// Tool function for processing chat streaming response

import { chatConfig } from "@/const/chatConfig";
import { ChatMessageType, AgentStep } from "@/types/chat";
import log from "@/lib/logger";
import { MESSAGE_ROLES } from "@/const/chatConfig";

import {
  deduplicateImages,
  deduplicateSearchResults,
} from "../internal/chatHelpers";

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
}

// Processing Streaming Response Data
export const handleStreamResponse = async (
  reader: ReadableStreamDefaultReader<Uint8Array>,
  setMessages: React.Dispatch<React.SetStateAction<ChatMessageType[]>>,
  resetTimeout: () => void,
  stepIdCounter: React.MutableRefObject<number>,
  setIsSwitchedConversation: React.Dispatch<React.SetStateAction<boolean>>,
  isNewConversation: boolean,
  setConversationTitle: (title: string) => void,
  fetchConversationList: () => Promise<any>,
  currentConversationId: number,
  // TODO: Sevice should not be passed but imported
  conversationService: any,
  isDebug: boolean = false,
  t: any
) => {
  const decoder = new TextDecoder();
  let buffer = "";

  // Used to accumulate different types of content

  // Create an empty step object
  let currentStep: AgentStep = {
    id: ``,
    title: "",
    content: "",
    expanded: true,
    contents: [],
    metrics: "",
    thinking: { content: "", expanded: true },
    code: { content: "", expanded: true },
    output: { content: "", expanded: true },
  };

  // Generate conversation title immediately when stream starts (for new conversations)
  // This runs in parallel with the streaming response
  if (isNewConversation) {
    // Use setTimeout to ensure the user message has been added to state
    setTimeout(async () => {
      try {
        // Get the current messages to find the user's question
        setMessages((prevMessages) => {
          const firstUserMessage = prevMessages.find(
            (msg) => msg.role === MESSAGE_ROLES.USER
          );
          if (firstUserMessage?.content) {
            // Call the generate title from question interface
            conversationService
              .generateTitle({
                conversation_id: currentConversationId,
                question: firstUserMessage.content,
              })
              .then((title: string) => {
                if (title) {
                  setConversationTitle(title);
                }
                // Update the conversation list
                fetchConversationList();
              })
              .catch((error: Error) => {
                log.error(
                  t("chatStreamHandler.generateTitleFailed"),
                  error
                );
              });
          }
          return prevMessages;
        });
      } catch (error) {
        log.error(t("chatStreamHandler.generateTitleFailed"), error);
      }
    }, 0);
  }

  let lastContentType:
    | typeof chatConfig.contentTypes.MODEL_OUTPUT
    | typeof chatConfig.contentTypes.MODEL_OUTPUT_CODE
    | typeof chatConfig.contentTypes.PARSING
    | typeof chatConfig.contentTypes.EXECUTION
    | typeof chatConfig.contentTypes.AGENT_NEW_RUN
    | typeof chatConfig.contentTypes.GENERATING_CODE
    | typeof chatConfig.contentTypes.SEARCH_CONTENT
    | typeof chatConfig.contentTypes.CARD
    | typeof chatConfig.contentTypes.MEMORY_SEARCH
    | typeof chatConfig.contentTypes.PREPROCESS
    | null = null;
  let lastModelOutputIndex = -1; // Track the index of the last model output in currentStep.contents
  let lastCodeOutputIndex = -1; // Track the index of the last code output for proper streaming
  let searchResultsContent: any[] = [];
  let allSearchResults: any[] = [];
  let finalAnswer = "";

  try {
    while (true) {
      let readResult;
      try {
        readResult = await reader.read();
      } catch (readError: any) {
        // If read is aborted, break the loop gracefully
        if (readError?.name === "AbortError" || readError?.name === "AbortSignal") {
          break;
        }
        throw readError;
      }
      const { done, value } = readResult;
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (line.startsWith("data:")) {
          resetTimeout(); // Reset the timeout timer each time new data is received
          const jsonStr = line.substring(5).trim();

          try {
            // Parse the JSON data received each time
            const jsonData: JsonData = JSON.parse(jsonStr);

            if (jsonData.type && jsonData.content) {
              const messageType = jsonData.type;
              const messageContent = jsonData.content;

              // Process different types of messages
              switch (messageType) {
                case chatConfig.messageTypes.STEP_COUNT:
                  // Increment the counter for each new step
                  stepIdCounter.current += 1;

                  // Create a new step - use the counter and UUID combination to generate a unique ID
                  currentStep = {
                    id: `step-${
                      stepIdCounter.current
                    }-${Date.now()}-${Math.random()
                      .toString(36)
                      .substring(2, 9)}`,
                    title: messageContent.trim(),
                    content: "",
                    expanded: true,
                    contents: [], // Use an array to store all content in order
                    metrics: "",
                    thinking: { content: "", expanded: true },
                    code: { content: "", expanded: true },
                    output: { content: "", expanded: true },
                  };

                  // Reset status tracking variables
                  lastContentType = null;
                  lastModelOutputIndex = -1;
                  lastCodeOutputIndex = -1;

                  break;

                case chatConfig.messageTypes.TOKEN_COUNT:
                  // Process token counting logic
                  currentStep.metrics = messageContent;
                  break;

                case chatConfig.messageTypes.MODEL_OUTPUT:
                  // Process main model output content

                  // If there's no currentStep, create one for simple responses
                  if (!currentStep) {
                    currentStep = {
                      id: `step-simple-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 9)}`,
                      title: "AI Response",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: "",
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                  }

                  // If the last streaming output is model output, append
                  if (
                    lastContentType === chatConfig.contentTypes.MODEL_OUTPUT &&
                    lastModelOutputIndex >= 0
                  ) {
                    const modelOutput =
                      currentStep.contents[lastModelOutputIndex];
                    modelOutput.content = modelOutput.content + messageContent;
                  } else {
                    // Otherwise, create new model output content
                    currentStep.contents.push({
                      id: `model-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 7)}`,
                      type: chatConfig.messageTypes.MODEL_OUTPUT,
                      content: messageContent,
                      expanded: true,
                      timestamp: Date.now(),
                    });
                    lastModelOutputIndex = currentStep.contents.length - 1;
                  }

                  // Update the last processed content type
                  lastContentType = chatConfig.contentTypes.MODEL_OUTPUT;
                  break;

                case chatConfig.messageTypes.MODEL_OUTPUT_THINKING:
                  // Merge consecutive thinking chunks; create new group only when previous subType is not "thinking"
                  if (!currentStep) {
                    currentStep = {
                      id: `step-thinking-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 9)}`,
                      title: "AI Thinking",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: "",
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                  }

                  const shouldAppendThinking =
                    lastContentType === chatConfig.contentTypes.MODEL_OUTPUT &&
                    lastModelOutputIndex >= 0 &&
                    currentStep.contents[lastModelOutputIndex] &&
                    currentStep.contents[lastModelOutputIndex].subType ===
                      "thinking";

                  if (shouldAppendThinking) {
                    // Append to existing thinking content
                    currentStep.contents[lastModelOutputIndex].content +=
                      messageContent;
                  } else {
                    // Create a new thinking content group
                    currentStep.contents.push({
                      id: `thinking-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 7)}`,
                      type: chatConfig.messageTypes.MODEL_OUTPUT,
                      subType: "thinking",
                      content: messageContent,
                      expanded: true,
                      timestamp: Date.now(),
                    });
                    lastModelOutputIndex = currentStep.contents.length - 1;
                  }

                  lastContentType = chatConfig.contentTypes.MODEL_OUTPUT;
                  break;

                case chatConfig.messageTypes.MODEL_OUTPUT_DEEP_THINKING:
                  // Consecutive deep_thinking chunks should be combined until a thinking chunk arrives
                  if (!currentStep) {
                    currentStep = {
                      id: `step-thinking-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 9)}`,
                      title: "AI Thinking",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: "",
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                  }

                  const shouldAppendDeep =
                    lastContentType === chatConfig.contentTypes.MODEL_OUTPUT &&
                    lastModelOutputIndex >= 0 &&
                    currentStep.contents[lastModelOutputIndex] &&
                    currentStep.contents[lastModelOutputIndex].subType ===
                      "deep_thinking";

                  if (shouldAppendDeep) {
                    // Append to existing deep_thinking content
                    currentStep.contents[lastModelOutputIndex].content +=
                      messageContent;
                  } else {
                    // Create a new deep_thinking content group
                    currentStep.contents.push({
                      id: `deep-thinking-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 7)}`,
                      type: chatConfig.messageTypes.MODEL_OUTPUT,
                      subType: "deep_thinking",
                      content: messageContent,
                      expanded: true,
                      timestamp: Date.now(),
                    });
                    lastModelOutputIndex = currentStep.contents.length - 1;
                  }

                  lastContentType = chatConfig.contentTypes.MODEL_OUTPUT;
                  break;

                case chatConfig.messageTypes.MODEL_OUTPUT_CODE:
                  // Process code generation
                  // If there's no currentStep, create one
                  if (!currentStep) {
                    currentStep = {
                      id: `step-code-${Date.now()}-${Math.random()
                        .toString(36)
                        .substring(2, 9)}`,
                      title: "Code Generation",
                      content: "",
                      expanded: true,
                      contents: [],
                      metrics: "",
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                  }

                  if (isDebug) {
                    // In debug mode, use MODEL_OUTPUT_CODE type for streaming output
                    let processedContent = messageContent;

                    // Check if we should append to existing code content
                    // Only append if the last content type was MODEL_OUTPUT_CODE and we have a valid index
                    const shouldAppendCode =
                      lastContentType === chatConfig.contentTypes.MODEL_OUTPUT_CODE &&
                      lastCodeOutputIndex >= 0 &&
                      currentStep.contents[lastCodeOutputIndex] &&
                      currentStep.contents[lastCodeOutputIndex].type ===
                        chatConfig.messageTypes.MODEL_OUTPUT_CODE;

                    if (shouldAppendCode) {
                      const codeOutput =
                        currentStep.contents[lastCodeOutputIndex];
                      const codePrefix = t("chatStreamHandler.codePrefix");

                      // In append mode, also check for prefix in case it wasn't removed before
                      if (
                        codeOutput.content.includes(codePrefix) &&
                        processedContent.trim()
                      ) {
                        // Clean existing content
                        codeOutput.content = codeOutput.content.replace(
                          new RegExp(`^(${codePrefix}|代码|Code)[：:]\\s*`, "i"),
                          ""
                        );
                      }

                      // Directly append the new content
                      let newContent = codeOutput.content + processedContent;
                      // Remove incomplete "<end" suffix if present (streaming artifact)
                      if (newContent.endsWith("<end")) {
                        newContent = newContent.slice(0, -4);
                      }
                      codeOutput.content = newContent;
                    } else {
                      // Create new code content with MODEL_OUTPUT_CODE type
                      // Remove "代码：" or "Code:" prefix if present at the start
                      const codePrefix = t("chatStreamHandler.codePrefix");
                      if (processedContent.startsWith(codePrefix)) {
                        processedContent = processedContent.substring(
                          codePrefix.length
                        );
                      }
                      // Also handle Chinese and English variants directly
                      processedContent = processedContent.replace(/^(代码|Code)[：:]\s*/i, "");
                      
                      // Remove incomplete "<end" suffix if present
                      if (processedContent.endsWith("<end")) {
                        processedContent = processedContent.slice(0, -4);
                      }
                      
                      currentStep.contents.push({
                        id: `model-code-${Date.now()}-${Math.random()
                          .toString(36)
                          .substring(2, 7)}`,
                        type: chatConfig.messageTypes.MODEL_OUTPUT_CODE,
                        content: processedContent,
                        expanded: true,
                        timestamp: Date.now(),
                      });
                      // Track the new code content index
                      lastCodeOutputIndex = currentStep.contents.length - 1;
                    }

                    // Update the last processed content type to MODEL_OUTPUT_CODE
                    lastContentType = chatConfig.contentTypes.MODEL_OUTPUT_CODE;
                  } else {
                    // In non-debug mode, use the original logic - add a stable loading prompt
                    // Check if there is a code generation prompt
                    if (lastContentType === chatConfig.contentTypes.GENERATING_CODE) {
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
                      metrics: "",
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
                          metrics: "",
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

                      if (!lastMsg.searchResults) {
                        lastMsg.searchResults = [];
                      }

                      // Use the public deduplication function to process search results
                      if (
                        searchResultsContent &&
                        searchResultsContent.length > 0
                      ) {
                        lastMsg.searchResults = deduplicateSearchResults(
                          lastMsg.searchResults,
                          searchResultsContent
                        );
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
                    // Parse the image data structure
                    let imageUrls = JSON.parse(messageContent).images_url;

                    if (imageUrls.length > 0) {
                      // Update the images of the current message
                      setMessages((prev) => {
                        const newMessages = [...prev];
                        const lastMsg = newMessages[newMessages.length - 1];

                        // Check if lastMsg exists before accessing its properties
                        if (!lastMsg) {
                          return newMessages;
                        }

                        // If there is no image array, initialize it
                        if (!lastMsg.images) {
                          lastMsg.images = [];
                        }

                        // Use the public deduplication function to process images
                        lastMsg.images = deduplicateImages(
                          lastMsg.images,
                          imageUrls
                        );
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
                      metrics: "",
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
                      metrics: "",
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
                      metrics: "",
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
                      metrics: "",
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true },
                    };
                  }

                  // Check if there's already a memory_search message to update
                  const existingMemoryIndex = currentStep.contents.findIndex(
                    (item) => item.type === chatConfig.messageTypes.MEMORY_SEARCH
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
                          } catch (_) {}
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
                      metrics: "",
                      thinking: { content: "", expanded: true },
                      code: { content: "", expanded: true },
                      output: { content: "", expanded: true }
                    };
                  }

                  const normalizedPreprocessData = {
                    id: `preprocess-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`,
                    type: chatConfig.contentTypes.PREPROCESS,
                    content: messageContent,
                    expanded: true,
                    timestamp: Date.now()
                  };

                  currentStep.contents.push(normalizedPreprocessData);

                  // Update the last processed content type
                  lastContentType = chatConfig.contentTypes.PREPROCESS;
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
                  // Update the current step
                  if (currentStep) {
                    if (!lastMsg.steps) lastMsg.steps = [];

                    // Find and update existing steps
                    const stepIndex = lastMsg.steps.findIndex(
                      (s) => s.id === currentStep?.id
                    );
                    if (stepIndex >= 0) {
                      lastMsg.steps[stepIndex] = currentStep;
                    } else {
                      // Only add new steps when there is content
                      if (
                        currentStep.contents &&
                        currentStep.contents.length > 0
                      ) {
                        lastMsg.steps.push(currentStep);
                      }
                    }
                  }

                  // Update other special content
                  if (finalAnswer) lastMsg.finalAnswer = finalAnswer;
                }

                return newMessages;
              });
            }
          } catch (parseError) {}
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
          const messageContent = jsonData.content;

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
        lastMsg.isComplete = true;

        // Check and remove duplicate steps
        if (lastMsg.steps && lastMsg.steps.length > 0) {
          const uniqueSteps = [];
          const seenTitles = new Set();

          for (const step of lastMsg.steps) {
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
          lastMsg.steps = uniqueSteps;
        }
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
