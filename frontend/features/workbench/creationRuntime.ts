import yaml from "js-yaml";

export interface SkillCreationDraft {
  files: Record<string, string>;
  complete: boolean;
  targets: string[] | null;
  started: boolean;
  checkpoints: Record<
    string,
    { files: Record<string, string>; started: boolean }
  >;
}

export const initialSkillCreationDraft: SkillCreationDraft = {
  files: {},
  complete: false,
  targets: null,
  started: false,
  checkpoints: {},
};

export interface SkillCreationEvent {
  type: string;
  content?: string;
  path?: string;
  paths?: string[];
  phase?: string;
  attempt_id?: string;
}

/** Keep generated files separate from the generic Agent's conversation state. */
export function applySkillCreationEvent(
  draft: SkillCreationDraft,
  event: SkillCreationEvent
): SkillCreationDraft {
  if (event.type === "model_attempt_control" && event.attempt_id) {
    const checkpoints = { ...draft.checkpoints };
    if (event.phase === "begin") {
      checkpoints[event.attempt_id] = {
        files: { ...draft.files },
        started: draft.started,
      };
      return { ...draft, checkpoints };
    }
    const saved = checkpoints[event.attempt_id];
    delete checkpoints[event.attempt_id];
    return event.phase === "rollback" && saved
      ? { ...draft, files: saved.files, started: saved.started, checkpoints }
      : { ...draft, checkpoints };
  }
  if (event.type === "agent_new_run") {
    return { ...draft, complete: false, started: false, targets: null };
  }
  if (event.type === "target_files") {
    return { ...draft, targets: event.paths?.length ? event.paths : null };
  }
  if (event.type === "skill_body" || event.type === "file_content") {
    const path = event.type === "skill_body" ? "SKILL.md" : event.path;
    if (!path) return draft;
    const files = { ...draft.files };
    if (!draft.started) {
      if (draft.targets) {
        for (const target of draft.targets) delete files[target];
      } else {
        for (const target of Object.keys(files)) delete files[target];
      }
    }
    files[path] = (files[path] ?? "") + (event.content ?? "");
    return { ...draft, files, started: true, complete: false };
  }
  if (event.type === "done") {
    return { ...draft, complete: Boolean(draft.files["SKILL.md"]?.trim()) };
  }
  if (event.type === "error") {
    return { ...draft, complete: false };
  }
  return draft;
}

export function buildSkillSavePayload(draft: SkillCreationDraft) {
  if (!draft.complete) return null;
  const raw = draft.files["SKILL.md"]?.trim();
  if (!raw) return null;
  const match = raw.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/);
  if (!match) return null;
  let metadata: Record<string, unknown>;
  try {
    const parsed = yaml.load(match[1]);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed))
      return null;
    metadata = parsed as Record<string, unknown>;
  } catch {
    return null;
  }
  const name = typeof metadata.name === "string" ? metadata.name.trim() : "";
  const description =
    typeof metadata.description === "string" ? metadata.description.trim() : "";
  if (!name || !description) return null;
  const tags = Array.isArray(metadata.tags)
    ? metadata.tags.filter((tag): tag is string => typeof tag === "string")
    : [];
  return {
    name,
    description,
    tags,
    source: "custom",
    content: raw.slice(match[0].length).trim(),
    files: Object.entries(draft.files)
      .filter(([path]) => path !== "SKILL.md")
      .map(([path, content]) => ({ path, content })),
  };
}
