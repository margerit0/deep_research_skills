import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { resolve } from 'node:path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'ATLAS_')
  const proxy = {
    '/api': {
      target: env.ATLAS_BACKEND_URL || 'http://127.0.0.1:2024',
      changeOrigin: true,
      rewrite: (path: string) => path.replace(/^\/api/, ''),
    },
  }
  return {
    plugins: [react()],
    build:
      mode === 'workflow-m0'
        ? {
            outDir: 'dist/workflow-m0',
            rollupOptions: { input: resolve(import.meta.dirname, 'm0/workflow.html') },
          }
        : undefined,
    server: { proxy, watch: { ignored: ['**/test-results/**', '**/playwright-report/**'] } },
    preview: { proxy },
  }
})
