import JSZip from "jszip";

/**
 * Data structure for importing an agent
 */
export interface ImportAgentData {
  agent_id: number;
  agent_info: Record<string, any>;
  mcp_info?: Array<{
    mcp_server_name: string;
    mcp_url: string;
  }>;
  business_logic_model_id?: number | null;
  business_logic_model_name?: string | null;
  skills?: Array<{ skill_name: string; skill_zip_base64: string }>;
}

/**
 * Convert ArrayBuffer to base64 string
 * Uses chunking for better performance with large files
 */
export const arrayBufferToBase64 = (buffer: ArrayBuffer): string => {
  let binary = "";
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;

  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode(...chunk);
  }

  return btoa(binary);
};

/**
 * Extract skill name from ZIP path (e.g. "skills/my-skill.zip" -> "my-skill")
 */
export const extractSkillNameFromPath = (path: string): string => {
  const filename = path.split("/").pop() || "";
  return filename.replace(/\.zip$/i, "");
};

export interface ParseAgentFileOptions {
  onFileNotFound?: (message: string) => void;
  onParseError?: (message: string) => void;
  onValidationError?: (message: string) => void;
  onGenericError?: (error: unknown) => void;
}

/**
 * Parse an agent import file (JSON or ZIP)
 * Returns the parsed ImportAgentData or null if parsing failed
 */
export async function parseAgentImportFile(
  file: File,
  options: ParseAgentFileOptions = {}
): Promise<ImportAgentData | null> {
  const { onFileNotFound, onParseError, onValidationError } = options;

  if (!file.name.endsWith(".json") && !file.name.endsWith(".zip")) {
    onParseError?.("businessLogic.config.error.invalidFileType");
    return null;
  }

  try {
    let agentData: ImportAgentData;

    if (file.name.endsWith(".zip")) {
      const zip = await JSZip.loadAsync(file);
      const agentJsonFile = zip.file("agent.json");
      if (!agentJsonFile) {
        onFileNotFound?.("agent.json not found in ZIP");
        return null;
      }
      const content = await agentJsonFile.async("string");
      try {
        agentData = JSON.parse(content);
      } catch {
        onParseError?.("businessLogic.config.error.invalidFileType");
        return null;
      }

      const skills: Array<{ skill_name: string; skill_zip_base64: string }> = [];
      const skillsFolder = zip.folder("skills");
      if (skillsFolder) {
        const skillFiles = Object.keys(zip.files).filter(
          (name) =>
            name.startsWith("skills/") && name.toLowerCase().endsWith(".zip")
        );
        for (const skillFileName of skillFiles) {
          const skillZipFile = zip.file(skillFileName);
          if (skillZipFile) {
            const skillZipContent = await skillZipFile.async("arraybuffer");
            const base64 = arrayBufferToBase64(skillZipContent);
            const skillName = extractSkillNameFromPath(skillFileName);
            skills.push({
              skill_name: skillName,
              skill_zip_base64: base64,
            });
          }
        }
      }
      agentData.skills = skills;
    } else {
      const fileContent = await file.text();
      try {
        agentData = JSON.parse(fileContent);
      } catch {
        onParseError?.("businessLogic.config.error.invalidFileType");
        return null;
      }
    }

    if (!agentData.agent_id || !agentData.agent_info) {
      onValidationError?.("businessLogic.config.error.invalidFileType");
      return null;
    }

    return agentData;
  } catch (error) {
    options.onGenericError?.(error);
    return null;
  }
}

/**
 * Trigger file input click and return a Promise that resolves with the selected file
 * Returns null if no file was selected
 */
export function selectFile(
  accept: string = ".json,.zip"
): Promise<File | null> {
  return new Promise((resolve) => {
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = accept;

    fileInput.onchange = (event) => {
      const file = (event.target as HTMLInputElement).files?.[0];
      resolve(file || null);
    };

    fileInput.click();
  });
}

/**
 * Open import wizard with file selection
 * This is a convenience function that combines file selection and parsing
 */
export async function openImportWizardWithFile(
  options: ParseAgentFileOptions & {
    onSuccess: (data: ImportAgentData) => void;
  }
): Promise<void> {
  const { onSuccess, onParseError } = options;
  const file = await selectFile(".json,.zip");

  if (!file) return;

  const data = await parseAgentImportFile(file, {
    onParseError: (msg) => onParseError?.(msg),
    ...options,
  });

  if (data) {
    onSuccess(data);
  }
}
