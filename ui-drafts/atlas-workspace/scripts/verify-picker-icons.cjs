const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const modulesDir = process.env.ATLAS_NODE_MODULES;
const { chromium } = require(modulesDir ? path.join(modulesDir, 'playwright') : 'playwright');
const sharp = require(modulesDir ? path.join(modulesDir, 'sharp') : 'sharp');
const rootDir = path.resolve(__dirname, '..');
const lucideUmd = process.env.ATLAS_LUCIDE_UMD || (modulesDir ? path.join(modulesDir, 'lucide/dist/umd/lucide.js') : require.resolve('lucide/dist/umd/lucide.js'));

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.ATLAS_CHROMIUM_EXECUTABLE ? { executablePath: process.env.ATLAS_CHROMIUM_EXECUTABLE } : {}) });
  const results = [], errors = [];
  try {
    for (const theme of ['light', 'dark']) {
      const context = await browser.newContext({ viewport: { width: 1056, height: 1100 }, colorScheme: theme });
      // Reproduce the inline host not providing its icon library at all.
      await context.addInitScript(() => Object.defineProperty(window, 'lucide', { configurable: true, get() { return undefined; }, set() {} }));
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(pathToFileURL(path.join(rootDir, 'preview/atlas-glass-preview.html')).href);
      const frame = page.frames().find(item => item.parentFrame());
      await frame.locator('#cw-model').waitFor();
      assert.equal(await frame.locator('svg.lucide').count(), 0);
      const icons = await frame.locator('[data-picker-trigger] i[data-lucide]').evaluateAll(async elements => Promise.all(elements.map(async element => {
        const style = getComputedStyle(element), bounds = element.getBoundingClientRect();
        const image = new Image();
        image.src = style.maskImage.slice(5, -2);
        await image.decode();
        return { name: element.dataset.lucide, width: bounds.width, height: bounds.height, pixels: image.naturalWidth };
      })));
      assert.deepEqual(icons.map(icon => icon.name), ['chevron-down', 'layers', 'chevron-down']);
      icons.forEach(icon => assert(icon.width >= 11 && icon.height >= 11 && icon.pixels === 72));
      const toolbar = frame.locator('.cw-composer-toolbar');
      const crop = await toolbar.evaluate(element => {
        const left = element.getBoundingClientRect().left;
        const end = element.querySelector('#cw-skill').getBoundingClientRect().right;
        return Math.ceil(end - left + 5);
      });
      await sharp(await toolbar.screenshot()).extract({ left: 0, top: 0, width: crop, height: 32 }).resize({ width: crop * 2 }).toFile(path.join(rootDir, `references/atlas-picker-icons-${theme}.png`));
      await frame.locator('#cw-model').click();
      assert(await frame.locator('#cw-model-menu').isVisible());
      await frame.locator('[data-model-value="qwen"]').press('ArrowDown');
      await frame.locator('[data-model-value="deepseek"]').press('Enter');
      assert.equal(await frame.locator('[data-model-label]').innerText(), 'DeepSeek V3.2');
      await frame.locator('#cw-skill').click();
      await frame.locator('[data-skill-value="product-comparison"]').click();
      assert.match(await frame.locator('[data-skill-label]').innerText(), /产品对比/);
      await frame.locator('#cw-skill').click();
      assert(await frame.locator('[data-skill-value="product-comparison"] .cw-menu-check').evaluate(element => getComputedStyle(element).visibility === 'visible'));
      await frame.locator('[data-skill-value="product-comparison"]').press('Escape');
      await page.setViewportSize({ width: 352, height: 1100 });
      for (const name of ['model', 'skill']) {
        await frame.locator(`[data-picker-trigger="${name}"]`).click();
        assert(await frame.locator(`[data-picker-menu="${name}"]`).evaluate(element => {
          const bounds = element.getBoundingClientRect(), form = element.closest('form').getBoundingClientRect();
          return bounds.left >= form.left && bounds.right <= form.right;
        }));
        await frame.locator(`[data-picker-menu="${name}"] [aria-checked="true"]`).press('Escape');
      }
      // A late host initialization replaces the placeholders without double icons.
      await frame.evaluate(() => { delete window.lucide; });
      await frame.addScriptTag({ path: lucideUmd });
      await frame.evaluate(() => lucide.createIcons());
      assert.equal(await frame.locator('[data-picker-trigger] svg.lucide').count(), 3);
      assert.equal(await frame.locator('[data-picker-trigger] i[data-lucide]').count(), 0);
      results.push({ theme, icons, noHostLibrary: true, mouseAndKeyboardMenus: true, narrowMenus: true, lateHostWithoutDuplicates: true });
      await context.close();
    }
    assert.deepEqual(errors, []);
    const report = { results, errors };
    await fs.writeFile(path.join(rootDir, 'references/atlas-picker-icons-verification.json'), JSON.stringify(report, null, 2) + '\n');
    console.log(JSON.stringify(report));
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
