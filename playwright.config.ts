// Playwright for SM Bean: the golden paths and the harness self-checks under tests/e2e, against the
// e2e server (python -m tests.e2e.server), on Desktop Chrome, iPhone 13 and Pixel 7.
//
//   npm run test:e2e                                   # starts the server on E2E_PORT (8150) and runs everything
//   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers npx playwright test tests/e2e/self --project=pixel-7
//
// One worker: the suite shares one server and one database. Each test makes its own rows through
// fixtures, so the order does not matter. See tests/e2e/README.md.
import fs from 'node:fs';
import path from 'node:path';

import { defineConfig, devices } from '@playwright/test';

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
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  snapshotPathTemplate: '{testDir}/__screenshots__/{testFilePath}/{arg}-{projectName}{ext}',
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
