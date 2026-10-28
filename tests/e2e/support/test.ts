// `test` and `expect` for every spec: Playwright's, plus the harness, sign-in, axe and the network guard.
//
//   harness   harness.fixture<T>(name, payload), harness.probe<T>(name, params), harness.ids
//   as        await as('owner') or as({ email }) puts that person's session cookie in page.context()
//   axe       await axe(page, label) runs WCAG 2.2 AA and fails on serious or critical violations
//   network   network.blocked lists the browser requests the guard aborted in this test; a redirect
//             the browser followed off the server (network.escaped) fails the test at its end
import { expect, test as base } from '@playwright/test';

import { type AxeOptions, type AxeResults, checkAccessibility } from './axe';
import { Harness, type Role, type SessionResult } from './harness';
import { guardNetwork, type NetworkGuard } from './network';
import { installMockNavigationBarrier } from './mock-navigation.cjs';

export { expect };
export type { AxeOptions, AxeResults } from './axe';
export type { HarnessIds, Role, SessionResult } from './harness';
export type { NetworkGuard } from './network';

type As = (who: Role | { email: string }) => Promise<SessionResult>;
type Axe = (page: Parameters<typeof checkAccessibility>[0], label: string, options?: AxeOptions) => Promise<AxeResults>;

type TestFixtures = {
  as: As;
  axe: Axe;
  network: NetworkGuard;
  onboardingQuarantine: void;
  mockedNavigationBarrier: boolean;
};

type WorkerFixtures = {
  harness: Harness;
  engineNotice: void;
};

const guards = new WeakMap<object, NetworkGuard>();

export const test = base.extend<TestFixtures, WorkerFixtures>({
  mockedNavigationBarrier: [true, { option: true }],

  page: async ({ page, baseURL, mockedNavigationBarrier }, use) => {
    const barrier = mockedNavigationBarrier ? installMockNavigationBarrier(page, String(baseURL)) : null;
    try { await use(page); }
    finally { await barrier?.dispose(); }
  },

  onboardingQuarantine: [
    async ({}, use, testInfo) => {
      testInfo.skip(
        testInfo.project.name === 'iphone-13' &&
          testInfo.file.endsWith('/golden/02-onboarding.spec.ts') &&
          process.env.E2E_VERIFY_ONBOARDING_QUARANTINE !== '1',
        'Quarantined while the mocked form navigation race is repaired and verified: https://github.com/hemantsatishjadhav06-ai/calander-9-/issues/19',
      );
      await use();
    },
    { auto: true },
  ],

  harness: [
    async ({ playwright }, use, workerInfo) => {
      const baseURL = String(workerInfo.project.use.baseURL);
      const request = await playwright.request.newContext({ baseURL });
      await use(await Harness.connect(request));
      await request.dispose();
    },
    { scope: 'worker' },
  ],

  engineNotice: [
    async ({ browserName }, use, workerInfo) => {
      if (workerInfo.project.name === 'iphone-13' && browserName !== 'webkit') {
        console.log(
          `iphone-13: WebKit is not installed here, so this project runs on ${browserName} ` +
            'with the iPhone 13 viewport, scale and touch (CI runs it on WebKit).',
        );
      }
      await use();
    },
    { scope: 'worker', auto: true },
  ],

  context: async ({ context, baseURL }, use) => {
    const guard = await guardNetwork(context, String(baseURL));
    guards.set(context, guard);
    await use(context);
    if (guard.escaped.length > 0) {
      throw new Error(
        `The browser followed a redirect off the e2e server, which no route can stop: ${guard.escaped.join(', ')}. ` +
          "Route the app's own URL that answers the redirect instead (tests/e2e/README.md, Network).",
      );
    }
  },

  network: async ({ context }, use) => {
    const guard = guards.get(context);
    if (!guard) {
      throw new Error('The network guard was not installed on this browser context.');
    }
    await use(guard);
  },

  as: async ({ context, harness, baseURL }, use) => {
    await use(async (who) => {
      const payload = typeof who === 'string' ? { role: who } : { email: who.email };
      const session = await harness.fixture<SessionResult>('session', payload);
      await context.addCookies([
        {
          name: session.cookie.name,
          value: session.cookie.value,
          url: String(baseURL),
          httpOnly: true,
          sameSite: 'Lax',
        },
      ]);
      return session;
    });
  },

  axe: async ({}, use, testInfo) => {
    await use((page, label, options) => checkAccessibility(page, label, testInfo, options));
  },
});
