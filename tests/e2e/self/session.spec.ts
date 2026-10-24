// Signing in without the login form: the session fixture creates the session on the server and the
// browser receives only the cookie (the form is rate limited; only golden path 1 posts it).
import { expect, test } from '../support/test';

test('a session fixture opens Home of workspace A for the owner', async ({ page, as, harness, axe }) => {
  const home = `/workspace/${harness.ids.workspace_a}/studio/`;

  const session = await as('owner');
  const response = await page.goto(home);

  expect(session.user.email).toBe(harness.ids.users.owner.email);
  expect(response?.status()).toBe(200);
  expect(new URL(page.url()).pathname).toBe(home);
  await expect(page.getByRole('main')).toBeVisible();
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  await axe(page, 'Home (owner)');
});

test('a session fixture by email signs that person in', async ({ page, as, harness }) => {
  const home = `/workspace/${harness.ids.workspace_a}/studio/`;

  await as({ email: harness.ids.users.editor.email });
  await page.goto('/');

  expect(new URL(page.url()).pathname).toBe(home);
});

test('without a session, Home sends the visitor to the login page', async ({ page, harness }) => {
  await page.goto(`/workspace/${harness.ids.workspace_a}/studio/`);

  expect(new URL(page.url()).pathname).toBe('/accounts/login/');
});
