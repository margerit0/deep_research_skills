import { defineConfig } from '@playwright/test'

const port = Number(process.env.ATLAS_TEST_PORT ?? 5173)

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  workers: 2,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1024, height: 962 },
    colorScheme: 'light',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: { channel: 'chrome' },
  },
  // A TCP health check avoids HTTP proxy settings affecting the local server probe.
  webServer: {
    command: `npm run dev -- --port ${port} --strictPort`,
    port,
    reuseExistingServer: !process.env.CI,
  },
})
