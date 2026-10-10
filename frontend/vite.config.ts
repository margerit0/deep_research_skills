import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'ATLAS_')
  const proxy = {
    '/api': {
      target: env.ATLAS_BACKEND_URL || 'http://127.0.0.1:2024',
      changeOrigin: true,
      rewrite: (path: string) => path.replace(/^\/api/, ''),
    },
  }
  return { plugins: [react()], server: { proxy }, preview: { proxy } }
})
