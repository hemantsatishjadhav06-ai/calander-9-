// The per-workspace switches (spec D6, R6; docs/specs/02-cut-and-merge.md): a switch hides its
// navigation and its creation entry points, never its pages.
//
// Each test makes a workspace of its own (team_workspace) and turns its switches with
// workspace_switches, which refuses the seeded workspaces every other spec shares. Blog: off, there
// is no Blog item (nor a Blog entry in Go to); on, Blog is the seventh item and leads to the blog;
// off again, the item goes and the blog's page still answers. Extra providers: off, Bluesky,
// Mastodon, DEV.to, Threads and TikTok are not on the connect screen at all; on, each of them is,
// ready to connect or listed as not available yet, as the site's credentials decide.
import { expectLit, go, isPhone, openMore } from '../support/nav';
import { expect, test } from '../support/test';

type TeamWorkspace = { workspace_id: string; users: Record<'owner' | 'editor' | 'client', { id: string; email: string }> };

const EXTRA_PROVIDERS = ['bluesky', 'mastodon', 'devto', 'threads', 'tiktok'];

test('the Blog item shows only while the blog switch is on', async ({ page, as, axe, harness }) => {
  const made = await harness.fixture<TeamWorkspace>('team_workspace', {});
  const workspace = made.workspace_id;
  const switches = (features: Record<string, boolean>) =>
    harness.fixture<{ features: Record<string, boolean> }>('workspace_switches', { workspace_id: workspace, features });
  await as({ email: made.users.owner.email });

  // Off (the default without a website): no item and nothing to find in Go to.
  await page.goto(`/workspace/${workspace}/studio/`);
  await expect(page.getByTestId('nav-activity')).toBeAttached();
  await expect(page.getByTestId('nav-blog')).toHaveCount(0);
  await expect(page.getByTestId('palette-item-blog')).toHaveCount(0);
  await axe(page, 'Home without Blog (owner, switch off)');

  expect((await switches({ blog: true })).features.blog).toBe(true);
  await page.reload();
  if (isPhone(page)) await openMore(page);
  await expect(page.getByTestId('nav-blog')).toBeVisible();
  await expect(page.getByTestId('palette-item-blog')).toBeAttached();
  await axe(page, isPhone(page) ? 'Menu drawer with Blog' : 'Home with Blog in the sidebar');
  const href = await go(page, 'blog');
  expect(href).toBe(`/workspace/${workspace}/blog/`);
  expect(new URL(page.url()).pathname).toBe(href);
  await expectLit(page, 'blog');
  await axe(page, 'Blog (owner, switch on)');

  // Off again: the item goes, the page stays.
  expect((await switches({ blog: false })).features.blog).toBe(false);
  const response = await page.goto(`/workspace/${workspace}/blog/`);
  expect(response?.status(), 'a switch hides the item, never the page').toBe(200);
  await expect(page.getByTestId('nav-blog')).toHaveCount(0);
  await expect(page.getByTestId('palette-item-blog')).toHaveCount(0);
  await axe(page, 'Blog (owner, switch off)');
});

test('the extra providers are on the connect screen only while their switch is on', async ({
  page,
  as,
  axe,
  harness,
}) => {
  const made = await harness.fixture<TeamWorkspace>('team_workspace', {});
  const workspace = made.workspace_id;
  const connect = `/social-accounts/${workspace}/connect/`;
  await as({ email: made.users.owner.email });

  // Off (the default): none of them, while the rest of the screen is unchanged.
  expect((await page.goto(connect))?.status()).toBe(200);
  await expect(page.getByTestId('connect-platform-facebook')).toBeVisible();
  for (const platform of EXTRA_PROVIDERS) {
    await expect(page.getByTestId(`connect-platform-${platform}`), `${platform} off`).toHaveCount(0);
    await expect(page.getByTestId(`connect-later-${platform}`), `${platform} off`).toHaveCount(0);
  }
  await axe(page, 'Connect a platform (extra providers off)');

  // On: each one is there, once.
  const on = await harness.fixture<{ features: Record<string, boolean> }>('workspace_switches', {
    workspace_id: workspace,
    features: { extra_providers: true },
  });
  expect(on.features.extra_providers).toBe(true);
  await page.reload();
  await expect(page.getByTestId('connect-platform-facebook')).toBeVisible();
  for (const platform of EXTRA_PROVIDERS) {
    const ready = await page.getByTestId(`connect-platform-${platform}`).count();
    const later = await page.getByTestId(`connect-later-${platform}`).count();
    expect(ready + later, `${platform} on: offered once`).toBe(1);
  }
  // Bluesky and Mastodon need no site credentials: they are ready to connect.
  await expect(page.getByTestId('connect-platform-bluesky')).toBeVisible();
  await expect(page.getByTestId('connect-platform-mastodon')).toBeVisible();
  await axe(page, 'Connect a platform (extra providers on)');
});
