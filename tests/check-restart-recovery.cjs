const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/ui/restart-recovery.js'), 'utf8');
const key = 'better-codex.running-external-turns.v1';
const parent = '11111111-1111-4111-8111-111111111111';
const child = '22222222-2222-4222-8222-222222222222';
const model = 'owned-external-fixture';
const values = new Map();
const storage = {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value)};
function boot(rows, {fail = false, admissionUnknown = false, delayedManager = false, nativeIdle = false} = {}) {
  const callbacks = {}, starts = [], notices = [];
  const manager = {
    getConversation: id => rows[id],
    getConversationCwd: () => 'C:/owned-project',
    async readThread(id, options) {
      assert.equal(options.includeTurns, false);
      return {thread: {cwd: 'C:/owned-project', status: {type: nativeIdle ? 'idle' : rows[id].threadRuntimeStatus.type}}};
    },
    getCachedConversations: () => Object.values(rows),
    addNotificationCallback: (_, callback) => { callbacks.event = callback; },
    addTurnInterruptStartedListener: callback => { callbacks.stop = callback; },
    addConversationRemovedListener: callback => { callbacks.removed = callback; },
    addThreadArchivedListener: callback => { callbacks.archived = callback; },
    addThreadDeletedListener: callback => { callbacks.deleted = callback; },
    getSubagentDescendantSnapshot: id => ({descendantThreads: id === parent && rows[child] ? [{id: child}] : []}),
    interruptConversation(id, reason, expectedTurn) {
      callbacks.stop?.(id);
      callbacks.event({method: 'turn/completed', params: {threadId: id, turn: {id: rows[id].turnId, status: 'interrupted'}}});
      return {id, reason, expectedTurn};
    },
    stopThread(id, initiatedBy) { return this.interruptConversation(id, initiatedBy === 'user' ? 'user-stop' : 'system'); },
    async resumeConversation(request) {
      assert.equal(request.model, null);
      assert.equal(request.reasoningEffort, null);
      assert.equal(request.workspaceRoots[0], 'C:/owned-project');
      if (fail) throw Error('owned unavailable fixture');
      return {status: 'ready'};
    },
    async listThreadTurns(id, options) {
      assert.equal(options.limit, 1);
      assert.equal(options.itemsView, 'notLoaded');
      return {response: {data: [{id: rows[id].turnId, status: rows[id].status}]}};
    },
    async discoverSubagentDescendantSnapshot(id) {
      return {descendantThreads: id === parent && rows[child] ? [{id: child, status: {type: 'idle'}}] : []};
    },
    async startEmptyTurn(id, options) {
      starts.push(id);
      assert.match(options.continuationInput[0].text, /subagents/);
      if (id === parent && rows[child]) assert.match(options.continuationInput[0].text, new RegExp(child));
      // The native start path retains the existing model, permissions and tools.
      assert.deepEqual(Object.keys(options), ['continuationInput']);
      if (admissionUnknown) throw Error('owned uncertain admission');
      rows[id].turnId += '-resumed';
      rows[id].status = 'inProgress';
      rows[id].threadRuntimeStatus.type = 'active';
      callbacks.event({method: 'turn/started', params: {threadId: id, turn: {id: rows[id].turnId}}});
    },
  };
  const atom = {};
  let currentManager = delayedManager ? null : manager, watcher, watchCount = 0;
  const scope = {watch(callback) {
    watchCount++;
    watcher = () => callback({get(actualAtom, host) {
      assert.equal(actualAtom, atom);
      assert.equal(host, 'local');
      return currentManager;
    }});
    watcher();
  }};
  const context = vm.createContext({gatewayProviderConfig: {models: {[model]: 'fixture'}},
    gatewayNativeManagerAtom: atom, queueMicrotask,
    localStorage: storage, console: {warn: text => notices.push(text)},
    addEventListener: (name, callback) => { callbacks[name] = callback; }});
  vm.runInContext(source, context);
  context.gatewayWatchRestartRecovery(scope, text => notices.push(text));
  context.gatewayWatchRestartRecovery(scope, text => notices.push(text));
  assert.equal(watchCount, 1, 'Repeated composer renders must not add watchers');
  return {context, callbacks, starts, notices, manager,
    managerReady() { currentManager = manager; watcher(); },
    async done() { await new Promise(queueMicrotask); return context.gatewayRestartRecovery; }};
}
function row(id, status = 'interrupted', selected = model, active = false) {
  return {id, turnId: `turn-${id}`, latestModel: selected, status,
    threadRuntimeStatus: {type: active ? 'active' : 'idle'}};
}
function saved(rows) {
  values.set(key, JSON.stringify(Object.fromEntries(Object.values(rows).map(row =>
    [row.id, {turnId: row.turnId, model: row.latestModel}]))));
}
(async () => {
  // Running parent and child survive an actual fresh JS context, without text history.
  let rows = {[parent]: row(parent, 'inProgress', model, true), [child]: row(child, 'inProgress', model, true)};
  let app = boot(rows);
  await app.done();
  assert.equal(app.starts.length, 0);
  assert.equal(Object.keys(JSON.parse(values.get(key))).length, 2);
  // Shutdown may interrupt turns before beforeunload reaches the renderer.
  app.manager.interruptConversation(parent, 'system');
  assert.equal(Object.keys(JSON.parse(values.get(key))).length, 2,
    'System interruption before beforeunload must retain recovery records');
  app.callbacks.beforeunload();
  app.callbacks.event({method: 'turn/completed', params: {threadId: parent, turn: {id: rows[parent].turnId}}});
  rows = {[parent]: row(parent), [child]: row(child)};
  app = boot(rows);
  assert.equal((await app.done()).resumed, 2);
  assert.deepEqual(app.starts, [parent, child]);
  // Renderer reloads reattach active turns without a second inference.
  app = boot(rows);
  assert.equal((await app.done()).reattached, 2);
  assert.equal(app.starts.length, 0);
  const stop = app.manager.interruptConversation(parent, 'user-stop', 'expected-turn-fixture');
  assert.equal(stop.expectedTurn, 'expected-turn-fixture');
  assert.equal(values.get(key), '{}', 'User Stop clears known descendants too');
  rows = {[parent]: row(parent, 'inProgress', model, true)};
  app = boot(rows); await app.done();
  app.callbacks.removed?.(parent);
  assert.equal(Object.keys(JSON.parse(values.get(key))).length, 1,
    'Unloading a cached conversation is not archive/delete');
  app.callbacks.archived(parent);
  assert.equal(values.get(key), '{}');
  app.callbacks.event({method: 'turn/started', params: {threadId: parent, turn: {id: rows[parent].turnId}}});
  app.callbacks.deleted(parent);
  assert.equal(values.get(key), '{}');
  for (const state of ['completed', 'failed']) {
    rows = {[parent]: row(parent, state)}; saved(rows);
    app = boot(rows); await app.done();
    assert.equal(app.starts.length, 0);
    assert.equal(values.get(key), '{}');
  }
  rows = {[parent]: row(parent)}; saved(rows);
  rows[parent].latestModel = 'native-fixture';
  app = boot(rows); await app.done();
  assert.equal(app.starts.length, 0);
  assert.equal(values.get(key), '{}');
  // A later turn supersedes the saved one, including deliberate user resumes.
  rows = {[parent]: row(parent)}; saved(rows); rows[parent].turnId = 'newer-turn';
  app = boot(rows); await app.done(); assert.equal(app.starts.length, 0);
  rows = {[parent]: row(parent)}; saved(rows);
  app = boot(rows, {fail: true});
  assert.equal((await app.done()).failed, 1);
  assert.equal(Object.keys(JSON.parse(values.get(key))).length, 1);
  assert.equal(app.notices.length, 1);
  app = boot(rows, {admissionUnknown: true}); await app.done();
  assert.equal(app.starts.length, 1);
  assert.equal(Object.keys(JSON.parse(values.get(key))).length, 1);
  rows = {[parent]: row(parent)}; saved(rows);
  app = boot(rows, {delayedManager: true});
  assert.equal(await app.done(), undefined, 'Startup must wait for the raw native manager');
  app.managerReady();
  assert.equal((await app.done()).resumed, 1);
  app.managerReady(); await app.done();
  assert.equal(app.starts.length, 1, 'Manager readiness updates must not replay recovery');
  rows = {[parent]: row(parent, 'inProgress', model, true)}; saved(rows);
  app = boot(rows, {nativeIdle: true});
  assert.equal((await app.done()).resumed, 1, 'Stale renderer activity cannot prevent server-confirmed idle recovery');
  console.log('PASS: raw-manager startup readiness, pre-unload system interruptions, cache eviction, parent/child recovery, explicit user Stop, archive/delete and uncertain admissions. Offline native API fixtures only.');
})().catch(error => { console.error(error); process.exitCode = 1; });
