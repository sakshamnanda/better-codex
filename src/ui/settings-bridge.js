// Private local RPC only. Existing secrets are never returned to the renderer.
(() => {
  let sequence = 0;
  const pending = new Map();
  globalThis.gatewaySettingsReply = (id, response) => {
    const entry = pending.get(id);
    if (!entry) return;
    pending.delete(id); clearTimeout(entry.timer);
    response.error ? entry.reject(Error(response.error)) : entry.resolve(response.result);
  };
  globalThis.gatewaySettingsRequest = value => new Promise((resolve, reject) => {
    if (typeof globalThis.betterCodexSettings !== `function`) return reject(Error(`Reopen through Codex (Custom Providers) to use these settings.`));
    const id = ++sequence;
    const timer = setTimeout(() => {pending.delete(id);reject(Error(`Settings are taking longer than expected. Reopen this page to check before saving again.`));},180000);
    pending.set(id,{resolve,reject,timer});
    globalThis.betterCodexSettings(JSON.stringify({id,request:value}));
  });
  globalThis.gatewaySettingsOpen = (section = `providers`, provider = null) => {
    if (typeof globalThis.gatewaySettingsNavigate === `function`) {
      globalThis.gatewaySettingsNavigate(section,provider);
    } else {
      globalThis.gatewaySettingsPending = {section,provider};
      zo.dispatchHostMessage({type:`navigate-to-route`,path:`/settings/general`});
    }
  };
})();
