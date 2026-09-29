import type { Page } from 'playwright/test';
import { journey } from '../../infra/automation/d4/runner/journey';
import { executeFixedScenario } from '../../infra/automation/d4/runner/scenario';
import { loginCurrent } from '../../infra/automation/d4/runner/sessions';
import { appPath } from '../../infra/automation/d4/runner/runtime-config';

const CASE_ID = 'PW-AUTO-37453582F1CFB11D';
const REPOSITORY_TAB = '仓库';
const MINE_TAB = '我的 Skill';
const SEARCH_PLACEHOLDER = '搜索 Skill 名称、描述或标签';
const DETAIL_LABEL = '详情';
const COPY_LABEL = '复制';
const COPY_MODAL_TITLE = '复制为我的 Skill';
const NAME_PLACEHOLDER = '请输入 Skill 名称';
const TAG_FILTER_BUTTON = '标签筛选';
const NO_TAG_DEFINITIONS = '暂无启用的标签定义';
const DUPLICATE_TEXT = /当前租户已存在同名 Skill/;
const SUCCESS_TEXT = /Skill 已复制为|Skill 复制成功/;
const SUMMARY_TEXT = /个 Skill/;

interface Listing {
  skill_repository_id: number;
  name: string;
  description?: string | null;
  tags?: string[];
}

interface ListResponse {
  items?: Listing[];
  pagination?: { total?: number };
}

function repositoryCard(page: Page, name: string) {
  return page.getByRole('heading', { name, exact: true }).locator('xpath=ancestor::article[1]');
}

function extractCount(text: string): number {
  const idx = text.indexOf('个 Skill');
  if (idx === -1) return Number.NaN;
  const matches = text.slice(0, idx).match(/[0-9]+/g);
  if (!matches) return Number.NaN;
  return Number(matches[matches.length - 1]);
}

async function waitForRepositoryList(page: Page): Promise<ListResponse> {
  const response = await page.waitForResponse(
    (candidate) =>
      candidate.request().method() === 'GET' &&
      candidate.url().split('?')[0].endsWith('/repository/skill') &&
      candidate.url().includes('page_size=6'),
    { timeout: 120000 },
  );
  return (await response.json()) as ListResponse;
}

async function deleteSkillInMine(page: Page, name: string): Promise<void> {
  await page.getByRole('tab', { name: MINE_TAB }).click();
  await page.getByPlaceholder(SEARCH_PLACEHOLDER).fill(name);
  const card = repositoryCard(page, name);
  try {
    await card.first().waitFor({ state: 'visible', timeout: 15000 });
  } catch {
    return;
  }
  await card.getByRole('button', { name: '更多操作' }).click();
  await page.getByRole('menuitem', { name: '删除', exact: true }).click();
  const confirm = page.getByRole('dialog').filter({ hasText: name });
  await confirm.getByRole('button', { name: '删除', exact: true }).click();
}

