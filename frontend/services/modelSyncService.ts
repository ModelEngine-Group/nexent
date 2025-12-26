import { modelService } from "./modelService";
import { ModelType } from "@/types/modelConfig";

const TYPES_TO_SYNC: ModelType[] = [
  ("llm" as unknown) as ModelType,
  ("embedding" as unknown) as ModelType,
  ("multi_embedding" as unknown) as ModelType,
  ("vlm" as unknown) as ModelType,
  ("tts" as unknown) as ModelType,
  ("stt" as unknown) as ModelType,
];

/**
 * Sync models from ModelEngine and verify connectivity.
 * Returns an object with overall success and per-model verification results.
 */
export async function syncModelEngine(apiKey: string) {
  let syncFailed = false;
  try {
    for (const type of TYPES_TO_SYNC) {
      try {
        const providerModels = await modelService.addProviderModel({
          provider: "modelengine",
          type: type as any,
          apiKey,
        });
        if (providerModels && providerModels.length > 0) {
          await modelService.addBatchCustomModel({
            api_key: apiKey,
            provider: "modelengine",
            type,
            models: providerModels,
          });
        }
      } catch (err) {
        // mark that at least one provider fetch failed
        syncFailed = true;
      }
    }

    // reload all models from backend
    const allModelsAfter = await modelService.getAllModels();
    const modelEngineModels = allModelsAfter.filter((m) => m.source === "modelengine");

    // update persisted api keys for modelengine models if needed
    if (modelEngineModels.length > 0 && apiKey) {
      const updates = modelEngineModels.map((m) => ({
        model_id: String(m.id || m.name || m.displayName),
        apiKey: apiKey,
      }));
      try {
        await modelService.updateBatchModel(updates);
      } catch (err) {
        // non-fatal; continue to verification but flag sync failure
        syncFailed = true;
      }
    }

    // verify each persistent model and collect results
    const verificationResults: Array<{ displayName: string; type: string; connected: boolean }> = [];
    for (const m of modelEngineModels) {
      if (!m.displayName) continue;
      try {
        const connected = await modelService.verifyCustomModel(m.displayName);
        verificationResults.push({ displayName: m.displayName, type: m.type, connected });
      } catch (err) {
        verificationResults.push({ displayName: m.displayName, type: m.type, connected: false });
      }
    }

    const anyUnavailable = verificationResults.some((r) => !r.connected);
    const success = !syncFailed && !anyUnavailable;
    return { success, verificationResults, error: syncFailed ? "provider_fetch_failed" : undefined };
  } catch (err: any) {
    return { success: false, verificationResults: [], error: err?.message || String(err) };
  }
}
