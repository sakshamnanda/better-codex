// Check the generated cleanup binding without starting the desktop.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const selected = process.env.BETTER_CODEX_TEST_DEPLOYMENT || fs.readFileSync(path.join(root, '.local/deployment-path.txt'), 'utf8').trim();
const source = fs.readFileSync(path.resolve(root, selected, 'Provider-Overlay.source.js'), 'utf8');
const binding = source.match(/globalThis\.gatewaySubagentRequest=\(method,params\)=>\{.*?\};(?=gatewayWatchRestartRecovery)/g);
assert.equal(binding?.length, 1);
const scope = {}, calls = [];
const context = vm.createContext({D: scope, nS(store, host) {
  assert.equal(store, scope);
  assert.equal(host, 'local');
  return {sendRequest(method, params) { calls.push({method, params}); return Promise.resolve({}); }};
}});
vm.runInContext(binding[0], context);
for (const method of ['thread/list', 'thread/archive', 'thread/delete']) {
  const params = {threadId: 'owned-fixture'};
  context.gatewaySubagentRequest(method, params);
  assert.equal(calls.at(-1).method, method);
  assert.equal(calls.at(-1).params, params);
}
assert.throws(() => context.gatewaySubagentRequest('thread/start', {}));
assert.equal(calls.length, 3);
console.log('PASS: guarded renderer binding uses the original local RPC and forwards only list/archive/delete with unchanged parameters.');
