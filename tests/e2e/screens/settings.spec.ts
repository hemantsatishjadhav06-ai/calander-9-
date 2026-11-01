// Settings (spec D5, R5; docs/specs/02-cut-and-merge.md): one screen with a tab per settings page.
//
// Each test makes its own workspace (brand_timezone_workspace: an owner and an editor, a blank
// brand profile saved an hour ago), so a saved colour or a viewer never reaches another spec. The
// owner opens Settings from the gear, saves a new primary colour on the Brand tab; the form posts
// to the brand page's own handler, which stores it and answers with the Brand page showing it,
// and the tab shows it too. Tabs follow each page's own check: the owner sees Approvals and
// Autopilot, an editor Autopilot but not Approvals (a workspace manager's), a viewer neither, and
// asking for one of them by address is refused. The old settings pages answer a 301 to their tab.
import { expectLit, go } from '../support/nav';
import { expect, test } from '../support/test';

const NEW_PRIMARY = '#2a5d8f';

type BrandWorkspace = {
  workspace_id: string;
  owner: { id: string; email: string };
  editor: { id: string; email: string };
};

type BrandState = { brand: { primary_color: string; accent_color: string; updated_at: string } };

const ALL_TABS = ['brand', 'accounts', 'team', 'approvals', 'autopilot', 'notifications', 'advanced'];

