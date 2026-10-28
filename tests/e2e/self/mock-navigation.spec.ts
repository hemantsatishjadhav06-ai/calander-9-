import { expect, test } from '../support/test';

test('a mocked POST document commits before its callback, while ordinary navigation failures still reject', async ({ page, baseURL, axe, network }) => {
  const start = `${baseURL}/__e2e__/mock-navigation-start`;
  const post = `${baseURL}/__e2e__/mock-navigation-post`;
  const callback = `${baseURL}/__e2e__/mock-navigation-callback`;
  const failure = `${baseURL}/__e2e__/mock-navigation-failure`;
  const document = (body: string) => `<!doctype html><html lang="en"><title>Controlled navigation</title><main><h1>Navigation check</h1>${body}</main></html>`;
  let posts = 0;
  let failedAttempts = 0;
  const order: string[] = [];
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame() && frame.url() === post) order.push('post-commit');
  });
  page.on('request', (request) => {
    if (request.url() === callback) order.push('callback-request');
  });
  await page.route(start, (route) => route.fulfill({
    contentType: 'text/html',
    body: document(`<form method="post" action="${post}"><button data-testid="navigation-submit">Continue</button></form>`),
  }));
  await page.route(post, async (route) => {
    expect(route.request().method()).toBe('POST');
    posts += 1;
    await route.fulfill({ contentType: 'text/html', body: document('<p>The mock provider answered.</p>') });
  });
  await page.route(callback, (route) => route.fulfill({
    contentType: 'text/html', body: document('<p data-testid="navigation-result">Callback arrived.</p>'),
  }));
  await page.route(failure, async (route) => {
    failedAttempts += 1;
    await route.abort('failed');
  });
  await page.goto(start);
  await axe(page, 'Controlled form navigation');
  const answered = page.waitForResponse((response) => response.url() === post);
  await page.getByTestId('navigation-submit').click();
  expect((await answered).status()).toBe(200);
  // Deliberately start at response headers, exactly like the unchanged onboarding golden path.
  await page.goto(callback);
  await expect(page.getByTestId('navigation-result')).toHaveText('Callback arrived.');
  expect(order).toEqual(['post-commit', 'callback-request']);
  expect(posts).toBe(1);
  await axe(page, 'Controlled callback navigation');
  await expect(page.goto(failure)).rejects.toThrow();
  expect(failedAttempts).toBe(1);
  expect(network.blocked).toEqual([]);
});
