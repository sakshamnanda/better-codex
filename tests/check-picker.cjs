// Verify registry-driven categories while retaining native selection and effort props.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '..');
const providers = JSON.parse(fs.readFileSync(path.join(root, 'config/providers.json'), 'utf8'));
const config = {
  providers: [{id: 'openai', label: 'ChatGPT'}, ...Object.entries(providers).map(([id, entry]) => ({id, label: entry.label, defaultModel: entry.default_model,enabled:entry.enabled!==false}))],
  models: Object.fromEntries(Object.entries(providers).flatMap(([id, entry]) => Object.keys(entry.models).map(model => [model, id]))),
  disabledModels:Object.values(providers).flatMap(entry=>Object.entries(entry.models).filter(([,route])=>route.enabled===false).map(([id])=>id)),
};
const selection = path.join(root, '.local/deployment-path.txt');
const deployment = process.env.BETTER_CODEX_TEST_DEPLOYMENT||(fs.existsSync(selection) ? fs.readFileSync(selection, 'utf8').trim() : '.local/deployment');
const built = fs.readFileSync(path.join(root, deployment, 'Provider-Overlay.source.js'), 'utf8');
const embedded = JSON.parse(built.split('const gatewayProviderConfig = ')[1].split(/;\r?\n/)[0]);
assert.deepEqual(embedded, config);
config.providers.push({id: 'fixture', label: 'Fixture Provider', defaultModel: 'fixture-model'});
config.models['fixture-model'] = 'fixture';
const reference = {current: {}};
const context = {
  Z: () => ({useState: value => [value, () => {}], useRef: () => reference, useEffect: () => {}}),
  CU: {Fragment: 'fragment', jsx: (type, props) => ({type, ...props}), jsxs: (type, props) => ({type, ...props})},
  mh: {Title: 'title', Item: 'item', Separator: 'separator'}, wn: 'selected-icon',
};
vm.createContext(context);
// Exercise the actual generated helper, including reviewed renamed bindings.
const updatedBuild=built.includes('function e8e(e){e=gatewayPickerMenuProps(e);');
if(updatedBuild)Object.assign(context,{Pf:context.Z,YU:context.CU,Fi:context.mh,Wu:context.wn});
const helper=built.slice(built.indexOf('globalThis.gatewayUpdateProviderConfig ='),built.indexOf(updatedBuild?'\nfunction e8e(e){':'\nfunction b8e(e){'));
assert(helper.includes('function gatewayPickerMenuProps(props)'));
vm.runInContext('const gatewayProviderConfig = ' + JSON.stringify(config) + ';\n' + helper, context);
const chatRef = {current: null};
let defaultSelections = 0;
const chatReact = {useRef: () => chatRef, useEffect: effect => effect()};
const selectDefault = () => defaultSelections++;
context.gatewayChatDefaultModel(chatReact, 'existing-chat', true, selectDefault);
assert.equal(defaultSelections, 0);
context.gatewayChatDefaultModel(chatReact, null, false, selectDefault);
assert.equal(defaultSelections, 0);
context.gatewayChatDefaultModel(chatReact, null, true, selectDefault);
assert.equal(defaultSelections, 1);
// Renders after a user's model change must not reset the new composer again.
context.gatewayChatDefaultModel(chatReact, null, true, selectDefault);
assert.equal(defaultSelections, 1);
context.gatewayChatDefaultModel(chatReact, 'saved-chat', true, selectDefault);
context.gatewayChatDefaultModel(chatReact, null, true, selectDefault);
assert.equal(defaultSelections, 2);
context.gatewayChatDefaultModel(chatReact, null, true, selectDefault, 'other-project');
assert.equal(defaultSelections, 3);
context.gatewayChatDefaultModel(chatReact, null, true, selectDefault, 'other-project');
assert.equal(defaultSelections, 3);
assert(built.includes('gatewayChatDefaultModel(pG,i,!yt&&!q&&he?.isModelLocked!==!0&&jt!=null,'));
assert(built.includes('sn(jt.model,jt.defaultReasoningEffort,{persistAsDefault:!1})},JSON.stringify([T,S.cwd])'));
assert(built.includes('gatewayChatDefaultModel(ZW,n,(w||T)&&Qe&&!We,'));
assert(built.includes('sA(D,`default`,T);g({slug:f.defaultModelSlug,'));
(async () => {
  const selected = [];
  const options = ['gpt-native-fixture', ...Object.keys(config.models)].map(id => ({id: id + ':high', onSelect: () => {selected.push(id);}}));
  for (const provider of config.providers) {
    const model = provider.id === 'openai' ? 'gpt-native-fixture' : provider.defaultModel;
    const props = {active: true, selectedPowerSelection: {model, reasoningEffort: 'high'}, modelListConfig: {options, defaultOption: 'native-default', extras: 'native-extra'}, onToggleMenuView: view => assert.equal(view, 'simple')};
    const result = context.gatewayPickerMenuProps(props);
    if(provider.enabled===false||provider.id!=='openai'&&!provider.defaultModel){
      assert.equal(result.modelListConfig.options.length,0);continue;
    }
    assert.strictEqual(result.selectedPowerSelection, props.selectedPowerSelection);
    assert.equal(result.modelListConfig.defaultOption, provider.id === 'openai' ? 'native-default' : null);
    assert(result.modelListConfig.options.every(option => context.gatewayPickerOptionProvider(option) === provider.id));
    assert(result.modelListConfig.options.length > 0);
    const next = config.providers.find(entry => entry.id !== provider.id && entry.id !== 'openai'&&entry.enabled!==false&&entry.defaultModel)??config.providers.find(entry=>entry.id!==provider.id&&entry.enabled!==false);
    const item = result.menuHeader.children.find(child => child?.children === next.label);
    item.onSelect({preventDefault() {}});
    await Promise.resolve();
    assert.equal(selected.at(-1), next.id==='openai'?'gpt-native-fixture':next.defaultModel);
  }
  const disabled=config.providers.find(p=>p.id!=='openai');
  config.disabledModels.push('fixture-model');context.gatewayUpdateProviderConfig(config);
  const modelProps={active:true,selectedPowerSelection:{model:'fixture-model',reasoningEffort:'high'},modelListConfig:{options}};
  const hidden=context.gatewayPickerMenuProps(modelProps);
  assert.equal(hidden.modelListConfig.options.length,0);assert.strictEqual(hidden.selectedPowerSelection,modelProps.selectedPowerSelection);
  assert(hidden.menuHeader.children.some(c=>c?.children==='Fixture Provider'&&c.disabled));
  config.disabledModels=[];context.gatewayUpdateProviderConfig(config);
  assert(context.gatewayPickerMenuProps(modelProps).modelListConfig.options.some(o=>o.id==='fixture-model:high'));
  config.providers.find(p=>p.id===disabled.id).enabled=false;
  context.gatewayUpdateProviderConfig(config);
  const props={active:true,selectedPowerSelection:{model:disabled.defaultModel,reasoningEffort:'high'},modelListConfig:{options}};
  const result=context.gatewayPickerMenuProps(props);
  assert.strictEqual(result.selectedPowerSelection,props.selectedPowerSelection);
  assert.equal(result.modelListConfig.options.length,0);
  const item=result.menuHeader.children.find(c=>c?.children===disabled.label);assert.equal(item.disabled,true);
  const count=selected.length;item.onSelect({preventDefault(){}});await Promise.resolve();assert.equal(selected.length,count);
  const native=context.gatewayPickerMenuProps({...props,selectedPowerSelection:{model:'gpt-native-fixture'},modelListConfig:{options:options.filter(o=>o.id.startsWith('gpt-native-fixture'))}});
  assert(native.menuHeader.children.some(c=>c?.children===disabled.label&&c.disabled));
  assert(!native.menuHeader.children.some(c=>c?.children==='API keys'));
  assert(!native.menuHeader.children.some(c=>['Better Codex','Providers','Models'].includes(c?.children)));
  const nativeAll=context.gatewayPickerMenuProps({...props,selectedPowerSelection:{model:'gpt-native-fixture'},modelListConfig:{options}});
  nativeAll.menuHeader.children.find(c=>c?.children===disabled.label).onSelect({preventDefault(){}});
  await Promise.resolve();assert.equal(selected.length,count);
  console.log('PASS: generated registry matches configuration; provider filters/defaults, new category, original callbacks and effort props preserved.');
})().catch(error => {console.error(error); process.exitCode = 1;});
