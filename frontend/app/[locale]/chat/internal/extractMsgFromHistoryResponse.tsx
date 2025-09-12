"use client";

import { ROLE_ASSISTANT } from "@/const/agentConfig";
import { chatConfig } from "@/const/chatConfig";
import {
  ApiMessage,
  SearchResult,
  AgentStep,
  ApiMessageItem,
  ChatMessageType,
  MinioFileItem,
} from "@/types/chat";
import log from "@/lib/logger";

// function: process the user break tag
const processSpecialTag = (content: string, t: any): string => {
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

export function extractAssistantMsgFromResponse(
  dialog_msg: ApiMessage,
  index: number,
  create_time: number,
  t: any
) {
  let searchResultsContent: SearchResult[] = [];
  if (
    dialog_msg.search &&
    Array.isArray(dialog_msg.search) &&
    dialog_msg.search.length > 0
  ) {
    searchResultsContent = dialog_msg.search.map((item) => ({
      title: item.title || t("extractMsg.unknownTitle"),
      url: item.url || "#",
      text: item.text || t("extractMsg.noContentDescription"),
      published_date: item.published_date || "",
      source_type: item.source_type || "",
      filename: item.filename || "",
      score: typeof item.score === "number" ? item.score : undefined,
      score_details: item.score_details || {},
      tool_sign: item.tool_sign || "",
      cite_index: typeof item.cite_index === "number" ? item.cite_index : -1,
    }));
  }

  // handle images
  let imagesContent: string[] = [];
  if (
    dialog_msg.picture &&
    Array.isArray(dialog_msg.picture) &&
    dialog_msg.picture.length > 0
  ) {
    imagesContent = dialog_msg.picture;
  }

  // extract the content of the Message
  let finalAnswer = "";
  let steps: AgentStep[] = [];
  if (dialog_msg.message && Array.isArray(dialog_msg.message)) {
    dialog_msg.message.forEach((msg: ApiMessageItem) => {
      switch (msg.type) {
        case chatConfig.messageTypes.FINAL_ANSWER: {
          // process the final_answer content and identify the user break tag
          finalAnswer += processSpecialTag(msg.content, t);
          break;
        }

        case chatConfig.messageTypes.STEP_COUNT: {
          // create a new step
          steps.push({
            id: `step-${steps.length + 1}`,
            title: msg.content.trim(),
            content: "",
            expanded: false,
            contents: [],
            metrics: "",
            thinking: { content: "", expanded: false },
            code: { content: "", expanded: false },
            output: { content: "", expanded: false },
          });
          break;
        }

        case chatConfig.messageTypes.MODEL_OUTPUT_THINKING: {
          const currentStep = steps[steps.length - 1];
          if (currentStep) {
            const contentId = `model-${Date.now()}-${Math.random()
              .toString(36)
              .substring(2, 7)}`;
            currentStep.contents.push({
              id: contentId,
              type: "model_output",
              subType: "thinking",
              content: msg.content,
              expanded: true,
              timestamp: Date.now(),
            });
          }
          break;
        }

        case chatConfig.messageTypes.EXECUTION_LOGS: {
          const currentStep = steps[steps.length - 1];
          if (currentStep) {
            // create a new execution output
            const contentId = `execution-${Date.now()}-${Math.random()
              .toString(36)
              .substring(2, 7)}`;

            currentStep.contents.push({
              id: contentId,
              type: "execution",
              content: msg.content,
              expanded: true,
              timestamp: Date.now(),
            });
          }
          break;
        }

        case chatConfig.messageTypes.ERROR: {
          const currentStep = steps[steps.length - 1];
          if (currentStep) {
            // create the error content
            const contentId = `error-${Date.now()}-${Math.random()
              .toString(36)
              .substring(2, 7)}`;
            currentStep.contents.push({
              id: contentId,
              type: "error",
              content: msg.content,
              expanded: true,
              timestamp: Date.now(),
            });
          }
          break;
        }

        case chatConfig.messageTypes.SEARCH_CONTENT_PLACEHOLDER: {
          const currentStep = steps[steps.length - 1];
          if (currentStep) {
            try {
              // parse placeholder content to get unit_id
              const placeholderData = JSON.parse(msg.content);
              const unitId = placeholderData.unit_id;

              if (
                unitId &&
                dialog_msg.search_unit_id &&
                dialog_msg.search_unit_id[unitId.toString()]
              ) {
                // get the corresponding search results according to unit_id
                const unitSearchResults =
                  dialog_msg.search_unit_id[unitId.toString()];

                // create the JSON string of search content
                const searchContent = JSON.stringify(unitSearchResults);

                // add the search content as a search_content type message
                const contentId = `search-content-${Date.now()}-${Math.random()
                  .toString(36)
                  .substring(2, 7)}`;
                currentStep.contents.push({
                  id: contentId,
                  type: "search_content",
                  content: searchContent,
                  expanded: true,
                  timestamp: Date.now(),
                });
              }
            } catch (e) {
              log.error(t("extractMsg.cannotParseSearchPlaceholder"), e);
            }
          }
          break;
        }

        case chatConfig.messageTypes.TOKEN_COUNT: {
          const currentStep = steps[steps.length - 1];
          if (currentStep) {
            currentStep.metrics = msg.content;
          }
          break;
        }

        case chatConfig.messageTypes.CARD: {
          const currentStep = steps[steps.length - 1];
          if (currentStep) {
            // create the card content
            const contentId = `card-${Date.now()}-${Math.random()
              .toString(36)
              .substring(2, 7)}`;
            currentStep.contents.push({
              id: contentId,
              type: "card",
              content: msg.content,
              expanded: true,
              timestamp: Date.now(),
            });
          }
          break;
        }

        case chatConfig.messageTypes.TOOL: {
          const currentStep = steps[steps.length - 1];
          if (currentStep) {
            // create the tool call content
            const contentId = `tool-${Date.now()}-${Math.random()
              .toString(36)
              .substring(2, 7)}`;
            currentStep.contents.push({
              id: contentId,
              type: "executing", // use the existing executing type to represent the tool call
              content: msg.content,
              expanded: true,
              timestamp: Date.now(),
            });
          }
          break;
        }

        default:
          // handle other types of messages
          break;
      }
    });
  }

  // create the formatted assistant message
  const formattedAssistantMsg: ChatMessageType = {
    id: `assistant-${index}-${Date.now()}`,
    role: ROLE_ASSISTANT,
    message_id: dialog_msg.message_id,
    content: "",
    opinion_flag: dialog_msg.opinion_flag,
    timestamp: new Date(create_time),
    steps: steps,
    finalAnswer: finalAnswer,
    agentRun: "",
    isComplete: true,
    showRawContent: false,
    searchResults: searchResultsContent,
    images: imagesContent,
    attachments: undefined,
  };
  return formattedAssistantMsg;
}

export function extractUserMsgFromResponse(
  dialog_msg: ApiMessage,
  index: number,
  create_time: number
) {
  let userContent = "";
  if (Array.isArray(dialog_msg.message)) {
    const stringMessage = dialog_msg.message.find(
      (m: { type: string; content: string }) => m.type === "string"
    );
    userContent = stringMessage?.content || "";
  } else if (typeof dialog_msg.message === "string") {
    userContent = dialog_msg.message;
  } else if (dialog_msg.message && typeof dialog_msg.message === "object") {
    const msgObj = dialog_msg.message as { content?: string };
    userContent = msgObj.content || "";
  }

  // handle the minio_files of the user message
  let userAttachments: MinioFileItem[] = [];
  if (
    dialog_msg.minio_files &&
    Array.isArray(dialog_msg.minio_files) &&
    dialog_msg.minio_files.length > 0
  ) {
    // handle the minio_files
    userAttachments = dialog_msg.minio_files.map((item) => {
      return {
        type: item.type || "",
        name: item.name || "",
        size: item.size || 0,
        object_name: item.object_name,
        url: item.url,
        description: item.description,
      };
    });
  }

  const formattedUserMsg: ChatMessageType = {
    id: `user-${index}-${Date.now()}`,
    role: "user",
    message_id: dialog_msg.message_id,
    content: userContent,
    opinion_flag: dialog_msg.opinion_flag, // user message does not have the like/dislike status
    timestamp: new Date(create_time),
    showRawContent: true,
    isComplete: true,
    // add the attachments field, no longer use minio_files
    attachments: userAttachments.length > 0 ? userAttachments : undefined,
  };
  return formattedUserMsg;
}
