// Before/after pairs for the owner, and the light diff (spec D9; plan T12). Never a test of the
// product: nothing here compares against a baseline or writes under tests/. See tests/e2e/README.md,
// "Pairs and the light diff".
//
//   PAIR_SIDE=before E2E_PORT=<main's port> npm run pairs -- tests/e2e/pairs/00-shell.pair.ts
//   E2E_PORT=<this branch's port> npm run pairs -- tests/e2e/pairs/00-shell.pair.ts
//   PAIR_BEFORE_PORT=<main's port> E2E_PORT=<this branch's port> npm run pairs:diff
//
// PAIR_SIDE (before | after | diff; `pairs:diff` sets diff) picks the side. The before side runs
// against a server already started from a worktree of main, so nothing is started for it. The after
// side and the diff start this branch's server on E2E_PORT when none is listening there.
import fs from 'node:fs';
import path from 'node:path';

import { type BrowserContextOptions, defineConfig, devices } from '@playwright/test';

const SIDES = ['before', 'after', 'diff'] as const;
export type PairRun = (typeof SIDES)[number];

const given = process.env.PAIR_SIDE || 'after';
if (!(SIDES as readonly string[]).includes(given)) {
  throw new Error(`PAIR_SIDE is "${given}"; it must be one of ${SIDES.join(', ')}.`);
}
export const pairRun = given as PairRun;

/** Where the images go: test-results/ is gitignored, and pairs never enter the repository. */
export const PAIRS_DIR = path.join(__dirname, 'test-results', 'pairs');

/**
 * What prints a time, by selectors that already match on main (045978b has no data-visual-dynamic):
 * the `<time>` elements, Home's greeting and date, and every `timesince` the templates print ("5 minutes
 * ago", "1 hour, 2 minutes ago", "3 days from now"; copy such as "Last 24 hours" stays compared). Only
 * `pairs:diff` masks them, on both of its servers; a pair for the owner is never masked (D9).
 */
const UNIT = '\\d+\\s(minute|hour|day|week|month|year)s?';
export const pairMasks: readonly string[] = [
  'time',
  'header:has([data-home-status]) > h1',
  '#today-heading + p',
  `text=/${UNIT}(,\\s${UNIT})?\\s(ago|from now)/`,
];

function contextOptions(device: string): BrowserContextOptions {
  const { defaultBrowserType: _engine, ...options } = devices[device];
  return options;
}

type PairDevice = BrowserContextOptions & { viewport: { width: number; height: number } };

/** The two widths as browser context options, so the diff opens both servers with the same ones. */
export const pairDevices: Record<'pair-390' | 'pair-1440', PairDevice> = {
  // iPhone 13's screen, 390 x 844. Chromium with the local system-ui (Inter here), so a pair is not
  // a typeface sign-off (D9); with `CI` set it is WebKit, as in playwright.config.ts.
  'pair-390': { ...contextOptions('iPhone 13'), viewport: { width: 390, height: 844 } },
  'pair-1440': { ...contextOptions('Desktop Chrome'), viewport: { width: 1440, height: 900 } },
};

const port = Number(process.env.E2E_PORT || 8150);
const baseURL = `http://127.0.0.1:${port}`;
const venvPython = path.join(__dirname, '.venv', 'bin', 'python');
const python = process.env.E2E_PYTHON || (fs.existsSync(venvPython) ? venvPython : 'python');
// The diff's servers run without the worker, so no row changes between the two renders of a page.
const serverFlags = pairRun === 'diff' ? '--reset --no-worker' : '--reset';

export default defineConfig({
  testDir: 'tests/e2e/pairs',
  testMatch: pairRun === 'diff' ? /diff\.ts$/ : /\.pair\.ts$/,
  // Playwright empties its output folder on every run, so it gets one of its own per side; the images
  // are written beside it (PAIRS_DIR/<pair>/<side>/) and survive the other side's run.
  outputDir: path.join(PAIRS_DIR, '.playwright', pairRun),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  globalSetup: './tests/e2e/support/global-setup.ts',
  reporter: [['list']],
  use: {
    baseURL,
    colorScheme: 'light',
    timezoneId: 'Asia/Kolkata',
    serviceWorkers: 'block',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'pair-390', use: { ...pairDevices['pair-390'], browserName: process.env.CI ? 'webkit' : 'chromium' } },
    { name: 'pair-1440', use: { ...pairDevices['pair-1440'], browserName: 'chromium' as const } },
  ],
  webServer:
    pairRun === 'before'
      ? undefined
      : {
          command: `"${python}" -m tests.e2e.server ${serverFlags} --port ${port}`,
          url: `${baseURL}/health/`,
          timeout: 180_000,
          reuseExistingServer: true,
          stdout: 'pipe',
          stderr: 'pipe',
          env: {
            DJANGO_SETTINGS_MODULE: 'config.settings.e2e',
            E2E_PORT: String(port),
            E2E_BASE_URL: baseURL,
            PYTHONUNBUFFERED: '1',
          },
        },
});