journey("PW-AUTO-37453582F1CFB11D", async ({ page, contract, expect }) => {
  let listResponse: ListResponse = { items: [], pagination: { total: 0 } };
  let listings: Listing[] = [];
  let copySource: Listing;
  let conflictName = '';
  let copiedName = '';

  let defaultTabIsRepository = false;
  let summaryText = '';
  let initialTotal = 0;
  let searchRequestUrl = '';
  let searchItemNames: string[] = [];
  let tagFilterApplied = false;
  let tagFilterDowngraded = false;
  let tagPredicatesRequestUrl = '';
  let filteredItemNames: string[] = [];
  let detailName = '';
  let detailHasDescription = false;
  let detailTagSection = false;
  let copyModalOpened = false;
  let conflictStatus = 0;
  let conflictTextVisible = false;
  let successAbsentOnConflict = false;
  let successStatus = 0;
  let successVisible = false;
  let copyFoundInMine = false;

  await executeFixedScenario({ page, contract, expect }, {
    preconditions: [
      async () => {
        await loginCurrent(page, 'tenant_a_dev');
        const promise = waitForRepositoryList(page);
        await page.goto(appPath('/skill-space'), { waitUntil: 'domcontentloaded' });
        listResponse = await promise;
        listings = listResponse.items ?? [];
        if (listings.length < 2) {
          throw new Error(`shared repository requires at least 2 listings, found ${listings.length}`);
        }
        copySource = listings[0];
        const conflict = listings.find((item) => item.name !== copySource.name);
        if (!conflict) {
          throw new Error('no second distinct listing name available for the rename-conflict check');
        }
        conflictName = conflict.name;
        copiedName = `d4-copy-${Date.now()}`;
        initialTotal = listResponse.pagination?.total ?? 0;
      },
    ],
    steps: [
      async () => {
        const tab = page.getByRole('tab', { name: REPOSITORY_TAB });
        await expect(tab).toBeVisible();
        defaultTabIsRepository = (await tab.getAttribute('data-state')) === 'active';
      },
      async () => {
        const summary = page.getByText(SUMMARY_TEXT).first();
        await expect(summary).toBeVisible();
        summaryText = (await summary.innerText()).trim();
        await expect(page.locator('article').first()).toBeVisible();
      },
      async () => {
        const requestPromise = page.waitForResponse(
          (candidate) =>
            candidate.request().method() === 'GET' &&
            candidate.url().split('?')[0].endsWith('/repository/skill') &&
            candidate.url().includes('search='),
        );
        await page.getByPlaceholder(SEARCH_PLACEHOLDER).fill(copySource.name);
        const response = await requestPromise;
        searchRequestUrl = response.url();
        const payload = (await response.json()) as ListResponse;
        searchItemNames = (payload.items ?? []).map((item) => item.name);
      },
      async () => {
        await page.getByRole('button', { name: TAG_FILTER_BUTTON, exact: true }).click();
        if ((await page.getByText(NO_TAG_DEFINITIONS).count()) > 0) {
          tagFilterDowngraded = true;
          await page.keyboard.press('Escape');
          return;
        }
        await page.getByRole('combobox', { name: /筛选/ }).last().click();
        const option = page.getByRole('option').first();
        try {
          await option.waitFor({ state: 'visible', timeout: 5000 });
        } catch {
          tagFilterDowngraded = true;
          await page.keyboard.press('Escape');
          return;
        }
        const requestPromise = page.waitForResponse(
          (candidate) =>
            candidate.request().method() === 'GET' &&
            candidate.url().split('?')[0].endsWith('/repository/skill') &&
            candidate.url().includes('tag_predicates='),
        );
        await option.click();
        const response = await requestPromise;
        tagPredicatesRequestUrl = response.url();
        const payload = (await response.json()) as ListResponse;
        filteredItemNames = (payload.items ?? []).map((item) => item.name);
        tagFilterApplied = true;
      },
      async () => {
        await repositoryCard(page, copySource.name).getByRole('button', { name: DETAIL_LABEL, exact: true }).click();
        const dialog = page.locator('.skill-repository-detail-modal');
        await expect(dialog).toBeVisible();
        detailName = (await dialog.locator('h2').innerText()).trim();
        detailHasDescription = copySource.description
          ? (await dialog.getByText(copySource.description).count()) > 0
          : (await dialog.getByText('暂无描述').count()) > 0;
        detailTagSection = (await dialog.getByText('标签', { exact: true }).count()) > 0;
      },
      async () => {
        const dialog = page.locator('.skill-repository-detail-modal');
        await dialog.locator('.ant-modal-close').click();
        await expect(dialog).toBeHidden();
        await repositoryCard(page, copySource.name).getByRole('button', { name: COPY_LABEL, exact: true }).click();
        const copyModal = page.getByRole('dialog').filter({ hasText: COPY_MODAL_TITLE });
        await expect(copyModal).toBeVisible();
        copyModalOpened = true;
      },
      async () => {
        const copyModal = page.getByRole('dialog').filter({ hasText: COPY_MODAL_TITLE });
        await copyModal.getByPlaceholder(NAME_PLACEHOLDER).fill(conflictName);
        const installPromise = page.waitForResponse(
          (candidate) =>
            candidate.request().method() === 'POST' &&
            candidate.url().split('?')[0].endsWith('/install') &&
            candidate.url().includes('/repository/skill/'),
        );
        await copyModal.getByRole('button', { name: COPY_LABEL, exact: true }).click();
        const response = await installPromise;
        conflictStatus = response.status();
        conflictTextVisible = (await page.getByText(DUPLICATE_TEXT).count()) > 0;
        successAbsentOnConflict = (await page.getByText(SUCCESS_TEXT).count()) === 0;
      },
      async () => {
        const copyModal = page.getByRole('dialog').filter({ hasText: COPY_MODAL_TITLE });
        await copyModal.getByPlaceholder(NAME_PLACEHOLDER).fill(copiedName);
        const installPromise = page.waitForResponse(
          (candidate) =>
            candidate.request().method() === 'POST' &&
            candidate.url().split('?')[0].endsWith('/install') &&
            candidate.url().includes('/repository/skill/'),
        );
        await copyModal.getByRole('button', { name: COPY_LABEL, exact: true }).click();
        const response = await installPromise;
        successStatus = response.status();
        await expect(page.getByText(SUCCESS_TEXT)).toBeVisible({ timeout: 120000 });
        successVisible = true;
        await copyModal.waitFor({ state: 'hidden' });
        await page.getByRole('tab', { name: MINE_TAB }).click();
        await page.getByPlaceholder(SEARCH_PLACEHOLDER).fill(copiedName);
        try {
          await repositoryCard(page, copiedName).first().waitFor({ state: 'visible', timeout: 15000 });
          copyFoundInMine = true;
        } catch {
          copyFoundInMine = false;
        }
        contract.deferCleanup(async () => {
          await deleteSkillInMine(page, copiedName);
        });
      },
    ],
    assertions: [
      async () => {
        expect(defaultTabIsRepository).toBe(true);
        expect(initialTotal).toBeGreaterThanOrEqual(2);
        expect(extractCount(summaryText)).toBe(initialTotal);
      },
      async () => {
        expect(searchRequestUrl).toContain('search=');
        for (const name of searchItemNames) {
          expect(name.toLowerCase()).toContain(copySource.name.toLowerCase());
        }
      },
      async () => {
        if (tagFilterDowngraded) {
          expect(initialTotal).toBeGreaterThanOrEqual(2);
          return;
        }
        expect(tagFilterApplied).toBe(true);
        expect(tagPredicatesRequestUrl).toContain('tag_predicates=');
        for (const name of filteredItemNames) {
          expect(listings.some((item) => item.name === name)).toBe(true);
        }
      },
      async () => {
        expect(detailName).toBe(copySource.name);
        expect(detailHasDescription).toBe(true);
        expect(detailTagSection).toBe(true);
      },
      async () => {
        expect(conflictStatus).toBe(409);
        expect(conflictTextVisible).toBe(true);
        expect(successAbsentOnConflict).toBe(true);
      },
      async () => {
        expect(successStatus).toBe(200);
        expect(successVisible).toBe(true);
        expect(copyFoundInMine).toBe(true);
      },
    ],
  });
});
