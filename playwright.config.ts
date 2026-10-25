import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  testMatch: '**/*.spec.ts',
  outputDir: 'test-results/e2e/private',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [['./e2e/sanitized-reporter.ts']],
  use: {
    baseURL: process.env.LAVA_E2E_BASE_URL,
    trace: 'off',
    screenshot: 'off',
    video: 'off',
    launchOptions: process.env.LAVA_E2E_CHROMIUM
      ? { executablePath: process.env.LAVA_E2E_CHROMIUM }
      : {},
  },
  projects: [
    { name: 'desktop', use: { browserName: 'chromium', viewport: { width: 1280, height: 900 } } },
    {
      name: 'mobile',
      use: {
        browserName: 'chromium', viewport: { width: 390, height: 844 },
        isMobile: true, hasTouch: true,
      },
    },
  ],
});
