import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

const { Window } = await import(process.env.HAPPY_DOM_MODULE || 'happy-dom');
const root = path.resolve(import.meta.dirname, '..');
const html = await fs.readFile(path.join(root, 'dist/webui-preview.html'), 'utf8');
const catalog = JSON.parse(await fs.readFile(path.join(root, 'build/module/webroot/catalog.json'), 'utf8'));
const inventory = JSON.parse(await fs.readFile(path.join(root, '.cache/inventory.json'), 'utf8'));
const expectedReplaced = catalog.apps.length;
const expectedAll = inventory.apps.length;
const waitFor = async condition => {
  for (let i = 0; i < 150; i++) {
    if (condition()) return;
    await new Promise(resolve => setTimeout(resolve, 10));
  }
  throw new Error('UI update timed out');
};

async function open(transform = source => source) {
  const window = new Window({ url: 'https://preview.invalid/', settings: { disableJavaScriptEvaluation: true } });
  window.document.write(html);
  const code = window.document.querySelector('script[nonce]').textContent;
  window.happyDOM.settings.disableJavaScriptEvaluation = false;
  window.eval(transform(code));
  return window;
}

const window = await open();
const document = window.document;
const $ = selector => document.querySelector(selector);
const search = term => {
  $('#search').value = term;
  $('#search').dispatchEvent(new window.Event('input'));
};
try {
  await waitFor(() => document.querySelectorAll('.app-row').length === expectedReplaced);
  assert.deepEqual(Array.from(window.PCI_CALLS, c => c.split(' ').at(-1)), ['snapshot']);
  assert.equal(document.querySelectorAll('.comparison').length, expectedReplaced);
  assert.equal($('[aria-selected=true]').dataset.filter, 'replaced');
  assert.equal($('.app-reason').textContent, '移除营销装饰 · 补全计划');
  search('百度网盘');
  assert.equal(document.querySelectorAll('.app-row').length, 1);
  assert.equal($('.app-name').textContent, '百度网盘');
  assert.equal(document.querySelectorAll('.comparison > .icon img').length, 2);
  search('拼多多');
  assert.equal(document.querySelectorAll('.app-row').length, 1);
  assert.equal($('.app-reason').textContent, '移除营销装饰 · 补全计划');
  assert.equal(document.querySelectorAll('.comparison > .icon img').length, 2);
  search('闲鱼');
  assert.equal(document.querySelectorAll('.app-row').length, 1);
  assert.equal($('.app-reason').textContent, '适配自适应图标 · 补全计划');
  assert.equal(document.querySelectorAll('.comparison > .icon img').length, 2);
  for (const name of ['招商银行', '高德地图', 'QQ']) {
    search(name);
    assert.equal(document.querySelectorAll('.app-row').length, 1);
    assert.equal($('.app-reason').textContent, '适配自适应图标 · 补全计划');
    assert.equal(document.querySelectorAll('.comparison > .icon img').length, 2);
  }
  search('');
  $('#tab-untouched').click();
  assert.ok(document.querySelectorAll('.untouched-row').length > 0);
  assert.equal($('#comparison-label').hidden, false);
  for (const row of document.querySelectorAll('.untouched-row')) {
    assert.deepEqual(Array.from(row.children, node => node.className), ['app-info', 'comparison']);
    assert.equal(row.querySelectorAll('.comparison > .icon').length, 2);
    assert.equal(row.querySelector('.icon-empty').textContent, '—');
    assert.equal(row.querySelector('.arrow').textContent, '');
    assert.equal(row.querySelector('.status').textContent, '未替换');
    assert.equal(row.querySelector('.app-reason'), null);
  }
  search('网易云');
  assert.equal(document.querySelectorAll('.app-row').length, 1);
  assert.equal(document.querySelectorAll('.reason-button').length, 0);
  search('not-an-installed-app');
  assert.equal($('#empty').hidden, false);
  search('');
  $('#tab-all').click();
  assert.equal(document.querySelectorAll('.app-row').length, expectedAll);
  for (const row of document.querySelectorAll('.app-row')) {
    assert.deepEqual(Array.from(row.children, node => node.className), ['app-info', 'comparison']);
    assert.equal(row.querySelectorAll('.comparison > .icon').length, 2);
  }
  search('com.taobao.taobao');
  assert.equal($('.app-name').textContent, '淘宝');
  assert.equal(document.querySelectorAll('.app-row').length, 1);
  search('');
  $('#tab-replaced').dispatchEvent(new window.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
  assert.equal($('[aria-selected=true]').dataset.filter, 'untouched');
  window.PCI_CLEAR_HOLD = true;
  $('#clear-cache').click();
  $('#clear-cache').click();
  assert.equal($('#clear-cache').disabled, true);
  assert.equal($('#clear-cache').getAttribute('aria-busy'), 'true');
  assert.equal($('#clear-label').textContent, '正在清除…');
  assert.equal($('#cache-message').textContent, '正在清除图标缓存…');
  assert.equal($('#cache-elapsed').hidden, false);
  // Feedback is set before the command is dispatched, then remains interactive.
  assert.equal(window.PCI_CALLS.length, 1);
  await waitFor(() => Boolean(window.PCI_PENDING_CLEAR));
  $('#tab-all').click();
  search('闲鱼');
  assert.equal($('.app-name').textContent, '闲鱼');
  search('');
  await new Promise(resolve => setTimeout(resolve, 1100));
  assert.match($('#cache-elapsed').textContent, /已用时 [1-9]\d* 秒/);
  window[window.PCI_PENDING_CLEAR].stdout.emit('data', 'SUCCESS (preview)');
  window[window.PCI_PENDING_CLEAR].emit('exit', 0);
  window.PCI_CLEAR_HOLD = false;
  await waitFor(() => $('#clear-label').textContent === '清除图标缓存');
  assert.match($('#cache-message').textContent, /预览模式：未执行清除/);
  assert.equal($('#cache-status').dataset.tone, 'success');
  assert.equal($('#cache-elapsed').hidden, true);
  assert.equal($('#clear-cache').getAttribute('aria-busy'), 'false');
  assert.deepEqual(Array.from(window.PCI_CALLS, c => c.split(' ').at(-1)), ['snapshot', 'clear-cache']);
  assert.deepEqual(Array.from(window.PCI_TRANSPORTS), ['spawn', 'spawn']);
  window.PCI_CLEAR_FAIL = true;
  $('#clear-cache').click();
  await waitFor(() => $('#cache-message').textContent.includes('图标尚未生效'));
  assert.equal($('#clear-cache').disabled, false);
  assert.equal($('#cache-status').dataset.tone, 'error');
} finally {
  window.happyDOM.abort();
  window.close();
}

const hostile = await open(code => code.replace('const sdk =',
  'fixture.infos.find(i => i.packageName === "tv.danmaku.bili").appLabel = "<img src=x onerror=alert(1)>";\nconst sdk ='));
try {
  await waitFor(() => hostile.document.querySelectorAll('.app-row').length === expectedReplaced);
  assert.equal(hostile.document.querySelectorAll('img[onerror]').length, 0);
  assert.ok([...hostile.document.querySelectorAll('.app-name')].some(n => n.textContent === '<img src=x onerror=alert(1)>'));
} finally {
  hostile.happyDOM.abort(); hostile.close();
}

const failed = await open(code => code.replace('const sdk =',
  `fixture.snapshot = fixture.snapshot.replace(${JSON.stringify('tv.danmaku.bili\tactive')}, ${JSON.stringify('tv.danmaku.bili\tinactive\tresource-not-selected')});\nconst sdk =`));
try {
  await waitFor(() => failed.document.querySelectorAll('.app-row').length === expectedReplaced);
  const explanation = failed.document.querySelector('.reason-button');
  assert.equal(failed.document.querySelectorAll('.reason-button').length, 1);
  assert.equal(explanation.textContent, '说明');
  explanation.click();
  assert.equal(failed.document.querySelector('#reason-dialog').open, true);
  assert.equal(failed.document.querySelector('#reason-text').textContent, '系统仍在使用原图标，当前替换未生效。');
  failed.document.querySelector('#close-dialog').click();
  assert.equal(failed.document.querySelector('#reason-dialog').open, false);
} finally {
  failed.happyDOM.abort(); failed.close();
}

const outside = await open(code => code.replace('const sdk =', 'delete window.ksu;\nconst sdk ='));
try {
  await waitFor(() => outside.document.querySelector('#load-error').hidden === false);
  assert.equal(outside.document.querySelector('#load-error').textContent, '请从 KernelSU 打开此界面');
  assert.equal(outside.document.querySelectorAll('.app-row').length, 0);
  assert.equal(outside.document.querySelector('#clear-cache').disabled, true);
} finally {
  outside.happyDOM.abort(); outside.close();
}

const paint = await open(code => code.replace('const sdk =', `
window.PCI_FRAMES = [];
window.requestAnimationFrame = callback => { window.PCI_FRAMES.push(callback); return window.PCI_FRAMES.length; };
delete window.ksu.spawn;
const beforeExec = window.ksu.exec;
window.ksu.exec = function(command, options, callback) {
  if (command.endsWith(' clear-cache')) window.PCI_FEEDBACK_AT_CALL = document.querySelector('#cache-message').textContent;
  return beforeExec.call(this, command, options, callback);
};
const sdk =`));
try {
  await waitFor(() => paint.document.querySelectorAll('.app-row').length === expectedReplaced);
  paint.document.querySelector('#clear-cache').click();
  assert.equal(paint.document.querySelector('#cache-message').textContent, '正在清除图标缓存…');
  assert.equal(paint.PCI_CALLS.length, 1);
  paint.PCI_FRAMES.shift()();
  assert.equal(paint.PCI_CALLS.length, 1);
  paint.PCI_FRAMES.shift()();
  await waitFor(() => paint.PCI_CALLS.length === 2);
  assert.equal(paint.PCI_FEEDBACK_AT_CALL, '正在清除图标缓存…');
  await waitFor(() => paint.document.querySelector('#cache-status').dataset.tone === 'success');
} finally {
  paint.happyDOM.abort(); paint.close();
}
await fs.writeFile(path.join(root, 'build/ui-preview/dom-results.json'), JSON.stringify({
  default_replaced: expectedReplaced, preview_apps: expectedAll, netdisk_comparison: 'passed', search_filters: 'passed', keyboard_tabs: 'passed',
  pdd_comparison: 'passed', idlefish_comparison: 'passed',
  cmb_amap_comparisons: 'passed',
  qq_comparison: 'passed',
  icon_sources_without_scope_labels: 'passed',
  unified_row_structure: 'passed', untouched_replacement_slot: 'dash_not_duplicate_icon',
  unadapted_apps_have_no_explanation: true, explanation_only_for_failed_replacements: 'passed',
  cache_button_progress_success_failure: 'passed', double_click: 'one_request', no_clear_on_open: true,
  async_spawn_transport: 'passed', feedback_before_dispatch: 'passed',
  legacy_feedback_painted_before_exec: 'passed',
  elapsed_time_and_interactive_page: 'passed', persistent_result: 'passed',
  untrusted_labels: 'text_only', missing_ksu_bridge: 'explicit_error',
  renderer: 'happy-dom; no browser layout or phone runtime verification',
}, null, 2) + '\n');
console.log('DOM interaction tests passed. No phone operations or browser layout checks.');
