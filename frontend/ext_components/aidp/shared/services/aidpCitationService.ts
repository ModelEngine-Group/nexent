import aidpKnowledgeService from "./aidpKnowledgeService";
import type { AidpDownloadLocator } from "@/types/source";

/** Download an explicitly located original file through the existing AIDP proxy. */
export async function downloadAidpCitation(
  locator: AidpDownloadLocator,
  filename: string
): Promise<void> {
  const response = await aidpKnowledgeService.downloadDoc(
    locator.kds_id,
    locator.file_uuid
  );
  const blobUrl = URL.createObjectURL(await response.blob());
  try {
    const link = document.createElement("a");
    link.href = blobUrl;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}
