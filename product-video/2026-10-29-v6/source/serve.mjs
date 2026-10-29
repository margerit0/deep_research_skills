import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
const here = path.dirname(fileURLToPath(import.meta.url))
const repo = path.resolve(here, '../../..')
const frontend = path.join(repo, 'frontend')
const require = createRequire(path.join(frontend, 'package.json'))
const { createServer } = await import(pathToFileURL(require.resolve('vite')).href)
const { default: react } = await import(pathToFileURL(require.resolve('@vitejs/plugin-react')).href)
const pkg = JSON.parse(await fs.readFile(path.join(frontend, 'package.json'), 'utf8'))
const alias = Object.fromEntries(Object.keys(pkg.dependencies).map(name => [name, path.join(frontend, 'node_modules', name).replaceAll('\\', '/')]))
const server = await createServer({
  configFile: false,
  root: repo,
  plugins: [react()],
  cacheDir: path.resolve(here, '../cache/vite'),
  resolve: { alias },
  optimizeDeps: { entries: ['product-video/2026-10-29-v6/source/app.html'] },
  server: { host: '127.0.0.1', port: 5190, strictPort: true, hmr: false, fs: { allow: [repo] }, watch: { ignored: ['**/cache/**', '**/preview/**', '**/final/**'] } },
})
await server.listen()
console.log('Video preview: http://127.0.0.1:5190/product-video/2026-10-29-v6/source/index.html')
