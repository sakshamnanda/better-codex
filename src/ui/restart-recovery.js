// Store only running turn identifiers; native Codex retains history and settings.
const gatewayRecoveryManagers = new WeakSet();
const gatewayRecoveryScopes = new WeakSet();
function gatewayWatchRestartRecovery(scope, report) {
  if (gatewayRecoveryScopes.has(scope)) return;
  gatewayRecoveryScopes.add(scope);
  scope.watch(({get}) => {
    const manager = get(gatewayNativeManagerAtom, `local`);
    if (manager) queueMicrotask(() => {
      try { gatewayInstallRestartRecovery(manager, report); }
      catch { report(`Better Codex could not initialize external chat recovery.`); }
    });
  });
}
function gatewayInstallRestartRecovery(manager, report = message => console.warn(message), storage = globalThis.localStorage) {
  if (gatewayRecoveryManagers.has(manager)) return;
  const key = `better-codex.running-external-turns.v1`;
  let pending;
  try {
    pending = JSON.parse(storage.getItem(key) ?? `{}`);
    if (!pending || Array.isArray(pending) || typeof pending !== `object`) return;
  } catch { return; }
  gatewayRecoveryManagers.add(manager);
  const external = model => Object.hasOwn(gatewayProviderConfig.models, model);
  const validId = id => /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/.test(id);
  const valid = entry => entry && typeof entry.turnId === `string` && typeof entry.model === `string`;
  const save = () => {
    try { storage.setItem(key, JSON.stringify(pending)); }
    catch { report(`Better Codex could not save restart recovery state.`); }
  };
  const forget = id => { delete pending[id]; save(); };
  const remember = (id, turnId) => {
    const model = manager.getConversation(id)?.latestModel;
    if (!validId(id) || !external(model) || typeof turnId !== `string`) return;
    pending[id] = {turnId, model};
    save();
  };
  let closing = false;
  globalThis.addEventListener(`beforeunload`, () => { closing = true; });
  manager.addNotificationCallback([`turn/started`, `turn/completed`], event => {
    const {threadId, turn} = event.params;
    if (event.method === `turn/started`) remember(threadId, turn.id);
    else if (!closing && [`completed`, `failed`].includes(turn.status) && pending[threadId]?.turnId === turn.id) forget(threadId);
  });
  // Native shutdown and cache eviction also interrupt/unload chats.
  // Only explicit user Stop, archive and delete cancel restart recovery.
  const forgetTree = id => {
    for (const thread of manager.getSubagentDescendantSnapshot(id).descendantThreads) delete pending[thread.id];
    forget(id);
  };
  for (const [method, userReason] of [[`interruptConversation`, `user-stop`], [`stopThread`, `user`]]) {
    const original = manager[method];
    Object.defineProperty(manager, method, {configurable: true, value: function(id, reason, ...args) {
      if (reason === userReason) forgetTree(id);
      return original.call(this, id, reason, ...args);
    }});
  }
  manager.addThreadArchivedListener(forget);
  manager.addThreadDeletedListener(forget);
  globalThis.gatewayRestartRecovery = (async () => {
    const result = {resumed: 0, reattached: 0, skipped: 0, failed: 0};
    // Capture turns already running when the verified overlay reloads its renderer.
    for (const conversation of manager.getCachedConversations()) {
      if (conversation.threadRuntimeStatus?.type !== `active` || !external(conversation.latestModel)) continue;
      try {
        const page = await manager.listThreadTurns(conversation.id, {itemsView: `notLoaded`, sortDirection: `desc`, limit: 1});
        const turn = page.response.data[0];
        if (turn?.status === `inProgress` && !pending[conversation.id]) remember(conversation.id, turn.id);
      } catch { result.failed++; }
    }
    const candidates = Object.entries(pending);
    for (const [id, entry] of candidates) {
      if (!validId(id) || !valid(entry) || !external(entry.model)) { forget(id); result.skipped++; continue; }
      try {
        const stored = await manager.readThread(id, {includeTurns: false});
        const resumed = await manager.resumeConversation({conversationId: id, model: null,
          reasoningEffort: null, serviceTier: null,
          workspaceRoots: [stored.thread.cwd]});
        if (resumed.status !== `ready`) { result.failed++; continue; }
        const conversation = manager.getConversation(id);
        const page = await manager.listThreadTurns(id, {itemsView: `notLoaded`, sortDirection: `desc`, limit: 1});
        const turn = page.response.data[0];
        if (pending[id] !== entry) continue;
        if (conversation?.latestModel !== entry.model || turn?.id !== entry.turnId ||
            ![`inProgress`, `interrupted`].includes(turn.status)) {
          forget(id); result.skipped++; continue;
        }
        const current = await manager.readThread(id, {includeTurns: false});
        if (current.thread.status.type === `active`) { result.reattached++; continue; }
        const descendants = await manager.discoverSubagentDescendantSnapshot(id);
        const workers = descendants.descendantThreads.map(thread => ({id: thread.id,
          status: thread.status?.type ?? `unknown`}));
        if (pending[id] !== entry || closing) continue;
        // Native startEmptyTurn rechecks runtime ownership and keeps saved settings.
        await manager.startEmptyTurn(id, {continuationInput: [{type: `text`,
          text: `Continue the task interrupted by the app restart. Check saved tool results and current files before repeating actions. Reconcile saved subagents with the available native agent inventory; previous live agent handles may no longer exist. Use the native chat tools with these saved worker chat IDs to inspect progress and collect results before creating replacement workers: ${JSON.stringify(workers)}. Preserve the original task, project instructions and permissions.`,
          text_elements: []}]});
        result.resumed++;
      } catch {
        // Keep uncertain admissions for a native status check on the next launch.
        result.failed++;
      }
    }
    if (result.failed) report(`Better Codex could not recover some interrupted external chats. Open them to resume; their recovery records were retained.`);
    return result;
  })();
}
