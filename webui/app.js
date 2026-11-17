import { exec, pm, getPackagesInfo } from './vendor/kernelsu.js';
import { parseSnapshot, makeApps, filterApps, cacheError } from './model.mjs';
import { runModuleCommand } from './commands.mjs';

const $ = selector => document.querySelector(selector);
const bridge = typeof window.ksu?.exec === 'function';
const preview = window.PIXEL_CLEAN_ICONS_PREVIEW === true;
let apps = [];
let filter = 'replaced';
let busy = false;

$('#preview-badge').hidden = !preview;
for (let i = 0; i < 5; i++) {
  const skeleton = document.createElement('div');
  skeleton.className = 'skeleton';
  $('#app-list').append(skeleton);
}

function icon(src, name) {
  const holder = document.createElement('span');
  holder.className = 'icon';
  const fallback = () => {
    const mark = document.createElement('span');
    mark.className = 'icon-fallback';
    mark.textContent = [...name][0] || '·';
    mark.setAttribute('aria-label', `${name}图标暂不可预览`);
    holder.replaceChildren(mark);
  };
  if (!src) { fallback(); return holder; }
  const image = document.createElement('img');
  image.alt = name;
  image.loading = 'lazy';
  image.decoding = 'async';
  image.addEventListener('error', fallback, { once: true });
  image.src = src;
  holder.append(image);
  return holder;
}

function row(app) {
  const item = document.createElement('article');
  item.className = `app-row${app.managed ? '' : ' untouched-row'}`;
  const info = document.createElement('div');
  info.className = 'app-info';
  const name = document.createElement('h2');
  name.className = 'app-name';
  name.textContent = app.name;
  info.append(name);
  const metadata = document.createElement('div');
  metadata.className = 'app-meta';
  if (app.managed) {
    const reason = document.createElement('p');
    reason.className = 'app-reason';
    reason.textContent = [app.reason, app.source].filter(Boolean).join(' · ');
    metadata.append(reason);
  }
  const status = document.createElement('span');
  status.className = `status ${app.managed ? app.status : 'untouched'}`;
  status.textContent = app.managed ? (preview ? '预览' :
    { active: '已生效', inactive: '未生效', unknown: '未确认' }[app.status]) : '未替换';
  metadata.append(status);
  if (app.explanation) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'reason-button';
    button.textContent = '说明';
    button.setAttribute('aria-label', `查看${app.name}未生效说明`);
    button.addEventListener('click', () => {
      $('#reason-title').textContent = app.name;
      $('#reason-text').textContent = app.explanation;
      $('#reason-dialog').showModal();
    });
    metadata.append(button);
  }
  info.append(metadata);
  const comparison = document.createElement('div');
  comparison.className = 'comparison';
  const arrow = document.createElement('span');
  arrow.className = 'arrow';
  arrow.textContent = app.managed ? '→' : '';
  arrow.setAttribute('aria-hidden', 'true');
  const before = icon(app.managed ? app.before : app.icon, `${app.name}${app.managed ? '原图' : '当前图标'}`);
  let after;
  if (app.managed) {
    after = icon(app.after, `${app.name}替换后`);
  } else {
    after = document.createElement('span');
    after.className = 'icon icon-empty';
    after.textContent = '—';
    after.setAttribute('role', 'img');
    after.setAttribute('aria-label', '未替换');
  }
  comparison.append(before, arrow, after);
  item.append(info, comparison);
  return item;
}

function render() {
  const visible = filterApps(apps, filter, $('#search').value);
  $('#app-list').replaceChildren(...visible.map(row));
  $('#app-list').setAttribute('aria-busy', 'false');
  $('#app-list').setAttribute('aria-labelledby', `tab-${filter}`);
  $('#empty').hidden = visible.length > 0;
  $('#empty-message').textContent = $('#search').value.trim() ? '没有找到应用' : (filter === 'replaced' ? '暂无替换图标' : '暂无应用');
  $('#list-caption').textContent = `${visible.length} 个应用`;
  const comparisons = visible.some(app => app.managed);
  $('#comparison-label').hidden = visible.length === 0;
  $('#source-note').hidden = !comparisons;
  const replaced = apps.filter(app => app.managed).length;
  for (const [key, count] of Object.entries({ replaced, untouched: apps.length - replaced, all: apps.length })) {
    $(`[data-count="${key}"]`).textContent = count;
  }
  $('#summary').textContent = `已替换 ${replaced} 个应用图标`;
}

