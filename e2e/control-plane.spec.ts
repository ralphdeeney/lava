import { expect, test, type BrowserContext, type Page } from '@playwright/test';
import { createHash, randomBytes } from 'node:crypto';
import { readFileSync, statSync, mkdirSync, chmodSync } from 'node:fs';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';

type Account = { id: string; username: string; password: string };

function accounts(): Account[] {
  const file = process.env.LAVA_E2E_ACCOUNTS_FILE;
  if (!file || (statSync(file).mode & 0o077) !== 0) {
    throw new Error('A private, operator-provisioned disposable-account fixture is required');
  }
  const users = JSON.parse(readFileSync(file, 'utf8')).users as Account[];
  if (!Array.isArray(users) || users.length !== 2 || users.some(user => !user.id || !user.username || !user.password)) {
    throw new Error('Two isolated disposable users are required');
  }
  return users;
}

function suffix(): string { return randomBytes(5).toString('hex'); }

function fixtureAction(payload: object): void {
  const helper = process.env.LAVA_E2E_EXPIRE_HELPER;
  const python = process.env.LAVA_E2E_PYTHON;
  if (!helper || !python) throw new Error('A disposable, ownership-checked fixture helper is required');
  const result = spawnSync(python, [helper], {
    input: JSON.stringify(payload), encoding: 'utf8', timeout: 15_000,
  });
  if (result.status !== 0) throw new Error('Disposable fixture helper did not complete');
}

// Independent journeys do not share abuse counters. The helper permits only this run's
// provisioned accounts/peer bucket in the dedicated disposable *_test database.
// Production limits remain unchanged and have separate real rate-limit security tests.
test.beforeEach(() => { fixtureAction({ action: 'reset_login_attempts' }); });

async function login(page: Page, account: Account): Promise<void> {
  await page.goto('/login');
  await page.getByLabel('Username', { exact: true }).fill(account.username);
  await page.getByLabel('Password', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page).toHaveURL(/\/projects(?:\?.*)?$/);
}

async function createProject(page: Page): Promise<{ id: string; name: string }> {
  const name = `Browser project ${suffix()}`;
  await page.goto('/projects');
  await page.getByRole('link', { name: 'Create project', exact: true }).click();
  await page.getByLabel('Project name', { exact: true }).fill(name);
  await page.getByLabel('Description', { exact: true }).fill('Disposable functional browser acceptance data');
  await page.getByRole('button', { name: 'Create project', exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}$/);
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  return { id: new URL(page.url()).pathname.split('/').at(-1)!, name };
}

