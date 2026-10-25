import { expect, test, type APIResponse, type BrowserContext, type Page } from '@playwright/test';
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
  if (!Array.isArray(users) || users.length !== 5 || users.some(user => !user.id || !user.username || !user.password)) {
    throw new Error('Five isolated disposable users are required');
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

async function mutateAPI(page: Page, path: string, method: 'POST' | 'PATCH' | 'DELETE', data: object = {}): Promise<APIResponse> {
  const session = await page.request.get('/api/auth/session');
  expect(session.status()).toBe(200);
  const csrf = (await session.json()).csrf_token as string;
  return page.request.fetch(`/api${path}`, {
    method, data, headers: { Origin: new URL(page.url()).origin, 'X-CSRF-Token': csrf },
  });
}

async function invite(page: Page, project: { id: string; name: string }, account: Account, role: 'admin' | 'developer' | 'viewer'): Promise<void> {
  await page.goto(`/projects/${project.id}/members`);
  await page.getByLabel('Username', { exact: true }).fill(account.username);
  await page.getByLabel('Username', { exact: true }).focus();
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Role', { exact: true })).toBeFocused();
  await page.getByLabel('Role', { exact: true }).selectOption(role);
  await page.getByRole('button', { name: 'Invite member', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Invitation created');
}

async function respondToInvitation(page: Page, project: { name: string }, decision: 'Accept' | 'Decline'): Promise<void> {
  await page.goto('/invitations');
  const card = page.locator('li.resource-card').filter({ hasText: project.name });
  await expect(card).toBeVisible();
  await card.getByRole('button', { name: `${decision} invitation` }).click();
  await expect(page.getByRole('status')).toContainText(
    decision === 'Accept' ? 'Invitation accepted' : 'Invitation declined',
  );
}

async function createEnvironment(page: Page, projectId: string, name: string, slug: string): Promise<string> {
  await page.goto(`/projects/${projectId}/environments`);
  await page.getByRole('link', { name: 'Create environment', exact: true }).first().click();
  await page.getByLabel('Name', { exact: true }).fill(name);
  await page.getByLabel('Slug', { exact: true }).fill(slug);
  await page.getByRole('button', { name: 'Create environment', exact: true }).click();
  await expect(page).toHaveURL(/\/environments\/[0-9a-f-]{36}$/);
  await expect(page.getByRole('heading', { name, exact: true })).toBeVisible();
  return new URL(page.url()).pathname.split('/').at(-1)!;
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

test('invited developer gains access and loses it immediately on revocation', async ({ page, browser }) => {
  test.setTimeout(90_000);
  const [owner, developer] = accounts();
  await login(page, owner);
  const project = await createProject(page);
  await invite(page, project, developer, 'viewer');
  const memberContext = await browser.newContext({ baseURL: process.env.LAVA_E2E_BASE_URL, viewport: page.viewportSize() ?? undefined });
  try {
    const member = await memberContext.newPage();
    await login(member, developer);
    await respondToInvitation(member, project, 'Accept');
    await page.goto(`/projects/${project.id}/members`);
    const role = page.getByLabel(`Role for ${developer.username}`);
    await role.selectOption('developer');
    await role.locator('xpath=ancestor::form').getByRole('button', { name: 'Save role' }).click();
    await expect(page.getByRole('status')).toContainText('Role updated');
    const service = await createService(member, project.id);
    const stagingId = await createEnvironment(member, project.id, 'Staging', 'staging');
    await member.goto(`/projects/${project.id}/services/${service.id}`);
    await member.getByLabel('Associated environment').selectOption(stagingId);
    await member.getByLabel('Build method').selectOption('railpack');
    await member.getByLabel('Deployment branch').fill('develop');
    await member.getByLabel('Desired replicas').fill('2');
    await member.getByRole('button', { name: 'Save configuration' }).click();
    await expect(member.getByRole('status')).toContainText('Configuration saved');
    await member.reload();
    await expect(member.getByLabel('Associated environment')).toHaveValue(stagingId);
    await expect(member.getByLabel('Deployment branch')).toHaveValue('develop');
    const persisted = await member.request.get(`/api/projects/${project.id}/services/${service.id}`);
    expect(persisted.status()).toBe(200);
    expect((await persisted.json()).build_method).toBe('railpack');
    await page.goto(`/projects/${project.id}/members`);
    page.once('dialog', dialog => dialog.accept());
    const row = page.locator('li.resource-card').filter({ has: page.getByRole('heading', { name: developer.username }) });
    await row.getByRole('button', { name: 'Revoke access' }).click();
    await expect(page.getByRole('status')).toContainText('Access revoked');
    await member.goto(`/projects/${project.id}`);
    await expect(member.getByRole('heading', { name: /not found|not available|unavailable/i })).toBeVisible();
    expect((await member.request.get(`/api/projects/${project.id}`)).status()).toBe(404);
    expect((await member.request.get(`/api/projects/${project.id}/services/${service.id}`)).status()).toBe(404);
  } finally { await memberContext.close(); }
});

test('viewer can read but cannot mutate project resources', async ({ page, browser }) => {
  test.setTimeout(75_000);
  const [owner, , viewer, , stranger] = accounts();
  await login(page, owner);
  const project = await createProject(page);
  await invite(page, project, viewer, 'viewer');
  const viewContext = await browser.newContext({ baseURL: process.env.LAVA_E2E_BASE_URL, viewport: page.viewportSize() ?? undefined });
  const strangerContext = await browser.newContext({ baseURL: process.env.LAVA_E2E_BASE_URL, viewport: page.viewportSize() ?? undefined });
  try {
    const viewPage = await viewContext.newPage();
    await login(viewPage, viewer);
    await respondToInvitation(viewPage, project, 'Accept');
    await viewPage.goto(`/projects/${project.id}`);
    await expect(viewPage.getByRole('heading', { name: project.name })).toBeVisible();
    await expect(viewPage.getByRole('link', { name: 'Create service' })).toHaveCount(0);
    await viewPage.goto(`/projects/${project.id}/members`);
    await expect(viewPage.getByRole('heading', { name: 'Members' })).toBeVisible();
    await expect(viewPage.getByRole('heading', { name: viewer.username })).toBeVisible();
    await expect(viewPage.getByRole('heading', { name: 'Invite member' })).toHaveCount(0);
    expect(await viewPage.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    expect((await mutateAPI(viewPage, `/projects/${project.id}/environments`, 'POST', { name: 'No', slug: 'no' })).status()).toBe(403);
    expect((await mutateAPI(viewPage, `/projects/${project.id}/services`, 'POST', {
      name: 'No', service_type: 'api', desired_state: 'stopped', resources: { cpu: 1, memory_mb: 512 },
    })).status()).toBe(403);
    const strangerPage = await strangerContext.newPage();
    await login(strangerPage, stranger);
    expect((await strangerPage.request.get(`/api/projects/${project.id}`)).status()).toBe(404);
    await strangerPage.goto(`/projects/${project.id}`);
    await expect(strangerPage.getByRole('heading', { name: /not found|not available|unavailable/i })).toBeVisible();
  } finally { await viewContext.close(); await strangerContext.close(); }
});

test('admin manages members without gaining owner authority', async ({ page, browser }) => {
  test.setTimeout(75_000);
  const [owner, , viewer, admin] = accounts();
  await login(page, owner);
  const project = await createProject(page);
  await invite(page, project, admin, 'admin');
  const adminContext = await browser.newContext({ baseURL: process.env.LAVA_E2E_BASE_URL, viewport: page.viewportSize() ?? undefined });
  try {
    const adminPage = await adminContext.newPage();
    await login(adminPage, admin);
    await respondToInvitation(adminPage, project, 'Accept');
    await invite(adminPage, project, viewer, 'viewer');
    const duplicate = await mutateAPI(adminPage, `/projects/${project.id}/invitations`, 'POST', { username: viewer.username, role: 'viewer' });
    expect([400, 409]).toContain(duplicate.status());
    const grantOwner = await mutateAPI(adminPage, `/projects/${project.id}/members`, 'POST', { username: viewer.username, role: 'owner' });
    expect([403, 422]).toContain(grantOwner.status());
    const members = await page.request.get(`/api/projects/${project.id}/members`);
    expect(members.status()).toBe(200);
    const ownerMembership = (await members.json()).find((member: { role: string }) => member.role === 'owner');
    expect(ownerMembership).toBeTruthy();
    const finalOwnerRemoval = await mutateAPI(page, `/projects/${project.id}/members/${ownerMembership.id}`, 'DELETE');
    expect([403, 409]).toContain(finalOwnerRemoval.status());
    expect((await page.request.get(`/api/projects/${project.id}`)).status()).toBe(200);
  } finally { await adminContext.close(); }
});

test('project environments stay isolated and archived metadata is immutable', async ({ page }) => {
  test.setTimeout(75_000);
  await login(page, accounts()[0]);
  const first = await createProject(page);
  const developmentId = await createEnvironment(page, first.id, 'Development', 'development');
  const productionId = await createEnvironment(page, first.id, 'Production', 'production');
  expect(developmentId).not.toBe(productionId);
  const second = await createProject(page);
  const secondDevelopmentId = await createEnvironment(page, second.id, 'Development', 'development');
  expect(secondDevelopmentId).not.toBe(developmentId);
  expect((await page.request.get(`/api/projects/${second.id}/environments/${developmentId}`)).status()).toBe(404);
  await page.goto(`/projects/${first.id}/environments/${developmentId}`);
  page.once('dialog', dialog => dialog.accept());
  await page.getByRole('button', { name: 'Archive environment' }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${first.id}/environments$`));
  const archived = await page.request.get(`/api/projects/${first.id}/environments/${developmentId}`);
  expect(archived.status()).toBe(200);
  expect((await archived.json()).lifecycle_status).toBe('archived');
  const refused = await mutateAPI(page, `/projects/${first.id}/environments/${developmentId}`, 'PATCH', { name: 'Undeclared' });
  expect([403, 409]).toContain(refused.status());
  expect((await page.request.get(`/api/projects/${first.id}/environments/${productionId}`)).status()).toBe(200);
});

test('declined and revoked invitations cannot be accepted', async ({ page, browser }) => {
  test.setTimeout(75_000);
  const [owner, developer, viewer] = accounts();
  await login(page, owner);
  const project = await createProject(page);
  await invite(page, project, developer, 'viewer');
  const pending = await page.request.get(`/api/projects/${project.id}/invitations`);
  expect(pending.status()).toBe(200);
  const first = (await pending.json()).find((invitation: { invitee_name: string }) => invitation.invitee_name === developer.username);
  expect(first).toBeTruthy();
  const devContext = await browser.newContext({ baseURL: process.env.LAVA_E2E_BASE_URL, viewport: page.viewportSize() ?? undefined });
  const viewContext = await browser.newContext({ baseURL: process.env.LAVA_E2E_BASE_URL, viewport: page.viewportSize() ?? undefined });
  try {
    const devPage = await devContext.newPage();
    await login(devPage, developer);
    await respondToInvitation(devPage, project, 'Decline');
    expect([400, 403, 404, 409]).toContain((await mutateAPI(devPage, `/invitations/${first.id}/accept`, 'POST')).status());
    await invite(page, project, viewer, 'viewer');
    const pendingAgain = await page.request.get(`/api/projects/${project.id}/invitations`);
    const second = (await pendingAgain.json()).find((invitation: { invitee_name: string; status: string }) => invitation.invitee_name === viewer.username && invitation.status === 'pending');
    expect(second).toBeTruthy();
    await page.goto(`/projects/${project.id}/members`);
    const row = page.locator('li.resource-card').filter({ has: page.getByRole('heading', { name: viewer.username }) });
    await row.getByRole('button', { name: 'Revoke invitation' }).click();
    await expect(page.getByRole('status')).toContainText('Invitation revoked');
    const viewPage = await viewContext.newPage();
    await login(viewPage, viewer);
    expect([400, 403, 404, 409]).toContain((await mutateAPI(viewPage, `/invitations/${second.id}/accept`, 'POST')).status());
    expect((await viewPage.request.get(`/api/projects/${project.id}`)).status()).toBe(404);
  } finally { await devContext.close(); await viewContext.close(); }
});
