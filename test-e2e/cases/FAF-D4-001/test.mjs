/** FAF-D4-001: fixed Playwright checks, executed with the authenticated CUA tab. */
export async function assertResult(tab, { answer, pure = false }) {
  const result = tab.playwright.locator("p").filter({ hasText: new RegExp("^" + answer + "$") });
  await result.waitFor({ state: "visible", timeoutMs: 10000 });
  const count = await result.count();
  if (count !== 1)
    throw new Error(`Expected one answer paragraph, found ${count}`);
  const reasoning = tab.playwright.getByRole("button", {
    name: "Reasoning",
    exact: true,
  });
  const cards = await reasoning.count();
  if (pure && cards !== 0)
    throw new Error(`Pure answer created ${cards} reasoning cards`);
  if (!pure && cards === 1) {
    const expanded = await reasoning.getAttribute("aria-expanded");
    if (expanded === "true") await reasoning.click({ timeoutMs: 10000 });
    if (!(await result.isVisible()))
      throw new Error("Answer disappeared inside collapsed reasoning");
  }
  return {
    answerCount: count,
    reasoningCards: cards,
    answerVisible: await result.isVisible(),
  };
}

export async function sendScenario(tab, { url, prompt }) {
  await tab.goto(url);
  const input = tab.playwright.getByRole("textbox", {
    name: "发送消息...",
    exact: true,
  });
  await input.waitFor({ state: "visible", timeoutMs: 10000 });
  await input.fill(prompt, { timeoutMs: 10000 });
  await tab.playwright
    .getByRole("button", { name: "发送", exact: true })
    .click({ timeoutMs: 10000 });
}

export async function reloadHistory(tab, title) {
  await tab.reload();
  await tab.playwright.getByRole("textbox", { name: "发送消息...", exact: true }).waitFor({ state: "visible", timeoutMs: 10000 });
  const history = tab.playwright.getByRole("button", {
    name: title,
    exact: true,
  });
  await history.waitFor({ state: "visible", timeoutMs: 10000 });
  await history.click({ timeoutMs: 10000 });
}

export async function assertSubagentResult(tab, childName) {
  const group = tab.playwright.getByRole("button", { name: "1 subagent call", exact: true });
  if ((await group.count()) === 1 && (await group.getAttribute("aria-expanded")) !== "true") await group.click({ timeoutMs: 10000 });
  const childHeader = tab.playwright.getByRole("button", { name: new RegExp(childName + " Completed") });
  await childHeader.waitFor({ state: "visible", timeoutMs: 10000 });
  if ((await childHeader.getAttribute("aria-expanded")) !== "true") await childHeader.click({ timeoutMs: 10000 });
  const result = tab.playwright.locator("p").filter({ hasText: /^FAF-CHILD-OK$/ });
  await result.waitFor({ state: "visible", timeoutMs: 10000 });
  if ((await result.count()) !== 1) throw new Error("Subagent answer appears more than once");
  const placement = await result.evaluate((element) => {
    const card = element.closest(".my-3.ml-3");
    const reasoning = element.closest(".aui-reasoning-content");
    return { inChildCard: Boolean(card), inReasoning: Boolean(reasoning) };
  });
  if (!placement.inChildCard || placement.inReasoning) throw new Error("Wrong subagent answer placement");
  return { answerCount: 1, ...placement };
}
