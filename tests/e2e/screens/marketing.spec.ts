// The public site (spec D9, R8; docs/specs/02-cut-and-merge.md): Home, How it works and Request
// invite, linked to each other, for someone signed out.
//
// The header links them (behind the menu button on a phone); axe runs on each page and on the open
// phone menu. The invite form is filled and sent: the request answers with a redirect to the same
// page, which thanks the person, and every platform operator has exactly one notification of that
// request. The operator is made by a fixture (the e2e settings have no support address, so without
// one nobody could be told), and the views' rate-limit counters are cleared first, as golden path 11
// does, so earlier runs from this machine's address never refuse the request.
import { type Page } from '@playwright/test';

import { expect, test } from '../support/test';

type InviteRequests = { operators: string[]; notifications: { operator: string; title: string; is_read: boolean }[] };

/** Follow a header link the way this device shows it: straight on desktop, through the menu button below 901px. */
async function follow(page: Page, axe: (page: Page, label: string) => Promise<unknown>, key: string, path: string) {
  const toggle = page.getByTestId('marketing-nav-toggle');
  if (await toggle.isVisible()) {
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByTestId(`marketing-nav-${key}`)).toBeVisible();
    await axe(page, `Public menu open (${key} next)`);
  }
  await Promise.all([page.waitForURL((url) => url.pathname === path), page.getByTestId(`marketing-nav-${key}`).click()]);
  await expect(page.getByTestId(`marketing-nav-${key}`)).toHaveAttribute('aria-current', 'page');
}

test('Home, How it works and Request invite are linked, render and pass axe; the invite form thanks the person', async ({
  page,
  axe,
  harness,
  network,
}) => {
  const since = Date.now() / 1000;
  const home = await page.goto('/');
  expect(home?.status()).toBe(200);
  await expect(page.getByTestId('marketing-nav-home')).toHaveAttribute('aria-current', 'page');
  await axe(page, 'Home (public)');

  await follow(page, axe, 'how_it_works', '/how-it-works/');
  await axe(page, 'How it works (public)');

  await follow(page, axe, 'request_invite', '/request-invite/');
  const form = page.getByTestId('request-invite-form');
  await expect(form).toBeVisible();
  await expect(page.getByTestId('request-invite-honeypot'), 'the bot trap is hidden from people').toBeHidden();
  await axe(page, 'Request invite (public)');

  const operator = await harness.fixture<{ email: string }>('invite_operator', {});
  await harness.fixture('reset_rate_limits', {});
  const email = `ravi-${Date.now()}@agency.example`;
  await page.getByTestId('request-invite-name').fill('Ravi Kumar');
  await page.getByTestId('request-invite-agency').fill('Kokapet Social');
  await page.getByTestId('request-invite-email').fill(email);
  await page.getByTestId('request-invite-note').fill('Three real-estate brands, two of them on Instagram.');
  const sent = page.waitForResponse(
    (response) => response.request().method() === 'POST' && new URL(response.url()).pathname === '/request-invite/',
  );
  await page.getByTestId('request-invite-submit').click();
  const answer = await sent;
  expect(answer.status(), 'the request answers with a redirect to the thank-you').toBe(302);
  await page.waitForURL((url) => url.pathname === '/request-invite/' && url.searchParams.get('sent') === '1');
  await expect(page.getByTestId('request-invite-thanks')).toBeVisible();
  await expect(form).toHaveCount(0);
  await axe(page, 'Request invite sent (public)');

  const told = await harness.probe<InviteRequests>('invite_requests', { email });
  expect(told.operators).toContain(operator.email);
  expect(told.notifications.map((notice) => notice.operator).sort()).toEqual([...told.operators].sort());
  for (const notice of told.notifications) {
    expect(notice).toMatchObject({ title: 'Invite request from Ravi Kumar (Kokapet Social)', is_read: false });
  }
  // A reload repeats the GET only: nobody is told twice.
  await page.reload();
  await expect(page.getByTestId('request-invite-thanks')).toBeVisible();
  expect((await harness.probe<InviteRequests>('invite_requests', { email })).notifications).toHaveLength(
    told.operators.length,
  );

  expect(network.blocked).toEqual([]);
  expect((await harness.probe<{ hosts: string[] }>('refused_network', { since })).hosts).toEqual([]);
});
