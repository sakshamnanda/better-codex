// Updating this registry preserves the native model-selection callbacks and
// per-chat state. Native catalog additions still need their own backend refresh.
globalThis.gatewayUpdateProviderConfig = value => {
  gatewayProviderConfig.providers=value.providers;
  gatewayProviderConfig.models=value.models;
};
function gatewayPickerOptionProvider(option) {
  const id = option.id ?? ``;
  for (const model of Object.keys(gatewayProviderConfig.models).sort((a, b) => b.length - a.length)) {
    if (id === model || id.startsWith(model + `:`)) return gatewayProviderConfig.models[model];
  }
  return `openai`;
}
function gatewayPickerMenuProps(props) {
  const React = Z();
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const previousModels = React.useRef({});
  React.useEffect(() => { if (!props.active) setError(null); }, [props.active]);
  const menu = props.modelListConfig;
  const options = menu.options ?? [];
  const hasExternal = options.some(option => gatewayPickerOptionProvider(option) !== `openai`);
  if (!hasExternal) return props;
  const selected = options.find(option => option.selected);
  const selectedModel = props.selectedPowerSelection?.model;
  const choice = selectedModel != null ? gatewayPickerOptionProvider({id:selectedModel}) : gatewayPickerOptionProvider(selected ?? {});
  if (selected && gatewayPickerOptionProvider(selected) === choice) previousModels.current[choice] = selected.id;
  async function selectProvider(provider, event) {
    event.preventDefault();
    if (busy || props.modelSelectionDisabled || provider === choice) return;
    const candidates = options.filter(option => !option.disabled && gatewayPickerOptionProvider(option) === provider);
    const target = candidates.find(option => option.id === previousModels.current[provider])
      ?? candidates.find(option => { const id = gatewayProviderConfig.providers.find(entry => entry.id === provider)?.defaultModel; return id && (option.id === id || option.id.startsWith(id + `:`)); })
      ?? candidates[0];
    if (target == null) return;
    setBusy(true);
    setError(null);
    try {
      const result = await target.onSelect();
      if (result === false) throw Error(`Model selection was cancelled`);
      props.onToggleMenuView?.(`simple`);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : `Could not select this provider's model`);
    } finally {
      setBusy(false);
    }
  }
  const providers = gatewayProviderConfig.providers;
  const header = (0, CU.jsxs)(CU.Fragment, { children: [
    props.menuHeader,
    (0, CU.jsx)(mh.Title, { children: `Provider` }),
    ...providers.map(provider => (0, CU.jsx)(mh.Item, {
      role: `menuitemradio`,
      "aria-checked": choice === provider.id,
      RightIcon: choice === provider.id ? wn : undefined,
      disabled: busy || props.modelSelectionDisabled || !options.some(option => !option.disabled && gatewayPickerOptionProvider(option) === provider.id),
      SubText: provider.description ? (0, CU.jsx)(`span`, { className: `text-codex-description`, children: provider.description }) : null,
      onSelect: event => { void selectProvider(provider.id, event); },
      children: provider.label,
    }, provider.id)),
    error ? (0, CU.jsx)(mh.Item, {disabled:true, subTextAllowWrap:true, children:error}) : null,
    (0, CU.jsx)(mh.Separator, {}),
    (0, CU.jsx)(mh.Title, { children: `Better Codex` }),
    ...[[`providers`,`Providers`],[`keys`,`API keys`],[`models`,`Models`]].map(([section,label]) =>
      (0, CU.jsx)(mh.Item, {onSelect:() => { void globalThis.gatewaySettingsOpen(section); }, children:label}, `better-codex-` + section)),
    (0, CU.jsx)(mh.Separator, {}),
  ] });
  return { ...props, menuHeader: header,
    modelListConfig: { ...menu,
      options: options.filter(option => gatewayPickerOptionProvider(option) === choice),
      defaultOption: choice === `openai` ? menu.defaultOption : null,
      extras: choice === `openai` ? menu.extras : null,
    },
  };
}
