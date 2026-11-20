// Copyright (c) 2025-2026 Huawei Technologies Co., Ltd. All rights reserved.

import { journey } from "../../infra/automation/d4/runner/journey";
import { loginCurrent } from "../../infra/automation/d4/runner/sessions";
import { AidpKnowledgePage } from "../../infra/automation/d4/pages/aidp-knowledge.page";

/**
 * PW-KB-AIDP-02 — AIDP knowledge base chunk settings, end to end.
 *
 * Proves the user-visible chunk configuration introduced by commit 01400d399:
 * the create page shows the AIDP defaults (512 tokens, 10 percent overlap,
 * Top K 10, similarity 0) instead of the retired 1024 / 12.5 percent pair, the
 * Information tab lists chunk tokens and overlap in create order with stored
 * values, the chunk edit modal reuses the create page mode cards, an edited
 * chunk token survives a full page reload, and an out-of-range overlap is
 * rejected without a partial write.
 *
 * Contract IDs come from case.yaml through contract.expectedIds, so the step
 * and assertion counts stay coupled to the authored contract.
 */

const RETIRED_CHUNK_TOKENS = "1024";
const RETIRED_OVERLAP_PERCENT = "12.5";
const EXPECTED_CHUNK_TOKENS = "512";
const EXPECTED_OVERLAP_PERCENT = "10";
const EXPECTED_TOPK = "10";
const EDIT_TO_CHUNK_TOKENS = 1024;

