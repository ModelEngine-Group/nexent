/** CMSR-D4-001: run with the Codex built-in tab's Playwright API after login.
 * control contains HTTP fixture callbacks; it never controls browser state.
 * Fixture must separate the auxiliary title reserve (8192) from Agent reserve (4096).
 */
export async function test_cmsr_d4_001({ tab, url, marker, control, save }) {
  // Built-in Playwright waits may yield after a short host deadline; retry
  // those waits within the case's bounded deadline, preserving other errors.
  const wait = async (locator, state, timeoutMs) => {
    const deadline = Date.now() + timeoutMs;
    while (true) {
      try { await locator.waitFor({ state, timeoutMs: 3000 }); return; }
      catch (error) {
        if (!String(error).includes('selector deadline exceeded') || Date.now() >= deadline) throw error;
      }
    }
  };
  const require = (value, message) => { if (!value) throw new Error(message); };
  await tab.goto(url);
  await wait(tab.playwright.getByRole('heading', { name: 'Hello, I am PR4057 Repair Acceptance', exact: true }), 'visible', 15000);
  await tab.playwright.getByRole('textbox', { name: 'Send a message...', exact: true }).fill(`Reply with exactly ${marker}`);
  await tab.playwright.getByRole('button', { name: 'Send', exact: true }).click();
  await wait(tab.playwright.locator('p').filter({ hasText: /<code>print\(/ }), 'visible', 30000);
  const paused = await tab.playwright.domSnapshot();
  require((await control.stats()).success_stream_paused, 'Provider completed before safe UI fragment');
  require(paused.includes('strong: Step 1'), 'Missing Step 1 before model fragment');
  require(paused.includes('Stop generating'), 'Stream already completed');
  require(!/CMSR_LEAK_|INVALID_SEMANTIC_FIRST/.test(paused), 'Failed content survived rollback');
  await save('paused', paused, await tab.screenshot({ fullPage: false }));
  await control.release();
  await wait(tab.playwright.getByRole('button', { name: 'Executed code python', exact: true }), 'visible', 30000);
  await wait(tab.playwright.getByRole('button', { name: 'Stop generating', exact: true }), 'hidden', 30000);
  await tab.reload();
  await wait(tab.playwright.getByRole('button', { name: `<final_answer>${marker}</final_answer>`, exact: true }), 'visible', 15000);
  await tab.playwright.getByRole('button', { name: `<final_answer>${marker}</final_answer>`, exact: true }).click();
  await wait(tab.playwright.getByRole('button', { name: 'Reasoning', exact: true }), 'visible', 15000);
  await tab.playwright.getByRole('button', { name: 'Reasoning', exact: true }).click();
  const refreshed = await tab.playwright.domSnapshot();
  require(refreshed.includes(`<code>print("${marker}")</code>`), 'Committed raw action missing after refresh');
  require((await tab.playwright.getByRole('button', { name: 'Executed code python', exact: true }).count()) === 1, 'Duplicate execution card');
  require((refreshed.match(/strong: Step 1/g) || []).length === 1, 'Step 1 lost or duplicated');
  require(!/CMSR_LEAK_|INVALID_SEMANTIC_FIRST|Connecting|Thinking\.\.\./.test(refreshed), 'Failed or pending state survived refresh');
  require(refreshed.includes(`paragraph: ${marker}`), 'Final answer missing');
  await save('refreshed', refreshed, await tab.screenshot({ fullPage: false }));
  return { case_id: 'CMSR-D4-001', marker, provider: await control.stats() };
}
