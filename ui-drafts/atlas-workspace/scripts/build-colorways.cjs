// Generate every color study from the same editable layout and local interactions.
const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const rootDir = path.resolve(__dirname, '..');
const variants = [
  { key: 'apple', name: 'Apple 银白' },
  { key: 'claude', name: 'Claude 暖陶' },
  { key: 'forest', name: '青绿 · 林间' }
];

async function wrap(source, destination) {
  assert(process.env.ATLAS_VISUALIZE_RENDERER, 'Set ATLAS_VISUALIZE_RENDERER');
  execFileSync(process.env.ATLAS_PYTHON || 'python', [process.env.ATLAS_VISUALIZE_RENDERER, source, destination, '--force'], { stdio: 'pipe' });
  const modulesDir = process.env.ATLAS_NODE_MODULES;
  const lucide = process.env.ATLAS_LUCIDE_UMD || (modulesDir ? path.join(modulesDir, 'lucide/dist/umd/lucide.js') : require.resolve('lucide/dist/umd/lucide.js'));
  let markup = await fs.readFile(destination, 'utf8');
  for (const [url, file] of [
    ['https://unpkg.com/@floating-ui/core@1.7.3/dist/floating-ui.core.umd.min.js', path.join(rootDir, 'vendor/floating-ui.core.umd.min.js')],
    ['https://unpkg.com/@floating-ui/dom@1.7.4/dist/floating-ui.dom.umd.min.js', path.join(rootDir, 'vendor/floating-ui.dom.umd.min.js')],
    ['https://unpkg.com/lucide@1.17.0/dist/umd/lucide.js', lucide]
  ]) markup = markup.replace(url, 'data:text/javascript;base64,' + (await fs.readFile(file)).toString('base64'));
  await fs.writeFile(destination, markup);
}

(async () => {
  const source = await fs.readFile(path.join(rootDir, 'atlas-conversation-workspace.html'), 'utf8');
  const sections = [];
  for (const { key, name } of variants) {
    const fragment = source.replace('data-palette="apple"', `data-palette="${key}"`).replace('aria-label="星图工作台 · Apple 银白"', `aria-label="星图工作台 · ${name}"`);
    const file = path.join(rootDir, 'preview', `atlas-${key}-workspace.html`);
    await fs.writeFile(file, fragment);
    await wrap(file, path.join(rootDir, 'preview', `atlas-${key}-preview.html`));
    // Namespace IDs, graph markers, styles and selectors, so all three DOMs stay live.
    // The conversation snapshot remains shared to compare the same research state.
    const namespaced = fragment.replaceAll('atlas-conversation-workspace', `atlas-${key}-workspace`).replaceAll('cw-', `cw-${key}-`);
    sections.push(`<section data-variant="${name}" aria-label="${name}"${key === 'apple' ? '' : ' hidden'}>\n${namespaced}\n</section>`);
  }
  const gallery = `<div id="atlas-colorways" class="viz-carousel" aria-label="星图工作台配色方案" data-previous-label="上一套配色" data-next-label="下一套配色">\n${sections.join('\n')}\n</div>\n`;
  assert(Buffer.byteLength(gallery) < 1000000);
  for (const match of gallery.matchAll(/<script>([\s\S]*?)<\/script>/g)) new Function(match[1]);
  const galleryFile = path.join(rootDir, 'atlas-colorways.html');
  await fs.writeFile(galleryFile, gallery);
  await wrap(galleryFile, path.join(rootDir, 'preview', 'atlas-colorways-preview.html'));
  await fs.copyFile(path.join(rootDir, 'preview/atlas-apple-preview.html'), path.join(rootDir, 'preview/atlas-glass-preview.html'));
  await fs.copyFile(path.join(rootDir, 'atlas-conversation-workspace.html'), path.join(rootDir, 'preview/atlas-glass-workspace.html'));
  console.log('Built Apple, Claude and forest previews and the shared variant carousel.');
})().catch(error => { console.error(error); process.exitCode = 1; });
