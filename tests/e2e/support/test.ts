// `test` and `expect` for every spec: Playwright's, plus the harness, sign-in, axe and the network guard.
//
//   harness   harness.fixture<T>(name, payload), harness.probe<T>(name, params), harness.ids
//   as        await as('owner') or as({ email }) puts that person's session cookie in page.context()
//   axe       await axe(page, label) runs WCAG 2.2 AA and fails on serious or critical violations
//   network   network.blocked lists the browser requests the guard aborted in this test
import { expect, test as base } from '@playwright/test';

import { type AxeOptions, type AxeResults, checkAccessibility } from './axe';
import { Harness, type Role, type SessionResult } from './harness';
import { guardNetwork, type NetworkGuard } from './network';

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
};

type WorkerFixtures = {
  harness: Harness;
  engineNotice: void;
};

const guards = new WeakMap<object, NetworkGuard>();

export const test = base.extend<TestFixtures, WorkerFixtures>({
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
    guards.set(context, await guardNetwork(context, String(baseURL)));
    await use(context);
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