async function createService(page: Page, projectId: string): Promise<{ id: string; name: string }> {
  const name = `Browser service ${suffix()}`;
  await page.goto(`/projects/${projectId}`);
  await page.getByRole('link', { name: 'Create service', exact: true }).click();
  await page.getByLabel('Service name', { exact: true }).fill(name);
  await page.getByLabel('Service type', { exact: true }).selectOption('api');
  await page.getByLabel('Desired state', { exact: true }).selectOption('stopped');
  await page.getByLabel('CPU cores', { exact: true }).fill('1');
  await page.getByLabel('Memory (MiB)', { exact: true }).fill('512');
  await page.getByRole('button', { name: 'Create service', exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[0-9a-f-]{36}\/services\/[0-9a-f-]{36}$/);
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  return { id: new URL(page.url()).pathname.split('/').at(-1)!, name };
}

async function checkSafeScreenshot(page: Page, context: BrowserContext, name: string): Promise<void> {
  if (!new URL(page.url()).pathname.startsWith('/projects')) return;
  const html = await page.content();
  const secrets = [...accounts().map(account => account.password), ...(await context.cookies()).map(cookie => cookie.value)];
  if (secrets.some(secret => secret && html.includes(secret))) return;
  const directory = process.env.LAVA_E2E_REPORT_DIR ?? 'test-results/e2e/public';
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  const target = join(directory, name);
  await page.screenshot({ path: target, fullPage: true, mask: [page.locator('input, textarea, [data-secret]')] });
  chmodSync(target, 0o600);
}

test.afterEach(async ({ page, context }, testInfo) => {
  if (testInfo.status !== testInfo.expectedStatus && !page.isClosed()) {
    try {
      await checkSafeScreenshot(page, context, `${testInfo.project.name}-${createHash('sha256').update(testInfo.title).digest('hex').slice(0, 12)}.png`);
    } catch { /* Withhold an unverified screenshot rather than exposing credentials. */ }
  }
});

test('authenticated project and service journey persists after refresh', async ({ page, context }) => {
  await login(page, accounts()[0]);
  const session = (await context.cookies()).find(cookie => cookie.name === 'lava_session');
  expect(Boolean(session)).toBeTruthy();
  expect(session!.httpOnly).toBe(true);
  expect(session!.sameSite).toBe('Lax');
  expect(session!.secure).toBe(new URL(page.url()).protocol === 'https:');
  const project = await createProject(page);
  const service = await createService(page, project.id);
  await page.getByLabel('CPU cores', { exact: true }).fill('2');
  await page.getByLabel('Memory (MiB)', { exact: true }).fill('1024');
  await page.getByRole('button', { name: 'Save configuration', exact: true }).click();
  await expect(page.getByRole('status')).toContainText(/saved/i);
  await page.reload();
  await expect(page.getByLabel('CPU cores', { exact: true })).toHaveValue('2');
  await expect(page.getByLabel('Memory (MiB)', { exact: true })).toHaveValue('1024');
  const response = await page.request.get(`/api/projects/${project.id}/services/${service.id}`);
  expect(response.status()).toBe(200);
  const persisted = await response.json();
  expect(persisted.resources).toEqual({ cpu: 2, memory_mb: 1024 });
  await page.goto(`/projects/${project.id}`);
  await expect(page.getByRole('link').filter({ has: page.getByRole('heading', { name: service.name, exact: true }) })).toBeVisible();
});

test('incorrect login and validation errors stay safe', async ({ page }) => {
  const account = accounts()[0];
  await page.goto('/login');
  await page.getByLabel('Username', { exact: true }).fill(account.username);
  await page.getByLabel('Password', { exact: true }).fill(account.password + 'x');
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(/invalid|unable|incorrect/i);
  const body = await page.locator('body').innerText();
  expect(body.includes(account.password)).toBe(false);
  await login(page, account);
  const project = await createProject(page);
  await page.getByRole('link', { name: 'Create service', exact: true }).click();
  await page.getByLabel('Service name', { exact: true }).fill('Invalid name / forbidden');
  await page.getByRole('button', { name: 'Create service', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText(/invalid|valid|check/i);
  const response = await page.request.get(`/api/projects/${project.id}/services`);
  expect(response.status()).toBe(200);
  expect((await response.json()).length).toBe(0);
});

test('cross-user project and service access is denied', async ({ page, browser }) => {
  const [accountA, accountB] = accounts();
  await login(page, accountA);
  const project = await createProject(page);
  const service = await createService(page, project.id);
  const contextB = await browser.newContext({ baseURL: process.env.LAVA_E2E_BASE_URL, viewport: page.viewportSize() ?? undefined });
  try {
    const pageB = await contextB.newPage();
    await login(pageB, accountB);
    const projectResponse = await pageB.request.get(`/api/projects/${project.id}`);
    expect(projectResponse.status()).toBe(404);
    const serviceResponse = await pageB.request.get(`/api/projects/${project.id}/services/${service.id}`);
    expect(serviceResponse.status()).toBe(404);
    await pageB.goto(`/projects/${project.id}`);
    await expect(pageB.getByRole('heading', { name: /not found|not available|unavailable/i })).toBeVisible();
    expect((await pageB.locator('body').innerText()).includes(project.name)).toBe(false);
  } finally { await contextB.close(); }
});

test('logout invalidates the current session', async ({ page, context }) => {
  await login(page, accounts()[0]);
  const oldCookie = (await context.cookies()).find(cookie => cookie.name === 'lava_session')!;
  await page.goto('/sessions');
  await page.getByRole('button', { name: 'Log out', exact: true }).click();
  await expect(page).toHaveURL(/\/login(?:\?.*)?$/);
  expect((await context.cookies()).some(cookie => cookie.name === 'lava_session')).toBe(false);
  await context.addCookies([oldCookie]);
  await page.goto('/projects');
  await expect(page).toHaveURL(/\/login(?:\?.*)?$/);
  expect((await page.request.get('/api/auth/session')).status()).toBe(401);
});

test('logout all revokes other browser sessions', async ({ page, browser }) => {
  const account = accounts()[0];
  await login(page, account);
  const other = await browser.newContext({ baseURL: process.env.LAVA_E2E_BASE_URL, viewport: page.viewportSize() ?? undefined });
  try {
    const otherPage = await other.newPage();
    await login(otherPage, account);
    await page.goto('/sessions');
    await page.getByRole('button', { name: 'Log out all sessions', exact: true }).click();
    await expect(page).toHaveURL(/\/login(?:\?.*)?$/);
    expect((await page.context().cookies()).some(cookie => cookie.name === 'lava_session')).toBe(false);
    await otherPage.goto('/projects');
    await expect(otherPage).toHaveURL(/\/login(?:\?.*)?$/);
  } finally { await other.close(); }
});

test('expired sessions redirect to login', async ({ page, context }) => {
  const account = accounts()[0];
  await login(page, account);
  const cookie = (await context.cookies()).find(value => value.name === 'lava_session');
  if (!cookie) throw new Error('Expected browser session cookie');
  fixtureAction({ action: 'expire_session', user_id: account.id, session_token: cookie.value });
  await page.goto('/projects');
  await expect(page).toHaveURL(/\/login(?:\?.*)?$/);
  expect((await page.request.get('/api/auth/session')).status()).toBe(401);
});

test('unsafe next redirects stay on this application', async ({ page }) => {
  const expectedOrigin = new URL(process.env.LAVA_E2E_BASE_URL!).origin;
  await page.goto('/login?next=' + encodeURIComponent('https://attacker.invalid/collect'));
  await page.getByLabel('Username', { exact: true }).fill(accounts()[0].username);
  await page.getByLabel('Password', { exact: true }).fill(accounts()[0].password);
  await page.getByRole('button', { name: 'Log in', exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  expect(new URL(page.url()).origin).toBe(expectedOrigin);
});

test('keyboard navigation and responsive layout', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Username', { exact: true }).focus();
  await page.keyboard.type(accounts()[0].username);
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Password', { exact: true })).toBeFocused();
  await page.keyboard.type(accounts()[0].password);
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Log in', exact: true })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole('navigation')).toBeVisible();
  const fits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(fits).toBe(true);
});
