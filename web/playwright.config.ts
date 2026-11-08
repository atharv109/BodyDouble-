import { defineConfig, devices } from '@playwright/test'

// Default: run against the mock control plane (fixture replay) on :8001.
// Live: API_TARGET=http://localhost:8000 npx playwright test
const live = process.env.API_TARGET
const api = live ?? 'http://localhost:8001'
const port = 5179

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: `http://localhost:${port}`, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    ...(live ? [] : [{ command: 'node mock/server.mjs 8001', url: 'http://localhost:8001/instances',
      env: { MOCK_DELAY: '60' }, reuseExistingServer: false }]),
    { command: `npx vite --port ${port} --strictPort`, url: `http://localhost:${port}`,
      env: { API_TARGET: api }, reuseExistingServer: false },
  ],
})
