import assert from 'node:assert/strict';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import fs from 'node:fs/promises';

// Use an existing Playwright installation; no browser or package is installed here.
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = path.resolve(import.meta.dirname, '..');
const catalog = JSON.parse(await fs.readFile(path.join(root, 'build/module/webroot/catalog.json'), 'utf8'));
const inventory = JSON.parse(await fs.readFile(path.join(root, '.cache/inventory.json'), 'utf8'));
const expectedReplaced = catalog.apps.length;
const expectedAll = inventory.apps.length;
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH || '/opt/google/chrome/chrome',
  headless: true,
  args: ['--no-sandbox', '--disable-dev-shm-usage', '--disable-crashpad-for-testing', '--allow-file-access-from-files'],
});
try {
  const context = await browser.newContext({ viewport: { width: 412, height: 915 }, deviceScaleFactor: 1, colorScheme: 'light' });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(pathToFileURL(path.join(root, 'build/ui-preview/index.html')).href);
  await page.waitForFunction(count => document.querySelectorAll('.app-row').length === count, expectedReplaced);
  assert.deepEqual(await page.evaluate(() => window.PCI_CALLS.map(c => c.split(' ').at(-1))), ['snapshot']);
  assert.equal(await page.locator('[aria-selected=true]').innerText(), `已替换 ${expectedReplaced}`);
  assert.equal(await page.locator('.comparison').count(), expectedReplaced);
  assert.equal(await page.locator('.app-reason').first().innerText(), '移除营销装饰 · 补全计划');
  await page.screenshot({ path: path.join(root, 'build/ui-preview/replaced.png') });

  await page.getByRole('tab', { name: /^未替换/ }).click();
  assert.ok(await page.locator('.untouched-row').count() > 0);
  assert.equal(await page.locator('.untouched-row .icon-empty').count(), await page.locator('.untouched-row').count());
  await page.getByRole('searchbox').fill('网易云');
  assert.equal(await page.locator('.app-row').count(), 1);
  assert.equal(await page.locator('.reason-button').count(), 0);
  await page.getByRole('searchbox').fill('not-an-installed-app');
  assert.equal(await page.locator('#empty').isVisible(), true);
  await page.getByRole('searchbox').fill('');
  await page.screenshot({ path: path.join(root, 'build/ui-preview/untouched.png') });

  await page.getByRole('tab', { name: /^全部/ }).click();
  assert.equal(await page.locator('.app-row').count(), expectedAll);
  await page.getByRole('searchbox').fill('com.taobao.taobao');
  assert.equal(await page.locator('.app-row').count(), 1);
  assert.equal(await page.locator('.app-name').innerText(), '淘宝');
  await page.getByRole('searchbox').fill('');
  await page.getByRole('tab', { name: /^已替换/ }).click();

  await page.getByRole('button', { name: '清除图标缓存', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: '正在清除…' }).isDisabled(), true);
  assert.equal(await page.locator('.cache-spinner').isVisible(), true);
  assert.equal(await page.locator('#cache-message').innerText(), '正在清除图标缓存…');
  await page.waitForFunction(() => document.querySelector('#clear-label').textContent === '清除图标缓存');
  assert.match(await page.locator('#cache-message').innerText(), /预览模式：未执行清除/);
  await page.evaluate(() => { window.PCI_CLEAR_FAIL = true; });
  await page.getByRole('button', { name: '清除图标缓存', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#cache-message').textContent.includes('图标尚未生效'));
  assert.equal(await page.getByRole('button', { name: '清除图标缓存', exact: true }).isEnabled(), true);
  assert.deepEqual(await page.evaluate(() => window.PCI_CALLS.map(c => c.split(' ').at(-1))), ['snapshot', 'clear-cache', 'clear-cache']);

  for (const width of [360, 390, 480]) {
    await page.setViewportSize({ width, height: 850 });
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, `overflow at ${width}px`);
  }
  await page.setViewportSize({ width: 412, height: 915 });
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.screenshot({ path: path.join(root, 'build/ui-preview/dark.png') });
  assert.deepEqual(errors, []);

  // Packaged UI without a KSU bridge must not show mock application data.
  const outside = await context.newPage();
  await outside.goto(pathToFileURL(path.join(root, 'build/module/webroot/index.html')).href);
  await outside.getByText('请从 KernelSU 打开此界面').waitFor();
  assert.equal(await outside.locator('.app-row').count(), 0);
  assert.equal(await outside.getByRole('button', { name: '清除图标缓存', exact: true }).isDisabled(), true);
  await fs.writeFile(path.join(root, 'build/ui-preview/browser-results.json'), JSON.stringify({
    default_replaced: expectedReplaced, preview_apps: expectedAll, filters: 'passed', search: 'passed', unadapted_apps_have_no_explanation: true,
    cache_progress_success_failure: 'passed', no_clear_on_open: true, mobile_widths: [360, 390, 480],
    dark_mode: 'passed', browser_without_ksu: 'passed', page_errors: errors,
    note: 'Browser uses an explicitly labeled fake KSU bridge; no phone was accessed.',
  }, null, 2) + '\n');
  console.log('Browser UI flows passed; screenshots written to build/ui-preview/.');
} finally {
  await browser.close();
}
