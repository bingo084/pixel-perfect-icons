export const PACKAGE = /^[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+$/;

export function parseSnapshot(text) {
  const lines = text.trim().split(/\r?\n/);
  if (lines.shift() !== 'PIXEL_CLEAN_ICONS_V1') throw new Error('应用列表格式无效');
  const split = lines.indexOf('__OVERLAY_STATES__');
  if (split < 0) throw new Error('图标状态格式无效');
  const packages = [...new Set(lines.slice(0, split).filter(p => PACKAGE.test(p)))];
  const states = new Map();
  const issues = new Map();
  for (const line of lines.slice(split + 1)) {
    const [pkg, status, issue = '-', extra] = line.split('\t');
    if (!PACKAGE.test(pkg) || !['active', 'inactive', 'unknown'].includes(status) || extra !== undefined ||
        !['-', 'overlay-not-active', 'disabled', 'mapping-missing', 'resource-not-selected', 'check-unavailable'].includes(issue)) {
      throw new Error('图标状态格式无效');
    }
    states.set(pkg, status);
    issues.set(pkg, issue);
  }
  return { packages, states, issues };
}

export function failureExplanation(status, issue) {
  if (status !== 'inactive') return '';
  return {
    disabled: '图标覆盖尚未启用，重启后再试。',
    'mapping-missing': '当前应用的图标资源未匹配，可能需要更新适配。',
    'resource-not-selected': '系统仍在使用原图标，当前替换未生效。',
  }[issue] || '图标覆盖尚未生效，重启后再试。';
}

export function makeApps(snapshot, infos, catalog) {
  const metadata = new Map(catalog.apps.map((app, order) => [app.package, { ...app, order }]));
  const labels = new Map();
  for (const info of infos) {
    if (!PACKAGE.test(info.packageName) || info.error) continue;
    const owner = info.userId === 0 || (typeof info.uid === 'number' && info.uid >= 0 && info.uid < 100000);
    if (!owner && (info.userId != null || info.uid != null)) continue;
    if (!labels.has(info.packageName) || owner) labels.set(info.packageName, info.appLabel);
  }
  return snapshot.packages.map(pkg => {
    const meta = metadata.get(pkg);
    const status = meta ? (snapshot.states.get(pkg) || 'unknown') : null;
    return {
      package: pkg,
      name: labels.get(pkg)?.trim() || meta?.name || pkg,
      managed: Boolean(meta),
      status,
      reason: meta?.reason || '',
      source: meta?.source || '',
      explanation: meta ? failureExplanation(status, snapshot.issues?.get(pkg)) : '',
      before: safeAsset(meta?.before),
      after: safeAsset(meta?.after),
      icon: `ksu://icon/${pkg}`,
      order: meta?.order ?? Number.MAX_SAFE_INTEGER,
    };
  }).sort((a, b) => a.order - b.order || a.name.localeCompare(b.name, 'zh-CN', { numeric: true }));
}

export function safeAsset(path) {
  return typeof path === 'string' && /^assets\/[A-Za-z0-9._-]+\.png$/.test(path) ? path : null;
}

export function filterApps(apps, filter, query) {
  const term = query.trim().normalize('NFKC').toLocaleLowerCase();
  return apps.filter(app => (filter === 'all' || app.managed === (filter === 'replaced')) &&
    `${app.name}\n${app.package}`.normalize('NFKC').toLocaleLowerCase().includes(term));
}

export function cacheError(output) {
  if (/Unlock|unlock/i.test(output)) return '请先解锁手机';
  if (/not ready|NOT ACTIVE|NOT SELECTED|MISSING MAP/.test(output)) return '图标尚未生效，请重启后再试';
  if (/not the default home/.test(output)) return '请先将 Pixel Launcher 设为默认桌面';
  if (/already running/.test(output)) return '正在清除图标缓存';
  if (/owner user|Owner user/.test(output)) return '请切换到机主用户后重试';
  return '清除失败，请稍后重试';
}
