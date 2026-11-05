// Playwright for SM Bean: the golden paths and the harness self-checks under tests/e2e, against the
// e2e server (python -m tests.e2e.server), on Desktop Chrome, iPhone 13 and Pixel 7.
//
//   npm run test:e2e                                   # starts the server on E2E_PORT (8150) and runs everything
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npx playwright test tests/e2e/self --project=pixel-7
//
// One worker: the suite shares one server and one database. Each test makes its own rows through
// fixtures, so the order does not matter. See tests/e2e/README.md.
//
// tests/e2e/visual/ compares screenshots with the baselines under tests/e2e/__screenshots__/ only when
// E2E_VISUAL=1 (CI's visual job and the baseline workflow); elsewhere those specs skip, saying why.
import fs from 'node:fs';
import path from 'node:path';

import { defineConfig, devices } from '@playwright/test';

/**
 * Whether a run writes baselines: only the baseline workflow (.github/workflows/visual-baselines.yml),
 * which sets CI, E2E_VISUAL=1 and E2E_UPDATE_BASELINES=1 together. Every other run, a local `CI=1`
 * run included, compares at most and never writes (spec D9).
 */
export function updateSnapshotsFor(env: Record<string, string | undefined>): 'all' | 'none' {
  return env.CI && env.E2E_VISUAL === '1' && env.E2E_UPDATE_BASELINES === '1' ? 'all' : 'none';
}

const port = Number(process.env.E2E_PORT || 8150);
const baseURL = `http://127.0.0.1:${port}`;
const venvPython = path.join(__dirname, '.venv', 'bin', 'python');
const python = process.env.E2E_PYTHON || (fs.existsSync(venvPython) ? venvPython : 'python');

export default defineConfig({
  testDir: 'tests/e2e',
  outputDir: 'test-results',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: !!process.env.CI,
  // Fails the run when the server tried to reach outside the machine during it (spec R2).
  globalSetup: './tests/e2e/support/global-setup.ts',
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  snapshotPathTemplate: '{testDir}/__screenshots__/{testFilePath}/{arg}-{projectName}{ext}',
  // Never 'missing' (Playwright's default), which would write a baseline wherever one is absent.
  updateSnapshots: updateSnapshotsFor(process.env),
  expect: {
    toHaveScreenshot: { maxDiffPixelRatio: 0.001 },
  },
  use: {
    baseURL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    timezoneId: 'Asia/Kolkata',
    serviceWorkers: 'block',
  },
  projects: [
    { name: 'desktop-chrome', use: { ...devices['Desktop Chrome'] } },
    {
      name: 'iphone-13',
      // WebKit in CI. Here the Playwright CDN is out of reach, so a local run uses Chromium with the
      // iPhone 13 viewport, scale and touch, and says so once per run (tests/e2e/support/test.ts).
      use: { ...devices['iPhone 13'], ...(process.env.CI ? {} : { browserName: 'chromium' as const }) },
    },
    { name: 'pixel-7', use: { ...devices['Pixel 7'] } },
  ],
  webServer: {
    command: `"${python}" -m tests.e2e.server --reset --port ${port}`,
    url: `${baseURL}/health/`,
    timeout: 180_000,
    reuseExistingServer: !process.env.CI,
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
