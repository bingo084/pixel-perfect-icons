// The native exec bridge waits for completion. Prefer spawn so WebView stays responsive.
const SCRIPT = '/data/adb/modules/pixel-clean-icons/ui.sh';
const ACTIONS = new Set(['snapshot', 'clear-cache']);
let sequence = 0;

function commandError(code, message) {
  return Object.assign(new Error(message), { code });
}

export function runModuleCommand(action, { host = window, exec, timeoutMs } = {}) {
  if (!ACTIONS.has(action)) return Promise.reject(commandError('ACTION', 'Unsupported module action'));
  const limit = timeoutMs ?? (action === 'clear-cache' ? 180000 : 60000);
  return new Promise((resolve, reject) => {
    let settled = false;
    let timer;
    let callback;
    let stdout = '';
    let stderr = '';
    const finish = (error, result) => {
      if (settled) return;
      settled = true;
      host.clearTimeout(timer);
      // KernelSU may emit an error immediately after a nonzero exit event.
      if (callback) host.setTimeout(() => { delete host[callback]; }, 1000);
      if (error) reject(error); else resolve(result);
    };
    const deadline = () => {
      timer = host.setTimeout(() => finish(commandError('TIMEOUT', 'Completion was not received')), limit);
    };
    const collect = stream => ({
      emit(event, value) {
        if (settled || event !== 'data') return;
        const text = String(value ?? '');
        if (!text) return;
        const chunk = text.endsWith('\n') ? text : text + '\n';
        if (stream === 'stdout') stdout += chunk; else stderr += chunk;
        if (stdout.length + stderr.length > 1048576) finish(commandError('OUTPUT', 'Excessive module output'));
      },
    });
    try {
      if (typeof host.ksu?.spawn === 'function') {
        callback = `pci_command_${Date.now()}_${sequence++}`;
        host[callback] = {
          stdout: collect('stdout'), stderr: collect('stderr'),
          emit(event, value) {
            if (event === 'exit') {
              const code = Number(value);
              finish(null, { errno: Number.isInteger(code) ? code : -1, stdout, stderr });
            } else if (event === 'error') {
              finish(null, { errno: Number(value?.exitCode) || -1, stdout,
                stderr: stderr || String(value?.message || 'Command failed') });
            }
          },
        };
        deadline();
        // All arguments are fixed; no UI text or package name enters this command.
        host.ksu.spawn('sh', JSON.stringify([SCRIPT, action]), '{}', callback);
      } else {
        if (typeof exec !== 'function') throw new Error('Missing execution bridge');
        // Legacy managers keep a working fallback. The caller paints feedback first.
        const result = exec(`sh ${SCRIPT} ${action}`);
        deadline();
        Promise.resolve(result).then(value => finish(null, value),
          () => finish(commandError('START', 'Could not start module command')));
      }
    } catch {
      finish(commandError('START', 'Could not start module command'));
    }
  });
}