function setFilter(next) {
  filter = next;
  for (const button of document.querySelectorAll('[data-filter]')) {
    const selected = button.dataset.filter === filter;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
  }
  render();
}

function cacheMessage(message, tone) {
  $('#cache-message').textContent = message;
  $('#cache-status').dataset.tone = tone;
}

function paintFeedback() {
  return new Promise(resolve => {
    const timer = setTimeout(resolve, 100);
    requestAnimationFrame(() => requestAnimationFrame(() => { clearTimeout(timer); resolve(); }));
  });
}

for (const button of document.querySelectorAll('[data-filter]')) {
  button.addEventListener('click', () => setFilter(button.dataset.filter));
  button.addEventListener('keydown', event => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...document.querySelectorAll('[data-filter]')];
    const current = tabs.indexOf(button);
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 :
      (current + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    setFilter(tabs[next].dataset.filter);
    tabs[next].focus();
  });
}
$('#search').addEventListener('input', render);
$('#close-dialog').addEventListener('click', () => $('#reason-dialog').close());
$('#reason-dialog').addEventListener('click', event => { if (event.target === $('#reason-dialog')) $('#reason-dialog').close(); });

$('#clear-cache').addEventListener('click', async () => {
  if (!bridge || busy) return;
  busy = true;
  $('#clear-cache').disabled = true;
  $('#clear-cache').setAttribute('aria-busy', 'true');
  $('#clear-label').textContent = '正在清除…';
  cacheMessage('正在清除图标缓存…', 'pending');
  const started = performance.now();
  const tick = () => { $('#cache-elapsed').textContent = `已用时 ${Math.floor((performance.now() - started) / 1000)} 秒`; };
  $('#cache-elapsed').hidden = false;
  tick();
  const ticker = setInterval(tick, 1000);
  try {
    await paintFeedback();
    const result = await runModuleCommand('clear-cache', { exec });
    if (result.errno !== 0) throw new Error(cacheError(`${result.stdout}\n${result.stderr}`));
    cacheMessage(preview ? '预览模式：未执行清除' : '图标缓存已清除，返回桌面查看', 'success');
  } catch (error) {
    const message = error.code === 'TIMEOUT' ? '暂未收到清除结果，请稍后查看桌面' :
      error.code === 'START' ? '清除请求未能启动，请重试' : error.code ? '清除失败，请稍后重试' : error.message || '清除失败，请稍后重试';
    cacheMessage(message, error.code === 'TIMEOUT' ? 'unknown' : 'error');
  } finally {
    clearInterval(ticker);
    $('#cache-elapsed').hidden = true;
    busy = false;
    $('#clear-cache').disabled = false;
    $('#clear-cache').setAttribute('aria-busy', 'false');
    $('#clear-label').textContent = '清除图标缓存';
  }
});

async function start() {
  try {
    if (!bridge) throw new Error('请从 KernelSU 打开此界面');
    const response = await fetch('./catalog.json');
    if (!response.ok) throw new Error('图标清单读取失败');
    const catalog = await response.json();
    const result = await runModuleCommand('snapshot', { exec });
    if (result.errno !== 0) throw new Error(/Owner user/.test(result.stderr) ? '请切换到机主用户后打开' : '应用列表读取失败，请重新打开界面');
    const snapshot = parseSnapshot(result.stdout);
    const infos = pm.support ? pm.getPackagesInfo(snapshot.packages) : getPackagesInfo(snapshot.packages);
    if (snapshot.packages.length && !infos.length) throw new Error('无法读取应用信息，请更新 KernelSU 管理器');
    apps = makeApps(snapshot, infos, catalog);
    render();
    $('#clear-cache').disabled = false;
  } catch (error) {
    $('#summary').textContent = '暂时无法读取应用';
    $('#load-error').textContent = error.code === 'TIMEOUT' ? '应用列表读取超时，请重新打开界面' :
      error.code ? '应用列表读取失败，请重新打开界面' : error.message || '读取失败，请重新打开界面';
    $('#load-error').hidden = false;
    $('#app-list').replaceChildren();
    $('#app-list').setAttribute('aria-busy', 'false');
    $('#comparison-label').hidden = true;
  }
}
start();