test('the owner saves the brand colour from the Brand tab, and the Brand page shows it', async ({
  page,
  as,
  axe,
  harness,
  network,
}) => {
  const since = Date.now() / 1000;
  const made = await harness.fixture<BrandWorkspace>('brand_timezone_workspace', {});
  const workspace = made.workspace_id;
  const state = () => harness.probe<BrandState>('brand_timezone_state', { workspace_id: workspace });
  const before = await state();
  expect(before.brand.primary_color).not.toBe(NEW_PRIMARY.toUpperCase());

  await as({ email: made.owner.email });
  await page.goto(`/workspace/${workspace}/studio/`);
  const href = await go(page, 'settings');
  expect(href).toBe(`/workspace/${workspace}/settings/`);
  await expectLit(page, 'settings');
  // The first tab the owner may use is Brand; every tab is there for the owner.
  await expect(page.getByTestId('settings-tab-brand')).toHaveAttribute('aria-current', 'page');
  for (const tab of ALL_TABS) await expect(page.getByTestId(`settings-tab-${tab}`)).toBeVisible();
  const panel = page.getByTestId('settings-panel-brand');
  await expect(panel).toBeVisible();
  await axe(page, 'Settings: Brand (owner)');

  const primary = panel.getByTestId('brand-primary-color');
  await expect(primary).toHaveAttribute('value', before.brand.primary_color);
  await primary.fill(NEW_PRIMARY);
  const brandPath = `/workspace/${workspace}/studio/brand/`;
  const saved = page.waitForResponse(
    (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === brandPath,
  );
  await panel.getByTestId('brand-save').click();
  const answer = await saved;
  expect(answer.status(), 'the brand page’s own handler saved it').toBe(302);
  expect(new URL(answer.headers()['location'] ?? '', page.url()).pathname).toBe(brandPath);
  expect((await state()).brand.primary_color).toBe(NEW_PRIMARY.toUpperCase());

  // The Brand page it answers with shows the stored colour (stored in capitals).
  await page.waitForURL((url) => url.pathname === brandPath);
  await expect(page.getByTestId('brand-primary-color')).toHaveAttribute('value', NEW_PRIMARY.toUpperCase());
  await expectLit(page, 'settings');
  await axe(page, 'Brand page after saving from Settings (owner)');

  // And so does the tab.
  await page.goto(`/workspace/${workspace}/settings/?tab=brand`);
  await expect(page.getByTestId('settings-panel-brand').getByTestId('brand-primary-color')).toHaveAttribute(
    'value',
    NEW_PRIMARY.toUpperCase(),
  );
  await axe(page, 'Settings: Brand after saving (owner)');

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});

test('a staff member sees only the tabs their permissions allow', async ({ page, as, axe, harness }) => {
  const made = await harness.fixture<BrandWorkspace>('brand_timezone_workspace', {});
  const workspace = made.workspace_id;
  const viewer = await harness.fixture<{ email: string }>('workspace_member', { role: 'viewer', workspace_id: workspace });
  const settings = `/workspace/${workspace}/settings/`;

  // The editor: Autopilot (create_posts) but neither Approvals (a manager's) nor Accounts.
  await as({ email: made.editor.email });
  expect((await page.goto(settings))?.status()).toBe(200);
  await expect(page.getByTestId('settings-tab-brand')).toBeVisible();
  await expect(page.getByTestId('settings-tab-autopilot')).toBeVisible();
  await expect(page.getByTestId('settings-tab-approvals')).toHaveCount(0);
  await expect(page.getByTestId('settings-tab-accounts')).toHaveCount(0);
  await axe(page, 'Settings (editor)');
  expect((await page.goto(`${settings}?tab=approvals`))?.status()).toBe(403);
  await axe(page, 'Settings: Approvals refused (editor)');

  // The viewer: neither Approvals nor Autopilot, and both refused by address.
  await page.context().clearCookies();
  await as({ email: viewer.email });
  expect((await page.goto(settings))?.status()).toBe(200);
  await expect(page.getByTestId('settings-panel-brand')).toBeVisible();
  await expect(page.getByTestId('settings-tab-brand')).toBeVisible();
  await expect(page.getByTestId('settings-tab-notifications')).toBeVisible();
  for (const tab of ['approvals', 'autopilot', 'accounts']) {
    await expect(page.getByTestId(`settings-tab-${tab}`), `no ${tab} tab for a viewer`).toHaveCount(0);
  }
  // A viewer may read the brand, never save it.
  await expect(page.getByTestId('brand-primary-color')).toBeDisabled();
  await expect(page.getByTestId('brand-save')).toHaveCount(0);
  await axe(page, 'Settings (viewer)');
  for (const [tab, name] of [
    ['approvals', 'Approvals'],
    ['autopilot', 'Autopilot'],
  ]) {
    expect((await page.goto(`${settings}?tab=${tab}`))?.status(), `${tab} by address`).toBe(403);
    await axe(page, `Settings: ${name} refused (viewer)`);
  }
});

test('the old settings pages land on their tab', async ({ page, as, axe, harness }) => {
  const made = await harness.fixture<BrandWorkspace>('brand_timezone_workspace', {});
  const workspace = made.workspace_id;
  await as({ email: made.owner.email });

  const moves: { from: string; tab: string }[] = [
    { from: `/workspace/${workspace}/studio/settings/`, tab: 'brand' },
    { from: `/workspaces/${workspace}/settings/`, tab: 'brand' },
    { from: `/social-accounts/${workspace}/`, tab: 'accounts' },
    { from: `/workspace/${workspace}/settings/clients/`, tab: 'team' },
  ];
  for (const { from, tab } of moves) {
    const response = await page.goto(from);
    expect(response?.status(), `${from} lands on a page`).toBe(200);
    const first = response!.request().redirectedFrom();
    expect(first, `${from} redirected`).not.toBeNull();
    expect(new URL(first!.url()).pathname).toBe(from);
    expect((await first!.response())?.status(), `${from} moved for good`).toBe(301);
    const landed = new URL(page.url());
    expect(landed.pathname).toBe(`/workspace/${workspace}/settings/`);
    expect(landed.searchParams.get('tab')).toBe(tab);
    await expect(page.getByTestId(`settings-tab-${tab}`)).toHaveAttribute('aria-current', 'page');
    await expect(page.getByTestId(`settings-panel-${tab}`)).toBeVisible();
    await expectLit(page, 'settings');
    await axe(page, `Settings: ${tab}, from ${from}`);
  }
});