journey("PW-KB-AIDP-02", async (context) => {
  const { page, contract } = context;
  const aidp = new AidpKnowledgePage(page);
  const runTag = `aidp-chunk-${Date.now().toString(36)}`;
  const kbName = `chunk-ui-${runTag}`;

  type Defaults = Awaited<ReturnType<AidpKnowledgePage["openCreatePageAndReadChunkDefaults"]>>;
  type InfoRows = Awaited<ReturnType<AidpKnowledgePage["readInformationChunkRows"]>>;

  let observedDefaults: Defaults;
  let infoRowsAfterEdit: InfoRows;

  await contract.precondition(contract.expectedIds("preconditions")[0], async () => {
    await loginCurrent(page, "tenant_a_admin");
    await aidp.open();
    return "AIDP branch is active and the Local storage control is absent";
  });

  // Step 1 — create page chunk defaults.
  await contract.step(contract.expectedIds("steps")[0], async () => {
    observedDefaults = await aidp.openCreatePageAndReadChunkDefaults();
    // Reject the retired pair first, so the assertion message names the actual
    // regression instead of only reporting a mismatch against the new default.
    if (observedDefaults.chunkTokens === RETIRED_CHUNK_TOKENS) {
      throw new Error("create page still shows the retired 1024 chunk token default");
    }
    if (observedDefaults.overlapPercent === RETIRED_OVERLAP_PERCENT) {
      throw new Error("create page still shows the retired 12.5 percent overlap default");
    }
    if (observedDefaults.chunkTokens !== EXPECTED_CHUNK_TOKENS) {
      throw new Error(
        `create page chunk tokens must default to ${EXPECTED_CHUNK_TOKENS}, got ${observedDefaults.chunkTokens}`
      );
    }
    if (observedDefaults.overlapPercent !== EXPECTED_OVERLAP_PERCENT) {
      throw new Error(
        `create page overlap must default to ${EXPECTED_OVERLAP_PERCENT} percent, got ${observedDefaults.overlapPercent}`
      );
    }
    if (observedDefaults.topk !== EXPECTED_TOPK) {
      throw new Error(`create page Top K must default to ${EXPECTED_TOPK}, got ${observedDefaults.topk}`);
    }
    if (Number(observedDefaults.similarity) !== 0) {
      throw new Error(`create page similarity must default to 0, got ${observedDefaults.similarity}`);
    }
    return `chunk=${observedDefaults.chunkTokens}, overlap=${observedDefaults.overlapPercent}%, topk=${observedDefaults.topk}, similarity=${observedDefaults.similarity}`;
  });

  // Step 2 — chunk mode cards.
  await contract.step(contract.expectedIds("steps")[1], async () => {
    await aidp.expectChunkModeCards();
    return "both chunk mode cards render and smart splitting is preselected";
  });

  // Step 3 — create the run-owned knowledge base.
  await contract.step(contract.expectedIds("steps")[2], async () => {
    await aidp.createKnowledgeBase({
      name: kbName,
      description: `chunk settings journey ${runTag}`,
      embeddingModelLabel: "bge-m3",
    });
    return `knowledge base ${kbName} created`;
  });

  // Step 4 — Information tab shows stored chunk values in create order.
  await contract.step(contract.expectedIds("steps")[3], async () => {
    await aidp.openInformationTab();
    const rows = await aidp.readInformationChunkRows();
    if (!rows.chunkToken.includes(EXPECTED_CHUNK_TOKENS)) {
      throw new Error(
        `Information tab must show chunk tokens ${EXPECTED_CHUNK_TOKENS}, got ${JSON.stringify(rows.chunkToken)}`
      );
    }
    if (!rows.chunkOverlap.includes(EXPECTED_OVERLAP_PERCENT)) {
      throw new Error(
        `Information tab must show overlap ${EXPECTED_OVERLAP_PERCENT} percent, got ${JSON.stringify(rows.chunkOverlap)}`
      );
    }
    if (rows.chunkToken.includes("--")) {
      throw new Error("Information tab renders a placeholder instead of the stored chunk token value");
    }
    return `chunk row=${JSON.stringify(rows.chunkToken)}, overlap row=${JSON.stringify(rows.chunkOverlap)}`;
  });

  // Step 5 — edit modal reuses the create page mode cards.
  await contract.step(contract.expectedIds("steps")[4], async () => {
    await aidp.openChunkTokenEditor();
    return "the chunk token edit modal offers the same chunk mode cards";
  });

  // Step 6 — edit the chunk token.
  await contract.step(contract.expectedIds("steps")[5], async () => {
    await aidp.saveChunkToken(EDIT_TO_CHUNK_TOKENS);
    return `chunk tokens saved as ${EDIT_TO_CHUNK_TOKENS}`;
  });

  // Step 7 — persistence across a full reload.
  await contract.step(contract.expectedIds("steps")[6], async () => {
    await page.reload({ waitUntil: "domcontentloaded" });
    await aidp.openInformationTab();
    infoRowsAfterEdit = await aidp.readInformationChunkRows();
    if (!infoRowsAfterEdit.chunkToken.includes(String(EDIT_TO_CHUNK_TOKENS))) {
      throw new Error(
        `chunk tokens must read back ${EDIT_TO_CHUNK_TOKENS} after reload, got ${JSON.stringify(infoRowsAfterEdit.chunkToken)}`
      );
    }
    if (!infoRowsAfterEdit.chunkOverlap.includes(EXPECTED_OVERLAP_PERCENT)) {
      throw new Error(
        `overlap percentage must stay ${EXPECTED_OVERLAP_PERCENT} after the chunk token edit, got ${JSON.stringify(infoRowsAfterEdit.chunkOverlap)}`
      );
    }
    return `chunk row after reload=${JSON.stringify(infoRowsAfterEdit.chunkToken)}`;
  });

  // Step 8 — an out-of-range overlap is rejected without a partial write.
  await contract.step(contract.expectedIds("steps")[7], async () => {
    await aidp.openChunkTokenEditorAndRejectOutOfRangeOverlap();
    await aidp.openInformationTab();
    const rows = await aidp.readInformationChunkRows();
    if (!rows.chunkToken.includes(String(EDIT_TO_CHUNK_TOKENS))) {
      throw new Error(
        `a rejected overlap must leave chunk tokens at ${EDIT_TO_CHUNK_TOKENS}, got ${JSON.stringify(rows.chunkToken)}`
      );
    }
    return "out-of-range overlap rejected and the previous chunk token preserved";
  });

  // Step 9 — cleanup.
  await contract.step(contract.expectedIds("steps")[8], async () => {
    await aidp.returnToListAndSearch(kbName);
    await aidp.deleteKnowledgeBase(kbName);
    await aidp.expectKnowledgeBaseAbsent(kbName);
    return `knowledge base ${kbName} deleted`;
  });

  // Step 10 — the journey lands leaving no run-owned knowledge base behind.
  await contract.step(contract.expectedIds("steps")[9], async () => {
    await aidp.expectKnowledgeBaseAbsent(kbName);
    return `no residual knowledge base named ${kbName}`;
  });
});
