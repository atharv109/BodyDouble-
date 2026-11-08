import { defineConfig, devices } from '@playwright/test'

// Default: run against the mock control plane (fixture replay) on :8001.
// Live: API_TARGET=http://localhost:8000 npx playwright test
const live = process.env.API_TARGET
const api = live ?? 'http://localhost:8011' // own port: never collides with a dev/QA mock on :8001
const port = 5179
export const pwPort = 5180
export const offPort = 5181 // real-mode-like: /dev/fake-case returns 404 (e2e/tryit.spec.ts)

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { baseURL: `http://localhost:${port}`, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
  webServer: [
    ...(live ? [] : [{ command: 'node mock/server.mjs 8011', url: 'http://localhost:8011/instances',
      env: { MOCK_DELAY: '60' }, reuseExistingServer: false }]),
    { command: `npx vite --port ${port} --strictPort`, url: `http://localhost:${port}`,
      env: { API_TARGET: api }, reuseExistingServer: false },
    // Password-mode pair for e2e/password.spec.ts: a mock with MOCK_PASSWORD set, behind its own vite.
    ...(live ? [] : [
      { command: 'node mock/server.mjs 8012', url: 'http://localhost:8012/auth/config',
        env: { MOCK_DELAY: '60', MOCK_PASSWORD: 'e2e-secret' }, reuseExistingServer: false },
      { command: `npx vite --port ${pwPort} --strictPort`, url: `http://localhost:${pwPort}`,
        env: { API_TARGET: 'http://localhost:8012' }, reuseExistingServer: false },
      { command: 'node mock/server.mjs 8013', url: 'http://localhost:8013/auth/config',
        env: { MOCK_DELAY: '60', MOCK_FAKE_CASE_OFF: '1' }, reuseExistingServer: false },
      { command: `npx vite --port ${offPort} --strictPort`, url: `http://localhost:${offPort}`,
        env: { API_TARGET: 'http://localhost:8013' }, reuseExistingServer: false },
    ]),
  ],
})
