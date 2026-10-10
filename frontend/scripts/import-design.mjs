// One-time migration of the approved Apple CSS and example fixture. The app
// imports only the generated local files and never loads the preview host.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { runInNewContext } from 'node:vm'

const source = readFileSync(
  new URL('../../ui-drafts/atlas-workspace/atlas-conversation-workspace.html', import.meta.url),
  'utf8',
)
let css = source.match(/<style>([\s\S]*?)<\/style>/)[1]
css = css.replace(/\/\* Palette-only alternatives[\s\S]*?(?=#atlas-conversation-workspace \*)/, '')
css = css.replace(/\/\* Local raster masks[\s\S]*?\/\* ATLAS_PICKER_ICON_MASKS_END \*\//, '')
mkdirSync(new URL('../src/data/', import.meta.url), { recursive: true })
writeFileSync(
  new URL('../src/apple.css', import.meta.url),
  '/* Apple silver tokens and layout migrated from the approved design. */\n' + css.trim() + '\n',
)
const nodes = runInNewContext('(' + source.match(/const nodes=(\{[\s\S]*?\n  \});/)[1] + ')')
const inspection = runInNewContext(
  '(' + source.match(/const inspection=(\{[\s\S]*?\n  \});/)[1] + ')',
)
writeFileSync(
  new URL('../src/data/example-nodes.json', import.meta.url),
  JSON.stringify({ nodes, inspection }, null, 2) + '\n',
)
