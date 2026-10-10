const fs = require('node:fs/promises');
const path = require('node:path');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const modulesDir = process.env.ATLAS_NODE_MODULES;
const { chromium } = require(modulesDir ? path.join(modulesDir, 'playwright') : 'playwright');
const rootDir = path.resolve(__dirname, '..');
const variants = ['apple', 'claude', 'forest'];
const report = { layouts: [], colors: [], checks: [], errors: [], requestFailures: [] };

(async () => {
  const browser = await chromium.launch({ headless: true, ...(process.env.ATLAS_CHROMIUM_EXECUTABLE ? { executablePath: process.env.ATLAS_CHROMIUM_EXECUTABLE } : {}) });
  try {
    const context = await browser.newContext({ viewport: { width: 1056, height: 1180 }, colorScheme: 'light', reducedMotion: 'reduce' });
    const page = await context.newPage();
    page.on('pageerror', error => report.errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') report.errors.push(message.text()); });
    page.on('requestfailed', request => report.requestFailures.push(request.url()));
    await page.goto(pathToFileURL(path.join(rootDir, 'preview/atlas-colorways-preview.html')).href);
    const frame = page.frames().find(item => item.parentFrame());
    await frame.locator('.viz-carousel-controls').waitFor();
    const duplicateIds = await frame.evaluate(() => {
      const ids = [...document.querySelectorAll('[id]')].map(element => element.id);
      return ids.filter((id, i) => ids.indexOf(id) !== i);
    });
    assert.deepEqual(duplicateIds, []);
    const next = frame.getByRole('button', { name: '下一套配色', exact: true });
    for (const theme of ['light', 'dark']) {
      await page.emulateMedia({ colorScheme: theme, reducedMotion: 'reduce' });
      for (const key of variants) {
        const root = frame.locator(`#atlas-${key}-workspace`);
        assert(await root.isVisible(), `${key} carousel navigation`);
        for (const width of [1440, 1024, 736, 390, 320]) {
          await page.setViewportSize({ width: width + 32, height: 1180 });
          const size = await root.evaluate(element => {
            const box = element.getBoundingClientRect();
            return { width: box.width, height: box.height, overflow: [...element.querySelectorAll('*')].filter(child => {
              const rect = child.getBoundingClientRect();
              return rect.width > 0 && (rect.left < box.left - 1 || rect.right > box.right + 1);
            }).map(child => child.className?.baseVal ?? child.className) };
          });
          assert.deepEqual(size.overflow, [], `${key} ${theme} ${width}`);
          report.layouts.push({ key, theme, width, height: size.height, overflow: size.overflow });
          if (width === 1024 || width === 390) await root.screenshot({ path: path.join(rootDir, `references/atlas-colorway-${key}-${theme}-${width}.png`) });
        }
        await page.setViewportSize({ width: 1056, height: 1180 });
        const colors = await root.evaluate((element, key) => {
          const probe = document.createElement('span'); element.append(probe);
          function color(token) {
            probe.style.color = `var(--cw-${key}-${token})`;
            const parts = getComputedStyle(probe).color.match(/[\d.]+/g).map(Number);
            return [...parts.slice(0, 3), parts[3] ?? 1];
          }
          function blend(top, base) { return top.slice(0, 3).map((v, i) => v * top[3] + base[i] * (1 - top[3])); }
          function luminance(rgb) { return rgb.slice(0, 3).reduce((sum, v, i) => { v /= 255; return sum + (v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4) * [.2126, .7152, .0722][i]; }, 0); }
          function contrast(a, b) { const x = luminance(a), y = luminance(b); return (Math.max(x, y) + .05) / (Math.min(x, y) + .05); }
          const base = color('bg'), selected = blend(color('selected'), base), ratios = {};
          for (const token of ['text', 'muted', 'faint']) ratios[`${token}/base`] = contrast(color(token), base);
          ratios['muted/selected'] = contrast(color('muted'), selected);
          ratios['active/selected'] = contrast(color('accent-text'), selected);
          ratios['active/soft'] = contrast(color('accent-text'), blend(color('accent-soft'), base));
          ratios['good/soft'] = contrast(color('good'), blend(color('good-soft'), base));
          ratios['menu'] = contrast(color('text'), color('menu-bg'));
          probe.remove();
          return { base, ratios: Object.fromEntries(Object.entries(ratios).map(([name, ratio]) => [name, Number(ratio.toFixed(2))])) };
        }, key);
        report.colors.push({ key, theme, ...colors });
        for (const picker of ['model', 'skill']) {
          const trigger = root.locator(`[data-picker-trigger="${picker}"]`);
          assert.equal((await trigger.boundingBox()).height, 28);
          await trigger.click();
          const menu = root.locator(`[data-picker-menu="${picker}"]`);
          const style = await menu.evaluate(element => ({ background: getComputedStyle(element).backgroundColor, blur: getComputedStyle(element).backdropFilter, radius: getComputedStyle(element).borderRadius, width: element.getBoundingClientRect().width }));
          assert(!style.background.startsWith('rgba'), 'Menus remain opaque');
          assert.equal(style.blur, 'none'); assert.equal(style.radius, '11px'); assert.equal(style.width, 232);
          if (theme === 'light') await root.screenshot({ path: path.join(rootDir, `references/atlas-colorway-${key}-${picker}.png`) });
          await frame.locator(':focus').press('Escape');
        }
        await root.locator('[data-node="a"]').click();
        assert.equal(await root.locator('[data-detail-title]').innerText(), '技术与产品');
        await root.locator('[data-node="b"]').click();
        await root.locator('[data-inspector-tab="io"]').click();
        assert(await root.locator('[data-inspector-pane="io"]').isVisible());
        await root.locator('[data-inspector-tab="overview"]').click();
        const toggle = root.locator('[data-action="toggle-graph"]').first();
        await toggle.click(); assert.equal(await root.getAttribute('data-graph'), 'closed');
        await toggle.click(); assert.equal(await root.getAttribute('data-graph'), 'open');
        await next.click();
      }
    }
    const apple = frame.locator('#atlas-apple-workspace');
    await apple.locator('[data-picker-trigger="model"]').click();
    await apple.locator('[data-model-value="deepseek"]').click();
    await next.click(); await next.click(); await next.click();
    assert.equal(await apple.locator('[data-picker-trigger="model"]').getAttribute('data-value'), 'deepseek');
    const lowContrast = report.colors.flatMap(({ key, theme, ratios }) => Object.entries(ratios).filter(([, ratio]) => ratio < 4.5 || !Number.isFinite(ratio)).map(([name, ratio]) => `${key} ${theme} ${name}: ${ratio}`));
    assert.deepEqual(lowContrast, [], 'Text contrast');
    report.checks.push('Three live variants; no duplicate IDs or SVG markers; carousel retains interactions', 'Light/dark palettes and 320–1440 px layouts', 'Text token contrast >= 4.5 for base, selected, status and opaque menu surfaces (before decorative gradients)', '28 px picker buttons; opaque 232 px / 11 px menus; node inspector and collapsible graph');
    assert.deepEqual(report.errors, []); assert.deepEqual(report.requestFailures, []);
    console.log(JSON.stringify({ checks: report.checks, colors: report.colors, layouts: report.layouts.length }));
  } finally {
    await fs.writeFile(path.join(rootDir, 'references/atlas-colorways-verification.json'), JSON.stringify(report, null, 2) + '\n');
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
