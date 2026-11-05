import { expect, test } from '../support/test';
import { snap, thawClock, visualSpecsOnly, visualWorld } from '../support/visual';

// The first baseline (spec D9, plan T10): the shell around the visual workspace's Home, light, on the
// three projects, as the device shows it. It proves the baseline run before any screen depends on it,
// and is committed at the foundations gate (T13) in a `visual:` commit. Screen 1 removes the shell's
// New menu and screen 2 rebuilds Home, so each refreshes this file in its own `visual:` commit.
//
// Compared only where E2E_VISUAL=1 (CI's visual job and the baseline workflow); skipped elsewhere.

visualSpecsOnly();
test.use({ colorScheme: 'light' });

test.afterEach(async ({ harness }) => {
  await thawClock(harness);
});

test('the shell around Home', async ({ page, harness, as }) => {
  const world = await visualWorld(page, harness);
  await as({ email: world.users.owner.email });
  expect((await page.goto(`/workspace/${world.workspace_id}/studio/`))?.status()).toBe(200);
  await expect(page.getByTestId('home-today')).toBeVisible();
  await snap(page, 'home');
});
