/** TPC-D4-001: run with the authenticated Codex built-in browser tab. */
export async function test_tpc_d4_001({ tab, url, savedTitle, save }) {
  const wait = async (locator, state, timeoutMs = 30000) => {
    const deadline = Date.now() + timeoutMs;
    while (true) {
      try { await locator.waitFor({ state, timeoutMs: 3000 }); return; }
      catch (error) {
        if (!/selector deadline exceeded|Timed out after/.test(String(error)) || Date.now() >= deadline) throw error;
      }
    }
  };
  const dismissMemoryWarning = async () => {
    // On initial hydration the auth/embedding recheck can reopen this warning.
    // Resolve the current dialog each time; do not reuse a pre-reload handle.
    await wait(tab.playwright.getByRole('dialog', { name: 'Embedding model not configured', exact: true }), 'visible');
    for (let attempt = 0; attempt < 3; attempt++) {
      const dialog = tab.playwright.getByRole('dialog', { name: 'Embedding model not configured', exact: true });
      if (!(await dialog.isVisible())) return;
      await dialog.getByRole('button', { name: 'Close', exact: true }).click();
      await tab.playwright.domSnapshot();
      try { await dialog.waitFor({ state: 'hidden', timeoutMs: 3000 }); return; }
      catch (error) { if (!/selector deadline exceeded|Timed out/.test(String(error))) throw error; }
    }
    throw new Error('Embedding warning did not close within three attempts');
  };
  const require = (value, message) => { if (!value) throw new Error(message); };
  await tab.goto(url);
  await wait(tab.playwright.getByRole('button', { name: 'PR4060 Repair Acceptance Controlled semantic repair verification', exact: true }), 'visible');
  await dismissMemoryWarning();
  await tab.playwright.getByRole('button', { name: 'PR4060 Repair Acceptance Controlled semantic repair verification', exact: true }).click();
  await wait(tab.playwright.getByRole('textbox', { name: 'Send a message...', exact: true }), 'visible');
  await tab.playwright.getByRole('textbox', { name: 'Send a message...', exact: true }).fill('Read tpc-quality-check and reply with exactly TPC_SKILL_READ_OK');
  await tab.playwright.getByRole('button', { name: 'Send', exact: true }).click();
  await wait(tab.playwright.getByRole('button', { name: 'Executed code python', exact: true }), 'visible', 60000);
  await wait(tab.playwright.getByRole('button', { name: 'Stop generating', exact: true }), 'hidden', 60000);
  await save('completed', await tab.playwright.domSnapshot(), await tab.screenshot({ fullPage: false }));
  await tab.reload();
  await wait(tab.playwright.getByRole('button', { name: savedTitle, exact: true }), 'visible');
  await dismissMemoryWarning();
  await tab.playwright.getByRole('button', { name: savedTitle, exact: true }).click();
  await wait(tab.playwright.getByRole('button', { name: 'Executed code python', exact: true }), 'visible');
  const codeCard = tab.playwright.getByRole('button', { name: 'Executed code python', exact: true });
  if ((await codeCard.getAttribute('aria-expanded')) !== 'true') await codeCard.click();
  for (const group of await tab.playwright.getByRole('button', { name: '1 tool call', exact: true }).all()) {
    if ((await group.getAttribute('aria-expanded')) !== 'true') await group.click();
  }
  const skillCard = tab.playwright.getByRole('button', { name: 'Used tool: read_skill_md', exact: true });
  await wait(skillCard, 'visible');
  if ((await skillCard.getAttribute('aria-expanded')) !== 'true') await skillCard.click();
  const snapshot = await tab.playwright.domSnapshot();
  require(snapshot.includes('read_skill_md'), 'Skill read action missing after reload');
  // DOM snapshots escape quotes in generic text nodes containing JSON.
  require(snapshot.replace(/\\"/g, '"').includes('"skill_name": "tpc-quality-check"'), 'Saved skill arguments missing');
  require(snapshot.includes('TPC_SKILL_READ_OK'), 'Validated final missing after reload');
  require((await tab.playwright.getByRole('button', { name: 'Executed code python', exact: true }).count()) === 1, 'Duplicate execution card');
  require(!snapshot.includes('Connecting') && !snapshot.includes('Thinking...'), 'Pending state survived reload');
  await save('refreshed', snapshot, await tab.screenshot({ fullPage: false }));
  return { case_id: 'TPC-D4-001' };
}
