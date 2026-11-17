import test from 'node:test';
import assert from 'node:assert/strict';
import { parseSnapshot, makeApps, filterApps, safeAsset, cacheError } from '../webui/model.mjs';

const catalog = {
  apps: [{ package: 'example.replaced', name: '图标', reason: '移除营销装饰', source: '补全计划', scope: '仅普通入口', before: 'assets/example.replaced.before.png', after: 'assets/example.replaced.after.png' },
    { package: 'example.uninstalled', name: '已卸载', reason: '适配自适应图标' }],
  notes: { 'example.original': '当前版本的图标暂未适配。' },
};
const snapshot = parseSnapshot('PIXEL_CLEAN_ICONS_V1\nexample.replaced\nexample.original\nexample.replaced\n__OVERLAY_STATES__\nexample.replaced\tactive\n');
const infos = [{ packageName: 'example.replaced', appLabel: '哔哩哔哩', userId: 0, uid: 10226 },
  { packageName: 'example.original', appLabel: '高德地图', userId: 0, uid: 10300 },
  { packageName: 'example.replaced', appLabel: '其他用户的名字', userId: 10, uid: 1010226 }];

test('deduplicates launcher packages and does not include uninstalled targets', () => {
  const apps = makeApps(snapshot, infos, catalog);
  assert.equal(apps.length, 2);
  assert.equal(apps[0].name, '哔哩哔哩');
  assert.equal(apps[0].status, 'active');
  assert.equal(apps[0].source, '补全计划');
  assert.equal('scope' in apps[0], false);
  assert.equal(apps.some(a => a.package === 'example.uninstalled'), false);
});

test('unreplaced apps have no explanation, even with notes from an older catalog', () => {
  const apps = makeApps(snapshot, infos, catalog);
  const untouched = filterApps(apps, 'untouched', '');
  assert.equal(untouched.length, 1);
  assert.equal(untouched[0].status, null);
  assert.equal(untouched[0].reason, '');
  assert.equal(untouched[0].source, '');
  assert.equal(untouched[0].explanation, '');
});

test('three filters and Chinese or package search work together', () => {
  const apps = makeApps(snapshot, infos, catalog);
  assert.equal(filterApps(apps, 'replaced', '').length, 1);
  assert.equal(filterApps(apps, 'all', '').length, 2);
  assert.equal(filterApps(apps, 'all', '地图')[0].package, 'example.original');
  assert.equal(filterApps(apps, 'replaced', '地图').length, 0);
  assert.equal(filterApps(apps, 'all', ' ＥＸＡＭＰＬＥ.REPLACED ')[0].name, '哔哩哔哩');
});

test('a configured replacement that failed remains discoverable with its real status', () => {
  const data = { ...snapshot, states: new Map([['example.replaced', 'inactive']]),
    issues: new Map([['example.replaced', 'resource-not-selected']]) };
  const app = filterApps(makeApps(data, infos, catalog), 'replaced', '')[0];
  assert.equal(app.status, 'inactive');
  assert.equal(app.explanation, '系统仍在使用原图标，当前替换未生效。');
  const unknown = makeApps({ ...snapshot, states: new Map() }, infos, catalog)[0];
  assert.equal(unknown.status, 'unknown');
  assert.equal(unknown.explanation, '');
  assert.equal(makeApps(snapshot, infos, catalog)[0].explanation, '');
});

test('backend failure codes are parsed without exposing raw shell output', () => {
  const data = parseSnapshot('PIXEL_CLEAN_ICONS_V1\nexample.replaced\n__OVERLAY_STATES__\nexample.replaced\tinactive\tmapping-missing');
  const app = makeApps(data, infos, catalog)[0];
  assert.equal(app.explanation, '当前应用的图标资源未匹配，可能需要更新适配。');
});

test('malformed snapshots fail instead of pretending there are no applications', () => {
  for (const value of ['', 'other\n__OVERLAY_STATES__', 'PIXEL_CLEAN_ICONS_V1\nexample.app',
    'PIXEL_CLEAN_ICONS_V1\n__OVERLAY_STATES__\nexample.app\tactive\tinjected']) {
    assert.throws(() => parseSnapshot(value));
  }
});

test('package input cannot become a shell command or an image URL', () => {
  const data = parseSnapshot('PIXEL_CLEAN_ICONS_V1\nexample.app;rm\nhttps://example.com\n__OVERLAY_STATES__');
  assert.deepEqual(data.packages, []);
  for (const value of ['https://example.com/a.png', '../private.png', 'assets/a.svg', 'javascript:alert(1)']) {
    assert.equal(safeAsset(value), null);
  }
  assert.equal(safeAsset('assets/example.app.before.png'), 'assets/example.app.before.png');
});

test('readable cache errors cover locked devices, inactive overlays, and a busy operation', () => {
  assert.equal(cacheError('Unlock the owner user before refreshing.'), '请先解锁手机');
  assert.equal(cacheError('Overlays are not ready.'), '图标尚未生效，请重启后再试');
  assert.equal(cacheError('A refresh is already running.'), '正在清除图标缓存');
  assert.equal(cacheError('arbitrary exception'), '清除失败，请稍后重试');
});
