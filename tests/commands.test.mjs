import test from 'node:test';
import assert from 'node:assert/strict';
import { runModuleCommand } from '../webui/commands.mjs';

function bridge(implementation = () => {}) {
  const calls = [];
  const cleanup = [];
  const host = {
    setTimeout(fn, delay) {
      if (delay === 1000) { cleanup.push(fn); return { cleanup: true }; }
      return setTimeout(fn, delay);
    },
    clearTimeout(id) { if (!id?.cleanup) clearTimeout(id); },
    ksu: { spawn(command, args, options, callback) {
      calls.push({ command, args: JSON.parse(args), options: JSON.parse(options), callback });
      implementation(host[callback], calls.at(-1));
    } },
  };
  return { host, calls, cleanup: () => cleanup.splice(0).forEach(fn => fn()) };
}

test('dispatches only fixed arguments, collects streams, and cleans up after completion', async () => {
  const fixture = bridge(child => {
    child.stdout.emit('data', 'first line');
    child.stdout.emit('data', 'second line\n');
    child.stderr.emit('data', 'diagnostic');
    child.emit('exit', 0);
  });
  const result = await runModuleCommand('clear-cache', fixture);
  assert.deepEqual(result, { errno: 0, stdout: 'first line\nsecond line\n', stderr: 'diagnostic\n' });
  assert.equal(fixture.calls.length, 1);
  assert.deepEqual(fixture.calls[0].args, ['/data/adb/modules/pixel-clean-icons/ui.sh', 'clear-cache']);
  assert.equal(fixture.calls[0].command, 'sh');
  assert.deepEqual(fixture.calls[0].options, {});
  fixture.cleanup();
  assert.equal(fixture.host[fixture.calls[0].callback], undefined);
});

test('unrecognised actions never reach the native bridge', async () => {
  const fixture = bridge();
  await assert.rejects(runModuleCommand('clear-cache; echo injected', fixture), { code: 'ACTION' });
  assert.equal(fixture.calls.length, 0);
});

test('a nonzero exit keeps its output and a later error cannot overwrite the result', async () => {
  const fixture = bridge(child => {
    child.stdout.emit('data', 'Overlays are not ready.');
    child.emit('exit', 1);
    child.emit('error', { exitCode: 7, message: 'late error' });
  });
  const result = await runModuleCommand('clear-cache', fixture);
  assert.equal(result.errno, 1);
  assert.equal(result.stdout, 'Overlays are not ready.\n');
  fixture.cleanup();
});

test('an immediate bridge exception fails instead of leaving the button waiting forever', async () => {
  const fixture = bridge(() => { throw new Error('native start failed'); });
  await assert.rejects(runModuleCommand('clear-cache', fixture), { code: 'START' });
  fixture.cleanup();
  assert.equal(fixture.host[fixture.calls[0].callback], undefined);
});

test('an error event without an exit still completes the request', async () => {
  const fixture = bridge(child => child.emit('error', { exitCode: 7, message: 'root failed' }));
  const result = await runModuleCommand('clear-cache', fixture);
  assert.equal(result.errno, 7);
  assert.equal(result.stderr, 'root failed');
  fixture.cleanup();
});

test('a missing callback reports unknown completion and never retries automatically', async () => {
  const fixture = bridge();
  await assert.rejects(runModuleCommand('clear-cache', { ...fixture, timeoutMs: 5 }), { code: 'TIMEOUT' });
  const child = fixture.host[fixture.calls[0].callback];
  child.emit('exit', 0);
  assert.equal(fixture.calls.length, 1);
  fixture.cleanup();
});

test('legacy managers use the fixed exec fallback', async () => {
  const fixture = bridge();
  delete fixture.host.ksu.spawn;
  const calls = [];
  const result = await runModuleCommand('snapshot', { ...fixture, exec(command) {
    calls.push(command); return Promise.resolve({ errno: 0, stdout: 'snapshot', stderr: '' });
  } });
  assert.equal(result.stdout, 'snapshot');
  assert.deepEqual(calls, ['sh /data/adb/modules/pixel-clean-icons/ui.sh snapshot']);
});

test('unbounded output is rejected without submitting another command', async () => {
  const fixture = bridge(child => child.stdout.emit('data', 'x'.repeat(1048577)));
  await assert.rejects(runModuleCommand('snapshot', fixture), { code: 'OUTPUT' });
  assert.equal(fixture.calls.length, 1);
  fixture.cleanup();
});
