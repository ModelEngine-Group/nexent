import type { AidpUploadFailedItem } from "./aidpKnowledgeService";

export const getAidpUploadFailureDetails = (
  failedList: AidpUploadFailedItem[],
  language: string,
  fallbackMessage: string
) => {
  const isChinese = language.startsWith("zh");
  return failedList.map((item) => {
    const reason = isChinese
      ? item.reason_zh || item.reason_en
      : item.reason_en || item.reason_zh;
    return `${item.file_name}: ${reason || fallbackMessage}`;
  });
};
