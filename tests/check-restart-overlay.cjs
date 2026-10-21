const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const selected = process.env.BETTER_CODEX_TEST_DEPLOYMENT || fs.readFileSync(path.join(root, '.local/deployment-path.txt'), 'utf8').trim();
const source = fs.readFileSync(path.resolve(root, selected, 'Provider-Overlay.source.js'), 'utf8');
assert.ok(source.includes('import {G6n as gatewayNativeManagerAtom} from "./app-initial-5851df3f6cb1.js";'));
assert.ok(!source.includes('gatewayInstallRestartRecovery(nS('), 'The native RPC proxy cannot supply synchronous manager state or listeners');
const start = source.indexOf('function fG(e){');
const end = source.indexOf('function cn(e){return q&&e===Pe?zv:e}', start);
assert.ok(start > 0 && end > start);
const local = source.slice(start, end);
const hook = local.match(/\(0,pG\.useEffect\)\(\(\)=>\{if\(T===`local`\)gatewayWatchRestartRecovery\(l,.*?\)\},\[l,T\]\);/);
assert.ok(hook, 'Existing external chats use the local composer and must install the recovery watcher there');
for (const host of ['local', 'remote-fixture']) {
  const scope = {}, calls = [], effects = [];
  vm.runInNewContext(hook[0], {T: host, l: scope, cc: {}, pG: {useEffect(effect) { effects.push(effect); }},
    gatewayWatchRestartRecovery(actualScope, report) { calls.push(actualScope); assert.equal(typeof report, 'function'); }});
  assert.equal(calls.length, 0, 'Register outside render in the native effect lifecycle');
  effects[0]();
  assert.equal(calls.length, host === 'local' ? 1 : 0);
  if (calls.length) assert.equal(calls[0], scope);
}
console.log('PASS: generated local-chat composer installs the raw native manager watcher after render; remote hosts and RPC proxies are excluded.');
